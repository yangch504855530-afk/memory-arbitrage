from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import DEFAULT_DB_PATH, fetch_observations, fetch_products
from models import AnalysisResult, Product


def analyze(
    db_path: str | Path = DEFAULT_DB_PATH,
    product_id: str | None = None,
) -> list[AnalysisResult]:
    products = fetch_products(db_path)
    if product_id:
        products = [product for product in products if product.product_id == product_id]
    return [_analyze_product(product, db_path) for product in products]


def _analyze_product(product: Product, db_path: str | Path) -> AnalysisResult:
    observations = _sort_observations(fetch_observations(product.product_id, db_path))
    if not observations:
        return AnalysisResult(
            product_id=product.product_id,
            product_name=product.display_name,
            current_buy_price=None,
            xianyu_reference_price=None,
            price_spread=None,
            expected_profit=None,
            profit_rate=None,
            profit_rate_percent=None,
            below_target_buy_price=None,
            meet_min_profit_rate=None,
            is_7d_low=None,
            is_historical_low=None,
            sell_price_change="无价格记录",
            avg_7d_buy_price=None,
            avg_7d_sell_price=None,
            recommendation_level="暂不建议",
            buy_reason="缺少价格记录，先录入买入价和闲鱼参考价",
            suggested_action="关注",
            risk_tips="暂无价格记录，先录入买入价和闲鱼参考价",
            xianyu_listing_count=None,
            collected_at=None,
            source=None,
        )

    latest = observations[0]
    buy_price = latest["buy_price"]
    sell_price = latest["sell_price"]
    listing_count = latest["xianyu_listing_count"]
    collected_at = latest["collected_at"]
    source = latest["source"]

    price_spread = None
    expected_profit = None
    profit_rate = None
    profit_rate_percent = None
    if buy_price is not None and sell_price is not None:
        price_spread = sell_price - buy_price
        expected_profit = sell_price - buy_price - product.shipping_cost
        if buy_price > 0:
            profit_rate = expected_profit / buy_price
            profit_rate_percent = profit_rate * 100

    below_target = None
    if buy_price is not None and product.target_buy_price is not None:
        below_target = buy_price <= product.target_buy_price

    meet_min_rate = None
    if profit_rate is not None and product.min_profit_rate is not None:
        meet_min_rate = profit_rate >= product.min_profit_rate

    recent_observations = _recent_observations(observations, collected_at)
    avg_7d_buy_price = _average(row["buy_price"] for row in recent_observations)
    avg_7d_sell_price = _average(row["sell_price"] for row in recent_observations)
    is_7d_low = _is_lowest(buy_price, [row["buy_price"] for row in recent_observations])
    is_historical_low = _is_lowest(buy_price, [row["buy_price"] for row in observations])
    sell_price_change = _sell_price_change(sell_price, observations[1:])
    recommendation_level = _recommendation_level(
        expected_profit=expected_profit,
        below_target=below_target,
        meet_min_rate=meet_min_rate,
        is_7d_low=is_7d_low,
        is_historical_low=is_historical_low,
    )
    buy_reason = _build_buy_reason(
        recommendation_level=recommendation_level,
        expected_profit=expected_profit,
        below_target=below_target,
        meet_min_rate=meet_min_rate,
        is_7d_low=is_7d_low,
        is_historical_low=is_historical_low,
        profit_rate=profit_rate,
        product=product,
    )
    risk_tips = _build_risk_tips(
        product=product,
        buy_price=buy_price,
        sell_price=sell_price,
        listing_count=listing_count,
        collected_at=collected_at,
        source=source,
        expected_profit=expected_profit,
        profit_rate=profit_rate,
        is_7d_low=is_7d_low,
        sell_price_change=sell_price_change,
        avg_7d_buy_price=avg_7d_buy_price,
        avg_7d_sell_price=avg_7d_sell_price,
    )
    action = _suggest_action(recommendation_level, expected_profit)

    return AnalysisResult(
        product_id=product.product_id,
        product_name=product.display_name,
        current_buy_price=buy_price,
        xianyu_reference_price=sell_price,
        price_spread=price_spread,
        expected_profit=expected_profit,
        profit_rate=profit_rate,
        profit_rate_percent=profit_rate_percent,
        below_target_buy_price=below_target,
        meet_min_profit_rate=meet_min_rate,
        is_7d_low=is_7d_low,
        is_historical_low=is_historical_low,
        sell_price_change=sell_price_change,
        avg_7d_buy_price=avg_7d_buy_price,
        avg_7d_sell_price=avg_7d_sell_price,
        recommendation_level=recommendation_level,
        buy_reason=buy_reason,
        suggested_action=action,
        risk_tips=risk_tips,
        xianyu_listing_count=listing_count,
        collected_at=collected_at,
        source=source,
    )


def _recommendation_level(
    expected_profit: float | None,
    below_target: bool | None,
    meet_min_rate: bool | None,
    is_7d_low: bool | None,
    is_historical_low: bool | None,
) -> str:
    if expected_profit is None:
        return "暂不建议"
    if expected_profit <= 0:
        return "暂不建议"
    if (
        below_target is True
        and meet_min_rate is True
        and (is_7d_low is True or is_historical_low is True)
    ):
        return "强烈买入"
    if expected_profit > 0 and (below_target is True or meet_min_rate is True):
        return "可以关注"
    return "暂不建议"


def _suggest_action(recommendation_level: str, expected_profit: float | None) -> str:
    if recommendation_level == "强烈买入":
        return "买入"
    if recommendation_level == "可以关注":
        return "关注"
    if expected_profit is None:
        return "关注"
    if expected_profit <= 0:
        return "放弃"
    return "关注"


