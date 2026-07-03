from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import DEFAULT_DB_PATH, connect, fetch_observations, fetch_product, fetch_products, init_db
from models import Product, utc_now_iso


@dataclass(frozen=True)
class AlertEvent:
    product_id: str
    product_name: str
    alert_type: str
    source: str
    current_price: float | None
    previous_price: float | None
    threshold_price: float | None
    drop_abs: float | None
    drop_pct: float | None
    message: str
    created_at: str


def check_alerts(
    db_path: str | Path = DEFAULT_DB_PATH,
    product_id: str | None = None,
    min_drop_abs: float = 10,
    min_drop_pct: float = 5,
    cooldown_hours: int = 24,
) -> list[AlertEvent]:
    init_db(db_path)
    products = _select_products(db_path, product_id)
    events: list[AlertEvent] = []
    for product in products:
        events.extend(
            _check_product_alerts(
                product=product,
                db_path=db_path,
                min_drop_abs=min_drop_abs,
                min_drop_pct=min_drop_pct / 100 if min_drop_pct > 1 else min_drop_pct,
                cooldown_hours=cooldown_hours,
            )
        )
    return events


def _check_product_alerts(
    product: Product,
    db_path: str | Path,
    min_drop_abs: float,
    min_drop_pct: float,
    cooldown_hours: int,
) -> list[AlertEvent]:
    observations = [
        row
        for row in fetch_observations(product.product_id, db_path)
        if row["buy_price"] is not None and not str(row["source"] or "").startswith("xianyu")
    ]
    if not observations:
        return []

    observations = sorted(
        observations,
        key=lambda row: (_parse_datetime(str(row["collected_at"])) or _epoch(), row["id"]),
    )
    latest = observations[-1]
    previous_rows = observations[:-1]
    current_price = float(latest["buy_price"])
    previous_price = float(previous_rows[-1]["buy_price"]) if previous_rows else None
    previous_low = min(float(row["buy_price"]) for row in previous_rows) if previous_rows else None
    now = utc_now_iso()

    candidates: list[AlertEvent] = []
    if product.target_buy_price is not None and current_price <= float(product.target_buy_price):
        candidates.append(
            AlertEvent(
                product_id=product.product_id,
                product_name=product.display_name,
                alert_type="target_buy_reached",
                source=str(latest["source"] or ""),
                current_price=current_price,
                previous_price=previous_price,
                threshold_price=float(product.target_buy_price),
                drop_abs=_drop_abs(previous_price, current_price),
                drop_pct=_drop_pct(previous_price, current_price),
                message=f"当前买入价 {current_price:.2f} 已低于或等于目标买入价 {product.target_buy_price:.2f}",
                created_at=now,
            )
        )

    if previous_low is not None and current_price < previous_low:
        candidates.append(
            AlertEvent(
                product_id=product.product_id,
                product_name=product.display_name,
                alert_type="all_time_low",
                source=str(latest["source"] or ""),
                current_price=current_price,
                previous_price=previous_low,
                threshold_price=previous_low,
                drop_abs=_drop_abs(previous_low, current_price),
                drop_pct=_drop_pct(previous_low, current_price),
                message=f"当前买入价 {current_price:.2f} 创历史新低，之前最低 {previous_low:.2f}",
                created_at=now,
            )
        )

    if previous_price is not None and current_price < previous_price:
        drop_abs = previous_price - current_price
        drop_pct = drop_abs / previous_price if previous_price else None
        if drop_abs >= min_drop_abs or (drop_pct is not None and drop_pct >= min_drop_pct):
            candidates.append(
                AlertEvent(
                    product_id=product.product_id,
                    product_name=product.display_name,
                    alert_type="price_decreased",
                    source=str(latest["source"] or ""),
                    current_price=current_price,
                    previous_price=previous_price,
                    threshold_price=None,
                    drop_abs=drop_abs,
                    drop_pct=drop_pct,
                    message=f"当前买入价较上次下降 {drop_abs:.2f}（{drop_pct:.2%}）",
                    created_at=now,
                )
            )

    inserted: list[AlertEvent] = []
    with connect(db_path) as conn:
        for event in candidates:
            if _within_cooldown(conn, event.product_id, event.alert_type, cooldown_hours):
                continue
            conn.execute(
                """
                INSERT INTO alert_events (
                    product_id,
                    alert_type,
                    source,
                    current_price,
                    previous_price,
                    threshold_price,
                    drop_abs,
                    drop_pct,
                    message,
                    created_at,
                    notified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    event.product_id,
                    event.alert_type,
                    event.source,
                    event.current_price,
                    event.previous_price,
                    event.threshold_price,
                    event.drop_abs,
                    event.drop_pct,
                    event.message,
                    event.created_at,
                ),
            )
            inserted.append(event)
    return inserted


def _select_products(db_path: str | Path, product_id: str | None) -> list[Product]:
    if product_id:
        product = fetch_product(product_id, db_path)
        return [product] if product else []
    return fetch_products(db_path)


def _within_cooldown(
    conn: object,
    product_id: str,
    alert_type: str,
    cooldown_hours: int,
) -> bool:
    if cooldown_hours <= 0:
        return False
    row = conn.execute(
        """
        SELECT created_at
        FROM alert_events
        WHERE product_id = ? AND alert_type = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (product_id, alert_type),
    ).fetchone()
    if row is None:
        return False
    created_at = _parse_datetime(str(row["created_at"]))
    if created_at is None:
        return False
    return datetime.now(timezone.utc) - created_at < timedelta(hours=cooldown_hours)


def _drop_abs(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None:
        return None
    return previous - current


def _drop_pct(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return (previous - current) / previous


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc)
