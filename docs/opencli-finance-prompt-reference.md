# OpenCLI 财经命令速查手册

> 版本: opencli v1.7.12+ | 更新: 2026-05-08 | 适用场景: 量化交易数据采集、市场监控、财经研究

---

## 一、站点总览

| 站点 | 市场 | 浏览器 | 命令数 | 最佳场景 |
|---|---|---|---|---|
| `eastmoney` 东方财富 | A股/港股/美股 | ❌ 公共API | **15** | 行情/资金流/板块/龙虎榜/K线/ETF |
| `sinafinance` 新浪财经 | A股/港股/美股 | ❌ 公共API | **4** | 快速查价/热搜榜/快讯 |
| `xueqiu` 雪球 | 全球 | ✅ Cookie | **12** | 社交观点/自选股/基金/讨论 |
| `tdx` 通达信 | A股 | ✅ Cookie | **1** | 人气热搜排行 |
| `ths` 同花顺 | A股 | ✅ Cookie | **1** | 热度排行+连板信息 |
| `yahoo-finance` | 全球 | ✅ Cookie | **1** | ⚠️中国区不可用 |
| `binance` 币安 | 加密货币 | ❌ 公共API | **11** | 数字货币价格/K线/深度 |
| `barchart` | 美股 | ✅ Cookie | **4** | 期权链/Greeks/异常期权流 |
| `bloomberg` 彭博 | 全球 | ❌ RSS | **10** | 财经新闻/观点 |

---

## 二、AI Agent 提示词模板

### 2.1 获取 A 股热点

```
使用 opencli 查询今日 A 股热点:
1. 执行 `opencli tdx hot-rank --limit 10 -f json` 获取通达信人气榜
2. 执行 `opencli ths hot-rank --limit 10 -f json` 获取同花顺热度榜
3. 执行 `opencli eastmoney rank --limit 10 -f json` 获取涨跌排行
4. 交叉验证三个源的重叠个股,给出综合热度排名
5. 对 TOP5 个股逐个执行 `opencli eastmoney quote <code> -f json` 获取详细行情
   注意: 使用纯数字代码(如 600519),不要带 .SZ/.SH 后缀
```

### 2.2 主力资金分析

```
使用 opencli 分析今日主力资金:
1. `opencli eastmoney money-flow --limit 15 -f json` 获取主力资金净流入排行
2. `opencli eastmoney northbound -f json` 获取北向资金分时数据
3. `opencli eastmoney sectors --limit 10 -f json` 获取板块资金流向
4. 结合 money-flow 和 sectors 判断主力进攻方向
5. 对资金流入前3名个股查询K线: `opencli eastmoney kline <code> -f json`
```

### 2.3 个股深度分析

```
对股票 {CODE} 进行深度分析:
1. `opencli eastmoney quote {CODE} -f json` 实时行情 (纯数字代码,如 688041)
2. `opencli eastmoney kline {CODE} -f json` K线历史数据
3. `opencli eastmoney holders {CODE} -f json` 十大流通股东
4. `opencli sinafinance stock {CODE} -f json` 新浪行情确认
5. `opencli xueqiu comments {XUEQIU_SYMBOL} --limit 10 -f json` 雪球讨论 (雪球格式: SH600519)
6. `opencli eastmoney announcement --exchange sh` 相关公告
7. 综合以上数据给出分析摘要
```

### 2.4 板块轮动分析

```
分析今日板块轮动:
1. `opencli eastmoney sectors --limit 20 -f json` 获取全部板块排行
2. 按涨跌幅排序,识别领涨板块
3. 按主力资金排序,识别资金集中板块
4. 对领涨板块执行 `opencli eastmoney money-flow --limit 5 -f json` 找到板块龙头
5. 综合给出板块轮动方向判断
```

### 2.5 龙虎榜分析

```
分析今日龙虎榜:
1. `opencli eastmoney longhu -f json` 获取全部龙虎榜明细
2. 返回数据包含所有上榜个股,需自行按股票代码过滤
3. 识别机构专用席位买入的个股
4. 识别游资席位活跃的个股
5. 对龙虎榜个股查询K线: `opencli eastmoney kline <code> -f json`
6. 结合 `opencli eastmoney money-flow` 确认资金是否持续流入
```

### 2.6 加密货币监控

```
监控加密货币市场:
1. `opencli binance top -f json` 获取成交量 TOP 交易对
2. `opencli binance gainers -f json` 24h 涨幅榜
3. `opencli binance losers -f json` 24h 跌幅榜
4. 对关注的币种: `opencli binance price BTCUSDT -f json`
5. 查看深度: `opencli binance depth BTCUSDT -f json`
```

### 2.7 美股期权分析