def _build_risk_tips(
    product: Product,
    buy_price: float | None,
    sell_price: float | None,
    listing_count: int | None,
    collected_at: str | None,
    source: str | None,
    expected_profit: float | None,
    profit_rate: float | None,
    is_7d_low: bool | None,
    sell_price_change: str,
    avg_7d_buy_price: float | None,
    avg_7d_sell_price: float | None,
) -> str:
    tips: list[str] = []
    if buy_price is None:
        tips.append("缺少买入价")
    if sell_price is None:
        tips.append("缺少闲鱼参考价")
    if source == "manual":
        tips.append("手动录入价格，需复核")
    if listing_count is None:
        tips.append("未录入闲鱼在售数量")
    elif listing_count >= 30:
        tips.append("闲鱼在售数量较高，可能压价")
    elif listing_count <= 2:
        tips.append("闲鱼样本较少，参考价可能失真")
    if (
        sell_price is not None
        and product.target_sell_price is not None
        and sell_price < product.target_sell_price
    ):
        tips.append("闲鱼参考价低于目标卖出价")
    if product.target_buy_price is None:
        tips.append("未配置目标买入价")
    if product.min_profit_rate is None:
        tips.append("未配置最低利润率")
    if expected_profit is not None and expected_profit < 0:
        tips.append("预计亏损")
    if profit_rate is not None and product.min_profit_rate is not None:
        if profit_rate < product.min_profit_rate:
            tips.append("利润率不足")
    if is_7d_low is False:
        tips.append("当前买入价不是近7天最低")
    if sell_price_change.startswith("下降"):
        tips.append("闲鱼参考价较上次下降")
    if buy_price is not None and avg_7d_buy_price is not None and buy_price > avg_7d_buy_price:
        tips.append("当前买入价高于近7天均价")
    if sell_price is not None and avg_7d_sell_price is not None and sell_price < avg_7d_sell_price:
        tips.append("当前闲鱼参考价低于近7天均价")
    if collected_at and _is_stale(collected_at):
        tips.append("价格记录超过48小时")
    return "；".join(tips) if tips else "无明显风险"


def _build_buy_reason(
    recommendation_level: str,
    expected_profit: float | None,
    below_target: bool | None,
    meet_min_rate: bool | None,
    is_7d_low: bool | None,
    is_historical_low: bool | None,
    profit_rate: float | None,
    product: Product,
) -> str:
    if expected_profit is None:
        return "缺少买入价或闲鱼参考价，无法判断套利空间"
    if expected_profit <= 0:
        return "预计利润不为正，扣除邮费后没有套利空间"

    if recommendation_level == "强烈买入":
        low_text = "历史最低" if is_historical_low else "近7天最低"
        return (
            f"预计利润 {expected_profit:.2f}，利润率 {_percent_text(profit_rate)}，"
            f"买入价不高于目标价且达到最低利润率，当前买入价为{low_text}"
        )

    reasons: list[str] = []
    if expected_profit > 0:
        reasons.append(f"预计利润 {expected_profit:.2f}")
    if below_target is False:
        reasons.append("买入价高于目标买入价")
    elif below_target is True:
        reasons.append("买入价已低于目标")
    else:
        reasons.append("未配置目标买入价")

    if meet_min_rate is False:
        target = _percent_text(product.min_profit_rate)
        reasons.append(f"利润率 {_percent_text(profit_rate)} 未达到最低要求 {target}")
    elif meet_min_rate is True:
        reasons.append(f"利润率 {_percent_text(profit_rate)} 已达标")
    else:
        reasons.append("未配置最低利润率")

    if is_7d_low is False:
        reasons.append("当前买入价不是近7天最低")
    elif is_7d_low is True:
        reasons.append("当前买入价为近7天最低")

    return "；".join(reasons)


def _recent_observations(observations: list[object], latest_collected_at: str | None) -> list[object]:
    latest_dt = _parse_datetime(latest_collected_at)
    if latest_dt is None:
        return observations
    cutoff = latest_dt - timedelta(days=7)
    recent = []
    for row in observations:
        row_dt = _parse_datetime(row["collected_at"])
        if row_dt is None or row_dt >= cutoff:
            recent.append(row)
    return recent


def _sort_observations(observations: list[object]) -> list[object]:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(
        observations,
        key=lambda row: (_parse_datetime(row["collected_at"]) or epoch, row["id"]),
        reverse=True,
    )


def _average(values: object) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _is_lowest(current: float | None, values: list[float | None]) -> bool | None:
    if current is None:
        return None
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return current <= min(numeric) + 0.000001


def _sell_price_change(current_sell_price: float | None, previous_rows: list[object]) -> str:
    if current_sell_price is None:
        return "缺少当前闲鱼价"
    previous_sell_price = None
    for row in previous_rows:
        if row["sell_price"] is not None:
            previous_sell_price = float(row["sell_price"])
            break
    if previous_sell_price is None:
        return "无上次记录"
    diff = current_sell_price - previous_sell_price
    if diff > 0.000001:
        return f"上涨 {diff:.2f}"
    if diff < -0.000001:
        return f"下降 {abs(diff):.2f}"
    return "持平"


def _is_stale(collected_at: str) -> bool:
    try:
        dt = _parse_datetime(collected_at)
        if dt is None:
            return False
        return (datetime.now(timezone.utc) - dt).total_seconds() > 48 * 3600
    except ValueError:
        return False


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


def _percent_text(value: float | None) -> str:
    return "未知" if value is None else f"{value:.2%}"
