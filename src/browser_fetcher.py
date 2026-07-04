from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from collectors import jd_playwright, pdd_playwright, xianyu_playwright
from db import (
    DEFAULT_DB_PATH,
    fetch_observations,
    fetch_products,
    insert_price_observation,
    replace_xianyu_results,
)
from models import PriceObservation, Product, utc_now_iso
from xianyu_tools import XianyuSuggestion, suggest_prices


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FETCH_LOG_PATH = PROJECT_ROOT / "logs" / "fetch.log"
DEFAULT_BROWSER_PROFILE_DIR = PROJECT_ROOT / "data" / "browser-profile"
SUPPORTED_SOURCES = {"jd", "pdd", "xianyu"}


@dataclass(frozen=True)
class FetchOptions:
    product_id: str | None = None
    sources: list[str] | None = None
    headful: bool = False
    browser_channel: str | None = None
    profile_dir: str | None = None
    manual_wait: int = 0
    delay: float = 5
    limit: int = 10
    xianyu_result_limit: int = 20


@dataclass(frozen=True)
class FetchOutcome:
    product_id: str
    product_name: str
    platform: str
    ok: bool
    price: float | None = None
    title: str = ""
    url: str = ""
    observed_at: str = ""
    reason: str = ""
    item_count: int = 0
    suggested_sell_price: float | None = None
    risk_tips: str = ""


def fetch_prices(
    db_path: str | Path = DEFAULT_DB_PATH,
    options: FetchOptions | None = None,
    log_path: str | Path = DEFAULT_FETCH_LOG_PATH,
) -> list[FetchOutcome]:
    options = options or FetchOptions()
    sources = _normalize_sources(options.sources)
    products = _select_products(db_path=db_path, product_id=options.product_id, limit=options.limit)
    outcomes: list[FetchOutcome] = []

    _write_log(
        log_path,
        {
            "event": "start",
            "time": utc_now_iso(),
            "sources": sources,
            "limit": options.limit,
            "headful": options.headful,
            "browser_channel": options.browser_channel or "chromium",
            "profile_dir": options.profile_dir or "",
            "manual_wait": options.manual_wait,
        },
    )
    if not products:
        _write_log(log_path, {"event": "finish", "time": utc_now_iso(), "count": 0, "reason": "no products"})
        return outcomes

    with _start_browser(
        headful=options.headful,
        browser_channel=options.browser_channel,
        profile_dir=options.profile_dir,
    ) as browser:
        page = browser.new_page()
        for product in products:
            for source in sources:
                if source in {"jd", "pdd"} and product.buy_platform != source:
                    continue
                outcome = _fetch_one(
                    page,
                    product,
                    source,
                    db_path,
                    options.xianyu_result_limit,
                    options.manual_wait,
                )
                outcomes.append(outcome)
                _write_outcome_log(log_path, outcome)
                if _should_stop_for_manual_handling(outcome.reason):
                    _write_log(log_path, {"event": "stop", "time": utc_now_iso(), "reason": outcome.reason})
                    return outcomes
                time.sleep(max(options.delay, 0))
        page.close()
    _write_log(log_path, {"event": "finish", "time": utc_now_iso(), "count": len(outcomes)})
    return outcomes


def _fetch_one(
    page: object,
    product: Product,
    source: str,
    db_path: str | Path,
    xianyu_result_limit: int,
    manual_wait: int,
) -> FetchOutcome:
    observed_at = utc_now_iso()
    try:
        if source == "jd":
            return _fetch_buy(page, product, jd_playwright, "jd_auto", observed_at, db_path, manual_wait)
        if source == "pdd":
            return _fetch_buy(page, product, pdd_playwright, "pdd_auto", observed_at, db_path, manual_wait)
        if source == "xianyu":
            return _fetch_xianyu(page, product, observed_at, db_path, xianyu_result_limit, manual_wait)
        return FetchOutcome(
            product_id=product.product_id,
            product_name=product.display_name,
            platform=source,
            ok=False,
            observed_at=observed_at,
            reason=f"不支持的 source: {source}",
        )
    except Exception as exc:
        return FetchOutcome(
            product_id=product.product_id,
            product_name=product.display_name,
            platform=source,
            ok=False,
            observed_at=observed_at,
            reason=_classify_exception(exc),
        )


