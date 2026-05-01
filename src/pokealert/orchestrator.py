"""Main async monitor loop with heartbeat, web-scout, and health server."""
from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .checkers import build_checkers
from .heartbeat import HeartbeatService, HeartbeatStats, run_health_server
from .http_client import PoliteHttpClient
from .models import ProductConfig, StockResult, StockState
from .notifiers import BaseNotifier
from .storage import StateStore
from .web_scout import WebScout

log = structlog.get_logger(__name__)


class Orchestrator:
    def __init__(
        self,
        cfg: dict[str, Any],
        notifiers: list[BaseNotifier],
        store: StateStore,
    ):
        self.cfg = cfg
        self.products: list[ProductConfig] = cfg["products"]
        self.notifiers = notifiers
        self.store = store

        g = cfg.get("global", {})
        self.default_interval = int(g.get("default_interval_seconds", 180))
        self.jitter = int(g.get("jitter_seconds", 30))
        self.alert_cooldown = int(g.get("alert_cooldown_seconds", 900))

        self.stats = HeartbeatStats()
        self.stats.products_tracked = len(self.products)

        self.http = PoliteHttpClient(
            respect_robots=g.get("respect_robots_txt", True),
            circuit_threshold=int(g.get("circuit_breaker_threshold", 5)),
            circuit_cooldown=float(g.get("circuit_breaker_cooldown_seconds", 600)),
        )
        self.checkers = build_checkers(self.http)

        self.heartbeat = HeartbeatService(
            self.stats,
            interval_seconds=int(g.get("heartbeat_interval_seconds", 900)),
        )

        ws_cfg = cfg.get("web_scout", {}) or {}
        self.web_scout = WebScout(
            queries=ws_cfg.get("queries"),
            interval_seconds=int(ws_cfg.get("interval_seconds", 1800)),
            state_path=ws_cfg.get("state_path", "data/web_scout_seen.json"),
        ) if ws_cfg.get("enabled", True) else None

        port_env = os.getenv("PORT", "").strip()
        self.health_port = int(port_env) if port_env else int(g.get("health_port", 8080))
        self._stop = asyncio.Event()
        self._runner = None

    async def stop(self) -> None:
        self._stop.set()
        await self.heartbeat.stop()
        if self.web_scout:
            await self.web_scout.stop()
        await self.http.close()
        if self._runner is not None:
            await self._runner.cleanup()

    # ------------------------------------------------------------------ run

    async def run(self) -> None:
        await self.store.init()
        log.info(
            "orchestrator_starting",
            products=len(self.products),
            notifiers=[n.name for n in self.notifiers],
            health_port=self.health_port,
            web_scout_enabled=bool(self.web_scout),
        )

        if not self.notifiers:
            log.warning("no_notifiers_enabled_alerts_will_only_log")

        # Start background services
        self._runner = await run_health_server(self.stats, self.health_port)
        hb_task = asyncio.create_task(self.heartbeat.run(), name="heartbeat")
        ws_task = (
            asyncio.create_task(self.web_scout.run(), name="web_scout")
            if self.web_scout else None
        )

        product_tasks = [
            asyncio.create_task(self._run_product(p), name=f"product:{p.name}")
            for p in self.products
        ]

        try:
            await self._stop.wait()
        finally:
            for t in product_tasks + [hb_task] + ([ws_task] if ws_task else []):
                t.cancel()
            await asyncio.gather(*product_tasks, hb_task, *([ws_task] if ws_task else []),
                                 return_exceptions=True)

    async def _run_product(self, product: ProductConfig) -> None:
        checker = self.checkers.get(product.retailer)
        if checker is None:
            log.error("unknown_retailer", retailer=product.retailer, product=product.name)
            return

        interval = max(product.min_interval_seconds, 60)
        await asyncio.sleep(random.uniform(0, min(interval, 30)))

        while not self._stop.is_set():
            try:
                result = await checker.check(product)
                self.stats.incr_check()
                if result.state == StockState.ERROR:
                    self.stats.incr_error()
                # BLOCKED = expected/permanent (robots.txt, WAF 403, no API key)
                # These are not counted as errors — they are known limitations.
                await self._handle_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("checker_crashed", product=product.name)
                self.stats.incr_error()

            jitter = random.uniform(-self.jitter, self.jitter)
            sleep_for = max(60, interval + jitter)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

    async def _handle_result(self, result: StockResult) -> None:
        previous = await self.store.get_previous(result.product_key)
        await self.store.save(result)

        log.info(
            "check_done",
            product=result.product_name,
            retailer=result.retailer,
            state=result.state.value,
            price=result.price,
            previous_state=previous.state.value if previous else None,
        )

        if not result.is_transition_to_in_stock(previous):
            return

        last_alert = await self.store.last_alert_time(result.product_key)
        if last_alert and (
            datetime.now(timezone.utc) - last_alert
            < timedelta(seconds=self.alert_cooldown)
        ):
            log.info("alert_suppressed_cooldown", product=result.product_name)
            return

        log.info("dispatching_alert", product=result.product_name)
        sent_channels: list[str] = []
        for n in self.notifiers:
            ok = await n.send(result)
            if ok:
                sent_channels.append(n.name)

        if sent_channels:
            await self.store.record_alert(result.product_key, result.state, sent_channels)
            self.stats.incr_alert()
            log.info("alert_sent", product=result.product_name, channels=sent_channels)
        else:
            log.warning("alert_failed_all_channels", product=result.product_name)