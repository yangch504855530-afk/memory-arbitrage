from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from db import DEFAULT_DB_PATH, fetch_observations, fetch_products
from models import Product


CLOSE_TO_TARGET_RATIO = 1.05


@dataclass(frozen=True)
class SearchKeywordRow:
    product_id: str
    product_name: str
    sell_keyword: str
    suggested_keyword: str


@dataclass(frozen=True)
class BuyLinkRow:
    product_id: str
    product_name: str
    buy_platform: str
    buy_url: str
    target_buy_price: float | None


@dataclass(frozen=True)
class CollectionPlanRow:
    product_id: str
    product_name: str
    never_collected: bool
    overdue_24h: bool
    close_to_target_buy_price: bool
    priority: str
    latest_buy_price: float | None
    target_buy_price: float | None
    latest_collected_at: str
    reason: str


def build_search_keywords(db_path: str | Path = DEFAULT_DB_PATH) -> list[SearchKeywordRow]:
    rows: list[SearchKeywordRow] = []
    for product in fetch_products(db_path):
        suggested = _suggested_sell_keyword(product)
        rows.append(
            SearchKeywordRow(
                product_id=product.product_id,
                product_name=product.display_name,
                sell_keyword=product.sell_keyword,
                suggested_keyword=suggested,
            )
        )
    return rows


def build_buy_links(db_path: str | Path = DEFAULT_DB_PATH) -> list[BuyLinkRow]:
    rows: list[BuyLinkRow] = []
    for product in fetch_products(db_path):
        rows.append(
            BuyLinkRow(
                product_id=product.product_id,
                product_name=product.display_name,
                buy_platform=product.buy_platform,
                buy_url=product.buy_url,
                target_buy_price=product.target_buy_price,
            )
        )
    return rows


def build_collection_plan(db_path: str | Path = DEFAULT_DB_PATH) -> list[CollectionPlanRow]:
    rows: list[CollectionPlanRow] = []
    now = datetime.now(timezone.utc)

    for product in fetch_products(db_path):
        latest = _latest_observation(product.product_id, db_path)
        never_collected = latest is None
        latest_buy_price = latest["buy_price"] if latest else None
        latest_collected_at = str(latest["collected_at"]) if latest else ""
        latest_dt = _parse_datetime(latest_collected_at)
        overdue_24h = bool(latest_dt and (now - latest_dt).total_seconds() > 24 * 3600)
        close_to_target = _is_close_to_target(latest_buy_price, product.target_buy_price)

        if not (never_collected or overdue_24h or close_to_target):
            continue

        priority = _priority(
            never_collected=never_collected,
            overdue_24h=overdue_24h,
            close_to_target=close_to_target,
            latest_buy_price=latest_buy_price,
            target_buy_price=product.target_buy_price,
        )
        rows.append(
            CollectionPlanRow(
                product_id=product.product_id,
                product_name=product.display_name,
                never_collected=never_collected,
                overdue_24h=overdue_24h,
                close_to_target_buy_price=close_to_target,
                priority=priority,
                latest_buy_price=latest_buy_price,
                target_buy_price=product.target_buy_price,
                latest_collected_at=latest_collected_at,
                reason=_reason(never_collected, overdue_24h, close_to_target),
            )
        )

    priority_order = {"高": 0, "中": 1, "低": 2}
    return sorted(rows, key=lambda row: (priority_order[row.priority], row.product_id))


def _latest_observation(product_id: str, db_path: str | Path) -> object | None:
    observations = fetch_observations(product_id, db_path)
    if not observations:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(
        observations,
        key=lambda row: (_parse_datetime(row["collected_at"]) or epoch, row["id"]),
        reverse=True,
    )[0]


def _suggested_sell_keyword(product: Product) -> str:
    if product.sell_keyword:
        return product.sell_keyword
    if product.keyword:
        return product.keyword
    parts = [
        product.brand,
        product.model,
        product.capacity,
        product.frequency,
        product.memory_type,
        product.form_factor,
    ]
    return " ".join(part for part in parts if part).strip()


def _is_close_to_target(
    latest_buy_price: float | None,
    target_buy_price: float | None,
) -> bool:
    if latest_buy_price is None or target_buy_price is None or target_buy_price <= 0:
        return False
    return latest_buy_price <= target_buy_price * CLOSE_TO_TARGET_RATIO


def _priority(
    never_collected: bool,
    overdue_24h: bool,
    close_to_target: bool,
    latest_buy_price: float | None,
    target_buy_price: float | None,
) -> str:
    below_target = (
        latest_buy_price is not None
        and target_buy_price is not None
        and latest_buy_price <= target_buy_price
    )
    if never_collected or below_target or (overdue_24h and close_to_target):
        return "高"
    if overdue_24h or close_to_target:
        return "中"
    return "低"


def _reason(never_collected: bool, overdue_24h: bool, close_to_target: bool) -> str:
    reasons: list[str] = []
    if never_collected:
        reasons.append("从未采集")
    if overdue_24h:
        reasons.append("超过24小时未采集")
    if close_to_target:
        reasons.append("最近价格接近目标买入价")
    return "；".join(reasons)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None
