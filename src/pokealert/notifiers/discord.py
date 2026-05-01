"""Discord webhook notifier with per-retailer channel routing.

Routing strategy:
    DISCORD_WEBHOOK_<RETAILER>  — one channel per retailer (e.g. DISCORD_WEBHOOK_TARGET)
    DISCORD_WEBHOOK_URL         — fallback if no per-retailer webhook is set
    DISCORD_WEBHOOK_WEB_RESTOCKS— channel for web-search restock news
    DISCORD_WEBHOOK_HEARTBEAT   — channel for health / heartbeat pings

Retailer-specific role mentions:
    DISCORD_ROLE_<RETAILER>     — @mention this role when that retailer alerts
    DISCORD_ROLE_ID             — fallback role
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
import structlog

from ..models import StockResult, StockState
from .base import BaseNotifier

log = structlog.get_logger(__name__)


# Retailer → accent color for embeds (Discord decimal colors)
RETAILER_COLORS = {
    "pokemoncenter": 0xFFCB05,   # Pokémon yellow
    "target":        0xCC0000,   # Target red
    "bestbuy":       0x0046BE,   # Best Buy blue
    "walmart":       0x0071CE,   # Walmart blue
    "gamestop":      0xE41E26,   # GameStop red
    "amazon":        0xFF9900,   # Amazon orange
    "costco":        0x005DAA,   # Costco blue
}

RETAILER_EMOJI = {
    "pokemoncenter": "🟡",
    "target":        "🎯",
    "bestbuy":       "🔵",
    "walmart":       "🛒",
    "gamestop":      "🎮",
    "amazon":        "📦",
    "costco":        "🏬",
}

STATE_COLOR = {
    StockState.IN_STOCK:     0x2ECC71,  # green
    StockState.PRE_ORDER:    0x3498DB,  # blue
    StockState.QUEUE_ACTIVE: 0xF39C12,  # orange
    StockState.OUT_OF_STOCK: 0x95A5A6,  # grey
    StockState.UNKNOWN:      0x95A5A6,
    StockState.ERROR:        0xE74C3C,  # red
    StockState.BLOCKED:      0x7F8C8D,  # dark grey
}

STATE_EMOJI = {
    StockState.IN_STOCK:     "🟢 IN STOCK",
    StockState.PRE_ORDER:    "🔵 PRE-ORDER",
    StockState.QUEUE_ACTIVE: "🟠 QUEUE ACTIVE",
    StockState.OUT_OF_STOCK: "🔴 Out of Stock",
    StockState.UNKNOWN:      "❔ Unknown",
    StockState.ERROR:        "⚠️ Error",
    StockState.BLOCKED:      "⛔ Blocked",
}


class DiscordNotifier(BaseNotifier):
    """Sends embed to the Discord webhook mapped to the product's retailer."""

    name = "discord"

    def __init__(self, mention_role: bool = False):
        self.default_webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        self.default_role_id = os.getenv("DISCORD_ROLE_ID", "").strip()
        self.mention_role = mention_role

    # ---------------------------------------------------------------- routing

    def _webhook_for(self, retailer: str) -> Optional[str]:
        env_key = f"DISCORD_WEBHOOK_{retailer.upper()}"
        url = (os.getenv(env_key, "") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            url = ""
        fallback = (self.default_webhook or "").strip()
        if fallback and not fallback.startswith(("http://", "https://")):
            fallback = ""
        return url or fallback or None

    def _role_for(self, retailer: str) -> str:
        env_key = f"DISCORD_ROLE_{retailer.upper()}"
        return os.getenv(env_key, "").strip() or self.default_role_id

    def enabled(self) -> bool:
        if self.default_webhook:
            return True
        # Enabled if *any* per-retailer webhook is set
        for key in os.environ:
            if key.startswith("DISCORD_WEBHOOK_") and os.environ[key].strip():
                return True
        return False

    # ---------------------------------------------------------------- send

    async def send(self, result: StockResult) -> bool:
        webhook = self._webhook_for(result.retailer)
        if not webhook:
            log.warning(
                "discord_no_webhook_for_retailer",
                retailer=result.retailer,
                hint=f"Set DISCORD_WEBHOOK_{result.retailer.upper()} or DISCORD_WEBHOOK_URL",
            )
            return False

        content = None
        if self.mention_role:
            role_id = self._role_for(result.retailer)
            if role_id:
                content = f"<@&{role_id}>"

        embed = self._build_embed(result)
        payload = {"content": content, "embeds": [embed]}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(webhook, json=payload)
                if resp.status_code in (200, 204):
                    return True
                log.error(
                    "discord_send_failed",
                    retailer=result.retailer,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                return False
        except Exception as e:  # noqa: BLE001
            log.exception("discord_send_exception", error=str(e))
            return False

    # ---------------------------------------------------------------- embed

    @staticmethod
    def _build_embed(result: StockResult) -> dict:
        state = result.state
        retailer_label = result.retailer.replace("_", " ").title()
        r_emoji = RETAILER_EMOJI.get(result.retailer, "🏪")

        # Color: use state color if in-stock-ish, else retailer color
        if state in (StockState.IN_STOCK, StockState.PRE_ORDER, StockState.QUEUE_ACTIVE):
            color = STATE_COLOR[state]
        else:
            color = RETAILER_COLORS.get(result.retailer, 0x7F8C8D)

        price_str = (
            f"**${result.price:.2f}** {result.currency}" if result.price else "—"
        )
        state_label = STATE_EMOJI.get(state, state.value)

        fields = [
            {"name": "Status", "value": state_label, "inline": True},
            {"name": "Price", "value": price_str, "inline": True},
            {"name": "Retailer", "value": f"{r_emoji} {retailer_label}", "inline": True},
        ]

        if result.message:
            fields.append({"name": "Note", "value": result.message[:1024], "inline": False})

        # Always include a direct link as a clear, clickable field
        if result.url:
            fields.append(
                {
                    "name": "🔗 Direct Link",
                    "value": f"[Open product page →]({result.url})",
                    "inline": False,
                }
            )

        embed = {
            "title": result.product_name[:256],
            "url": result.url or "",
            "color": color,
            "fields": fields,
            "footer": {
                "text": "PokeAlert • Ethical monitor • Please buy only what you need",
            },
            "timestamp": result.checked_at.isoformat(),
        }
        return embed


# ---------------------------------------------------------------- helpers


async def post_to_webhook(webhook_url: str, *, content: str | None = None,
                          embed: dict | None = None) -> bool:
    """Standalone helper used by heartbeat and web-search modules."""
    if not webhook_url:
        return False
    webhook_url = webhook_url.strip()
    if not webhook_url.startswith(("http://", "https://")):
        log.warning("invalid_webhook_url_skipped", url_preview=webhook_url[:30])
        return False
    payload: dict = {}
    if content:
        payload["content"] = content
    if embed:
        payload["embeds"] = [embed]
    if not payload:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(webhook_url, json=payload)
            return resp.status_code in (200, 204)
    except Exception as e:  # noqa: BLE001
        log.exception("webhook_post_failed", error=str(e))
        return False