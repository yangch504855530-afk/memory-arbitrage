from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alerts import check_alerts
from analyzer import analyze
from browser_fetcher import FetchOptions, fetch_prices
from collection import build_buy_links, build_collection_plan, build_search_keywords
from collectors.manual import ManualCollector
from db import DEFAULT_DB_PATH, init_db, insert_price_observation
from exporter import export_csv
from importer import import_products
from price_importer import import_price_records
from sample_data import load_sample_data
from xianyu_tools import (
    DEFAULT_GENERATED_PRICES_PATH,
    DEFAULT_SEARCH_URLS_PATH,
    generate_prices_from_xianyu,
    generate_search_urls,
    import_xianyu_html,
    suggest_prices,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-arbitrage",
        description="内存条套利监控本地 MVP",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite database path, default: {DEFAULT_DB_PATH}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="初始化数据库")

    subparsers.add_parser("load-sample-data", help="导入样例商品和样例历史价格")

    import_parser = subparsers.add_parser("import-products", help="导入商品池 YAML/CSV")
    import_parser.add_argument(
        "--file",
        required=True,
        help="商品池文件路径，例如 config/products.example.yaml",
    )

    import_prices_parser = subparsers.add_parser("import-prices", help="从 CSV 批量导入价格记录")
    import_prices_parser.add_argument(
        "--file",
        required=True,
        help="价格 CSV 路径，例如 config/prices.csv",
    )

    record_parser = subparsers.add_parser("record-price", help="手动录入一次价格")
    record_parser.add_argument("--product-id", required=True)
    record_parser.add_argument("--buy-price", type=float, required=True)
    record_parser.add_argument("--sell-price", type=float, required=True)
    record_parser.add_argument("--xianyu-listing-count", type=int)
    record_parser.add_argument("--collected-at", help="ISO 时间，默认当前时间")
    record_parser.add_argument("--buy-source", default="", help="买入价来源备注")
    record_parser.add_argument("--sell-source", default="", help="闲鱼参考价来源备注")
    record_parser.add_argument("--raw-payload", default="", help="原始记录备注，可选")

    analyze_parser = subparsers.add_parser("analyze", help="运行分析")
    analyze_parser.add_argument("--product-id", help="只分析某个商品")
    analyze_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式",
    )

    export_parser = subparsers.add_parser("export-csv", help="导出 CSV 报表")
    export_parser.add_argument("--output", required=True, help="输出 CSV 路径")
    export_parser.add_argument("--product-id", help="只导出某个商品")

    subparsers.add_parser("search-keywords", help="输出闲鱼人工搜索关键词清单")
    subparsers.add_parser("open-buy-links", help="输出买入平台链接清单，不自动打开浏览器")
    subparsers.add_parser("collection-plan", help="输出今日待采集清单")

    search_urls_parser = subparsers.add_parser("generate-search-urls", help="生成闲鱼搜索链接和买入链接 CSV")
    search_urls_parser.add_argument(
        "--output",
        default=str(DEFAULT_SEARCH_URLS_PATH),
        help=f"输出 CSV 路径，默认: {DEFAULT_SEARCH_URLS_PATH}",
    )

    xianyu_html_parser = subparsers.add_parser("import-xianyu-html", help="导入手动保存的闲鱼搜索结果 HTML")
    xianyu_html_parser.add_argument("--product-id", required=True)
    xianyu_html_parser.add_argument("--file", required=True, help="HTML 文件路径")

    suggest_parser = subparsers.add_parser("suggest-prices", help="基于最新闲鱼 HTML 解析结果建议闲鱼参考价")
    suggest_parser.add_argument("--product-id", help="只建议某个商品")
    suggest_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式",
    )

    gen_prices_parser = subparsers.add_parser("generate-prices-from-xianyu", help="根据最新买入价和闲鱼建议价生成 prices.csv")
    gen_prices_parser.add_argument(
        "--output",
        default=str(DEFAULT_GENERATED_PRICES_PATH),
        help=f"输出 CSV 路径，默认: {DEFAULT_GENERATED_PRICES_PATH}",
    )

    fetch_parser = subparsers.add_parser("fetch-prices", help="自动采集买入价和闲鱼搜索结果 MVP")
    fetch_parser.add_argument("--product-id", help="只采集某个商品")
    fetch_parser.add_argument(
        "--source",
        action="append",
        choices=["jd", "pdd", "xianyu"],
        help="采集来源，可重复指定；不指定时默认 jd/pdd/xianyu",
    )
    fetch_parser.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    fetch_parser.add_argument("--delay", type=float, default=5, help="每个页面访问间隔秒数，默认 5")
    fetch_parser.add_argument("--limit", type=int, default=10, help="每次最多采集商品数，默认 10")

    alerts_parser = subparsers.add_parser("check-alerts", help="检查买入价降价提醒")
    alerts_parser.add_argument("--product-id", help="只检查某个商品")
    alerts_parser.add_argument("--min-drop-abs", type=float, default=10, help="较上次降价提醒金额阈值，默认 10")
    alerts_parser.add_argument("--min-drop-pct", type=float, default=5, help="较上次降价提醒百分比阈值，默认 5")
    alerts_parser.add_argument("--cooldown-hours", type=int, default=24, help="同类提醒冷却小时数，默认 24")
    alerts_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    try:
        if args.command == "init-db":
            init_db(db_path)
            print(f"数据库已初始化: {db_path}")
            return 0

        if args.command == "import-products":
            count = import_products(args.file, db_path=db_path)
            print(f"已导入/更新商品: {count} 个")
            return 0

        if args.command == "import-prices":
            count = import_price_records(args.file, db_path=db_path)
            print(f"已导入价格记录: {count} 条")
            return 0

        if args.command == "load-sample-data":
            result = load_sample_data(db_path=db_path)
            print(
                "样例数据已导入: "
                f"商品 {result['products']} 个，"
                f"价格记录 {result['observations']} 条，"
                f"清理旧样例价格 {result['deleted_observations']} 条"
            )
            return 0

        if args.command == "record-price":
            observation = ManualCollector().collect(
                product_id=args.product_id,
                buy_price=args.buy_price,
                sell_price=args.sell_price,
                xianyu_listing_count=args.xianyu_listing_count,
                collected_at=args.collected_at,
                buy_source=args.buy_source,
                sell_source=args.sell_source,
                raw_payload=args.raw_payload,
            )
            row_id = insert_price_observation(observation, db_path=db_path)
            print(f"价格记录已保存: observation_id={row_id}")
            return 0

        if args.command == "analyze":
            results = analyze(db_path=db_path, product_id=args.product_id)
            if args.format == "json":
                print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
            else:
                print_analysis_table(results)
            return 0

        if args.command == "export-csv":
            output = export_csv(args.output, db_path=db_path, product_id=args.product_id)
            print(f"CSV 报表已导出: {output}")
            return 0

        if args.command == "search-keywords":
            print_search_keywords(build_search_keywords(db_path=db_path))
            return 0

        if args.command == "open-buy-links":
            print_buy_links(build_buy_links(db_path=db_path))
            return 0

        if args.command == "collection-plan":
            print_collection_plan(build_collection_plan(db_path=db_path))
            return 0

        if args.command == "generate-search-urls":
            output = generate_search_urls(output_path=args.output, db_path=db_path)
            print(f"搜索链接 CSV 已生成: {output}")
            return 0

        if args.command == "import-xianyu-html":
            items = import_xianyu_html(
                product_id=args.product_id,
                html_path=args.file,
                db_path=db_path,
            )
            print(f"闲鱼 HTML 已解析并入库: {len(items)} 条")
            print_xianyu_items(items)
            return 0

        if args.command == "suggest-prices":
            suggestions = suggest_prices(db_path=db_path, product_id=args.product_id)
            if args.format == "json":
                print(json.dumps([row.__dict__ for row in suggestions], ensure_ascii=False, indent=2))
            else:
                print_suggestions(suggestions)
            return 0

        if args.command == "generate-prices-from-xianyu":
            output, rows = generate_prices_from_xianyu(output_path=args.output, db_path=db_path)
            print(f"prices.csv 已生成: {output}")
            print_generated_price_rows(rows)
            return 0

        if args.command == "fetch-prices":
            outcomes = fetch_prices(
                db_path=db_path,
                options=FetchOptions(
                    product_id=args.product_id,
                    sources=args.source,
                    headful=args.headful,
                    delay=args.delay,
                    limit=args.limit,
                ),
            )
            print_fetch_outcomes(outcomes)
            alert_rows = check_alerts(db_path=db_path, product_id=args.product_id)
            if alert_rows:
                print("\n新增降价提醒:")
                print_alert_events(alert_rows)
            else:
                print("\n暂无新增降价提醒")
            return 0

        if args.command == "check-alerts":
            alert_rows = check_alerts(
                db_path=db_path,
                product_id=args.product_id,
                min_drop_abs=args.min_drop_abs,
                min_drop_pct=args.min_drop_pct,
                cooldown_hours=args.cooldown_hours,
            )
            if args.format == "json":
                print(json.dumps([row.__dict__ for row in alert_rows], ensure_ascii=False, indent=2))
            else:
                print_alert_events(alert_rows)
            return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def print_analysis_table(results: list[object]) -> None:
    headers = [
        "商品名称",
        "买入价",
        "闲鱼价",
        "价差",
        "利润",
        "利润率%",
        "在售",
        "7天低",
        "历史低",
        "闲鱼涨跌",
        "7天买均",
        "7天鱼均",
        "推荐等级",
        "买入理由",
        "风险提示",
    ]
    rows = []
    for result in results:
        rows.append(
            [
                result.product_name,
                _money(result.current_buy_price),
                _money(result.xianyu_reference_price),
                _money(result.price_spread),
                _money(result.expected_profit),
                _percent(result.profit_rate),
                "" if result.xianyu_listing_count is None else str(result.xianyu_listing_count),
                _bool_text(result.is_7d_low),
                _bool_text(result.is_historical_low),
                result.sell_price_change,
                _money(result.avg_7d_buy_price),
                _money(result.avg_7d_sell_price),
                result.recommendation_level,
                result.buy_reason,
                result.risk_tips,
            ]
        )
    _print_table(headers, rows)


