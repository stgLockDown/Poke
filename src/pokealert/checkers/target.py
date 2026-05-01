"""Target checker using the public RedSky API.

Supports:
  * Ships-to-home availability
  * Pre-order detection
  * Local pickup at a preferred store (store_id)
  * Nearby-store pickup scan (zip_code + radius)
"""
from __future__ import annotations

import os

import structlog

from ..models import ProductConfig, StockResult, StockState
from .base import BaseChecker

log = structlog.get_logger(__name__)

REDSKY_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"  # public key used by target.com itself

PDP_URL = (
    "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
    "?key={key}&tcin={tcin}&pricing_store_id={store_id}"
)

FULFILLMENT_URL = (
    "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"
    "?key={key}&tcin={tcin}&store_id={store_id}"
    "&zip={zip}&state=&latitude=&longitude="
    "&scheduled_delivery_store_id={store_id}&required_store_id={store_id}"
    "&has_required_store_id=true"
)


class TargetChecker(BaseChecker):
    retailer = "target"

    async def check(self, product: ProductConfig) -> StockResult:
        if not product.tcin:
            return self._error(product, "target product requires a tcin")

        store_id = product.store_id or "1375"
        zip_code = (
            product.extra.get("zip_code")
            or os.getenv("DEFAULT_ZIP_CODE")
            or ""
        )

        pdp_resp = await self.http.get(
            PDP_URL.format(key=REDSKY_KEY, tcin=product.tcin, store_id=store_id)
        )
        if pdp_resp is None or pdp_resp.status_code != 200:
            return self._error(
                product,
                f"PDP fetch failed: {pdp_resp.status_code if pdp_resp else 'no response'}",
            )

        try:
            pdp = pdp_resp.json()
        except Exception as e:  # noqa: BLE001
            return self._error(product, f"PDP JSON parse failed: {e}")

        product_data = pdp.get("data", {}).get("product", {})
        if not product_data:
            return self._unknown(product, "No product in PDP response")

        canonical_url = (
            product_data.get("item", {}).get("enrichment", {}).get("buy_url")
            or f"https://www.target.com/p/-/A-{product.tcin}"
        )
        price_info = product_data.get("price", {})
        price = price_info.get("current_retail")

        ff_resp = await self.http.get(
            FULFILLMENT_URL.format(
                key=REDSKY_KEY, tcin=product.tcin,
                store_id=store_id, zip=zip_code,
            )
        )
        state = StockState.OUT_OF_STOCK
        message_parts: list[str] = []
        raw: dict = {}

        if ff_resp is not None and ff_resp.status_code == 200:
            try:
                ff = ff_resp.json()
                raw = ff.get("data", {}).get("product", {}).get("fulfillment", {})
                shipping = raw.get("shipping_options", {}) or {}
                avail = str(shipping.get("availability_status", "")).upper()
                if avail == "IN_STOCK":
                    state = StockState.IN_STOCK
                    message_parts.append("📦 Ships to home")
                elif avail == "PRE_ORDER_SELLABLE":
                    state = StockState.PRE_ORDER
                    message_parts.append("Pre-order")

                # Local pickup scan
                stores = raw.get("store_options", []) or []
                local_stores = []
                for s in stores:
                    opts = s.get("order_pickup", {}) or {}
                    if str(opts.get("availability_status", "")).upper() == "IN_STOCK":
                        local_stores.append({
                            "name": s.get("location_name") or "Target",
                            "distance": s.get("distance"),
                        })

                if local_stores:
                    # Upgrade to IN_STOCK if only local had it
                    if state != StockState.IN_STOCK:
                        state = StockState.IN_STOCK
                    top = ", ".join(
                        f"{s['name']}" + (f" ({s['distance']:.1f}mi)"
                                          if s.get("distance") else "")
                        for s in local_stores[:3]
                    )
                    message_parts.append(f"🏬 Pickup at {len(local_stores)} store(s): {top}")

            except Exception as e:  # noqa: BLE001
                log.warning("target_fulfillment_parse_failed", error=str(e))

        return StockResult(
            product_key=product.key,
            product_name=product.name,
            retailer=self.retailer,
            state=state,
            price=price,
            url=canonical_url,
            message=" | ".join(message_parts) if message_parts else None,
            raw=raw,
        )