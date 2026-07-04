from __future__ import annotations

import re
from typing import Any


PLATFORM = "pdd"


def fetch_buy_price(page: Any, url: str, manual_wait_seconds: int = 0) -> dict[str, object]:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _manual_wait(page, manual_wait_seconds)
    page.wait_for_timeout(3000)
    title = _page_title(page)
    price = _extract_price_from_selectors(
        page,
        [
            "[class*='price']",
            "[class*='Price']",
            "[data-testid*='price']",
            "[data-testid*='Price']",
        ],
    )
    body_text = _body_text(page)
    if price is None:
        price = _extract_price_from_text(body_text)

    if price is None:
        return {
            "ok": False,
            "platform": PLATFORM,
            "price": None,
            "title": title,
            "url": page.url,
            "reason": _failure_reason(body_text),
        }

    return {
        "ok": True,
        "platform": PLATFORM,
        "price": price,
        "title": title,
        "url": page.url,
        "reason": "",
    }


def _extract_price_from_selectors(page: Any, selectors: list[str]) -> float | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 10)
            for index in range(count):
                text = locator.nth(index).inner_text(timeout=1200)
                price = _extract_price_from_text(text)
                if price is not None:
                    return price
        except Exception:
            continue
    return None


def _extract_price_from_text(text: str) -> float | None:
    patterns = [
        r"[¥￥]\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)",
        r"(?:拼单价|券后|到手价|价格)\s*[:：]?\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = float(match.group(1))
            if 10 <= value <= 10000:
                return value
    return None


def _failure_reason(text: str) -> str:
    if _has_any(text, ["验证码", "安全验证", "滑块", "拖动滑块", "访问验证"]):
        return "触发验证码"
    if _has_any(text, ["登录后查看", "请登录", "手机号登录", "扫码登录"]):
        return "需要登录"
    if _has_any(text, ["访问过于频繁", "系统繁忙", "环境异常", "风险"]):
        return "触发风控"
    if text.strip():
        return "未找到价格元素"
    return "页面结构变化"


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _body_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _page_title(page: Any) -> str:
    for selector in ["h1", "[class*='title']", "[class*='Title']"]:
        try:
            text = page.locator(selector).first.inner_text(timeout=1000).strip()
            if text and len(text) >= 4:
                return text[:160]
        except Exception:
            continue
    try:
        return page.title()
    except Exception:
        return ""


def _manual_wait(page: Any, seconds: int) -> None:
    if seconds <= 0:
        return
    page.wait_for_timeout(seconds * 1000)
