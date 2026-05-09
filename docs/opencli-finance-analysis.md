# OpenCLI 财经站点完整分析报告

> 分析日期: 2026-05-04 | 更新: 2026-05-08 | OpenCLI 版本: v1.7.12 | 总命令数: 628 | 财经相关: 9 站点 / 73 命令

---

## 一、站点分类与详细命令

### 1. 东方财富 `eastmoney`（15 命令）

**定位**: 最全面的 A 股数据源,全部为公共 API,无需浏览器登录。

| 命令 | 说明 | 策略 | 浏览器 | 输出列 |
|---|---|---|---|---|
| `quote <symbols>` | 个股实时行情,支持逗号/空格分隔多代码 | public | ❌ | code, name, market, price, changePercent, change, open, high, low, prevClose, volume, turnover, turnoverRate, amplitude, peDynamic, priceBook, marketCap, floatMarketCap |
| `rank` | 涨跌/成交排行（沪深/北证/创/科/港/美） | public | ❌ | rank, code, name, price, changePercent, change, turnover, volume, turnoverRate, peDynamic, marketCap |
| `hot-rank` | 东方财富热股榜 | public | ❌ | (人气排行) |
| `money-flow` | 主力资金净流入排行（今日/5日/10日） | public | ❌ | rank, code, name, price, changePercent, mainNet, mainNetRatio, superNet, bigNet, mediumNet, smallNet |
| `northbound` | 沪深港通北向/南向资金分时净流入（万元） | public | ❌ | (分时数据) |
| `sectors` | 板块排行（行业/概念/地域）按涨跌幅/主力资金/成交额排序 | public | ❌ | rank, code, name, price, changePercent, mainNet, leadStock, leadChangePercent, upCount, downCount |
| `kline <symbol>` | K线历史数据（分/日/周/月/前复权/后复权） | public | ❌ | (OHLCV) |
| `longhu` | 龙虎榜明细（交易所公开披露，v1.7.12 返回全量数据） | public | ❌ | (龙虎榜数据) |
| `index-board` | 主要市场指数行情（A股/港股/美股） | public | ❌ | (指数数据) |
| `etf` | ETF 列表按成交额/涨跌幅排行 | public | ❌ | (ETF数据) |
| `convertible` | 可转债行情列表（默认按成交额排序） | public | ❌ | (可转债数据) |
| `holders <symbol>` | 十大流通股东（A股 F10 数据） | public | ❌ | (股东数据) |
| `announcement` | 上市公司公告（按交易所筛选） | public | ❌ | (公告数据) |
| `kuaixun` | 东方财富 7x24 财经快讯 | public | ❌ | (快讯数据) |

**使用示例**:
```bash
# 查询贵州茅台实时行情
opencli eastmoney quote 600519 -f json

# 查询多只股票
opencli eastmoney quote 600519,000858,688256 -f json

# 主力资金排行
opencli eastmoney money-flow --limit 10 -f json

# 板块排行
opencli eastmoney sectors --limit 10 -f json

# K线数据
opencli eastmoney kline 600519 -f json
```

---

### 2. 新浪财经 `sinafinance`（4 命令）

**定位**: 轻量快速行情查询+新闻,全部公共 API。支持中文股票名搜索。

| 命令 | 说明 | 策略 | 浏览器 | 输出列 |
|---|---|---|---|---|
| `stock <key>` | 个股行情（支持中文名/代码,自动匹配 A股→港股→美股） | public | ❌ | Symbol, Name, Price, Change, ChangePercent, Open, High, Low, Volume, MarketCap |
| `stock-rank` | 新浪财经热搜榜 | public | ❌ | rank, name, change, market, price, symbol, url |
| `news` | 7x24 小时实时快讯 | public | ❌ | (快讯) |
| `rolling-news` | 滚动新闻 | public | ❌ | (新闻) |

**参数**: `stock` 支持 `--market cn|hk|us|auto`

