"""Abstract base checker."""
from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from ..http_client import PoliteHttpClient
from ..models import ProductConfig, StockResult, StockState

log = structlog.get_logger(__name__)


class BaseChecker(ABC):
    retailer: str = "base"

    def __init__(self, http: PoliteHttpClient):
        self.http = http

    @abstractmethod
    async def check(self, product: ProductConfig) -> StockResult:
        ...

    def _error(self, product: ProductConfig, message: str) -> StockResult:
        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=StockState.ERROR,
            url=product.url,
            message=message,
        )

    def _unknown(self, product: ProductConfig, message: str) -> StockResult:
        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=StockState.UNKNOWN,
            url=product.url,
            message=message,
        )