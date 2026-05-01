"""Amazon checker using the official Product Advertising API 5.0."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)


class AmazonChecker(BaseChecker):
    retailer = "amazon"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.asin:
            return self._error(product, "amazon product requires an asin")

        access = os.getenv("AMAZON_ACCESS_KEY")
        secret = os.getenv("AMAZON_SECRET_KEY")
        tag = os.getenv("AMAZON_ASSOCIATE_TAG")
        region = os.getenv("AMAZON_REGION", "us-east-1")

        if not (access and secret and tag):
            return self._error(
                product,
                "Amazon PA-API creds missing. Set AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, "
                "AMAZON_ASSOCIATE_TAG in .env. (Requires Amazon Associates account.)",
            )

        try:
            from amazon_paapi import AmazonApi  # type: ignore
        except ImportError:
            return self._error(
                product,
                "amazon-paapi not installed. Run: pip install amazon-paapi",
            )

        try:
            amazon = AmazonApi(access, secret, tag, region)
            items = await asyncio.to_thread(amazon.get_items, product.asin)
            if not items:
                return self._unknown(product, "No items returned from PA-API")
            item: Any = items[0]

            url = getattr(item, "detail_page_url", None) or \
                  f"https://www.amazon.com/dp/{product.asin}?tag={tag}"

            offers = getattr(item, "offers", None)
            listings = getattr(offers, "listings", []) if offers else []

            state = StockState.OUT_OF_STOCK
            price = None
            if listings:
                listing = listings[0]
                avail = getattr(getattr(listing, "availability", None), "message", "") or ""
                if "in stock" in avail.lower() or "usually ships" in avail.lower():
                    state = StockState.IN_STOCK
                price_obj = getattr(listing, "price", None)
                if price_obj is not None:
                    price = getattr(price_obj, "amount", None)

            return StockResult(
                product_key=product.key,
                product_name=product.name,
                retailer=self.retailer,
                state=state,
                price=price,
                url=url,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("amazon_paapi_error")
            return self._error(product, f"PA-API error: {e}")