**使用示例**:
```bash
# 中文名搜索
opencli sinafinance stock 贵州茅台 -f json

# 代码搜索
opencli sinafinance stock 600519 -f json

# 港股
opencli sinafinance stock 00700 --market hk -f json

# 热搜榜
opencli sinafinance stock-rank -f json
```

---

### 3. 雪球 `xueqiu`（12 命令）

**定位**: 社交属性最强的投资平台,支持自选股管理、基金持仓、个股讨论。需要浏览器 Cookie。

| 命令 | 说明 | 策略 | 浏览器 | 输出列 |
|---|---|---|---|---|
| `stock <symbol>` | 实时行情 | cookie | ✅ | name, symbol, price, changePercent, marketCap |
| `search <query>` | 搜索股票（代码或名称） | cookie | ✅ | symbol, name, exchange, price, changePercent, url |
| `kline <symbol>` | K线历史数据（回溯N天） | cookie | ✅ | date, open, high, low, close, volume |
| `hot-stock` | 热门股票榜 | cookie | ✅ | rank, symbol, name, price, changePercent, heat, url |
| `hot` | 首页热门动态 | cookie | ✅ | (动态数据) |
| `watchlist` | 自选股列表 | cookie | ✅ | (自选股) |
| `groups` | 自选股分组列表 | cookie | ✅ | (分组) |
| `comments <symbol>` | 单只股票讨论动态 | cookie | ✅ | (讨论) |
| `feed` | 首页时间线 | cookie | ✅ | (动态) |
| `fund-snapshot` | 蛋卷基金快照（总资产/持仓） | cookie | ✅ | (基金) |
| `fund-holdings` | 蛋卷基金持仓明细 | cookie | ✅ | (持仓) |
| `earnings-date <symbol>` | 财报发布日期 | cookie | ✅ | (日期) |

**代码格式**: `SH600519`, `SZ000858`, `AAPL`, `00700`

**使用示例**:
```bash
# 搜索股票
opencli xueqiu search 茅台 --limit 5 -f json

# 实时行情
opencli xueqiu stock SH600519 -f json

# K线（最近30天）
opencli xueqiu kline SH600519 --days 30 -f json

# 热门股票
opencli xueqiu hot-stock --limit 10 -f json

# 个股讨论
opencli xueqiu comments SH600519 --limit 10 -f json
```

---

### 4. 通达信 `tdx`（1 命令）

**定位**: A 股人气热搜榜,含标签和人气值。

| 命令 | 说明 | 策略 | 浏览器 | 输出列 |
|---|---|---|---|---|
| `hot-rank` | 热搜人气榜 | cookie | ✅ | rank, name, symbol, changePercent, heat, tags |

**使用示例**:
```bash
opencli tdx hot-rank --limit 10 -f json
```

---

### 5. 同花顺 `ths`（1 命令）

**定位**: A 股热度排行,含连板信息和标签。

| 命令 | 说明 | 策略 | 浏览器 | 输出列 |
|---|---|---|---|---|
| `hot-rank` | 热度排行 | cookie | ✅ | rank, name, changePercent, heat, tags |

**使用示例**:
```bash
opencli ths hot-rank --limit 10 -f json
```

---

### 6. 币安 `binance`（11 命令）

**定位**: 加密货币全功能数据源,全部公共 API,无需登录。

| 命令 | 说明 | 策略 | 浏览器 |
|---|---|---|---|
| `price <symbol>` | 单交易对价格 | public | ❌ |
| `prices` | 全交易对最新价格 | public | ❌ |
| `ticker` | 24h ticker 统计（按成交量排序） | public | ❌ |
| `top` | 24h 成交量 TOP 交易对 | public | ❌ |
| `gainers` | 24h 涨幅最大 | public | ❌ |
| `losers` | 24h 跌幅最大 | public | ❌ |
| `klines <symbol>` | K线数据 | public | ❌ |
| `depth <symbol>` | 订单簿买卖深度 | public | ❌ |
| `asks <symbol>` | 卖单价格 | public | ❌ |
| `pairs` | 活跃交易对列表 | public | ❌ |
| `trades <symbol>` | 最近成交 | public | ❌ |

