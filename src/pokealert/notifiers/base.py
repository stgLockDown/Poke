"""Abstract notifier base."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import StockResult


class BaseNotifier(ABC):
    name: str = "base"

    @abstractmethod
    async def send(self, result: StockResult) -> bool:
        ...