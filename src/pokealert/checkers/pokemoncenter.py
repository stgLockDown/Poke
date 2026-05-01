"""Pokémon Center checker.

Uses only the public product page. Detects:
  * In stock (availability JSON-LD = InStock, or add-to-cart present)
  * Out of stock
  * Queue-It active (we do NOT attempt to join or bypass — just report)
"""
from __future__ import annotations

import json
import re

import structlog
from bs4 import BeautifulSoup

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)


class PokemonCenterChecker(BaseChecker):
    retailer = "pokemoncenter"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.url:
            return self._error(product, "pokemoncenter product requires a url")

        resp = await self.http.get(product.url)
        if resp is None:
            return self._blocked(product, "no response (robots.txt disallowed or circuit open)")

        body = resp.text

        # Detect Queue-It
        if "queue-it.net" in body.lower() or "queue-it" in resp.headers.get("location", "").lower():
            return StockResult(
                product_key=product.key,
                product_name=product.name,
                retailer=self.retailer,
                state=StockState.QUEUE_ACTIVE,
                url=product.url,
                message="Queue-It active — drop is likely live right now. Visit the URL manually.",
            )

        if resp.status_code in (403, 429):
            return self._blocked(product, f"HTTP {resp.status_code} — blocked/rate limited")
        if resp.status_code != 200:
            return self._error(product, f"HTTP {resp.status_code}")

        soup = BeautifulSoup(body, "lxml")
        price: float | None = None
        state: StockState | None = None

        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") not in ("Product", "IndividualProduct"):
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
                    price = None
                if "instock" in availability:
                    state = StockState.IN_STOCK
                elif "preorder" in availability:
                    state = StockState.PRE_ORDER
                elif "outofstock" in availability or "soldout" in availability:
                    state = StockState.OUT_OF_STOCK

        if state is None:
            text = body.lower()
            # Broad sold-out signals
            if re.search(r"sold\s*out|out\s*of\s*stock|unavailable|not\s+available|currently\s+unavailable", text):
                state = StockState.OUT_OF_STOCK
            # Add-to-cart / buy button signals
            elif re.search(r"add\s*to\s*(cart|bag)|buy\s+now|add-to-cart", text):
                state = StockState.IN_STOCK
            # Pokémon Center specific data attributes
            elif '"availability":"http://schema.org/InStock"' in body or "'availability':'InStock'" in body:
                state = StockState.IN_STOCK
            elif '"availability":"http://schema.org/OutOfStock"' in body:
                state = StockState.OUT_OF_STOCK
            # React/Next.js state blob
            elif re.search(r'"isOutOfStock"\s*:\s*true', body):
                state = StockState.OUT_OF_STOCK
            elif re.search(r'"isOutOfStock"\s*:\s*false', body):
                state = StockState.IN_STOCK
            # Fallback: if page loaded ok and mentions the product, assume OOS
            elif resp.status_code == 200 and len(body) > 5000:
                state = StockState.OUT_OF_STOCK

        if state is None:
            return self._unknown(product, "Could not parse availability from page")

        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=state,
            price=price,
            url=product.url,
        )