**使用示例**:
```bash
# BTC 价格
opencli binance price BTCUSDT -f json

# 涨幅榜
opencli binance gainers -f json

# K线
opencli binance klines ETHUSDT -f json

# 订单簿深度
opencli binance depth BTCUSDT -f json
```

---

### 7. Barchart（4 命令）

**定位**: 美股期权数据专用,含 Greeks 和异常期权流。

| 命令 | 说明 | 策略 | 浏览器 |
|---|---|---|---|
| `quote <symbol>` | 股票报价 | cookie | ✅ |
| `options <symbol>` | 期权链（含Greeks/IV/成交量/持仓量） | cookie | ✅ |
| `greeks <symbol>` | 期权 Greeks 概览（IV/Delta/Gamma/Theta/Vega） | cookie | ✅ |
| `flow` | 异常期权活动/期权流 | cookie | ✅ |

**使用示例**:
```bash
# 股票报价
opencli barchart quote AAPL -f json

# 期权链
opencli barchart options AAPL -f json

# Greeks
opencli barchart greeks AAPL -f json

# 异常期权流
opencli barchart flow -f json
```

---

### 8. 彭博 Bloomberg（10 命令）

**定位**: 全球财经新闻源,RSS 公共接口。

| 命令 | 说明 | 策略 | 浏览器 |
|---|---|---|---|
| `main` | 首页头条 | public | ❌ |
| `markets` | 市场新闻 | public | ❌ |
| `economics` | 经济新闻 | public | ❌ |
| `tech` | 科技新闻 | public | ❌ |
| `politics` | 政治新闻 | public | ❌ |
| `opinions` | 观点评论 | public | ❌ |
| `industries` | 行业新闻 | public | ❌ |
| `businessweek` | 商业周刊 | public | ❌ |
| `news <link>` | 读取完整文章内容 | public | ❌ |
| `feeds` | 列出所有 RSS Feed 别名 | public | ❌ |

---

### 9. Yahoo Finance `yahoo-finance`（1 命令）⚠️

**定位**: 全球股票报价。**中国区不可用**（Yahoo 2021年退出中国大陆）。

| 命令 | 说明 | 策略 | 浏览器 | 状态 |
|---|---|---|---|---|
| `quote <symbol>` | 股票报价 | cookie | ✅ | ❌ 中国区封锁 |

**替代方案**: 使用 `eastmoney quote` / `sinafinance stock` / `xueqiu stock`

---

## 二、能力矩阵

### 按数据类型

| 数据类型 | eastmoney | sinafinance | xueqiu | tdx | ths | binance | barchart | bloomberg |
|---|---|---|---|---|---|---|---|---|
| 实时行情 | ✅ | ✅ | ✅ | — | — | ✅ | ✅ | — |
| K线数据 | ✅ | — | ✅ | — | — | ✅ | — | — |
| 主力资金 | ✅ | — | — | — | — | — | — | — |
| 板块数据 | ✅ | — | — | — | — | — | — | — |
| 龙虎榜 | ✅ | — | — | — | — | — | — | — |
| 北向资金 | ✅ | — | — | — | — | — | — | — |
| ETF | ✅ | — | — | — | — | — | — | — |
| 可转债 | ✅ | — | — | — | — | — | — | — |
| F10/股东 | ✅ | — | — | — | — | — | — | — |
| 公告 | ✅ | — | — | — | — | — | — | — |
| 热搜/人气 | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | — |
| 社交讨论 | — | — | ✅ | — | — | — | — | — |
| 期权 | — | — | — | — | — | — | ✅ | — |
| 加密货币 | — | — | — | — | — | ✅ | — | — |
| 新闻/快讯 | ✅ | ✅ | — | — | — | — | — | ✅ |
| 自选股/基金 | — | — | ✅ | — | — | — | — | — |

