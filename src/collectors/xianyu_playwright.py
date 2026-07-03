from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from xianyu_tools import parse_xianyu_html


PLATFORM = "xianyu"


def fetch_search_results(page: Any, product: Any, limit: int = 20) -> dict[str, object]:
    url = f"https://www.goofish.com/search?q={quote_plus(product.sell_keyword or product.keyword or product.display_name)}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    body_text = _body_text(page)
    html = page.content()
    items = parse_xianyu_html(html, product)
    if limit > 0:
        items = items[:limit]

    if not items:
        return {
            "ok": False,
            "platform": PLATFORM,
            "items": [],
            "url": page.url,
            "reason": _failure_reason(body_text),
        }

    return {
        "ok": True,
        "platform": PLATFORM,
        "items": items,
        "url": page.url,
        "reason": "",
    }


def _failure_reason(text: str) -> str:
    if _has_any(text, ["验证码", "安全验证", "滑块", "拖动滑块", "访问验证"]):
        return "触发验证码"
    if _has_any(text, ["登录后", "请登录", "扫码登录", "账号登录"]):
        return "需要登录"
    if _has_any(text, ["访问过于频繁", "系统繁忙", "环境异常", "风险"]):
        return "触发风控"
    if text.strip():
        return "未找到搜索结果元素"
    return "页面结构变化"


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _body_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""
