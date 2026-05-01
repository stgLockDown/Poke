"""Web-search restock scout.

Periodically asks a search provider for recent restock news for TCGs / collectibles
and posts summaries to a dedicated Discord channel.

Supported providers:
  * Brave Search API   (BRAVE_API_KEY) — recommended, best free tier
  * Serper.dev         (SERPER_API_KEY)
  * SerpAPI            (SERPAPI_API_KEY)

If no API key is configured, this module stays idle and logs a one-time warning.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
import structlog

from .notifiers.discord import post_to_webhook

log = structlog.get_logger(__name__)


DEFAULT_QUERIES: list[str] = [
    # Pokémon
    "Pokemon TCG restock",
    "Pokemon Elite Trainer Box restock",
    "Pokemon booster box in stock",
    # Expanded TCGs
    "One Piece TCG restock",
    "MetaZoo TCG restock",
    "Lorcana restock",
    "Magic the Gathering restock announcement",
    "Yu-Gi-Oh restock",
]


class WebScout:
    def __init__(
        self,
        queries: list[str] | None = None,
        interval_seconds: int = 1800,
        state_path: str = "data/web_scout_seen.json",
    ):
        self.queries = queries or DEFAULT_QUERIES
        self.interval = max(600, interval_seconds)  # min 10 min to be polite
        self.webhook = os.getenv("DISCORD_WEBHOOK_WEB_RESTOCKS", "").strip()
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = self._load_seen()
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    def _load_seen(self) -> set[str]:
        if self.state_path.exists():
            try:
                return set(json.loads(self.state_path.read_text()))
            except Exception:  # noqa: BLE001
                return set()
        return set()

    def _save_seen(self) -> None:
        # Keep the set bounded
        if len(self._seen) > 2000:
            self._seen = set(list(self._seen)[-1500:])
        self.state_path.write_text(json.dumps(list(self._seen)))

    # ---------------------------------------------------------------- run

    async def run(self) -> None:
        if not self.webhook:
            log.warning(
                "web_scout_disabled",
                reason="DISCORD_WEBHOOK_WEB_RESTOCKS not set",
            )
            return

        provider = self._detect_provider()
        if not provider:
            log.warning(
                "web_scout_no_provider",
                hint="Set BRAVE_API_KEY or SERPER_API_KEY or SERPAPI_API_KEY",
            )
            return

        log.info("web_scout_starting", provider=provider, queries=len(self.queries))

        # First tick after a short delay (let app settle)
        await asyncio.sleep(30)

        while not self._stop.is_set():
            try:
                await self._tick(provider)
            except Exception:
                log.exception("web_scout_tick_failed")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    # ---------------------------------------------------------------- providers

    @staticmethod
    def _detect_provider() -> str | None:
        if os.getenv("BRAVE_API_KEY"):
            return "brave"
        if os.getenv("SERPER_API_KEY"):
            return "serper"
        if os.getenv("SERPAPI_API_KEY"):
            return "serpapi"
        return None

    async def _tick(self, provider: str) -> None:
        new_items: list[dict] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for q in self.queries:
                try:
                    results = await self._search(client, provider, q)
                except Exception as e:  # noqa: BLE001
                    log.warning("web_scout_search_failed", query=q, error=str(e))
                    continue
                for r in results:
                    key = hashlib.sha1((r.get("url", "") or r.get("title", "")).encode()).hexdigest()
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                    r["_query"] = q
                    new_items.append(r)
                await asyncio.sleep(1.0)  # polite inter-query delay

        self._save_seen()

        if not new_items:
            log.info("web_scout_no_new_items")
            return

        log.info("web_scout_new_items", count=len(new_items))
        # Post up to 10 per tick to avoid flooding the channel
        for item in new_items[:10]:
            await self._post_item(item)
            await asyncio.sleep(1.0)

    async def _search(self, client: httpx.AsyncClient, provider: str,
                      query: str) -> list[dict]:
        if provider == "brave":
            return await self._search_brave(client, query)
        if provider == "serper":
            return await self._search_serper(client, query)
        if provider == "serpapi":
            return await self._search_serpapi(client, query)
        return []

    async def _search_brave(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        key = os.getenv("BRAVE_API_KEY", "")
        headers = {"X-Subscription-Token": key, "Accept": "application/json"}
        params = {"q": query, "count": 10, "freshness": "pd"}  # past day
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers, params=params,
        )
        if resp.status_code != 200:
            log.warning("brave_http", status=resp.status_code)
            return []
        data = resp.json()
        results = []
        for r in (data.get("web", {}) or {}).get("results", []) or []:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", "") or r.get("extra_snippets", [""])[0] if r.get("extra_snippets") else "",
                "source": r.get("url", "").split("/")[2] if r.get("url") else "",
                "published": r.get("age", ""),
            })
        return results

    async def _search_serper(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        key = os.getenv("SERPER_API_KEY", "")
        headers = {"X-API-KEY": key, "Content-Type": "application/json"}
        resp = await client.post(
            "https://google.serper.dev/news",
            headers=headers,
            json={"q": query, "tbs": "qdr:d"},  # past day
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for r in data.get("news", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "source": r.get("source", ""),
                "published": r.get("date", ""),
            })
        return results

    async def _search_serpapi(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        key = os.getenv("SERPAPI_API_KEY", "")
        resp = await client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google_news", "q": query, "api_key": key, "when": "1d"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for r in data.get("news_results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "source": r.get("source", {}).get("name", "") if isinstance(r.get("source"), dict) else str(r.get("source", "")),
                "published": r.get("date", ""),
            })
        return results

    # ---------------------------------------------------------------- post

    async def _post_item(self, item: dict) -> None:
        embed = {
            "title": (item.get("title") or "Restock news")[:256],
            "url": item.get("url", ""),
            "description": (item.get("snippet") or "")[:400],
            "color": 0x9B59B6,   # purple for web-scout
            "fields": [
                {"name": "Search", "value": item.get("_query", "—"), "inline": True},
                {"name": "Source", "value": item.get("source", "—") or "—", "inline": True},
                {"name": "Published", "value": item.get("published", "—") or "—", "inline": True},
            ],
            "footer": {"text": "PokeAlert • Web Scout • Verify independently before acting"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await post_to_webhook(self.webhook, embed=embed)