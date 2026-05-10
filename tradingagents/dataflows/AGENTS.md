# AGENTS.md — tradingagents/dataflows

市场数据抽象层。将 10 个工具方法路由到 6 个数据供应商，支持降级链。

## 目录结构

```
dataflows/
├── interface.py           # VENDOR_METHODS 字典, route_to_vendor(), 降级逻辑
├── config.py              # 模块级单例: set_config() / get_config()
├── utils.py               # safe_ticker_component() — 路径遍历防护
├── stockstats_utils.py    # 指标计算 + OHLCV 数据加载（yfinance 和 tencent_sina 共用）
├── y_finance.py           # yfinance: OHLCV, 基本面, 财务报表
├── yfinance_news.py        # yfinance: 新闻 + 全球新闻
├── alpha_vantage.py        # 从 alpha_vantage_*.py 重新导出
├── alpha_vantage_common.py # 共用工具: 日期解析, 限速检测, API key 检查
├── alpha_vantage_*.py      # Alpha Vantage: 股票行情, 技术指标, 基本面, 新闻
├── tencent_sina.py         # A 股: 腾讯 K 线 + 新浪行情 + 东方财富 API
├── akshare_vendor.py       # A 股: AKShare — 内幕交易, 情绪, 个股财报
├── twelve_data.py          # Twelve Data — REST API，9 个方法（无需额外 pip 依赖）
├── tushare.py              # Tushare Pro — REST API，6 个方法（需 pip install tushare）
└── opencli_vendor.py       # A 股: OpenCLI — 11 个 A 股数据函数 + 1 个加密货币函数（可选）
```

## 供应商路由机制

1. `get_vendor(category, method)` 先检查 `tool_vendors[method]`，再检查 `data_vendors[category]`
2. 供应商字符串支持逗号分隔：`"tencent_sina,akshare"` → 按顺序依次尝试
3. `route_to_vendor(method)` 拆分字符串，依次尝试每个供应商，失败时追加剩余已注册供应商
4. 重试冷却时间：限速错误 2 秒，其他错误 1 秒

### A 股自动检测

当中文模式激活时（任意 `data_vendors` 类别包含 `"tencent_sina"`、`"akshare"` 或 `"tushare"`）：
- `route_to_vendor()` 跳过 `_WESTERN_VENDORS = {"yfinance", "alpha_vantage", "twelve_data"}` 中的供应商
- 这些供应商没有有用的 A 股数据，且触达限速会浪费数分钟
- 每次调用独立检测：`is_chinese_mode` 在每次调用时从 `primary_vendors` 重新判定

自动检测在两处触发：
- CLI: `cli/main.py:_is_ashare_ticker()` — 处理纯 6 位数字代码、`.SZ`/`.SH` 后缀、逗号分隔列表和带引号的输入（`"002876.SZ","000062.SZ"`）
- Graph: `tradingagents/graph/trading_graph.py:_is_chinese_ticker()` — 相同格式

检测到 A 股后，数据供应商自动设置为：大部分类别使用 `tencent_sina`，`sentiment_data` 使用 `akshare`，`fundamental_data` 使用 `"tencent_sina,akshare"`。

**10 个工具方法**定义在 `VENDOR_METHODS` 中，每个方法最多有 6 个供应商实现：

| 方法 | 类别 | 供应商 |
|--------|----------|---------|
| `get_stock_data` | core_stock_apis | yfinance, alpha_vantage, tencent_sina, akshare, twelve_data, tushare |
| `get_indicators` | technical_indicators | yfinance, alpha_vantage, tencent_sina, akshare, twelve_data, tushare |
| `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` | fundamental_data | yfinance, alpha_vantage, tencent_sina, akshare, twelve_data, tushare |
| `get_news`, `get_global_news`, `get_insider_transactions` | news_data | yfinance, alpha_vantage, tencent_sina, twelve_data（akshare 仅支持 insider_transactions） |
| `get_sentiment` | sentiment_data | 仅 akshare |

## 新增供应商

1. 创建 `new_vendor.py`，实现所需方法（签名与现有供应商一致）
2. 在 `interface.py` 中导入，并将每个方法添加到 `VENDOR_METHODS[method]["new_vendor"]`
3. 将 `"new_vendor"` 添加到 `VENDOR_LIST`
4. 如是 A 股供应商：加入 `_CHINESE_VENDORS`；如是西方供应商：加入 `_WESTERN_VENDORS`
5. 如是可选 pip 依赖：用条件导入（`try: import xxx`），不要加到 `pyproject.toml`
6. 无需其他注册——降级链会自动包含它

