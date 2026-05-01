"""Telegram bot notifier (plain HTTP API)."""
from __future__ import annotations

import os

import httpx
import structlog

from ..models import StockResult
from .base import BaseNotifier

log = structlog.get_logger(__name__)


class TelegramNotifier(BaseNotifier):
    name = "telegram"

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send(self, result: StockResult) -> bool:
        if not self.enabled():
            log.warning("telegram_disabled_no_creds")
            return False

        price_str = f"${result.price:.2f}" if result.price else "—"
        text = (
            f"🟢 *IN STOCK*: {self._esc(result.product_name)}\n"
            f"Retailer: `{result.retailer}`\n"
            f"Price: {price_str}\n"
        )
        if result.message:
            text += f"Note: _{self._esc(result.message)}_\n"
        if result.url:
            text += f"\n[Open product]({result.url})"

        api = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(api, json=payload)
                if resp.status_code == 200:
                    return True
                log.error("telegram_send_failed", status=resp.status_code, body=resp.text[:500])
                return False
        except Exception as e:  # noqa: BLE001
            log.exception("telegram_send_exception", error=str(e))
            return False

    @staticmethod
    def _esc(text: str) -> str:
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, "\\" + ch)
        return text