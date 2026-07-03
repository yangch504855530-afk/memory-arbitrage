from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import quote_plus

from db import (
    DEFAULT_DB_PATH,
    fetch_latest_xianyu_results,
    fetch_observations,
    fetch_product,
    fetch_products,
    replace_xianyu_results,
)
from models import Product, utc_now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEARCH_URLS_PATH = PROJECT_ROOT / "data" / "search_urls.csv"
DEFAULT_GENERATED_PRICES_PATH = PROJECT_ROOT / "data" / "prices.csv"

SEARCH_URL_HEADERS = [
    "product_id",
    "商品名称",
    "sell_keyword",
    "xianyu_search_url",
    "buy_platform",
    "buy_url",
    "target_buy_price",
]

GENERATED_PRICE_HEADERS = [
    "product_id",
    "buy_price",
    "sell_price",
    "xianyu_listing_count",
    "source",
    "observed_at",
]


@dataclass(frozen=True)
class XianyuParsedItem:
    title: str
    price: float | None
    item_id: str = ""
    location: str = ""
    item_updated_at: str = ""
    publish_time: str = ""
    want_info: str = ""
    item_url: str = ""
    condition: str = ""
    free_shipping: bool | None = None
    raw_text: str = ""


@dataclass(frozen=True)
class XianyuSuggestion:
    product_id: str
    product_name: str
    suggested_sell_price: float | None
    sample_count: int
    used_sample_count: int
    price_range: str
    used_price_range: str
    observed_at: str
    risk_tips: str


@dataclass(frozen=True)
class GeneratedPriceRow:
    product_id: str
    buy_price: float | None
    sell_price: float | None
    xianyu_listing_count: int
    source: str
    observed_at: str
    status: str


