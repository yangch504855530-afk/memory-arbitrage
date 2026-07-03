# 内存条套利监控日常操作手册

本文档说明每天如何使用 `memory-arbitrage` 做内存条套利监控。当前工具只用于本地记录、分析、有限自动采集和辅助决策，不绕过登录或验证码、不自动下单。

## 1. 每日采集流程

每天建议按下面顺序操作：

1. 进入项目目录。

```bash
cd /Users/chenghao/Documents/Codex/2026-07-03/google-drive/memory-arbitrage
```

2. 查看今日待采集清单。

```bash
python src/main.py collection-plan
```

重点优先看：

- `从未采集 = 是` 的商品
- `超过24小时 = 是` 的商品
- `接近目标 = 是` 的商品
- `优先级 = 高` 的商品

3. 优先尝试自动采集。

```bash
python src/main.py fetch-prices --limit 10 --delay 5
```

如果只想采集闲鱼：

```bash
python src/main.py fetch-prices --source xianyu --limit 3
```

如果只想排查某个京东商品：

```bash
python src/main.py fetch-prices --product-id kingbank-ddr4-3200-16g-001 --source jd --headful
```

自动采集成功后，可以直接运行：

```bash
python src/main.py analyze
```

`fetch-prices` 会在结束后自动检查新增降价提醒。需要单独复查时也可以运行：

```bash
python src/main.py check-alerts
```

4. 如果自动采集失败，再输出买入平台链接清单。

```bash
python src/main.py open-buy-links
```

按清单人工打开 `buy_url`，记录当前真实到手价。到手价应尽量包含店铺券、平台券、满减、支付优惠等你实际能拿到的价格。

5. 对自动闲鱼采集失败的商品，生成搜索链接。

```bash
python src/main.py generate-search-urls
```

打开 `data/search_urls.csv`，逐个查看 `xianyu_search_url` 和 `buy_url`。买入平台仍然人工核价；闲鱼侧可以保存搜索结果 HTML 给工具解析。

6. 保存闲鱼搜索结果 HTML。

在浏览器中打开闲鱼搜索链接，等搜索结果加载完成后，使用“网页另存为”保存到：

```text
data/xianyu/<product_id>.html
```

例如：

```text
data/xianyu/kingbank-ddr4-3200-16g-001.html
```

如果保存后工具解析不到商品，通常说明 HTML 中没有包含搜索结果数据。可以重新等待页面加载后保存，或复制搜索结果区域到一个本地 HTML 文件。

7. 导入闲鱼 HTML。

```bash
python src/main.py import-xianyu-html \
  --product-id kingbank-ddr4-3200-16g-001 \
  --file data/xianyu/kingbank-ddr4-3200-16g-001.html
```

8. 生成闲鱼建议价。

```bash
python src/main.py suggest-prices
```

重点看：

- `建议闲鱼价`
- `样本数`
- `采用样本`
- `价格区间`
- `采用区间`
- `风险提示`

9. 生成可导入的 `prices.csv`。

```bash
python src/main.py generate-prices-from-xianyu
```

默认输出：

```text
data/prices.csv
```

该文件会使用最新买入价和闲鱼建议价。没有最新买入价或没有闲鱼建议价的商品不会写入 CSV。

10. 导入生成的价格。

```bash
python src/main.py import-prices --file data/prices.csv
```

如果你不使用 HTML 解析，也可以继续手动填写 `config/prices.csv`。

可以先复制示例文件：

```bash
cp config/prices.example.csv config/prices.csv
```

手动填写后导入：

```bash
python src/main.py import-prices --file config/prices.csv
```

11. 运行分析。

```bash
python src/main.py analyze
```

12. 导出报表。

```bash
python src/main.py export-csv --output reports/arbitrage_report.csv
```

## 2. prices.csv 应该怎么填写

`prices.csv` 表头必须是：

```csv
product_id,buy_price,sell_price,xianyu_listing_count,source,observed_at
```

字段说明：

- `product_id`：商品池中的商品 ID，必须已经通过 `import-products` 导入。
- `buy_price`：买入平台当前实际到手价，必须是数字。
- `sell_price`：闲鱼参考价，必须是数字。
- `xianyu_listing_count`：闲鱼同款或近似同款在售数量，建议填写整数。
- `source`：数据来源，例如 `manual_batch`、`jd_manual`、`pdd_manual`、`taobao_manual`。
- `observed_at`：采集时间，使用 ISO 格式，例如 `2026-07-03T20:00:00+08:00`。

