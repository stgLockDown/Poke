"""SMTP email notifier."""
from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage

import structlog

from ..models import StockResult
from .base import BaseNotifier

log = structlog.get_logger(__name__)


class EmailNotifier(BaseNotifier):
    name = "email"

    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "").strip()
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "").strip()
        self.password = os.getenv("SMTP_PASSWORD", "").strip()
        self.from_addr = os.getenv("SMTP_FROM", self.user).strip()
        self.to_addr = os.getenv("SMTP_TO", "").strip()

    def enabled(self) -> bool:
        return bool(self.host and self.user and self.password and self.to_addr)

    async def send(self, result: StockResult) -> bool:
        if not self.enabled():
            log.warning("email_disabled_no_creds")
            return False

        msg = EmailMessage()
        msg["Subject"] = f"[PokeAlert] IN STOCK: {result.product_name}"
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr

        price_str = f"${result.price:.2f} {result.currency}" if result.price else "—"
        body = (
            f"{result.product_name}\n"
            f"Retailer: {result.retailer}\n"
            f"Status: {result.state.value}\n"
            f"Price: {price_str}\n"
        )
        if result.message:
            body += f"Note: {result.message}\n"
        if result.url:
            body += f"\nURL: {result.url}\n"
        body += f"\nChecked at: {result.checked_at.isoformat()}\n"
        msg.set_content(body)

        def _send_sync() -> bool:
            try:
                with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                    s.starttls()
                    s.login(self.user, self.password)
                    s.send_message(msg)
                return True
            except Exception as e:  # noqa: BLE001
                log.exception("email_send_failed", error=str(e))
                return False

        return await asyncio.to_thread(_send_sync)