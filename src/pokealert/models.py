"""Core data models for PokeAlert."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class StockState(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PRE_ORDER = "pre_order"
    QUEUE_ACTIVE = "queue_active"
    UNKNOWN = "unknown"
    ERROR = "error"
    BLOCKED = "blocked"   # Expected/permanent block (robots.txt, WAF 403, etc.)


@dataclass
class ProductConfig:
    name: str
    retailer: str
    min_interval_seconds: int = 180
    url: str | None = None
    tcin: str | None = None
    store_id: str | None = None
    sku: str | None = None
    asin: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        ident = self.url or self.tcin or self.sku or self.asin or self.name
        return f"{self.retailer}::{ident}"


@dataclass
class StockResult:
    product_key: str
    product_name: str
    retailer: str
    state: StockState
    price: float | None = None
    currency: str = "USD"
    url: str | None = None
    message: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = field(default_factory=dict)

    def is_transition_to_in_stock(self, previous: "StockResult | None") -> bool:
        if self.state != StockState.IN_STOCK:
            return False
        if previous is None:
            return True
        return previous.state != StockState.IN_STOCK