def print_search_keywords(rows: list[object]) -> None:
    headers = ["product_id", "商品名称", "sell_keyword", "建议复制到闲鱼搜索的关键词"]
    table_rows = [
        [
            row.product_id,
            row.product_name,
            row.sell_keyword,
            row.suggested_keyword,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def print_buy_links(rows: list[object]) -> None:
    headers = ["product_id", "商品名称", "buy_platform", "buy_url", "target_buy_price"]
    table_rows = [
        [
            row.product_id,
            row.product_name,
            row.buy_platform,
            row.buy_url,
            _money(row.target_buy_price),
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def print_collection_plan(rows: list[object]) -> None:
    if not rows:
        print("今天暂无待采集商品")
        return
    headers = [
        "product_id",
        "商品名称",
        "从未采集",
        "超过24小时",
        "接近目标",
        "优先级",
        "最近买入价",
        "目标买入价",
        "最近采集时间",
        "原因",
    ]
    table_rows = [
        [
            row.product_id,
            row.product_name,
            _bool_text(row.never_collected),
            _bool_text(row.overdue_24h),
            _bool_text(row.close_to_target_buy_price),
            row.priority,
            _money(row.latest_buy_price),
            _money(row.target_buy_price),
            row.latest_collected_at,
            row.reason,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def print_xianyu_items(rows: list[object]) -> None:
    headers = ["item_id", "标题", "价格", "地区", "时间", "成色", "包邮", "想要/浏览", "商品链接"]
    table_rows = [
        [
            row.item_id,
            row.title,
            _money(row.price),
            row.location,
            row.publish_time or row.item_updated_at,
            row.condition,
            _bool_text(row.free_shipping),
            row.want_info,
            row.item_url,
        ]
        for row in rows[:30]
    ]
    _print_table(headers, table_rows)
    if len(rows) > 30:
        print(f"仅展示前 30 条，实际解析 {len(rows)} 条")


def print_suggestions(rows: list[object]) -> None:
    headers = [
        "product_id",
        "商品名称",
        "建议闲鱼价",
        "样本数",
        "采用样本",
        "价格区间",
        "采用区间",
        "解析时间",
        "风险提示",
    ]
    table_rows = [
        [
            row.product_id,
            row.product_name,
            _money(row.suggested_sell_price),
            str(row.sample_count),
            str(row.used_sample_count),
            row.price_range,
            row.used_price_range,
            row.observed_at,
            row.risk_tips,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def print_generated_price_rows(rows: list[object]) -> None:
    headers = ["product_id", "buy_price", "sell_price", "闲鱼样本数", "source", "observed_at", "状态"]
    table_rows = [
        [
            row.product_id,
            _money(row.buy_price),
            _money(row.sell_price),
            str(row.xianyu_listing_count),
            row.source,
            row.observed_at,
            row.status,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def print_fetch_outcomes(rows: list[object]) -> None:
    headers = [
        "product_id",
        "平台",
        "成功",
        "价格/建议价",
        "闲鱼样本",
        "标题",
        "失败原因",
        "采集时间",
    ]
    table_rows = [
        [
            row.product_id,
            row.platform,
            _bool_text(row.ok),
            _money(row.price or row.suggested_sell_price),
            str(row.item_count or ""),
            row.title,
            row.reason or row.risk_tips,
            row.observed_at,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)
    print("采集日志: logs/fetch.log")


def print_alert_events(rows: list[object]) -> None:
    headers = [
        "product_id",
        "商品名称",
        "提醒类型",
        "当前价",
        "对比价",
        "降价额",
        "降幅",
        "source",
        "提醒内容",
        "时间",
    ]
    table_rows = [
        [
            row.product_id,
            row.product_name,
            _alert_type_text(row.alert_type),
            _money(row.current_price),
            _money(row.previous_price or row.threshold_price),
            _money(row.drop_abs),
            _percent(row.drop_pct),
            row.source,
            row.message,
            row.created_at,
        ]
        for row in rows
    ]
    _print_table(headers, table_rows)


def _alert_type_text(value: str) -> str:
    return {
        "target_buy_reached": "达到目标买入价",
        "all_time_low": "历史新低",
        "price_decreased": "较上次下降",
    }.get(value, value)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("暂无商品数据")
        return
    widths = [display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], min(display_width(cell), 36))

    def fmt_row(row: list[str]) -> str:
        cells = []
        for index, cell in enumerate(row):
            text = truncate_display(cell, widths[index])
            cells.append(text + " " * (widths[index] - display_width(text)))
        return " | ".join(cells)

    print(fmt_row(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(fmt_row(row))


def _money(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _percent(value: float | None) -> str:
    return "" if value is None else f"{value:.2%}"


def _bool_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "是" if value else "否"


def display_width(text: object) -> int:
    total = 0
    for char in str(text):
        total += 2 if ord(char) > 127 else 1
    return total


def truncate_display(text: object, max_width: int) -> str:
    source = str(text)
    if display_width(source) <= max_width:
        return source
    result = ""
    width = 0
    for char in source:
        char_width = 2 if ord(char) > 127 else 1
        if width + char_width > max_width - 2:
            break
        result += char
        width += char_width
    return result + ".."


if __name__ == "__main__":
    raise SystemExit(main())
