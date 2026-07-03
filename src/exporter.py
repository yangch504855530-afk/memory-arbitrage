from __future__ import annotations

import csv
from pathlib import Path

from analyzer import analyze
from db import DEFAULT_DB_PATH
from models import AnalysisResult


CSV_HEADERS = [
    "商品ID",
    "商品名称",
    "当前买入价",
    "当前闲鱼参考价",
    "闲鱼在售数量",
    "预计利润",
    "利润率",
    "是否近7天最低",
    "是否历史最低",
    "推荐等级",
    "买入理由",
    "风险提示",
    "更新时间",
]


def export_csv(
    output_path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
    product_id: str | None = None,
) -> Path:
    rows = analyze(db_path=db_path, product_id=product_id)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_result_to_row(row))
    return target


def _result_to_row(result: AnalysisResult) -> dict[str, object]:
    return {
        "商品ID": result.product_id,
        "商品名称": result.product_name,
        "当前买入价": _money(result.current_buy_price),
        "当前闲鱼参考价": _money(result.xianyu_reference_price),
        "闲鱼在售数量": "" if result.xianyu_listing_count is None else result.xianyu_listing_count,
        "预计利润": _money(result.expected_profit),
        "利润率": _percent(result.profit_rate),
        "是否近7天最低": _bool_text(result.is_7d_low),
        "是否历史最低": _bool_text(result.is_historical_low),
        "推荐等级": result.recommendation_level,
        "买入理由": result.buy_reason,
        "风险提示": result.risk_tips,
        "更新时间": result.collected_at or "",
    }


def _money(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _percent(value: float | None) -> str:
    return "" if value is None else f"{value:.2%}"


def _bool_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "是" if value else "否"
