"""Heartbeat: periodic 'I'm alive' signal.

Two surfaces:
  1. Discord webhook (DISCORD_WEBHOOK_HEARTBEAT) — posts a compact status embed
  2. HTTP /health endpoint — used by Railway, UptimeRobot, etc.

The heartbeat also surfaces basic stats: products tracked, checks performed,
last alert time, circuit-breaker status.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from aiohttp import web

from .notifiers.discord import post_to_webhook

log = structlog.get_logger(__name__)


@dataclass
class HeartbeatStats:
    started_at: float = field(default_factory=time.time)
    checks_performed: int = 0
    alerts_sent: int = 0
    last_check_at: float | None = None
    last_alert_at: float | None = None
    errors_since_start: int = 0
    products_tracked: int = 0
    version: str = "1.1.0"

    def incr_check(self) -> None:
        self.checks_performed += 1
        self.last_check_at = time.time()

    def incr_alert(self) -> None:
        self.alerts_sent += 1
        self.last_alert_at = time.time()

    def incr_error(self) -> None:
        self.errors_since_start += 1

    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def as_dict(self) -> dict:
        return {
            "status": "ok",
            "version": self.version,
            "uptime_seconds": self.uptime_seconds(),
            "products_tracked": self.products_tracked,
            "checks_performed": self.checks_performed,
            "alerts_sent": self.alerts_sent,
            "errors_since_start": self.errors_since_start,
            "last_check_at": (
                datetime.fromtimestamp(self.last_check_at, tz=timezone.utc).isoformat()
                if self.last_check_at else None
            ),
            "last_alert_at": (
                datetime.fromtimestamp(self.last_alert_at, tz=timezone.utc).isoformat()
                if self.last_alert_at else None
            ),
            "started_at": datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
        }


class HeartbeatService:
    def __init__(self, stats: HeartbeatStats, interval_seconds: int = 900):
        self.stats = stats
        self.interval = max(300, interval_seconds)  # minimum 5 min
        self.webhook = os.getenv("DISCORD_WEBHOOK_HEARTBEAT", "").strip()
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        # Startup ping
        await self._send_heartbeat(kind="startup")

        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                break  # stop requested
            except asyncio.TimeoutError:
                await self._send_heartbeat(kind="periodic")

        # Shutdown ping
        await self._send_heartbeat(kind="shutdown")

    async def _send_heartbeat(self, kind: str) -> None:
        if not self.webhook:
            log.debug("heartbeat_skip_no_webhook")
            return

        s = self.stats
        uptime_h = s.uptime_seconds() / 3600
        color_map = {"startup": 0x3498DB, "periodic": 0x2ECC71, "shutdown": 0xE67E22}
        title_map = {
            "startup":  "✅ PokeAlert started",
            "periodic": "💓 PokeAlert heartbeat",
            "shutdown": "🛑 PokeAlert shutting down",
        }

        embed = {
            "title": title_map.get(kind, "PokeAlert"),
            "color": color_map.get(kind, 0x2ECC71),
            "fields": [
                {"name": "Products tracked", "value": str(s.products_tracked), "inline": True},
                {"name": "Uptime", "value": f"{uptime_h:.1f} h", "inline": True},
                {"name": "Version", "value": s.version, "inline": True},
                {"name": "Checks performed", "value": str(s.checks_performed), "inline": True},
                {"name": "Alerts sent", "value": str(s.alerts_sent), "inline": True},
                {"name": "Errors", "value": str(s.errors_since_start), "inline": True},
            ],
            "footer": {"text": "PokeAlert heartbeat"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await post_to_webhook(self.webhook, embed=embed)


# ---------------------------------------------------------- HTTP /health


def build_health_app(stats: HeartbeatStats) -> web.Application:
    app = web.Application()

    async def health(_request):
        return web.json_response(stats.as_dict())

    async def root(_request):
        return web.Response(
            text="PokeAlert is running. See /health for status.\n",
            content_type="text/plain",
        )

    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)
    return app


async def run_health_server(stats: HeartbeatStats, port: int) -> web.AppRunner:
    app = build_health_app(stats)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("health_server_started", port=port)
    return runner