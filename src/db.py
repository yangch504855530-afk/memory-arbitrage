from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from models import PRODUCT_FIELDS, PriceObservation, Product, utc_now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "arbitrage.db"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                brand TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                keyword TEXT NOT NULL DEFAULT '',
                capacity TEXT NOT NULL DEFAULT '',
                frequency TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL DEFAULT '',
                form_factor TEXT NOT NULL DEFAULT '',
                buy_platform TEXT NOT NULL DEFAULT '',
                buy_url TEXT NOT NULL DEFAULT '',
                sell_platform TEXT NOT NULL DEFAULT '',
                sell_keyword TEXT NOT NULL DEFAULT '',
                target_buy_price REAL,
                target_sell_price REAL,
                min_profit_rate REAL,
                shipping_cost REAL NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                buy_price REAL,
                sell_price REAL,
                xianyu_listing_count INTEGER,
                collected_at TEXT NOT NULL,
                source TEXT NOT NULL,
                buy_source TEXT NOT NULL DEFAULT '',
                sell_source TEXT NOT NULL DEFAULT '',
                raw_payload TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(product_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_price_observations_product_time
            ON price_observations(product_id, collected_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS xianyu_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                price REAL,
                location TEXT NOT NULL DEFAULT '',
                item_updated_at TEXT NOT NULL DEFAULT '',
                want_info TEXT NOT NULL DEFAULT '',
                item_url TEXT NOT NULL DEFAULT '',
                source_file TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                raw_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(product_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_xianyu_results_product_time
            ON xianyu_results(product_id, observed_at DESC, id DESC);
            """
        )


def upsert_products(
    products: Iterable[Product],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    now = utc_now_iso()
    rows = [product.as_db_tuple() + (now, now) for product in products]
    if not rows:
        return 0

    columns = PRODUCT_FIELDS + ["created_at", "updated_at"]
    placeholders = ", ".join(["?"] * len(columns))
    update_assignments = ", ".join(
        f"{column}=excluded.{column}"
        for column in PRODUCT_FIELDS
        if column != "product_id"
    )

    sql = f"""
        INSERT INTO products ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(product_id) DO UPDATE SET
            {update_assignments},
            updated_at=excluded.updated_at
    """

    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(sql, rows)
    return len(rows)


def insert_price_observation(
    observation: PriceObservation,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    now = utc_now_iso()
    with connect(db_path) as conn:
        product = conn.execute(
            "SELECT product_id FROM products WHERE product_id = ?",
            (observation.product_id,),
        ).fetchone()
        if product is None:
            raise ValueError(
                f"Unknown product_id '{observation.product_id}'. Import products first."
            )

        cursor = conn.execute(
            """
            INSERT INTO price_observations (
                product_id,
                buy_price,
                sell_price,
                xianyu_listing_count,
                collected_at,
                source,
                buy_source,
                sell_source,
                raw_payload,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.product_id,
                observation.buy_price,
                observation.sell_price,
                observation.xianyu_listing_count,
                observation.collected_at,
                observation.source,
                observation.buy_source,
                observation.sell_source,
                observation.raw_payload,
                now,
            ),
        )
        return int(cursor.lastrowid)


def fetch_products(db_path: str | Path = DEFAULT_DB_PATH) -> list[Product]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(PRODUCT_FIELDS)} FROM products ORDER BY product_id"
        ).fetchall()
    return [Product.from_mapping(dict(row)) for row in rows]


def fetch_product(product_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> Product | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT {', '.join(PRODUCT_FIELDS)} FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
    return Product.from_mapping(dict(row)) if row else None


def fetch_latest_observation(
    product_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Row | None:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT *
            FROM price_observations
            WHERE product_id = ?
            ORDER BY collected_at DESC, id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()


def fetch_observations(
    product_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT *
            FROM price_observations
            WHERE product_id = ?
            ORDER BY collected_at DESC, id DESC
            """,
            (product_id,),
        ).fetchall()


def delete_observations_by_source(
    source: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM price_observations WHERE source = ?",
            (source,),
        )
        return int(cursor.rowcount)


def replace_xianyu_results(
    product_id: str,
    results: Iterable[dict[str, object]],
    source_file: str,
    observed_at: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    now = utc_now_iso()
    rows = [
        (
            product_id,
            str(result.get("title") or ""),
            result.get("price"),
            str(result.get("location") or ""),
            str(result.get("item_updated_at") or ""),
            str(result.get("want_info") or ""),
            str(result.get("item_url") or ""),
            source_file,
            observed_at,
            str(result.get("raw_text") or ""),
            now,
        )
        for result in results
    ]
    with connect(db_path) as conn:
        product = conn.execute(
            "SELECT product_id FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if product is None:
            raise ValueError(
                f"Unknown product_id '{product_id}'. Import products first."
            )
        conn.execute(
            "DELETE FROM xianyu_results WHERE product_id = ? AND source_file = ?",
            (product_id, source_file),
        )
        if rows:
            conn.executemany(
                """
                INSERT INTO xianyu_results (
                    product_id,
                    title,
                    price,
                    location,
                    item_updated_at,
                    want_info,
                    item_url,
                    source_file,
                    observed_at,
                    raw_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    return len(rows)


def fetch_latest_xianyu_results(
    product_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        latest = conn.execute(
            """
            SELECT observed_at
            FROM xianyu_results
            WHERE product_id = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        if latest is None:
            return []
        return conn.execute(
            """
            SELECT *
            FROM xianyu_results
            WHERE product_id = ? AND observed_at = ?
            ORDER BY price ASC, id ASC
            """,
            (product_id, latest["observed_at"]),
        ).fetchall()


def fetch_latest_xianyu_result_time(
    product_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT observed_at
            FROM xianyu_results
            WHERE product_id = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
    return str(row["observed_at"]) if row else None
