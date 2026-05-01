"""Notifier registry."""
from __future__ import annotations

from .base import BaseNotifier
from .desktop import DesktopNotifier
from .discord import DiscordNotifier
from .email import EmailNotifier
from .telegram import TelegramNotifier


def build_notifiers(cfg: dict) -> list[BaseNotifier]:
    notifiers: list[BaseNotifier] = []

    if cfg.get("discord", {}).get("enabled"):
        n = DiscordNotifier(mention_role=cfg["discord"].get("mention_role", False))
        if n.enabled():
            notifiers.append(n)

    if cfg.get("telegram", {}).get("enabled"):
        n = TelegramNotifier()
        if n.enabled():
            notifiers.append(n)

    if cfg.get("email", {}).get("enabled"):
        n = EmailNotifier()
        if n.enabled():
            notifiers.append(n)

    if cfg.get("desktop", {}).get("enabled"):
        n = DesktopNotifier()
        if n.enabled():
            notifiers.append(n)

    return notifiers


__all__ = ["BaseNotifier", "build_notifiers"]