from __future__ import annotations

import re
from statistics import median


class XianyuCollector:
    """Xianyu collector placeholder for saved search-result HTML parsing."""

    source = "xianyu_html"

    def parse_search_result_html(self, html: str) -> dict[str, float | int | None]:
        return parse_search_result_html(html)


def parse_search_result_html(html: str) -> dict[str, float | int | None]:
    prices = _extract_prices(html)
    listing_count = _extract_listing_count(html)
    reference_price = float(median(prices)) if prices else None
    return {
        "sell_price": reference_price,
        "xianyu_listing_count": listing_count,
    }


def _extract_prices(html: str) -> list[float]:
    prices: list[float] = []
    for match in re.finditer(r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)", html):
        value = float(match.group(1))
        if 10 <= value <= 10000:
            prices.append(value)
    return prices


def _extract_listing_count(html: str) -> int | None:
    patterns = [
        r"共\s*(\d+)\s*件",
        r"(\d+)\s*个宝贝",
        r"(\d+)\s*条结果",
        r"listingCount[\"']?\s*[:=]\s*[\"']?(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None