示例：

```csv
product_id,buy_price,sell_price,xianyu_listing_count,source,observed_at
kingbank-ddr4-3200-16g-001,157,211,11,manual_batch,2026-07-03T20:00:00+08:00
```

填写原则：

- 同一天可以录入多次，工具会按时间判断最新价格。
- 不确定的价格不要硬填，宁可当天跳过该商品。
- `buy_price` 尽量填你真实能下单的价格，不填页面标价。
- `sell_price` 要和商品规格一致，尤其注意 DDR4/DDR5、台式机/笔记本、容量、频率、品牌、是否马甲条。

## 2.1 自动采集的安装和边界

`fetch-prices` 需要安装 Playwright 浏览器：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

自动采集边界：

- 不自动登录
- 不绕过验证码
- 不破解接口
- 不自动下单
- 不并发采集
- 默认每个页面间隔 `5` 秒
- 默认每次最多采集 `10` 个商品
- 闲鱼侧只监听搜索页自然返回的搜索结果响应，监听不到时回退到 HTML/DOM 解析

遇到以下情况，工具会停止或给出失败原因：

- `需要登录`
- `触发验证码`
- `触发风控`
- `页面结构变化`
- `未找到价格元素`
- `未找到搜索结果元素`

处理建议：

- 先用 `--headful` 看页面真实状态。
- 如果是登录或验证码，不要反复运行。
- 回退到手动 `prices.csv`。
- 闲鱼可回退到保存 HTML 后使用 `import-xianyu-html`。

## 2.2 降价提醒如何看

降价提醒是本地事件，不会发邮件或推送。事件写入 SQLite 的 `alert_events` 表，并在命令行输出。

手动检查：

```bash
python src/main.py check-alerts
```

只检查单个商品：

```bash
python src/main.py check-alerts --product-id kingbank-ddr4-3200-16g-001
```

提醒类型：

- `达到目标买入价`：当前买入价不高于商品池里的 `target_buy_price`。
- `历史新低`：当前买入价低于该商品历史所有买入价。
- `较上次下降`：当前买入价低于上一次买入价，并达到阈值。

默认阈值：

```bash
python src/main.py check-alerts --min-drop-abs 10 --min-drop-pct 5 --cooldown-hours 24
```

含义：

- 较上次下降至少 `10` 元，或下降比例至少 `5%`，才触发“较上次下降”。
- 同一商品同一提醒类型默认 `24` 小时内只新增一次，避免重复提醒。
- 目标价和历史新低不受 `min-drop-abs` 限制，只受冷却时间限制。

## 3. 闲鱼参考价如何取值

闲鱼参考价建议取“同款低价区间中较合理的价格”，不要机械取最低价或最高价。

建议做法：

- 搜索 `sell_keyword`，优先筛选同品牌、同容量、同频率、同形态的商品。
- 观察低价区间，例如前 10 到 20 个相对正常的在售商品。
- 排除异常低价，例如描述明显有故障、仅包装盒、单条/套条不一致、需要自提、缺少关键信息、疑似引流价。
- 排除明显高挂价，例如远高于同款成交习惯、长期挂着无人问、标题堆砌但规格不清。
- 如果同款数量较多，参考价可以取正常低价区间的中位偏低价格。
- 如果同款数量很少，参考价要保守，风险提示里应关注“样本较少”。

简单例子：

如果同款正常在售价大多集中在 `200-220`，有一个 `160` 的异常低价和几个 `260+` 的高挂价，那么参考价可以取 `205` 或 `210`，不取 `160`，也不取 `260`。

使用 `suggest-prices` 时，工具会自动执行类似逻辑：先剔除异常低价和明显高挂价，再优先参考标题匹配同款、成色更接近全新/未拆封的低价区间样本。

自动闲鱼采集和 HTML 导入会尽量解析这些字段：

- 标题
- 价格
- 地区
- 发布时间/更新时间
- 想要人数/浏览信息
- 商品链接
- 成色，例如 `全新`、`准新`、`9成新`
- 是否包邮，如果页面数据可见

建议结果可信度判断：

