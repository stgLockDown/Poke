"""Config loader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ProductConfig


KNOWN_FIELDS = {
    "name", "retailer", "min_interval_seconds",
    "url", "tcin", "store_id", "sku", "asin",
}


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    products: list[ProductConfig] = []
    for p in data.get("products", []):
        interval = int(p.get("min_interval_seconds", 180))
        if interval < 60:
            interval = 60  # Hard floor
        extra = {k: v for k, v in p.items() if k not in KNOWN_FIELDS}
        products.append(
            ProductConfig(
                name=p["name"],
                retailer=p["retailer"],
                min_interval_seconds=interval,
                url=p.get("url"),
                tcin=p.get("tcin"),
                store_id=p.get("store_id"),
                sku=p.get("sku"),
                asin=p.get("asin"),
                extra=extra,
            )
        )
    data["products"] = products
    data.setdefault("global", {})
    data.setdefault("notifiers", {})
    data.setdefault("web_scout", {"enabled": True})
    return data