## 新增工具方法

1. 在供应商模块中添加该方法（不支持的供应商可跳过）
2. 在 `VENDOR_METHODS` 字典中添加供应商→函数的映射
3. 添加到对应的 `TOOLS_CATEGORIES` 条目（或新建类别）
4. 在 `agents/utils/` 中创建 `@tool` 装饰的函数（如 `sentiment_tools.py`），调用 `route_to_vendor()`
5. 在 `agent_utils.py` 中导入，并在 `trading_graph.py` 中注册到分析师的 `bind_tools()` + `ToolNode`

## 数据完整性规则（必须遵守）

- **防止前视偏差**：所有数据必须过滤至 `curr_date`。每个供应商实现都过滤 OHLCV（`data["Date"] <= curr_date`）、财务报表（移除未来报告期）和新闻（跳过 `curr_date` 之后的文章）。新工具必须同样遵守。
- **路径安全**：在任何文件系统路径中使用 ticker 之前，必须调用 `utils.py` 中的 `safe_ticker_component()`。防止 `../` 路径遍历和特殊字符攻击。

## tencent_sina 特性（A 股供应商）

- 新浪 API 返回 **GBK 编码** — 内部通过 `resp.encoding = "gbk"` 处理
- `get_insider_transactions()` 返回 `PERMANENT_FAILURE` 字符串（无免费中文内幕数据来源）— 应使用 akshare 降级
- `_api_get()` 对 429/5xx 错误使用指数退避重试，最多 3 次
- Ticker 格式：内部使用 `sh`/`sz` 前缀（如 `sh600183`）；`_detect_market()` + `_normalize_ticker()` 负责格式转换
- 中文搜索词可能导致新闻搜索失败 — 可在 `data_vendors["news_data"]` 中配置 yfinance 降级

## akshare_vendor 特性（A 股补充供应商）

- Ticker 格式：`"SH600519"` 或 `"SZ002876"`（交易所前缀 + 6 位代码）；`_normalize_ticker_to_akshare()` 负责从 `.SH`/`.SZ` 后缀格式转换
- **P0 `get_insider_transactions`**：使用 `stock_inner_trade_xq()`（东方财富批量数据）— 最多返回 19K 行，客户端按 ticker 过滤
- **P1 `get_sentiment`**：使用 `stock_comment_em()`（东方财富）— 返回综合评分、PE/PB 比率、买卖信号。仅 akshare 提供此方法，其他供应商均未实现。
- **P2 财务报表**（`get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`）：使用 `stock_*_by_report_em()` — 按个股查询，每次约 10 秒。单股分析比 tencent_sina 的全市场拉取更快。
- `get_news` / `get_global_news`：未实现（`stock_news_em()` 存在 pandas 3.0+pyarrow 兼容性问题）
- 所有方法包含 `_MAX_ROWS = 500` 截断，对大数据集会附加摘要行
- 自动纳入 A 股降级链：`fundamental_data: "tencent_sina,akshare"`，`sentiment_data: "akshare"`

## twelve_data 特性（REST API 供应商）

- 纯 REST API（`requests`），**无需额外 pip 依赖**（不使用 `twelvedata` Python SDK）
- API Key 通过环境变量 `TWELVE_DATA_API_KEY` 获取
- **9 个方法**全部注册到 `VENDOR_METHODS`，与 yfinance/alpha_vantage 签名兼容
- 属于 `_WESTERN_VENDORS`，A 股模式下自动排除
- 免费版限制：8 API credits/分钟，800 credits/天
- **免费版可用**：`get_stock_data`（OHLCV）、`get_indicators`（12 种技术指标）、`get_income_statement`、`get_cashflow`
- **免费版受限**：`get_fundamentals`（404）、`get_news`（404）、`get_insider_transactions`（需 Pro 计划）
- 错误处理：所有方法 try/except 包裹，失败时返回错误字符串（不抛异常），允许降级链尝试下一个供应商
- 技术指标名必须小写：`rsi`, `macd`, `close_50_sma`, `close_200_sma`, `boll` 等（完整列表见 `_INDICATOR_CONFIG`）
- Ticker 格式：不带交易所后缀（`AAPL`，不是 `AAPL.US`）

## tushare 特性（A 股供应商）

