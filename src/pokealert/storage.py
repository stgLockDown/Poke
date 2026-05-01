"""SQLite state store."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .models import StockResult, StockState


SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_state (
    product_key TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    retailer TEXT NOT NULL,
    state TEXT NOT NULL,
    price REAL,
    currency TEXT,
    url TEXT,
    message TEXT,
    checked_at TEXT NOT NULL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    state TEXT NOT NULL,
    channels TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_log_product ON alert_log(product_key, sent_at);
"""


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def get_previous(self, product_key: str) -> StockResult | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM stock_state WHERE product_key = ?", (product_key,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return StockResult(
            product_key=row["product_key"],
            product_name=row["product_name"],
            retailer=row["retailer"],
            state=StockState(row["state"]),
            price=row["price"],
            currency=row["currency"] or "USD",
            url=row["url"],
            message=row["message"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
            raw=json.loads(row["raw_json"] or "{}"),
        )

    async def save(self, result: StockResult) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO stock_state (product_key, product_name, retailer, state,
                                          price, currency, url, message, checked_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET
                    product_name=excluded.product_name,
                    retailer=excluded.retailer,
                    state=excluded.state,
                    price=excluded.price,
                    currency=excluded.currency,
                    url=excluded.url,
                    message=excluded.message,
                    checked_at=excluded.checked_at,
                    raw_json=excluded.raw_json
                """,
                (
                    result.product_key,
                    result.product_name,
                    result.retailer,
                    result.state.value,
                    result.price,
                    result.currency,
                    result.url,
                    result.message,
                    result.checked_at.isoformat(),
                    json.dumps(result.raw, default=str),
                ),
            )
            await db.commit()

    async def last_alert_time(self, product_key: str) -> datetime | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT sent_at FROM alert_log WHERE product_key = ? ORDER BY sent_at DESC LIMIT 1",
                (product_key,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row[0])

    async def record_alert(
        self, product_key: str, state: StockState, channels: list[str]
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO alert_log (product_key, sent_at, state, channels) VALUES (?, ?, ?, ?)",
                (
                    product_key,
                    datetime.now(timezone.utc).isoformat(),
                    state.value,
                    ",".join(channels),
                ),
            )
            await db.commit()