def generate_search_urls(
    output_path: str | Path = DEFAULT_SEARCH_URLS_PATH,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    rows = []
    for product in fetch_products(db_path):
        rows.append(
            {
                "product_id": product.product_id,
                "商品名称": product.display_name,
                "sell_keyword": _sell_keyword(product),
                "xianyu_search_url": _xianyu_search_url(_sell_keyword(product)),
                "buy_platform": product.buy_platform,
                "buy_url": product.buy_url,
                "target_buy_price": _money(product.target_buy_price),
            }
        )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SEARCH_URL_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return target


def import_xianyu_html(
    product_id: str,
    html_path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[XianyuParsedItem]:
    product = fetch_product(product_id, db_path)
    if product is None:
        raise ValueError(f"Unknown product_id '{product_id}'. Import products first.")

    source = Path(html_path)
    if not source.exists():
        raise FileNotFoundError(f"Xianyu HTML not found: {source}")

    html = source.read_text(encoding="utf-8", errors="ignore")
    items = parse_xianyu_html(html, product)
    observed_at = utc_now_iso()
    replace_xianyu_results(
        product_id=product_id,
        results=[item.__dict__ for item in items],
        source_file=str(source),
        observed_at=observed_at,
        db_path=db_path,
    )
    return items


def parse_xianyu_html(html: str, product: Product) -> list[XianyuParsedItem]:
    items = _parse_json_items(html, product) + _parse_dom_items(html)
    cleaned = _dedupe_items(items)
    scored = sorted(
        cleaned,
        key=lambda item: (
            -_title_score(product, item.title),
            item.price if item.price is not None else math.inf,
            item.title,
        ),
    )
    return scored


def parse_xianyu_search_json(raw: Any, product: Product | None = None) -> list[XianyuParsedItem]:
    items = _items_from_goofish_search_json(raw)
    if not items:
        items = _items_from_json(raw)
    cleaned = _dedupe_items(items)
    if product is None:
        return cleaned
    return sorted(
        cleaned,
        key=lambda item: (
            -_title_score(product, item.title),
            item.price if item.price is not None else math.inf,
            item.title,
        ),
    )


def suggest_prices(
    db_path: str | Path = DEFAULT_DB_PATH,
    product_id: str | None = None,
) -> list[XianyuSuggestion]:
    products = fetch_products(db_path)
    if product_id:
        products = [product for product in products if product.product_id == product_id]
    return [_suggest_price(product, db_path) for product in products]


def generate_prices_from_xianyu(
    output_path: str | Path = DEFAULT_GENERATED_PRICES_PATH,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[Path, list[GeneratedPriceRow]]:
    suggestions = {row.product_id: row for row in suggest_prices(db_path=db_path)}
    rows: list[GeneratedPriceRow] = []
    for product in fetch_products(db_path):
        latest_buy = _latest_buy_price(product.product_id, db_path)
        suggestion = suggestions.get(product.product_id)
        sell_price = suggestion.suggested_sell_price if suggestion else None
        status = "ok"
        if latest_buy is None:
            status = "缺少最新买入价"
        elif sell_price is None:
            status = "缺少闲鱼建议价"

        rows.append(
            GeneratedPriceRow(
                product_id=product.product_id,
                buy_price=latest_buy,
                sell_price=sell_price,
                xianyu_listing_count=suggestion.sample_count if suggestion else 0,
                source="xianyu_html_suggested",
                observed_at=utc_now_iso(),
                status=status,
            )
        )

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GENERATED_PRICE_HEADERS)
        writer.writeheader()
        for row in rows:
            if row.status != "ok":
                continue
            writer.writerow(
                {
                    "product_id": row.product_id,
                    "buy_price": _money(row.buy_price),
                    "sell_price": _money(row.sell_price),
                    "xianyu_listing_count": row.xianyu_listing_count,
                    "source": row.source,
                    "observed_at": row.observed_at,
                }
            )
    return target, rows


def _suggest_price(
    product: Product,
    db_path: str | Path,
) -> XianyuSuggestion:
    rows = fetch_latest_xianyu_results(product.product_id, db_path)
    observed_at = str(rows[0]["observed_at"]) if rows else ""
    items = [
        XianyuParsedItem(
            item_id=str(row["item_id"]) if "item_id" in row.keys() else "",
            title=str(row["title"]),
            price=row["price"],
            location=str(row["location"]),
            item_updated_at=str(row["item_updated_at"]),
            publish_time=str(row["publish_time"]) if "publish_time" in row.keys() else "",
            want_info=str(row["want_info"]),
            item_url=str(row["item_url"]),
            condition=str(row["condition"]) if "condition" in row.keys() else "",
            free_shipping=bool(row["free_shipping"]) if "free_shipping" in row.keys() and row["free_shipping"] is not None else None,
            raw_text=str(row["raw_text"]),
        )
        for row in rows
    ]
    valid = [item for item in items if item.price is not None and 10 <= float(item.price) <= 10000]
    if not valid:
        return XianyuSuggestion(
            product_id=product.product_id,
            product_name=product.display_name,
            suggested_sell_price=None,
            sample_count=0,
            used_sample_count=0,
            price_range="",
            used_price_range="",
            observed_at=observed_at,
            risk_tips="没有可用的闲鱼解析价格，请检查保存的 HTML 是否包含搜索结果",
        )

    matched = [item for item in valid if _title_score(product, item.title) >= 2]
    base_pool = matched if matched else valid
    no_match_risk = "未找到足够同款标题样本，已退回使用全部价格样本" if not matched else ""

    filtered, outlier_count = _filter_outliers([float(item.price) for item in base_pool])
    used_items = [item for item in base_pool if item.price is not None and float(item.price) in filtered]
    if not used_items:
        used_items = base_pool
        filtered = [float(item.price) for item in used_items if item.price is not None]

    preferred = [item for item in used_items if _has_preferred_condition(item.title)]
    if len(preferred) >= 2:
        used_items = preferred
        filtered = [float(item.price) for item in used_items if item.price is not None]

    low_band = _low_price_band(filtered)
    suggested = float(median(low_band)) if low_band else None

    risks = []
    if no_match_risk:
        risks.append(no_match_risk)
    if len(valid) < 5:
        risks.append("样本数量少，建议人工复核")
    if len(matched) < 3:
        risks.append("同款标题匹配样本少")
    if outlier_count:
        risks.append(f"已剔除异常价格 {outlier_count} 个")
    if len(preferred) < 2:
        risks.append("全新/未拆封样本不足，建议确认成色")
    risks.append("建议价来自保存 HTML 的静态解析，需人工确认规格和成色")

    return XianyuSuggestion(
        product_id=product.product_id,
        product_name=product.display_name,
        suggested_sell_price=round(suggested, 2) if suggested is not None else None,
        sample_count=len(valid),
        used_sample_count=len(used_items),
        price_range=_price_range([float(item.price) for item in valid if item.price is not None]),
        used_price_range=_price_range(filtered),
        observed_at=observed_at,
        risk_tips="；".join(risks),
    )


def _parse_json_items(html: str, product: Product) -> list[XianyuParsedItem]:
    items: list[XianyuParsedItem] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return items

    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=True)
        text = text.strip()
        if not text:
            continue
        payloads = _json_payloads(text)
        for payload in payloads:
            items.extend(parse_xianyu_search_json(payload, product))
    return items


def _json_payloads(text: str) -> list[Any]:
    candidates = []
    if text.startswith("{") or text.startswith("["):
        candidates.append(text)
    for pattern in [
        r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;",
        r"window\.__NUXT__\s*=\s*({.*?})\s*;",
    ]:
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            candidates.append(match.group(1))

    payloads = []
    for candidate in candidates:
        try:
            payloads.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return payloads


def _items_from_json(payload: Any) -> list[XianyuParsedItem]:
    items: list[XianyuParsedItem] = []
    if isinstance(payload, dict):
        item = _item_from_dict(payload)
        if item is not None:
            items.append(item)
        for value in payload.values():
            items.extend(_items_from_json(value))
    elif isinstance(payload, list):
        for value in payload:
            items.extend(_items_from_json(value))
    return items


def _items_from_goofish_search_json(payload: Any) -> list[XianyuParsedItem]:
    if not isinstance(payload, dict):
        return []
    result_list = (((payload or {}).get("data") or {}).get("resultList")) or []
    if not isinstance(result_list, list):
        return []

    items: list[XianyuParsedItem] = []
    for node in result_list:
        if not isinstance(node, dict):
            continue
        main = ((((node.get("data") or {}).get("item") or {}).get("main")) or {})
        if not isinstance(main, dict):
            continue
        ex_content = main.get("exContent") or {}
        detail_params = ex_content.get("detailParams") if isinstance(ex_content, dict) else {}
        click_args = (main.get("clickParam") or {}).get("args") if isinstance(main.get("clickParam"), dict) else {}
        if not isinstance(ex_content, dict):
            ex_content = {}
        if not isinstance(detail_params, dict):
            detail_params = {}
        if not isinstance(click_args, dict):
            click_args = {}

        item_id = (
            _first_text(ex_content, ["itemId", "item_id", "id"])
            or _first_text(detail_params, ["itemId", "item_id", "id"])
            or _first_text(click_args, ["item_id", "itemId", "id"])
        )
        title = (
            _first_text(ex_content, ["title", "name", "mainTitle"])
            or _first_text(detail_params, ["title", "name", "mainTitle"])
        )
        price = _price_from_any(
            _first_value(detail_params, ["soldPrice", "price", "displayPrice"])
            or _first_value(click_args, ["price", "soldPrice", "displayPrice"])
            or _first_value(ex_content, ["soldPrice", "currentPrice", "priceText"])
        )
        if not title or price is None:
            continue

        item_url = (
            _normalize_url(_first_text(ex_content, ["itemUrl", "url", "targetUrl", "detailUrl"]))
            or _normalize_url(_first_text(detail_params, ["itemUrl", "url", "targetUrl", "detailUrl"]))
            or (f"https://www.goofish.com/item?id={item_id}" if item_id else "")
        )
        tag = _first_text(click_args, ["tag", "tags"])
        tagname = _first_text(click_args, ["tagname", "tagName"])
        publish_time = (
            _timestamp_to_iso(_first_value(click_args, ["publishTime", "publish_time"]))
            or _first_text(ex_content, ["publishTime", "publish_time"])
            or _first_text(detail_params, ["publishTime", "publish_time"])
        )
        raw_source = main if main else node
        items.append(
            XianyuParsedItem(
                item_id=item_id,
                title=title,
                price=price,
                location=_first_text(ex_content, ["area", "location", "city", "sellerLocation"]),
                item_updated_at=_first_text(ex_content, ["updateTime", "itemUpdatedAt", "createdAt"]),
                publish_time=publish_time,
                want_info=(
                    _first_text(ex_content, ["wantCount", "wantNum", "browseInfo", "viewCount", "wantInfo"])
                    or _first_text(detail_params, ["wantCount", "wantNum", "browseInfo", "viewCount", "wantInfo"])
                ),
                item_url=item_url,
                condition=_first_text(ex_content, ["condition", "itemCondition"]) or _guess_condition(title),
                free_shipping=_free_shipping_from_texts([tag, tagname, title]),
                raw_text=_compact_text(json.dumps(raw_source, ensure_ascii=False))[:500],
            )
        )
    return items


def _item_from_dict(data: dict[str, Any]) -> XianyuParsedItem | None:
    item_id = _first_text(data, ["itemId", "item_id", "id"])
    title = _first_text(data, ["title", "name", "itemTitle", "mainTitle", "subject", "desc"])
    price = _price_from_any(
        _first_value(
            data,
            [
                "price",
                "soldPrice",
                "currentPrice",
                "priceText",
                "reservePrice",
                "discountPrice",
            ],
        )
    )
    if not title or price is None:
        return None

    return XianyuParsedItem(
        item_id=item_id,
        title=title,
        price=price,
        location=_first_text(data, ["area", "location", "city", "sellerLocation"]),
        item_updated_at=_first_text(data, ["publishTime", "updateTime", "createdAt", "itemUpdatedAt"]),
        publish_time=_timestamp_to_iso(_first_value(data, ["publishTime", "publish_time"]))
        or _first_text(data, ["publishTime", "publish_time"]),
        want_info=_first_text(data, ["wantCount", "wantNum", "browseInfo", "viewCount", "wantInfo"]),
        item_url=_normalize_url(_first_text(data, ["itemUrl", "url", "targetUrl", "detailUrl"]))
        or (f"https://www.goofish.com/item?id={item_id}" if item_id else ""),
        condition=_first_text(data, ["condition", "itemCondition"]) or _guess_condition(title),
        free_shipping=_free_shipping_from_texts(
            [
                _first_text(data, ["tag", "tags", "tagname", "tagName", "shipping"]),
                title,
            ]
        ),
        raw_text=_compact_text(json.dumps(data, ensure_ascii=False))[:500],
    )


def _parse_dom_items(html: str) -> list[XianyuParsedItem]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("beautifulsoup4 is required. Run: pip install -r requirements.txt") from exc

    soup = BeautifulSoup(html, "html.parser")
    items: list[XianyuParsedItem] = []
    for tag in soup.find_all(["a", "div", "li", "article", "section"]):
        text = _compact_text(tag.get_text(" ", strip=True))
        if len(text) < 8 or len(text) > 500:
            continue
        price = _extract_price(text)
        if price is None:
            continue
        identity = " ".join(tag.get("class", [])) + " " + str(tag.get("id") or "")
        if tag.name != "a" and not _looks_like_item_container(identity, text):
            continue

        title = _extract_title(tag, text)
        if not title:
            continue
        items.append(
            XianyuParsedItem(
                title=title,
                price=price,
                location=_extract_location(text),
                item_updated_at=_extract_item_time(text),
                want_info=_extract_want_info(text),
                item_url=_extract_item_url(tag),
                condition=_guess_condition(title),
                free_shipping=_free_shipping_from_texts([text]),
                raw_text=text[:500],
            )
        )
    return items


def _filter_outliers(prices: list[float]) -> tuple[list[float], int]:
    if len(prices) < 3:
        return sorted(prices), 0
    values = sorted(prices)
    center = median(values)
    lower = center * 0.55
    upper = center * 1.6
    if len(values) >= 5:
        q1 = values[len(values) // 4]
        q3 = values[(len(values) * 3) // 4]
        iqr = q3 - q1
        if iqr > 0:
            lower = max(lower, q1 - 1.5 * iqr)
            upper = min(upper, q3 + 1.5 * iqr)
    filtered = [price for price in values if lower <= price <= upper]
    return filtered, len(values) - len(filtered)


def _low_price_band(prices: list[float]) -> list[float]:
    values = sorted(prices)
    if not values:
        return []
    count = max(1, math.ceil(len(values) * 0.4))
    if len(values) >= 5:
        count = max(2, count)
    return values[:count]


def _dedupe_items(items: list[XianyuParsedItem]) -> list[XianyuParsedItem]:
    seen = set()
    deduped: list[XianyuParsedItem] = []
    for item in items:
        if item.price is None:
            continue
        key = (
            item.item_id,
            re.sub(r"\s+", "", item.title.lower())[:40],
            round(float(item.price), 2),
            item.item_url,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _title_score(product: Product, title: str) -> int:
    normalized = _normalize_for_match(title)
    score = 0
    for token in _product_tokens(product):
        if token and token in normalized:
            score += 1
    return score


def _product_tokens(product: Product) -> list[str]:
    raw_tokens = [
        product.brand,
        product.capacity,
        product.frequency,
        product.memory_type,
        product.form_factor,
    ]
    if product.model:
        raw_tokens.extend(product.model.split())
    if product.sell_keyword:
        raw_tokens.extend(product.sell_keyword.split())
    tokens = []
    for token in raw_tokens:
        normalized = _normalize_for_match(token)
        if len(normalized) >= 2 and normalized not in tokens:
            tokens.append(normalized)
    return tokens


def _has_preferred_condition(title: str) -> bool:
    return any(word in title for word in ["全新", "未拆", "未拆封", "未使用", "仅拆封", "准新"])


def _guess_condition(title: str | None) -> str:
    if not title:
        return ""
    match = re.search(r"(全新|未拆封|未使用|仅拆封|几乎全新|准新|[一二三四五六七八九十]成新|\d成新|\d{1,3}新)", title)
    return match.group(1) if match else ""


def _free_shipping_from_texts(texts: list[str]) -> bool | None:
    joined = " ".join(text for text in texts if text).lower()
    if not joined:
        return None
    if "不包邮" in joined or "运费到付" in joined:
        return False
    if "包邮" in joined or "free shipping" in joined or "freeship" in joined:
        return True
    return None


def _sell_keyword(product: Product) -> str:
    return product.sell_keyword or product.keyword or product.display_name


def _xianyu_search_url(keyword: str) -> str:
    return f"https://www.goofish.com/search?q={quote_plus(keyword)}"


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


def _looks_like_item_container(identity: str, text: str) -> bool:
    if re.search(r"item|card|goods|product|feed|result|list", identity, re.IGNORECASE):
        return True
    return bool(re.search(r"(想要|浏览|分钟前|小时前|今天|昨天|¥|￥)", text))


def _extract_title(tag: Any, text: str) -> str:
    for attr in ["title", "aria-label", "data-title"]:
        value = tag.get(attr)
        if value:
            return _clean_title(str(value))
    heading = tag.find(["h1", "h2", "h3", "h4"])
    if heading:
        return _clean_title(heading.get_text(" ", strip=True))
    without_price = re.sub(r"[¥￥]\s*\d+(?:\.\d{1,2})?", " ", text)
    without_price = re.sub(r"\b\d+(?:\.\d{1,2})?\s*(人想要|人浏览|浏览|想要)\b", " ", without_price)
    return _clean_title(without_price)


def _clean_title(text: str) -> str:
    cleaned = _compact_text(text)
    cleaned = re.sub(r"(¥|￥)\s*\d+(?:\.\d{1,2})?", " ", cleaned)
    cleaned = _compact_text(cleaned)
    return cleaned[:120]


def _extract_price(text: str) -> float | None:
    for pattern in [
        r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)(万)?",
        r"(?:price|价格)[\"':：\s]*([0-9]+(?:\.[0-9]{1,2})?)",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if len(match.groups()) >= 2 and match.group(2):
                value *= 10000
            if 10 <= value <= 10000:
                return value
    return None


def _price_from_any(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ["price", "priceText", "value", "amount", "cent"]:
            price = _price_from_any(value.get(key))
            if price is not None:
                if key == "cent" and price > 10000:
                    return price / 100
                return price
        return None
    return _extract_price(str(value)) or _numeric_price(str(value))


def _numeric_price(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]{1,2})?)", text)
    if not match:
        return None
    value = float(match.group(1))
    if "万" in text[match.end() : match.end() + 2]:
        value *= 10000
    if 10 <= value <= 10000:
        return value
    return None


def _extract_location(text: str) -> str:
    match = re.search(
        r"(北京|上海|天津|重庆|广州|深圳|杭州|南京|苏州|成都|武汉|西安|郑州|长沙|合肥|宁波|无锡|青岛|厦门|福州|东莞|佛山|南宁|昆明|沈阳|大连|长春|哈尔滨|石家庄|太原|济南|南昌|贵阳|兰州|银川|乌鲁木齐|呼和浩特)",
        text,
    )
    return match.group(1) if match else ""


def _extract_item_time(text: str) -> str:
    match = re.search(
        r"(刚刚|\d+\s*分钟前|\d+\s*小时前|今天|昨天|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        text,
    )
    return _compact_text(match.group(1)) if match else ""


def _extract_want_info(text: str) -> str:
    match = re.search(r"(\d+\s*(?:人想要|想要|人浏览|浏览))", text)
    return _compact_text(match.group(1)) if match else ""


def _extract_item_url(tag: Any) -> str:
    href = tag.get("href")
    if not href:
        link = tag.find("a", href=True)
        href = link.get("href") if link else ""
    return _normalize_url(str(href or ""))


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.goofish.com" + url
    return url


def _first_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None


def _first_text(data: dict[str, Any], keys: list[str]) -> str:
    value = _first_value(data, keys)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _compact_text(json.dumps(value, ensure_ascii=False))
    return _compact_text(str(value))


def _timestamp_to_iso(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = int(str(value).strip())
    except ValueError:
        return ""
    if number <= 0:
        return ""
    if number > 10_000_000_000:
        number = number // 1000
    return datetime.fromtimestamp(number, tz=timezone.utc).replace(microsecond=0).isoformat()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).lower().replace("gb", "g")


def _price_range(values: list[float]) -> str:
    if not values:
        return ""
    return f"{min(values):.2f}-{max(values):.2f}"


def _money(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


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
