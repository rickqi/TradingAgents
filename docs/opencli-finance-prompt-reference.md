# OpenCLI 财经命令速查手册

> 版本: opencli v1.7.8+ | 更新: 2026-05-04 | 适用场景: 量化交易数据采集、市场监控、财经研究

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
5. 对 TOP5 个股执行 `opencli eastmoney quote <codes> -f json` 获取详细行情
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
1. `opencli eastmoney quote {CODE} -f json` 实时行情
2. `opencli eastmoney kline {CODE} -f json` K线历史数据
3. `opencli eastmoney holders {CODE} -f json` 十大流通股东
4. `opencli sinafinance stock {CODE} -f json` 新浪行情确认
5. `opencli xueqiu comments {XUEQIU_SYMBOL} --limit 10 -f json` 雪球讨论
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
1. `opencli eastmoney longhu -f json` 获取龙虎榜明细
2. 识别机构专用席位买入的个股
3. 识别游资席位活跃的个股
4. 对龙虎榜个股查询K线: `opencli eastmoney kline <code> -f json`
5. 结合 `opencli eastmoney money-flow` 确认资金是否持续流入
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

### 2.10 TradingAgents 集成

```
将 opencli 数据接入 TradingAgents 框架:
1. 使用 opencli 获取候选股票池:
   - `opencli eastmoney rank --limit 30 -f json` 涨幅排行
   - `opencli eastmoney money-flow --limit 20 -f json` 资金流排行
2. 筛选出同时出现在两个榜单的股票代码
3. 将筛选出的代码传入 TradingAgents:
   ```
   python scripts/run_a_share.py <CODE> <DATE>
   ```
4. 或使用 Python API:
   ```python
   from tradingagents.graph.trading_graph import TradingAgentsGraph
   ta = TradingAgentsGraph(config=config)
   _, decision = ta.propagate("<CODE>", "<DATE>")
   ```
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
