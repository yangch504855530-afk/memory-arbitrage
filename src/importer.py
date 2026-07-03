from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from db import DEFAULT_DB_PATH, upsert_products
from models import Product, parse_float


REQUIRED_FIELDS = [
    "product_id",
    "brand",
    "model",
    "keyword",
    "capacity",
    "frequency",
    "memory_type",
    "form_factor",
    "buy_platform",
    "buy_url",
    "sell_platform",
    "sell_keyword",
    "target_buy_price",
    "target_sell_price",
    "min_profit_rate",
    "shipping_cost",
]

NUMERIC_FIELDS = [
    "target_buy_price",
    "target_sell_price",
    "min_profit_rate",
    "shipping_cost",
]


class ProductImportError(ValueError):
    pass


def load_products(path: str | Path) -> list[Product]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Product file not found: {source}")

    suffix = source.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        records = _load_yaml(source)
    elif suffix == ".csv":
        records = _load_csv(source)
    else:
        raise ValueError("Product file must be .yaml, .yml, or .csv")

    validate_product_records(records)
    return [Product.from_mapping(record) for record in records]


def import_products(path: str | Path, db_path: str | Path = DEFAULT_DB_PATH) -> int:
    products = load_products(path)
    return upsert_products(products, db_path=db_path)


def _load_yaml(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required. Run: pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    if isinstance(payload, dict):
        records = payload.get("products", [])
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError("YAML must be a list or contain a top-level 'products' list")

    if not isinstance(records, list):
        raise ValueError("'products' must be a list")
    return [dict(record) for record in records]


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def validate_product_records(records: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    seen_product_ids: dict[str, int] = {}

    if not records:
        errors.append("商品池为空：至少需要 1 条商品记录")

    for index, record in enumerate(records, start=1):
        label = f"记录 {index}"
        if not isinstance(record, dict):
            errors.append(f"{label}: 必须是字段字典")
            continue

        for field in REQUIRED_FIELDS:
            if _is_blank(record.get(field)):
                errors.append(f"{label}: 缺少必填字段 {field}")

        product_id = str(record.get("product_id", "")).strip()
        if product_id:
            first_index = seen_product_ids.get(product_id)
            if first_index is not None:
                errors.append(
                    f"{label}: 重复 product_id '{product_id}'，首次出现在记录 {first_index}"
                )
            else:
                seen_product_ids[product_id] = index

        for field in NUMERIC_FIELDS:
            value = record.get(field)
            if _is_blank(value):
                continue
            if not _is_number(value):
                errors.append(f"{label}: {field} 必须是数字，当前值为 {value!r}")

    if errors:
        raise ProductImportError("商品池校验失败：\n- " + "\n- ".join(errors))


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip()
    if text.endswith("%"):
        return False
    try:
        parse_float(text)
        return True
    except (TypeError, ValueError):
        return False