```
分析美股 {SYMBOL} 的期权数据:
1. `opencli barchart quote {SYMBOL} -f json` 股票行情
2. `opencli barchart options {SYMBOL} -f json` 期权链
3. `opencli barchart greeks {SYMBOL} -f json` Greeks 概览
4. `opencli barchart flow -f json` 异常期权活动
5. 分析 IV 和异常期权流判断市场情绪
```

### 2.8 财经新闻聚合

```
聚合今日财经新闻:
1. `opencli eastmoney kuaixun --limit 15 -f json` 东财7x24快讯
2. `opencli sinafinance news --limit 15 -f json` 新浪7x24快讯
3. `opencli bloomberg markets -f json` 彭博市场新闻
4. `opencli bloomberg tech -f json` 彭博科技新闻
5. 去重合并,按重要性和时间排序
```

### 2.9 ETF/可转债筛选

```
筛选 ETF 和可转债:
1. `opencli eastmoney etf --limit 20 -f json` ETF成交额排行
2. `opencli eastmoney convertible -f json` 可转债行情列表
3. 识别成交额放大且折价的可转债机会
4. 结合正股行情: `opencli eastmoney quote <正股代码> -f json`
```

### 2.10 每日市场全景报告（实战模板）

> 基于实际交易分析经验提炼。8 个命令覆盖市场全貌，可生成完整日报。

```
生成今日 A 股市场全景报告:

## 第一步: 市场概览 (3 个命令,可并行执行)
1. `opencli eastmoney index-board -f json` → 主要指数行情(上证/深证/创业板/科创50)
2. `opencli eastmoney rank --limit 20 -f json` → 涨跌排行 TOP20
3. `opencli eastmoney sectors --limit 15 -f json` → 板块涨跌排行

## 第二步: 资金面分析 (2 个命令,可并行执行)
4. `opencli eastmoney money-flow --limit 15 -f json` → 主力资金净流入排行
5. `opencli eastmoney northbound -f json` → 北向资金分时数据

## 第三步: 热点与异动 (2 个命令,可并行执行)
6. `opencli eastmoney longhu -f json` → 龙虎榜明细(机构/游资动向)
7. `opencli tdx hot-rank --limit 10 -f json` → 人气热搜榜

## 第四步: 新闻面
8. `opencli eastmoney kuaixun --limit 15 -f json` → 7×24 财经快讯

## 第五步: 持仓跟踪 (逐个执行)
9. 对持仓/关注个股逐个执行: `opencli eastmoney quote <code> -f json`
   注意: 代码用纯数字(688041),不要用 688041.SH 格式

## 报告框架:
1. 指数概览: 三大指数涨跌+成交量变化
2. 持仓跟踪: 关注个股涨跌+异动分析
3. 板块轮动: 领涨/领跌板块+资金流向
4. 资金面: 主力资金+北向资金方向
5. 龙虎榜: 机构买入/游资活跃个股
6. 热点追踪: 人气榜+热搜重叠股
7. 新闻要点: 影响市场的重大新闻
8. 综合研判: 多空力量对比+操作建议
```

### 2.11 持仓股批量诊断

```
对持仓组合 {CODE1,CODE2,...} 进行批量诊断:

## 逐个查询(每个代码单独执行,避免并发问题):
for CODE in {CODE1} {CODE2} ...:
  `opencli eastmoney quote {CODE} -f json` → 实时行情

## 然后查询整体市场环境:
`opencli eastmoney index-board -f json` → 指数环境
`opencli eastmoney sectors --limit 10 -f json` → 所属板块表现

## 综合分析:
1. 每只持仓股: 当日涨跌幅 + 换手率 + 量比(对比 quote 中的 volume)
2. 持仓股所属板块: 是否处于领涨/领跌板块
3. 个股相对板块强弱: 跑赢/跑输板块均值
4. 异动预警: 涨跌幅>5% 或 换手率>10% 标记
5. 操作建议: 持有/加仓/减仓/止损
```

### 2.12 TradingAgents 集成

TradingAgents 已内置 12 个 OpenCLI 工具,自动在 A-share 分析时激活:

| 工具函数 | CLI 命令 | 绑定 Agent | 数据内容 |
|---|---|---|---|
| `get_quote` | `eastmoney quote` | Market Analyst | 实时行情(PE/PB/市值/换手率等16项) |
| `get_kline` | `eastmoney kline` | Market Analyst | K线历史(日/周/月/分钟+复权) |
| `get_money_flow` | `eastmoney money-flow` | Market Analyst | 主力资金净流入排行 |
| `get_northbound` | `eastmoney northbound` | Market Analyst | 沪深港通北向/南向资金 |
| `get_sectors` | `eastmoney sectors` | Market Analyst | 板块排行(行业/概念/地域) |
| `get_longhu` | `eastmoney longhu` | Market Analyst | 龙虎榜明细 |
| `get_hot_rank` | `tdx hot-rank` | Market Analyst | 人气热搜排行 |
| `get_index_board` | `eastmoney index-board` | Market Analyst | 主要市场指数行情 |
| `get_kuaixun` | `eastmoney kuaixun` | Market + News | 7×24财经快讯 |
| `get_holders` | `eastmoney holders` | Fundamentals Analyst | 十大流通股东 |
| `get_announcement` | `eastmoney announcement` | News Analyst | 上市公司公告 |
| `get_stock_rank` | `eastmoney stock-rank` | Market Analyst | 热股排行 |