- `样本数 >= 5` 通常比只有 1 到 2 条更可信。
- `采用样本 >= 2` 比只采用 1 条更稳。
- `价格区间` 很宽时，说明市场价格分散，需要人工复核。
- `采用区间` 如果明显低于你肉眼看到的正常价格，可能是异常低价没有被完全剔除。
- `风险提示` 出现“同款标题匹配样本少”“全新/未拆封样本不足”时，不建议直接使用建议价。
- 商品标题中如果出现“故障”“维修”“仅包装”“自提”等，建议人工排除。

## 4. 如何判断强烈买入、关注、放弃

工具会输出 `推荐等级`、`买入理由` 和 `风险提示`，人工判断时建议这样理解。

### 强烈买入

通常表示：

- 当前买入价不高于 `target_buy_price`
- 预计利润为正
- 利润率达到 `min_profit_rate`
- 当前买入价处于近 7 天低位或历史低位

看到“强烈买入”也不要直接无脑下单，还需要人工确认：

- 闲鱼参考价是否真实可卖
- 在售数量是否过高
- 商品是否容易退货或翻车
- 买入平台是否有保价、售后、发货风险

### 可以关注

通常表示有利润空间，但条件没有全部满足，例如：

- 买入价略高于目标买入价
- 利润率达标但不是近期低位
- 当前价格接近目标，值得继续盯盘
- 闲鱼价格有上涨迹象，但买入端还不够便宜

处理建议：

- 加入当天重点关注
- 晚些时候再次查看平台优惠
- 如果买入价跌到目标价附近，再重新录价并分析

### 暂不建议或放弃

通常表示：

- 扣除邮费后预计利润不足
- 利润率低于最低要求
- 买入价明显高于目标价
- 闲鱼参考价下跌
- 闲鱼在售量较高，可能不好卖

处理建议：

- 暂不买入
- 观察是否需要下调目标买入价
- 如果连续多天都无利润，可以考虑移出商品池或降低采集频率

## 5. 试运营 7 天后复盘哪些指标

建议连续记录 7 天，每天至少导入一次 `prices.csv`。7 天后重点复盘下面几类问题。

### 哪些商品经常出现价差

看哪些商品多次出现：

- 预计利润为正
- 利润率达标
- 买入价接近或低于目标买入价

这些商品可以保留在高优先级白名单中，后续提高采集频率。

### 哪些商品闲鱼在售量高但不好卖

重点看：

- `xianyu_listing_count` 长期较高
- 闲鱼参考价持续下降
- 预计利润看起来不错，但实际难以成交

这类商品容易出现“账面套利、实际压价”的问题，应提高最低利润率，或降低参考卖出价。

### 哪些商品价格波动大

观察：

- 近 7 天买入价均值和当前买入价差异
- 是否经常出现历史低价或 7 天低价
- 闲鱼参考价是否频繁上涨/下降

价格波动大的商品适合重点监控，但下单前要留更高安全边际。

### 推荐买入是否真的准确

复盘所有出现过 `强烈买入` 的记录：

- 当时是否真的可以买到
- 买入后是否能按参考价卖出
- 实际成交周期有多长
- 实际利润是否接近工具计算结果
- 是否因为邮费、议价、平台优惠失效导致偏差

如果推荐准确率不高，不要先改代码，先检查商品池参数和闲鱼参考价口径。

### 是否需要调整 target_buy_price 和 min_profit_rate

根据 7 天记录调整参数：

- 如果经常错过机会，可以适当提高 `target_buy_price`，但要保证利润率。
- 如果经常显示有利润但实际卖不动，应降低 `target_sell_price` 或提高 `min_profit_rate`。
- 如果在售数量高、成交慢，应提高 `min_profit_rate`，给压价和库存时间留空间。
- 如果商品很稳定、周转快，可以适当降低 `min_profit_rate`，换取更多成交机会。

调整后重新导入商品池：

```bash
python src/main.py import-products --file config/products.yaml
```

试运营阶段建议每 7 天复盘一次，不要每天频繁改参数，否则很难判断策略是否有效。

## 6. 本次参考项目带来的使用变化

这次只吸收适合本地轻量版的做法：

- 闲鱼采集优先从 Playwright 打开的搜索页里监听搜索结果响应，减少保存 HTML 的次数。
- 仍然保留 HTML/DOM 解析作为失败回退，不要求登录态，也不处理验证码。
- 价格历史继续存在 `price_observations`，不单独引入复杂时间序列库。
- 降价提醒从历史价格派生，先做命令行和 SQLite 本地事件，不做邮件、浏览器推送或后台调度。