### 按市场

| 市场 | 推荐站点 | 最佳命令 |
|---|---|---|
| A股行情 | eastmoney | `quote` / `rank` / `kline` |
| A股热度 | tdx + ths + eastmoney | `hot-rank` / `rank` |
| A股资金 | eastmoney | `money-flow` / `northbound` / `sectors` |
| A股龙虎榜 | eastmoney | `longhu` |
| A股ETF/可转债 | eastmoney | `etf` / `convertible` |
| 港股行情 | eastmoney / xueqiu | `quote` / `stock` |
| 美股行情 | eastmoney / xueqiu | `quote` / `stock` |
| 美股期权 | barchart | `options` / `greeks` / `flow` |
| 加密货币 | binance | `price` / `top` / `gainers` / `klines` |
| 全球新闻 | bloomberg / sinafinance | `markets` / `news` |

---

## 三、API 类型分类

### 公共 API（无需浏览器,可并发）

- **eastmoney** — 全部 15 个命令
- **sinafinance** — 全部 4 个命令
- **binance** — 全部 11 个命令
- **bloomberg** — 全部 10 个命令

### Cookie/Browser Bridge（需要浏览器,串行执行）

- **xueqiu** — 全部 12 个命令
- **tdx** — 1 个命令
- **ths** — 1 个命令
- **barchart** — 4 个命令
- **yahoo-finance** — 1 个命令（中国区不可用）

---

## 四、与 TradingAgents 集成建议

### 4.1 数据采集层

OpenCLI 可作为 TradingAgents 的外部数据采集工具:

```
opencli 数据采集 → JSON 文件 → Python 脚本读取 → TradingAgents propagate()
```

### 4.2 候选股票筛选流程

```bash
# Step 1: 获取候选池
opencli eastmoney rank --limit 30 -f json > candidates.json
opencli eastmoney money-flow --limit 20 -f json >> candidates.json

# Step 2: Python 筛选
# 读取 JSON,取两个榜单交集,输出代码列表

# Step 3: 传入 TradingAgents
python scripts/run_a_share.py <CODE> <DATE>
```

### 4.3 已有数据源对比

| TradingAgents 数据源 | 覆盖市场 | OpenCLI 对应 |
|---|---|---|
| `yfinance` | 美股/全球 | `eastmoney quote` / `xueqiu stock` |
| `tencent_sina` | A股 | `eastmoney quote` / `sinafinance stock` |
| `akshare` | A股（扩展） | `eastmoney` 全系列（行情/资金/板块/龙虎榜） |
| `alpha_vantage` | 美股 | `barchart` / `bloomberg` |

**OpenCLI 独有数据（TradingAgents 当前不具备）**:
- 龙虎榜数据
- 北向资金分时
- 主力资金净流入
- 板块排行
- 可转债行情
- 加密货币数据
- 期权链/Greeks
- 社交讨论（雪球）
- 财经快讯

---

## 五、已知限制

1. **Browser Bridge 并发限制**: 同一时间只支持一个连接,Cookie 类命令必须串行
2. **知乎搜索 Bug**: `opencli zhihu search` 当前版本可能返回空结果
3. **Yahoo Finance 中国区封锁**: 无法从中国大陆使用,trace 显示 "Yahoo 产品与服务不可用"
4. **数据非逐笔**: 所有行情为近实时,存在短暂延迟
5. **A股代码格式差异**: eastmoney 用纯数字(600519), xueqiu 用带前缀(SH600519)
6. **opencli 版本**: v1.7.12, 建议定期 `npm update -g @jackwener/opencli` 更新

---

## 六、v1.7.12 实战验证记录

> 基于 2026-05-08 实际使用 opencli v1.7.12 执行完整市场分析日报的验证结果。

