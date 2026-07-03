from __future__ import annotations

import re


class TaobaoCollector:
    """Taobao collector placeholder for saved HTML parsing."""

    source = "taobao_html"

    def parse_price_from_html(self, html: str) -> float | None:
        return parse_price_from_html(html)


def parse_price_from_html(html: str) -> float | None:
    return _first_price(
        html,
        [
            r'"price"\s*:\s*"([0-9]+(?:\.[0-9]{1,2})?)"',
            r'"promotionPrice"\s*:\s*"([0-9]+(?:\.[0-9]{1,2})?)"',
            r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)",
        ],
    )


def _first_price(html: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None
