from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from db import DEFAULT_DB_PATH, fetch_products, insert_price_observation
from models import PriceObservation, parse_float, parse_int


REQUIRED_HEADERS = [
    "product_id",
    "buy_price",
    "sell_price",
    "xianyu_listing_count",
    "source",
    "observed_at",
]


class PriceImportError(ValueError):
    pass


def import_price_records(path: str | Path, db_path: str | Path = DEFAULT_DB_PATH) -> int:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Price CSV not found: {source}")

    records = _load_csv(source)
    validate_price_records(records, db_path=db_path)

    count = 0
    for record in records:
        observation = PriceObservation.from_mapping(
            {
                "product_id": record.get("product_id"),
                "buy_price": record.get("buy_price"),
                "sell_price": record.get("sell_price"),
                "xianyu_listing_count": record.get("xianyu_listing_count"),
                "source": record.get("source"),
                "observed_at": record.get("observed_at"),
                "buy_source": record.get("source"),
                "sell_source": record.get("source"),
                "raw_payload": f"batch_csv:{source.name}",
            }
        )
        insert_price_observation(observation, db_path=db_path)
        count += 1
    return count


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PriceImportError("价格 CSV 为空或缺少表头")
        missing_headers = [field for field in REQUIRED_HEADERS if field not in reader.fieldnames]
        if missing_headers:
            raise PriceImportError("价格 CSV 缺少字段: " + ", ".join(missing_headers))
        return [dict(row) for row in reader]


def validate_price_records(
    records: list[dict[str, Any]],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    errors: list[str] = []
    if not records:
        errors.append("价格 CSV 没有数据行")

    known_product_ids = {product.product_id for product in fetch_products(db_path)}

    for index, record in enumerate(records, start=1):
        label = f"记录 {index}"
        product_id = str(record.get("product_id", "")).strip()
        if not product_id:
            errors.append(f"{label}: product_id 不能为空")
        elif product_id not in known_product_ids:
            errors.append(f"{label}: product_id '{product_id}' 不存在，请先导入商品池")

        for field in ["buy_price", "sell_price"]:
            if _is_blank(record.get(field)):
                errors.append(f"{label}: {field} 不能为空")
            elif not _is_number(record.get(field)):
                errors.append(f"{label}: {field} 必须是数字，当前值为 {record.get(field)!r}")

        if _is_blank(record.get("source")):
            errors.append(f"{label}: source 不能为空")

        count_value = record.get("xianyu_listing_count")
        if not _is_blank(count_value) and not _is_int(count_value):
            errors.append(
                f"{label}: xianyu_listing_count 必须是整数，当前值为 {count_value!r}"
            )

        observed_at = record.get("observed_at")
        if _is_blank(observed_at):
            errors.append(f"{label}: observed_at 不能为空")
        elif not _is_datetime(observed_at):
            errors.append(f"{label}: observed_at 必须是 ISO 时间，当前值为 {observed_at!r}")

    if errors:
        raise PriceImportError("价格 CSV 校验失败：\n- " + "\n- ".join(errors))


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_number(value: Any) -> bool:
    if isinstance(value, str) and value.strip().endswith("%"):
        return False
    try:
        parse_float(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_int(value: Any) -> bool:
    try:
        parse_int(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_datetime(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False