### 6.1 破坏性变更

| 命令 | v1.7.11 行为 | v1.7.12 行为 | 解决方案 |
|---|---|---|---|
| `eastmoney quote 688041.SH` | ✅ 正常 | ❌ "Unrecognized symbol" | 使用纯数字: `quote 688041` |
| `eastmoney kline 688041.SH` | ✅ 正常 | ❌ 报错 | 同上: `kline 688041` |
| `eastmoney quote 600519,000858` | ✅ 正常 | ⚠️ 不稳定,可能报错 | 逐个查询最可靠 |
| `eastmoney longhu <symbol>` | 支持按个股过滤 | 不再支持位置参数过滤 | 返回全量数据,自行过滤 |
| `eastmoney money-flow <symbol>` | 支持按个股过滤 | 不再支持位置参数过滤 | 返回排行数据,自行匹配 |

### 6.2 已验证可用命令

以下命令在 v1.7.12 上实测可用(2026-05-08):

| 命令 | 测试状态 | 返回数据质量 | 备注 |
|---|---|---|---|
| `eastmoney index-board` | ✅ | 优秀 | 包含主要 A 股/港股/美股指数 |
| `eastmoney rank --limit 20` | ✅ | 优秀 | 涨跌排行,含市值/PE/换手率 |
| `eastmoney sectors --limit 15` | ✅ | 优秀 | 板块排行,`BK` 前缀代码,含领涨股 |
| `eastmoney money-flow --limit 15` | ✅ | 优秀 | 主力资金排行,区分超大/大/中/小单 |
| `eastmoney northbound` | ✅ | 良好 | 返回分时累计数据数组(万元) |
| `eastmoney longhu` | ✅ | 良好 | 全量龙虎榜,无个股过滤 |
| `eastmoney kuaixun --limit 15` | ✅ | 良好 | 7×24 快讯,Windows 下 `-f json` 避免编码问题 |
| `tdx hot-rank --limit 10` | ✅ | 良好 | 人气榜,含标签和人气值 |
| `eastmoney quote <code>` | ✅ | 优秀 | **纯数字代码**,16 项字段 |
| `eastmoney kline <code>` | ✅ | 优秀 | **纯数字代码**,OHLCV 数据 |

### 6.3 实战工作流

2026-05-08 市场分析日报使用的 8+20 命令序列:

```
# 阶段 1: 市场全景 (并行,均为公共 API)
opencli eastmoney index-board -f json
opencli eastmoney rank --limit 20 -f json
opencli eastmoney sectors --limit 15 -f json
opencli eastmoney money-flow --limit 15 -f json
opencli eastmoney northbound -f json
opencli eastmoney longhu -f json
opencli tdx hot-rank --limit 10 -f json
opencli eastmoney kuaixun --limit 15 -f json

# 阶段 2: 持仓跟踪 (逐个执行,避免逗号分隔不稳定)
opencli eastmoney quote 688041 -f json    # 兆易创新
opencli eastmoney quote 688256 -f json    # 寒武纪
opencli eastmoney quote 688012 -f json    # 中微公司
# ... 对每只持仓股逐个执行

# 阶段 3: 深入分析 (按需)
opencli eastmoney kline <code> -f json    # 对异常个股查 K 线
```

### 6.4 数据解读要点

| 数据源 | 关键字段 | 解读方法 |
|---|---|---|
| `money-flow` | `mainNet`(主力净流入,万元) | 正值=机构净买入;关注连续 3 日同方向 |
| `northbound` | 最后一个值=当日累计 | 北向单日+400亿以上为强信号 |
| `sectors` | `mainNet` + `leadStock` | 板块资金+龙头共振=板块趋势确认 |
| `longhu` | 机构专用席位 | 同一机构席位出现在多只个股=板块级布局 |
| `index-board` | `changePercent` | 三大指数涨跌一致性=市场方向,分化=结构性行情 |
