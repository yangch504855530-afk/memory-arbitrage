# 内存条套利监控 MVP

本项目是一个本地命令行版 MVP，用商品白名单维护内存条标的，记录买入平台价格和闲鱼卖出参考价，并计算预计利润、利润率、历史价格位置和推荐等级。

当前阶段保持轻量方案：本地 Python + SQLite + CSV，不做前端页面，不做自动下单，也不绕过平台登录、验证码或风控。自动采集只尝试读取公开页面可见数据，失败时回退到手动录价或 HTML 导入。

## 项目结构

```text
memory-arbitrage/
  README.md
  requirements.txt
  config/
    products.example.yaml
    products.sample.yaml
    prices.example.csv
    price_observations.sample.csv
  data/
    arbitrage.db
    search_urls.csv
    prices.csv
  src/
    main.py
    db.py
    models.py
    importer.py
    alerts.py
    collectors/
      manual.py
      jd.py
      jd_playwright.py
      pdd.py
      pdd_playwright.py
      taobao.py
      xianyu.py
      xianyu_playwright.py
    analyzer.py
    browser_fetcher.py
    exporter.py
    xianyu_tools.py
    sample_data.py
```

## 安装

```bash
cd memory-arbitrage
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

也可以不建虚拟环境，直接使用本机 Python 运行，但建议隔离依赖。

`fetch-prices` 依赖 Playwright 和 Chromium。其他命令不依赖浏览器，未安装 Chromium 时仍可使用手动录价、HTML 导入、分析和导出功能。

## 初始化数据库

```bash
python src/main.py init-db
```

默认数据库路径是：

```text
data/arbitrage.db
```

指定其他数据库：

```bash
python src/main.py --db data/test.db init-db
```

## 直接载入样例数据

第二阶段新增了样例商品和样例历史价格，方便直接看分析效果：

```bash
python src/main.py --db data/sample.db load-sample-data
python src/main.py --db data/sample.db analyze
```

样例数据包含 3 个内存条商品和多天价格记录，可以看到：

- 当前买入价是否为近 7 天最低
- 当前买入价是否为历史最低
- 闲鱼参考价相比上一次上涨、下降或持平
- 近 7 天平均买入价
- 近 7 天平均闲鱼参考价
- 推荐等级和买入理由

再次执行 `load-sample-data` 会清理旧的 `source=sample` 样例价格记录后重新导入，不会删除手动录入的价格。

## 维护商品池

商品池可以使用 YAML 或 CSV。推荐先复制示例：

```bash
cp config/products.example.yaml config/products.yaml
```

字段包括：

```text
product_id, brand, model, keyword, capacity, frequency, memory_type,
form_factor, buy_platform, buy_url, sell_platform, sell_keyword,
target_buy_price, target_sell_price, min_profit_rate, shipping_cost, note
```

导入商品池：

```bash
python src/main.py import-products --file config/products.yaml
```

导入时会做校验：

- `product_id` 不能重复
- 除 `note` 外，商品字段都按必填处理
- `target_buy_price`、`target_sell_price`、`min_profit_rate`、`shipping_cost` 必须是数字
- `min_profit_rate` 使用小数，例如 `0.12` 表示 12%

重复导入同一个已有商品会按 `product_id` 更新数据库中的商品基础信息。

## 手动录入价格

第一阶段和第二阶段都推荐先用手动录价跑通日常流程：

```bash
python src/main.py record-price \
  --product-id kingbank-ddr4-3200-16g-001 \
  --buy-price 158 \
  --sell-price 205 \
  --xianyu-listing-count 12 \
  --buy-source "京东手动查看" \
  --sell-source "闲鱼搜索中位数"
