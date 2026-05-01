"""GameStop checker using the public product page."""
from __future__ import annotations

import json
import re

import structlog
from bs4 import BeautifulSoup

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)


class GameStopChecker(BaseChecker):
    retailer = "gamestop"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.url:
            return self._error(product, "gamestop product requires a url")

        resp = await self.http.get(product.url)
        if resp is None:
            return self._error(product, "no response (blocked / paused / robots)")
        if resp.status_code != 200:
            return self._error(product, f"HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "lxml")
        state: StockState = StockState.UNKNOWN
        price: float | None = None

        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict) or item.get("@type") != "Product":
                    continue
                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if not isinstance(offers, dict):
                    continue
                availability = str(offers.get("availability", "")).lower()
                try:
                    price = float(offers.get("price")) if offers.get("price") else None
                except (TypeError, ValueError):
                    pass
                if "instock" in availability:
                    state = StockState.IN_STOCK
                elif "preorder" in availability:
                    state = StockState.PRE_ORDER
                elif "outofstock" in availability or "soldout" in availability:
                    state = StockState.OUT_OF_STOCK

        if state == StockState.UNKNOWN:
            text = resp.text.lower()
            if re.search(r"not available|sold out|out of stock", text):
                state = StockState.OUT_OF_STOCK
            elif re.search(r"add to cart", text):
                state = StockState.IN_STOCK

        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=state,
            price=price,
            url=product.url,
        )