def _fetch_buy(
    page: object,
    product: Product,
    collector: object,
    source: str,
    observed_at: str,
    db_path: str | Path,
    manual_wait: int,
) -> FetchOutcome:
    if not product.buy_url:
        return FetchOutcome(
            product_id=product.product_id,
            product_name=product.display_name,
            platform=product.buy_platform,
            ok=False,
            observed_at=observed_at,
            reason="缺少 buy_url",
        )
    result = collector.fetch_buy_price(page, product.buy_url, manual_wait_seconds=manual_wait)
    price = result.get("price")
    ok = bool(result.get("ok"))
    if ok and price is not None:
        insert_price_observation(
            PriceObservation(
                product_id=product.product_id,
                buy_price=float(price),
                sell_price=None,
                xianyu_listing_count=None,
                collected_at=observed_at,
                source=source,
                buy_source=str(result.get("url") or product.buy_url),
                raw_payload=json.dumps(result, ensure_ascii=False),
            ),
            db_path=db_path,
        )
    return FetchOutcome(
        product_id=product.product_id,
        product_name=product.display_name,
        platform=product.buy_platform,
        ok=ok,
        price=float(price) if price is not None else None,
        title=str(result.get("title") or ""),
        url=str(result.get("url") or product.buy_url),
        observed_at=observed_at,
        reason=str(result.get("reason") or ""),
    )


def _fetch_xianyu(
    page: object,
    product: Product,
    observed_at: str,
    db_path: str | Path,
    result_limit: int,
    manual_wait: int,
) -> FetchOutcome:
    result = xianyu_playwright.fetch_search_results(
        page,
        product,
        limit=result_limit,
        manual_wait_seconds=manual_wait,
    )
    ok = bool(result.get("ok"))
    items = list(result.get("items") or [])
    if ok:
        replace_xianyu_results(
            product_id=product.product_id,
            results=[item.__dict__ for item in items],
            source_file=f"xianyu_auto:{result.get('url') or ''}",
            observed_at=observed_at,
            db_path=db_path,
        )
        suggestion = _single_suggestion(product.product_id, db_path)
        latest_buy = _latest_buy_price(product.product_id, db_path)
        if suggestion.suggested_sell_price is not None:
            insert_price_observation(
                PriceObservation(
                    product_id=product.product_id,
                    buy_price=latest_buy,
                    sell_price=suggestion.suggested_sell_price,
                    xianyu_listing_count=suggestion.sample_count,
                    collected_at=observed_at,
                    source="xianyu_auto",
                    sell_source=str(result.get("url") or ""),
                    raw_payload=json.dumps(suggestion.__dict__, ensure_ascii=False),
                ),
                db_path=db_path,
            )
        return FetchOutcome(
            product_id=product.product_id,
            product_name=product.display_name,
            platform="xianyu",
            ok=True,
            price=suggestion.suggested_sell_price,
            url=str(result.get("url") or ""),
            observed_at=observed_at,
            item_count=len(items),
            suggested_sell_price=suggestion.suggested_sell_price,
            risk_tips=suggestion.risk_tips,
            reason="" if suggestion.suggested_sell_price is not None else "没有可用的闲鱼建议价",
        )
    return FetchOutcome(
        product_id=product.product_id,
        product_name=product.display_name,
        platform="xianyu",
        ok=False,
        url=str(result.get("url") or ""),
        observed_at=observed_at,
        reason=str(result.get("reason") or "未找到搜索结果元素"),
    )


