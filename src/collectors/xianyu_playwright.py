from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from xianyu_tools import parse_xianyu_html, parse_xianyu_search_json


PLATFORM = "xianyu"
SEARCH_API = "mtop.taobao.idlemtopsearch.pc.search"


def fetch_search_results(page: Any, product: Any, limit: int = 20) -> dict[str, object]:
    url = f"https://www.goofish.com/search?q={quote_plus(product.sell_keyword or product.keyword or product.display_name)}"
    captured_payloads: list[Any] = []

    def _on_response(response: Any) -> None:
        if SEARCH_API not in str(getattr(response, "url", "")):
            return
        try:
            captured_payloads.append(response.json())
        except Exception:
            pass

    page.on("response", _on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        if not captured_payloads:
            _scroll_once(page)
            page.wait_for_timeout(2500)
        body_text = _body_text(page)
        html = page.content()
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass

    items = []
    for payload in captured_payloads:
        items.extend(parse_xianyu_search_json(payload, product))
    items = _dedupe_items(items)
    if not items:
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
            "capture_mode": "response" if captured_payloads else "html",
        }

    return {
        "ok": True,
        "platform": PLATFORM,
        "items": items,
        "url": page.url,
        "reason": "",
        "capture_mode": "response" if captured_payloads else "html",
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


def _scroll_once(page: Any) -> None:
    try:
        page.evaluate("window.scrollTo(0, Math.min(document.body.scrollHeight, 1200))")
    except Exception:
        pass


def _dedupe_items(items: list[Any]) -> list[Any]:
    seen = set()
    deduped = []
    for item in items:
        key = item.item_id or (item.title, item.price, item.item_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