**触发条件**: 输入 A-share 代码(如 `000858.SZ`, `600519`)时自动激活,无需手动配置。
**降级策略**: 未安装 opencli 时所有工具静默跳过,不影响分析流程。

```bash
# 安装 opencli 后直接使用:
tradingagents    # 输入 A-share 代码即可
python -m cli.main

# 或使用 Python API:
python scripts/run_a_share.py 000858 2026-05-05
```

---

## 三、通用参数速查

```bash
# 输出格式
-f json          # JSON（推荐，结构化）
-f table         # 表格（默认）
-f csv           # CSV
-f markdown      # Markdown
-f yaml          # YAML
-f plain         # 纯文本

# 数量限制
--limit 10       # 限制返回数量

# 调试
--trace retain-on-failure   # 失败时保留 trace
-v                            # 详细输出

# 帮助
opencli <site> --help        # 站点帮助
opencli <site> <cmd> --help  # 命令帮助
```

---

## 四、注意事项

1. **串行执行** — Browser Bridge 同时只支持一个连接,不要并发执行 cookie 类命令
2. **公共 API 优先** — eastmoney/sinafinance/binance 为公共 API,无需浏览器,可安全并发
3. **知乎搜索** — `opencli zhihu search` 当前版本可能返回空结果
4. **Yahoo Finance** — 中国区已封锁,用 eastmoney/sinafinance/xueqiu 替代
5. **数据延迟** — 所有行情数据为近实时,非逐笔,适合分析决策而非高频交易
6. **A股代码格式** — eastmoney 使用纯数字(600519), xueqiu 使用带前缀(SH600519)

---

## 五、v1.7.12 实战踩坑记录

> 以下基于 2026-05-08 实际使用 opencli v1.7.12 执行每日市场分析的实战经验。

### 5.1 代码格式变更

| 变更 | 说明 | 影响 |
|---|---|---|
| `quote` 拒绝 `.SZ`/`.SH` 后缀 | v1.7.12 起 `eastmoney quote 688041.SH` 报错 | 必须用纯数字: `quote 688041` |
| `kline` 同样拒绝后缀 | 与 `quote` 行为一致 | 同上 |
| 多代码逗号分隔不稳定 | `quote 600519,000858` 可能报 "Unrecognized symbol" | 建议**逐个查询**,避免逗号分隔 |

### 5.2 各命令实际返回数据特征

| 命令 | 返回特征 | 实战提示 |
|---|---|---|
| `index-board` | 包含上证/深证/创业板/科创50等主要指数 | 涨跌幅字段为 `changePercent` |
| `rank` | 按 `--limit` 限制返回,字段包含市值/PE/换手率 | 可区分沪深/创业板/科创板 |
| `sectors` | 板块代码以 `BK` 开头,含 `leadStock`(领涨股) | 行业/概念/地域三类混合返回 |
| `money-flow` | `mainNet` 为主力净流入(万元),区分超大/大/中/小单 | 正值=净流入,负值=净流出 |
| `northbound` | 返回分时累计净流入数组(万元) | 最后一个值为当日累计 |
| `longhu` | 返回当日全部龙虎榜,按个股分组 | 需自行按股票代码过滤目标个股 |
| `hot-rank` (tdx) | 含 `tags` 标签和 `heat` 人气值 | 人气值可跨日对比 |
| `kuaixun` | 7×24 快讯,含发布时间和来源 | Windows 下可能有编码问题,建议 `-f json` |
| `quote` | 16 项字段,含 PE(动态)/PB/市值/换手率/振幅 | 逐个查询最可靠 |

### 5.3 最佳实践

1. **逐个查询行情** — `quote` 逗号分隔不稳定,建议 for 循环逐个执行
2. **并行执行公共 API** — eastmoney 15 个命令全部公共 API,可同时开多个终端并行
3. **先全景后聚焦** — 先用 index-board/rank/sectors 获取全貌,再针对性查个股
4. **资金面验证** — money-flow + northbound + sectors 三者交叉验证主力方向
5. **龙虎榜辅助判断** — 机构买入≠必涨,但机构集中买入的板块值得重点关注
6. **北向资金看趋势** — 单日数据意义有限,连续多日同方向才有参考价值