class _BrowserContext:
    def __init__(
        self,
        headful: bool,
        browser_channel: str | None,
        profile_dir: str | None,
    ):
        self.headful = headful
        self.browser_channel = _normalize_browser_channel(browser_channel)
        self.profile_dir = profile_dir
        self._playwright = None
        self._browser_or_context = None

    def __enter__(self) -> object:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is required for fetch-prices. Run: pip install -r requirements.txt && python -m playwright install chromium"
            ) from exc
        self._playwright = sync_playwright().start()
        launch_kwargs = {"headless": not self.headful}
        if self.browser_channel:
            launch_kwargs["channel"] = self.browser_channel

        if self.profile_dir:
            profile_path = Path(self.profile_dir)
            profile_path.mkdir(parents=True, exist_ok=True)
            self._browser_or_context = self._playwright.chromium.launch_persistent_context(
                str(profile_path),
                locale="zh-CN",
                **launch_kwargs,
            )
        else:
            self._browser_or_context = self._playwright.chromium.launch(**launch_kwargs)
        return self._browser_or_context

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._browser_or_context is not None:
            self._browser_or_context.close()
        if self._playwright is not None:
            self._playwright.stop()


def _start_browser(
    headful: bool,
    browser_channel: str | None = None,
    profile_dir: str | None = None,
) -> _BrowserContext:
    return _BrowserContext(
        headful=headful,
        browser_channel=browser_channel,
        profile_dir=profile_dir,
    )


def _normalize_browser_channel(browser_channel: str | None) -> str | None:
    if not browser_channel or browser_channel == "chromium":
        return None
    return browser_channel


def _normalize_sources(sources: list[str] | None) -> list[str]:
    if not sources:
        return ["jd", "pdd", "xianyu"]
    normalized = []
    for source in sources:
        value = source.strip().lower()
        if value not in SUPPORTED_SOURCES:
            raise ValueError(f"Unsupported source '{source}'. Supported: jd, pdd, xianyu")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _select_products(
    db_path: str | Path,
    product_id: str | None,
    limit: int,
) -> list[Product]:
    products = fetch_products(db_path)
    if product_id:
        products = [product for product in products if product.product_id == product_id]
    if limit > 0:
        products = products[:limit]
    return products


def _single_suggestion(product_id: str, db_path: str | Path) -> XianyuSuggestion:
    suggestions = suggest_prices(db_path=db_path, product_id=product_id)
    if suggestions:
        return suggestions[0]
    raise ValueError(f"Unable to build Xianyu suggestion for product_id '{product_id}'")


def _latest_buy_price(product_id: str, db_path: str | Path) -> float | None:
    observations = fetch_observations(product_id, db_path)
    if not observations:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    latest = sorted(
        observations,
        key=lambda row: (_parse_datetime(str(row["collected_at"])) or epoch, row["id"]),
        reverse=True,
    )[0]
    return latest["buy_price"]


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


def _should_stop_for_manual_handling(reason: str) -> bool:
    return reason in {"需要登录", "触发验证码", "触发风控"}


def _classify_exception(exc: Exception) -> str:
    text = str(exc)
    if any(word in text for word in ["验证码", "安全验证", "滑块"]):
        return "触发验证码"
    if any(word in text for word in ["login", "登录", "请登录"]):
        return "需要登录"
    if any(word in text for word in ["Timeout", "timeout", "超时"]):
        return "页面加载超时"
    if any(word in text for word in ["ERR_NAME_NOT_RESOLVED", "ERR_INTERNET_DISCONNECTED", "ERR_CONNECTION"]):
        return "网络不可用"
    return f"采集异常: {text[:120]}"


def _write_outcome_log(log_path: str | Path, outcome: FetchOutcome) -> None:
    _write_log(
        log_path,
        {
            "event": "fetch",
            "time": utc_now_iso(),
            "product_id": outcome.product_id,
            "platform": outcome.platform,
            "success": outcome.ok,
            "reason": outcome.reason,
            "price": outcome.price,
            "item_count": outcome.item_count,
            "url": outcome.url,
        },
    )


def _write_log(log_path: str | Path, payload: dict[str, object]) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
