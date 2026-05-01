"""Polite async HTTP client with rate limiting, backoff, and robots.txt checks."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger(__name__)


DEFAULT_UA = (
    "PokeAlert/1.0 (+https://github.com/yourname/pokealert; "
    "ethical-stock-monitor; contact=you@example.com)"
)

# When a proxy (residential/mobile) is configured, the user is running
# against retailer WAFs on their own legal/contractual terms. In that mode
# we present a normal browser UA so the IP-rotated traffic isn't blocked
# purely on UA grounds. The UA itself doesn't claim to be the PokeAlert bot
# in that mode; that trade-off is explicit and user-controlled via PROXY_URL.
BROWSER_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 "
    "Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 "
    "Firefox/125.0",
]


class PoliteHttpClient:
    """httpx.AsyncClient wrapper that is polite:
       * Self-identifying User-Agent
       * Per-host minimum delay between requests
       * robots.txt compliance (cached 24h)
       * Exponential-backoff retries on 429/503/network errors
       * Circuit breaker per host
    """

    def __init__(
        self,
        user_agent: str | None = None,
        per_host_min_interval: float = 1.5,
        respect_robots: bool = True,
        circuit_threshold: int = 5,
        circuit_cooldown: float = 600.0,
        timeout: float = 20.0,
    ):
        # --- Proxy support ---------------------------------------------------
        # PROXY_URL: e.g. http://user:pass@host:port  OR  socks5://host:port
        # When set, we assume the user has chosen to route through a
        # residential/mobile proxy to bypass datacenter-IP WAF blocks.
        self.proxy_url = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY")
        self.proxy_mode = bool(self.proxy_url)

        # In proxy mode, use a browser UA and rotate it per request to look
        # like normal residential traffic instead of a self-identifying bot.
        if self.proxy_mode:
            self.user_agent = user_agent or os.getenv(
                "USER_AGENT", BROWSER_UA_POOL[0]
            )
            self._ua_pool = list(BROWSER_UA_POOL)
        else:
            self.user_agent = user_agent or os.getenv("USER_AGENT", DEFAULT_UA)
            self._ua_pool = []

        self.per_host_min_interval = per_host_min_interval
        self.respect_robots = respect_robots
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown = circuit_cooldown

        # http2 is nice but requires the `h2` package; fall back gracefully.
        try:
            import h2  # noqa: F401
            http2 = True
        except ImportError:
            http2 = False

        client_kwargs: dict[str, Any] = dict(
            http2=http2,
            timeout=timeout,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        if self.proxy_mode:
            # httpx accepts `proxy=` (newer) or `proxies=` (older). Use proxy.
            try:
                client_kwargs["proxy"] = self.proxy_url
                self._client = httpx.AsyncClient(**client_kwargs)
            except TypeError:
                client_kwargs.pop("proxy", None)
                client_kwargs["proxies"] = self.proxy_url
                self._client = httpx.AsyncClient(**client_kwargs)
            log.info("http_client_proxy_enabled",
                     host=urlparse(self.proxy_url).hostname)
        else:
            self._client = httpx.AsyncClient(**client_kwargs)

        self._last_request_at: dict[str, float] = {}
        self._host_lock: dict[str, asyncio.Lock] = {}
        self._robots_cache: dict[str, tuple[RobotFileParser, float]] = {}
        self._error_count: dict[str, int] = {}
        self._host_paused_until: dict[str, float] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._host_lock:
            self._host_lock[host] = asyncio.Lock()
        return self._host_lock[host]

    async def _is_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        now = time.time()

        cached = self._robots_cache.get(host)
        if cached and now - cached[1] < 86400:
            rp = cached[0]
        else:
            rp = RobotFileParser()
            robots_url = f"{host}/robots.txt"
            try:
                resp = await self._client.get(robots_url, timeout=10)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.parse(["User-agent: *", "Allow: /"])
            except Exception as e:  # noqa: BLE001
                log.warning("robots_fetch_failed", host=host, error=str(e))
                rp.parse(["User-agent: *", "Allow: /"])
            self._robots_cache[host] = (rp, now)

        return rp.can_fetch(self.user_agent, url)

    def _host_is_paused(self, host: str) -> bool:
        return time.time() < self._host_paused_until.get(host, 0)

    def _record_error(self, host: str) -> None:
        self._error_count[host] = self._error_count.get(host, 0) + 1
        if self._error_count[host] >= self.circuit_threshold:
            self._host_paused_until[host] = time.time() + self.circuit_cooldown
            log.warning("circuit_breaker_tripped", host=host,
                        cooldown_seconds=self.circuit_cooldown)
            self._error_count[host] = 0

    def _record_success(self, host: str) -> None:
        self._error_count[host] = 0

    async def get(self, url: str, **kwargs: Any) -> httpx.Response | None:
        parsed = urlparse(url)
        host = parsed.netloc

        if self._host_is_paused(host):
            log.info("host_paused_skip", host=host, url=url)
            return None

        if not await self._is_allowed(url):
            log.warning("robots_disallowed", url=url)
            return None

        async with self._lock(host):
            last = self._last_request_at.get(host, 0)
            delta = time.time() - last
            if delta < self.per_host_min_interval:
                await asyncio.sleep(self.per_host_min_interval - delta)
            self._last_request_at[host] = time.time()

        # In proxy mode, rotate UA per request to blend into residential traffic.
        req_headers = dict(kwargs.pop("headers", {}) or {})
        if self.proxy_mode and self._ua_pool:
            import random
            req_headers.setdefault("User-Agent", random.choice(self._ua_pool))
            req_headers.setdefault(
                "Accept",
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8",
            )
            req_headers.setdefault("Accept-Language", "en-US,en;q=0.9")
            req_headers.setdefault("Sec-Fetch-Dest", "document")
            req_headers.setdefault("Sec-Fetch-Mode", "navigate")
            req_headers.setdefault("Sec-Fetch-Site", "none")
            req_headers.setdefault("Upgrade-Insecure-Requests", "1")

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=2, min=2, max=30),
                retry=retry_if_exception_type(
                    (httpx.TransportError, httpx.TimeoutException)
                ),
                reraise=True,
            ):
                with attempt:
                    resp = await self._client.get(
                        url, headers=req_headers, **kwargs
                    )

            if resp.status_code in (429, 503):
                retry_after = int(resp.headers.get("Retry-After", "30"))
                log.warning("rate_limited", host=host, status=resp.status_code,
                            retry_after=retry_after)
                await asyncio.sleep(min(retry_after, 120))
                self._record_error(host)
                return resp

            if resp.status_code >= 500:
                self._record_error(host)
            else:
                self._record_success(host)
            return resp

        except Exception as e:  # noqa: BLE001
            log.error("http_error", url=url, error=str(e))
            self._record_error(host)
            return None