```

字段含义：

- `buy-price`：当前买入平台到手价
- `sell-price`：闲鱼参考卖出价
- `xianyu-listing-count`：闲鱼搜索结果在售数量，可选
- `buy-source` / `sell-source`：数据来源备注
- `collected-at`：采集时间，可选，ISO 格式；不填则使用当前时间

## 批量录入价格

第三阶段新增 CSV 批量录价，适合每天人工看完几个平台后集中导入：

```bash
cp config/prices.example.csv config/prices.csv
python src/main.py import-prices --file config/prices.csv
```

价格 CSV 字段：

```text
product_id,buy_price,sell_price,xianyu_listing_count,source,observed_at
```

字段说明：

- `product_id`：必须已经存在于商品池
- `buy_price`：买入平台当前到手价
- `sell_price`：闲鱼参考价
- `xianyu_listing_count`：闲鱼在售数量，可以为空
- `source`：数据来源，例如 `manual_batch`、`jd_manual`、`xianyu_manual`
- `observed_at`：观察时间，ISO 格式，例如 `2026-07-03T20:00:00+08:00`

导入前会校验字段、数字格式、时间格式和商品是否存在。批量导入不会自动抓取网页，也不会自动下单。

## 闲鱼人工采集辅助

输出每个商品建议复制到闲鱼搜索的关键词：

```bash
python src/main.py search-keywords
```

输出字段：

- `product_id`
- 商品名称
- `sell_keyword`
- 建议复制到闲鱼搜索的关键词

## 买入平台链接清单

输出买入平台链接和目标买入价，方便逐个打开核价。命令只输出链接，不自动打开浏览器：

```bash
python src/main.py open-buy-links
```

输出字段：

- `product_id`
- 商品名称
- `buy_platform`
- `buy_url`
- `target_buy_price`

## 今日待采集清单

根据历史价格记录生成当天优先采集商品：

```bash
python src/main.py collection-plan
```

会标记：

- 从未采集
- 超过 24 小时未采集
- 最近价格接近目标买入价
- 推荐优先级：高 / 中 / 低

“接近目标买入价”默认按 `当前买入价 <= target_buy_price * 1.05` 判断。采集计划只用于人工核价提醒，不会触发真实爬虫或浏览器自动化。

## 半自动闲鱼 HTML 采集

第四阶段支持“手动保存 HTML + 本地解析”的半自动流程，不做自动登录、不绕过验证码、不使用浏览器自动化。

### 生成搜索链接

```bash
python src/main.py generate-search-urls
```

默认输出：

```text
data/search_urls.csv
```

字段包括：

- `product_id`
- 商品名称
- `sell_keyword`
- `xianyu_search_url`
- `buy_platform`
- `buy_url`
- `target_buy_price`

### 保存闲鱼 HTML

打开 `data/search_urls.csv` 中的 `xianyu_search_url`，等搜索结果加载完成后，把页面保存为 HTML，例如：

```text
data/xianyu/kingbank-ddr4-3200-16g-001.html
```

建议使用浏览器“网页另存为”。如果解析不到商品，通常是保存的 HTML 里没有包含搜索结果数据，可以尝试在结果加载完成后重新保存，或复制搜索结果区域为本地 HTML 文件。

### 导入闲鱼 HTML

```bash
python src/main.py import-xianyu-html \
  --product-id kingbank-ddr4-3200-16g-001 \
  --file data/xianyu/kingbank-ddr4-3200-16g-001.html
```

解析字段包括：

- 商品 ID（如果页面数据里可见）
- 标题
- 价格
- 地区
- 发布时间/更新时间
- 想要人数/浏览信息
- 商品链接
- 成色（按标题 best-effort 判断）
- 是否包邮（如果页面数据里可见）

### 建议闲鱼参考价

```bash
python src/main.py suggest-prices
```

只看单个商品：

```bash
python src/main.py suggest-prices --product-id kingbank-ddr4-3200-16g-001
```

建议价逻辑：

- 剔除异常低价
- 剔除明显高挂价
- 优先使用标题更匹配同款的样本
- 如果有足够“全新/未拆封/未使用”等样本，优先参考这些样本
- 从低价区间中取较合理的中位价格

结果里的 `风险提示` 必须看。样本太少、同款匹配少、全新样本不足时，建议人工复核后再使用。

### 生成可导入 prices.csv

```bash
python src/main.py generate-prices-from-xianyu
```

默认输出：

```text
data/prices.csv
```

该命令会读取最新买入价和最新闲鱼建议价，只把状态为 `ok` 的商品写入 CSV。生成后可以导入：

```bash
python src/main.py import-prices --file data/prices.csv
```

## 自动采集 MVP

第五阶段新增 `fetch-prices`，使用 Playwright 顺序打开页面，尝试读取买入平台价格和闲鱼第一页搜索结果。

原则：

- 不自动登录
- 不绕过验证码
- 不破解接口
- 不自动下单
- 不并发
- 不高频请求
- 遇到登录、验证码或风控时停止并提示人工处理

基础用法：

```bash
python src/main.py fetch-prices
```

常用参数：

```bash
python src/main.py fetch-prices --product-id kingbank-ddr4-3200-16g-001 --source jd --headful
python src/main.py fetch-prices --source xianyu --limit 3
python src/main.py fetch-prices --source jd --source xianyu --delay 8 --limit 5
python src/main.py fetch-prices --source xianyu --headful --browser-channel chrome --use-browser-profile --manual-wait 60 --limit 1
```

参数说明：

- `--product-id`：只采集某个商品
- `--source`：采集来源，可重复指定；支持 `jd`、`pdd`、`xianyu`
- `--headful`：显示浏览器窗口，适合排查页面问题
- `--browser-channel`：浏览器通道，默认 `chromium`；设为 `chrome` 时使用本机 Chrome
- `--use-browser-profile`：使用默认持久化资料目录 `data/browser-profile`
- `--profile-dir`：指定持久化浏览器资料目录，适合人工登录后复用 session
- `--manual-wait`：页面打开后等待人工处理的秒数，例如 `60`
- `--delay`：每个页面访问间隔秒数，默认 `5`
- `--limit`：每次最多采集商品数，默认 `10`

人工辅助浏览器模式：

```bash
python src/main.py fetch-prices \
  --source xianyu \
  --headful \
  --browser-channel chrome \
  --use-browser-profile \
  --manual-wait 60 \
  --limit 1