- 条件导入（`try: import tushare`），未安装时返回错误字符串，降级链自动尝试下一个供应商
- API Key 通过环境变量 `TUSHARE_API_KEY` 获取
- **6 个方法**注册到 `VENDOR_METHODS`：`get_stock_data`, `get_indicators`, `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`
- 属于 `_CHINESE_VENDORS`，西方模式下自动排除
- Ticker 格式：`ts_code` = `000858.SZ`（6位代码 + 交易所后缀）；`_normalize_to_ts_code()` 负责从各种格式转换
- **`get_stock_data`**：`pro.daily()` + `pro.adj_factor()`，前复权 Adj Close = `close * adj_factor / latest_adj_factor`，成交量 手→股（×100）
- **`get_indicators`**：`pro.daily_basic()` — PE/PB/PS/PE_TTM/换手率/量比/市值（需 ≥2000 积分）
- **`get_fundamentals`**：`pro.fina_indicator()` — ROE/毛利率/净利率/BPS/EPS
- **财务报表**：`pro.income()`、`pro.balancesheet()`、`pro.cashflow()` — 标准 Tushare 财务报表（需 ≥2000 积分）
- 所有财务方法通过 `ann_date <= curr_date` 过滤防止前视偏差
- 错误处理：所有方法 try/except 包裹，失败时返回错误字符串（不抛异常），降级链自动尝试下一个供应商
- 懒加载：`_get_pro_api()` 单例，首次调用时初始化 tushare SDK
- 限速：统一 rate limiter（0.3s 间隔，120次/分钟）

## 配置单例

`config.py` 维护一个模块级 `_config` 字典，导入时从 `DEFAULT_CONFIG` 初始化。

- `set_config(config)` — 通过 `dict.update()` 浅合并
- `get_config()` — 返回**浅拷贝**（修改返回值不会影响单例）
- `initialize_config()` — 在模块导入时调用，因此 `_config` 始终就绪

**不要直接编辑 `config.py`** — 应调用 `set_config()` 或将 config 传给 `TradingAgentsGraph()`。

## opencli_vendor（A 股可选扩展）

`opencli_vendor.py` 是一个独立的数据层，不通过 `VENDOR_METHODS` 路由。它直接被 `agents/utils/opencli_tools.py` 中的 `@tool` 函数调用。

**12 个 vendor 函数**（11 个 A 股 + 1 个加密货币）：

| 函数 | OpenCLI 命令 | 说明 |
|------|-------------|------|
| `get_quote` | `opencli eastmoney quote` | 实时行情：PE、PB、总市值、换手率等 16 个字段 |
| `get_kline` | `opencli eastmoney kline` | K 线历史：可配置周期（日/周/月/分钟）和复权方式 |
| `get_money_flow` | `opencli eastmoney money-flow` | 主力资金流向：机构净流入/流出 |
| `get_northbound` | `opencli eastmoney northbound` | 北向资金：`--direction north/south`，`--limit N` |
| `get_sectors` | `opencli eastmoney sectors` | 板块排名：`--sort change/drop/money-flow/turnover` |
| `get_longhu` | `opencli eastmoney longhu` | 龙虎榜：异常机构交易活动（支持股票代码过滤） |
| `get_hot_rank` | `opencli tdx hot-rank` | 热门搜索排行：散户关注度 |
| `get_index_board` | `opencli eastmoney index-board` | 指数面板：沪深 300、上证 50、恒生、标普 500 |
| `get_holders` | `opencli eastmoney holders` | 前十大机构持仓：仓位变动 |
| `get_announcement` | `opencli eastmoney announcement` | 公司公告：交易所官方披露 |
| `get_kuaixun` | `opencli eastmoney kuaixun` | 7×24 财经快讯：`--column 102`（A 股），`--limit N` |
| `get_crypto_price` | `opencli binance price` | 加密货币价格（仅 CLI `market` 命令使用，无 @tool 包装） |

**实现细节**：
- `_run_opencli(args)` — 通过 `subprocess.run()` 调用 `shutil.which("opencli")` 返回的完整路径（Windows 上 `opencli.CMD`）
- 所有函数返回格式化的 markdown 表格字符串（`_format_data_table()`）
- 非阻塞：`opencli` 不在 `pyproject.toml` 依赖中，未安装时所有工具静默跳过
- 超时 30 秒，失败返回错误字符串（不抛异常，不影响分析流水线）
- `get_crypto_price` 是唯一的非 A 股函数，无 `@tool` 包装，仅通过 CLI `market` 子命令使用
