from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


PRODUCT_FIELDS = [
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
    "note",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("%"):
        return float(text[:-1].strip()) / 100
    return float(text)


def parse_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str = ""
    model: str = ""
    keyword: str = ""
    capacity: str = ""
    frequency: str = ""
    memory_type: str = ""
    form_factor: str = ""
    buy_platform: str = ""
    buy_url: str = ""
    sell_platform: str = "xianyu"
    sell_keyword: str = ""
    target_buy_price: float | None = None
    target_sell_price: float | None = None
    min_profit_rate: float | None = None
    shipping_cost: float = 0
    note: str = ""

    @property
    def display_name(self) -> str:
        parts: list[str] = []
        name_so_far = ""
        for part in [self.brand, self.model, self.capacity, self.frequency]:
            if not part:
                continue
            if part.lower() in name_so_far.lower():
                continue
            parts.append(part)
            name_so_far = " ".join(parts)
        name = name_so_far.strip()
        return name or self.keyword or self.product_id

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Product":
        product_id = str(data.get("product_id", "")).strip()
        if not product_id:
            raise ValueError("product_id is required")

        payload: dict[str, Any] = {}
        for field in PRODUCT_FIELDS:
            value = data.get(field)
            if field in {"target_buy_price", "target_sell_price", "min_profit_rate"}:
                payload[field] = parse_float(value)
            elif field == "shipping_cost":
                payload[field] = parse_float(value, 0) or 0
            elif field == "product_id":
                payload[field] = product_id
            else:
                payload[field] = "" if value is None else str(value).strip()
        return cls(**payload)

    def as_db_tuple(self) -> tuple[Any, ...]:
        return tuple(getattr(self, field) for field in PRODUCT_FIELDS)


@dataclass(frozen=True)
class PriceObservation:
    product_id: str
    buy_price: float | None
    sell_price: float | None
    xianyu_listing_count: int | None = None
    collected_at: str = ""
    source: str = "manual"
    buy_source: str = ""
    sell_source: str = ""
    raw_payload: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PriceObservation":
        product_id = str(data.get("product_id", "")).strip()
        if not product_id:
            raise ValueError("product_id is required")
        return cls(
            product_id=product_id,
            buy_price=parse_float(data.get("buy_price")),
            sell_price=parse_float(data.get("sell_price")),
            xianyu_listing_count=parse_int(data.get("xianyu_listing_count")),
            collected_at=str(data.get("collected_at") or data.get("observed_at") or utc_now_iso()),
            source=str(data.get("source") or "manual"),
            buy_source=str(data.get("buy_source") or ""),
            sell_source=str(data.get("sell_source") or ""),
            raw_payload=str(data.get("raw_payload") or ""),
        )


@dataclass(frozen=True)
class AnalysisResult:
    product_id: str
    product_name: str
    current_buy_price: float | None
    xianyu_reference_price: float | None
    price_spread: float | None
    expected_profit: float | None
    profit_rate: float | None
    profit_rate_percent: float | None
    below_target_buy_price: bool | None
    meet_min_profit_rate: bool | None
    is_7d_low: bool | None
    is_historical_low: bool | None
    sell_price_change: str
    avg_7d_buy_price: float | None
    avg_7d_sell_price: float | None
    recommendation_level: str
    buy_reason: str
    suggested_action: str
    risk_tips: str
    xianyu_listing_count: int | None
    collected_at: str | None
    source: str | None