```

该模式会打开本机 Chrome，并把浏览器资料保存在 `data/browser-profile`。如果页面要求登录或出现验证，请在打开的窗口里人工处理；工具只等待并继续尝试解析，不会自动登录、不会处理验证码，也不会隐藏自动化特征或绕过风控。

买入平台采集：

- 京东商品要求 `buy_platform: jd`
- 拼多多商品要求 `buy_platform: pdd`
- 自动采集成功后，会写入 `price_observations`
- `source` 会保存为 `jd_auto` 或 `pdd_auto`

闲鱼采集：

- 根据 `sell_keyword` 打开闲鱼搜索页
- 优先监听搜索页自然返回的闲鱼搜索 JSON 响应
- 没有捕获到响应时，回退到页面 HTML/DOM 解析
- 解析第一页可见结果并写入 `xianyu_results`
- 自动运行建议价逻辑
- 如果生成了建议价，会写入 `price_observations`
- `source` 会保存为 `xianyu_auto`

日志：

```text
logs/fetch.log
```

日志会记录开始时间、商品 ID、平台、是否成功、失败原因和采集到的价格。

遇到登录、验证码或风控：

- 工具会停止，不会重试轰炸
- 可以加 `--headful` 查看页面状态
- 可以使用 `--browser-channel chrome --use-browser-profile --manual-wait 60` 进入人工辅助浏览器模式
- 不建议继续反复运行
- 回退到 `prices.csv` 手动录价，或使用 `import-xianyu-html` 导入手动保存的 HTML

## 降价提醒

本地提醒不发邮件、不发推送，只写入 SQLite 的 `alert_events` 表并在命令行输出。

手动检查：

```bash
python src/main.py check-alerts
```

只检查单个商品：

```bash
python src/main.py check-alerts --product-id kingbank-ddr4-3200-16g-001
```

调整较上次降价阈值和冷却时间：

```bash
python src/main.py check-alerts --min-drop-abs 5 --min-drop-pct 3 --cooldown-hours 24
```

提醒类型：

- `达到目标买入价`：当前买入价不高于 `target_buy_price`
- `历史新低`：当前买入价低于该商品历史买入价
- `较上次下降`：当前买入价较上次买入价下降，且达到金额或百分比阈值

`fetch-prices` 完成后会自动检查一次提醒。为了避免重复刷屏，同一商品同一提醒类型默认 24 小时内只新增一次事件。

## 运行分析

```bash
python src/main.py analyze
```

只分析单个商品：

```bash
python src/main.py analyze --product-id kingbank-ddr4-3200-16g-001
```

输出 JSON：

```bash
python src/main.py analyze --format json
```

核心公式：

```text
价差 = 闲鱼参考价 - 买入价
预计利润 = 闲鱼参考价 - 买入价 - 邮费
利润率 = 预计利润 / 买入价
```

分析结果包含：

- 价差
- 预计利润
- 利润率百分比
- 闲鱼在售数量
- 是否近 7 天最低
- 是否历史最低
- 闲鱼参考价相比上一次上涨、下降或持平
- 近 7 天平均买入价
- 近 7 天平均闲鱼参考价
- 推荐等级：`强烈买入` / `可以关注` / `暂不建议`
- 买入理由
- 风险提示

推荐等级的简化规则：

- `强烈买入`：预计利润为正，买入价不高于目标价，利润率达标，并且当前买入价处于近 7 天或历史低位
- `可以关注`：预计利润为正，但目标价、利润率或低位条件未全部满足
- `暂不建议`：缺少关键价格、预计利润不为正，或利润条件明显不足

## 导出 CSV 报表

```bash
python src/main.py export-csv --output reports/arbitrage_report.csv
```

CSV 使用 `utf-8-sig` 编码，方便用 Excel 打开。第二阶段报表字段包括：

- 商品ID
- 商品名称
- 当前买入价
- 当前闲鱼参考价
- 闲鱼在售数量
- 预计利润
- 利润率
- 是否近7天最低
- 是否历史最低
- 推荐等级
- 买入理由
- 风险提示
- 更新时间

## 采集模块扩展说明

`src/collectors/` 下预留了以下模块：

- `manual.py`：手动录入价格
- `jd.py`：京东 HTML 价格解析占位
- `pdd.py`：拼多多 HTML 价格解析占位
- `taobao.py`：淘宝 HTML 价格解析占位
- `xianyu.py`：闲鱼搜索结果 HTML 解析占位

当前版本不内置自动登录、自动翻页、验证码处理或风控绕过逻辑。后续如果扩展采集，建议只处理你有权访问的页面数据，并优先支持“保存的 HTML 文件解析”或平台允许的公开接口。

## 本次调研融合点

参考 GooFish-AIMonitor / ai-goofish-monitor 的闲鱼 Playwright 思路，本项目只融合“监听搜索页响应、解析商品字段、写本地 SQLite”的轻量部分，不引入账号轮换、代理轮换或风控绕过。

参考 price-tracker / PriceWise 的价格历史思路，本项目继续使用 `price_observations` 作为历史记录，再派生 `alert_events` 做目标价、历史新低、较上次下降三类本地提醒，不引入前端通知、邮件或复杂调度。
