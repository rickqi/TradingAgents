# AGENTS.md — tradingagents/dataflows

市场数据抽象层。将 10 个工具方法路由到 4 个数据供应商，支持降级链。

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
└── akshare_vendor.py       # A 股: AKShare — 内幕交易, 情绪, 个股财报
```

## 供应商路由机制

1. `get_vendor(category, method)` 先检查 `tool_vendors[method]`，再检查 `data_vendors[category]`
2. 供应商字符串支持逗号分隔：`"tencent_sina,akshare"` → 按顺序依次尝试
3. `route_to_vendor(method)` 拆分字符串，依次尝试每个供应商，失败时追加剩余已注册供应商
4. 重试冷却时间：限速错误 2 秒，其他错误 1 秒

### A 股自动检测

当中文模式激活时（任意 `data_vendors` 类别包含 `"tencent_sina"` 或 `"akshare"`）：
- `route_to_vendor()` 跳过 `_SKIP_FOR_CHINESE = {"yfinance", "alpha_vantage"}` 中的供应商
- 这些供应商没有有用的 A 股数据，且触达限速会浪费数分钟
- 每次调用独立检测：`is_chinese_mode` 在每次调用时从 `primary_vendors` 重新判定

自动检测在两处触发：
- CLI: `cli/main.py:_is_ashare_ticker()` — 处理纯 6 位数字代码、`.SZ`/`.SH` 后缀、逗号分隔列表和带引号的输入（`"002876.SZ","000062.SZ"`）
- Graph: `tradingagents/graph/trading_graph.py:_is_chinese_ticker()` — 相同格式

检测到 A 股后，数据供应商自动设置为：大部分类别使用 `tencent_sina`，`sentiment_data` 使用 `akshare`，`fundamental_data` 使用 `"tencent_sina,akshare"`。

**10 个工具方法**定义在 `VENDOR_METHODS` 中，每个方法最多有 4 个供应商实现：

| 方法 | 类别 | 供应商 |
|--------|----------|---------|
| `get_stock_data` | core_stock_apis | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_indicators` | technical_indicators | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` | fundamental_data | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_news`, `get_global_news`, `get_insider_transactions` | news_data | yfinance, alpha_vantage, tencent_sina（akshare 仅支持 insider_transactions） |
| `get_sentiment` | sentiment_data | 仅 akshare |

## 新增供应商

1. 创建 `new_vendor.py`，实现所需方法（签名与现有供应商一致）
2. 在 `interface.py` 中导入，并将每个方法添加到 `VENDOR_METHODS[method]["new_vendor"]`
3. 将 `"new_vendor"` 添加到 `VENDOR_LIST`
4. 无需其他注册——降级链会自动包含它

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

## 配置单例

`config.py` 维护一个模块级 `_config` 字典，导入时从 `DEFAULT_CONFIG` 初始化。

- `set_config(config)` — 通过 `dict.update()` 浅合并
- `get_config()` — 返回**浅拷贝**（修改返回值不会影响单例）
- `initialize_config()` — 在模块导入时调用，因此 `_config` 始终就绪

**不要直接编辑 `config.py`** — 应调用 `set_config()` 或将 config 传给 `TradingAgentsGraph()`。
