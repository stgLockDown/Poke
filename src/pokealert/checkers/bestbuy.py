"""Best Buy checker using the official Products API + Stores API for local stock.

Requires BESTBUY_API_KEY in .env. Get a free key at https://developer.bestbuy.com/

Local stock:
  If a product has `zip_code` and `radius` configured, we additionally query the
  in-store availability API and report the nearest store that has it. This is
  the official, documented, blessed way to do this.
"""
from __future__ import annotations

import os

import structlog

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)


BBY_PRODUCT_URL = (
    "https://api.bestbuy.com/v1/products(sku={sku})"
    "?apiKey={key}&format=json"
    "&show=sku,name,salePrice,regularPrice,onlineAvailability,"
    "orderable,url,addToCartUrl,preowned"
)

# Docs: https://bestbuyapis.github.io/api-documentation/#in-store-availability
BBY_STORES_URL = (
    "https://api.bestbuy.com/v1/stores(area({zip},{radius}))"
    "+products(sku={sku})?apiKey={key}&format=json"
    "&show=storeId,storeType,name,city,region,distance,products.inStoreAvailability"
)


class BestBuyChecker(BaseChecker):
    retailer = "bestbuy"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.sku:
            return self._error(product, "bestbuy product requires a sku")

        key = os.getenv("BESTBUY_API_KEY")
        if not key:
            return self._blocked(
                product,
                "BESTBUY_API_KEY not set. Get a free key at developer.bestbuy.com",
            )

        # -------- Online availability --------
        url = BBY_PRODUCT_URL.format(sku=product.sku, key=key)
        resp = await self.http.get(url)
        if resp is None:
            return self._blocked(product, "no response (robots.txt or circuit open)")
        if resp.status_code in (403, 429):
            return self._blocked(product, f"HTTP {resp.status_code} — blocked/rate limited")
        if resp.status_code != 200:
            return self._error(product, f"API HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return self._error(product, f"JSON parse failed: {e}")

        products = data.get("products", [])
        if not products:
            return self._unknown(product, "No products in API response")

        item = products[0]
        canonical_url = item.get("url") or f"https://www.bestbuy.com/site/sku/{product.sku}.p"
        price = item.get("salePrice") or item.get("regularPrice")

        online_avail = item.get("onlineAvailability")
        orderable = str(item.get("orderable", "")).lower()

        if orderable == "preorder":
            state = StockState.PRE_ORDER
        elif online_avail is True or orderable == "available":
            state = StockState.IN_STOCK
        elif online_avail is False or orderable in ("soldout", "comingsoon", "backorder"):
            state = StockState.OUT_OF_STOCK
        else:
            state = StockState.UNKNOWN

        message_parts = [f"orderable={orderable}"]

        # -------- Local / in-store availability (optional) --------
        zip_code = product.extra.get("zip_code") or os.getenv("DEFAULT_ZIP_CODE")
        radius = product.extra.get("radius", 25)
        if zip_code:
            try:
                local_stores = await self._check_local(product.sku, key, zip_code, int(radius))
                if local_stores:
                    message_parts.append(
                        f"🏬 Local stock at {len(local_stores)} store(s): "
                        + ", ".join(f"{s['name']} ({s['distance']}mi)"
                                    for s in local_stores[:3])
                    )
                    # Upgrade state to IN_STOCK if any local store has it
                    if state != StockState.IN_STOCK:
                        state = StockState.IN_STOCK
            except Exception as e:  # noqa: BLE001
                log.warning("bestbuy_local_check_failed", error=str(e))

        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=state,
            price=price,
            url=canonical_url,
            message="; ".join(message_parts),
        )

    async def _check_local(
        self, sku: str, key: str, zip_code: str, radius: int
    ) -> list[dict]:
        url = BBY_STORES_URL.format(zip=zip_code, radius=radius, sku=sku, key=key)
        resp = await self.http.get(url)
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return []

        stores_with_stock: list[dict] = []
        for store in data.get("stores", []):
            for sp in store.get("products", []):
                if sp.get("inStoreAvailability"):
                    stores_with_stock.append({
                        "name": store.get("name") or store.get("city", "?"),
                        "city": store.get("city"),
                        "region": store.get("region"),
                        "distance": store.get("distance"),
                        "storeId": store.get("storeId"),
                    })
                    break
        # Sort by distance
        stores_with_stock.sort(key=lambda s: s.get("distance") or 999)
        return stores_with_stock