"""Walmart checker using the public product page."""
from __future__ import annotations

import json
import re

import structlog
from bs4 import BeautifulSoup

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)


class WalmartChecker(BaseChecker):
    retailer = "walmart"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.url:
            return self._error(product, "walmart product requires a url")

        resp = await self.http.get(product.url)
        if resp is None:
            return self._blocked(product, "no response (robots.txt disallowed or circuit open)")
        if resp.status_code in (403, 412):
            return self._blocked(product, f"HTTP {resp.status_code} — WAF/bot challenge blocking datacenter IP")
        if resp.status_code == 429:
            return self._blocked(product, "HTTP 429 — rate limited")
        if resp.status_code != 200:
            return self._error(product, f"HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")

        state: StockState = StockState.UNKNOWN
        price: float | None = None
        message = None

        if tag and tag.string:
            try:
                data = json.loads(tag.string)
                initial = data.get("props", {}).get("pageProps", {}).get("initialData", {})
                node = initial.get("data", {}).get("product") or {}
                avail = str(node.get("availabilityStatus", "")).upper()
                price_node = (node.get("priceInfo", {}) or {}).get("currentPrice", {}) or {}
                price = price_node.get("price")

                if avail == "IN_STOCK":
                    state = StockState.IN_STOCK
                elif avail == "OUT_OF_STOCK":
                    state = StockState.OUT_OF_STOCK
                elif avail == "LIMITED_STOCK":
                    state = StockState.IN_STOCK
                    message = "Limited stock"
                elif avail in ("PREORDER", "PRE_ORDER"):
                    state = StockState.PRE_ORDER
            except Exception as e:  # noqa: BLE001
                log.warning("walmart_parse_failed", error=str(e))

        if state == StockState.UNKNOWN:
            text = resp.text.lower()
            if re.search(r"out of stock|unavailable", text):
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
            message=message,
        )