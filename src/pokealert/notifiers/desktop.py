"""Desktop notification fallback (optional)."""
from __future__ import annotations

import asyncio

import structlog

from ..models import StockResult
from .base import BaseNotifier

log = structlog.get_logger(__name__)


class DesktopNotifier(BaseNotifier):
    name = "desktop"

    def enabled(self) -> bool:
        try:
            import plyer  # noqa: F401
            return True
        except ImportError:
            return False

    async def send(self, result: StockResult) -> bool:
        if not self.enabled():
            return False

        def _send() -> bool:
            try:
                from plyer import notification  # type: ignore
                notification.notify(
                    title=f"IN STOCK: {result.product_name}",
                    message=f"{result.retailer} — {result.url or ''}",
                    app_name="PokeAlert",
                    timeout=15,
                )
                return True
            except Exception as e:  # noqa: BLE001
                log.exception("desktop_notify_failed", error=str(e))
                return False

        return await asyncio.to_thread(_send)