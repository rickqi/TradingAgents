# AGENTS.md — tradingagents/dataflows

Market data abstraction layer. Routes 10 tool methods across 4 vendors with fallback chains.

## Structure

```
dataflows/
├── interface.py           # VENDOR_METHODS dict, route_to_vendor(), fallback logic
├── config.py              # Module-level singleton: set_config() / get_config()
├── utils.py               # safe_ticker_component() — path-traversal guard
├── stockstats_utils.py    # Indicator computation + OHLCV loading (shared by yfinance + tencent_sina)
├── y_finance.py           # yfinance: OHLCV, fundamentals, financials
├── yfinance_news.py        # yfinance: news + global news
├── alpha_vantage.py        # Re-exports from alpha_vantage_*.py
├── alpha_vantage_common.py # Shared: date parsing, rate-limit detection, API key check
├── alpha_vantage_*.py      # Alpha Vantage: stock, indicator, fundamentals, news
├── tencent_sina.py         # A-share: Tencent K-line + Sina quotes + East Money APIs
└── akshare_vendor.py       # A-share: AKShare — insider transactions, sentiment, per-stock financials
```

## How Vendor Routing Works

1. `get_vendor(category, method)` checks `tool_vendors[method]` first, then `data_vendors[category]`
2. Vendor strings can be comma-separated: `"tencent_sina,akshare"` → tries each in order
3. `route_to_vendor(method)` splits the string, tries each vendor, appends remaining registered vendors on failure
4. Cooldown between retries: 2s for rate-limit errors, 1s for other errors

### A-Share Auto-Detection

When Chinese mode is active (any `data_vendors` category contains `"tencent_sina"` or `"akshare"`):
- `route_to_vendor()` skips vendors in `_SKIP_FOR_CHINESE = {"yfinance", "alpha_vantage"}`
- These vendors have no useful A-share data and rate-limiting burns minutes
- Detection is per-call: `is_chinese_mode` is determined fresh from `primary_vendors` each invocation

Auto-detection triggers in two places:
- CLI: `cli/main.py:_is_ashare_ticker()` — handles bare 6-digit codes, `.SZ`/`.SH` suffixes, comma-separated lists, and quoted inputs (`"002876.SZ","000062.SZ"`)
- Graph: `tradingagents/graph/trading_graph.py:_is_chinese_ticker()` — same formats

When detected, data vendors are auto-set to `tencent_sina` for most categories, `akshare` for `sentiment_data`, and `"tencent_sina,akshare"` for `fundamental_data`.

**10 tool methods** in `VENDOR_METHODS`, each with up to 4 vendor implementations:

| Method | Category | Vendors |
|--------|----------|---------|
| `get_stock_data` | core_stock_apis | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_indicators` | technical_indicators | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` | fundamental_data | yfinance, alpha_vantage, tencent_sina, akshare |
| `get_news`, `get_global_news`, `get_insider_transactions` | news_data | yfinance, alpha_vantage, tencent_sina (akshare has insider_transactions only) |
| `get_sentiment` | sentiment_data | akshare only |

## Adding a New Vendor

1. Create `new_vendor.py` implementing relevant methods (same signatures as existing vendors)
2. Import in `interface.py` and add each method to `VENDOR_METHODS[method]["new_vendor"]`
3. Add `"new_vendor"` to `VENDOR_LIST`
4. No other registration needed — fallback chain automatically includes it

## Adding a New Tool Method

1. Add the method to vendor modules (or skip vendors that don't support it)
2. Add to `VENDOR_METHODS` dict with vendor→function mapping
3. Add to the appropriate `TOOLS_CATEGORIES` entry (or create new category)
4. Create a `@tool`-decorated function in `agents/utils/` (e.g., `sentiment_tools.py`) that calls `route_to_vendor()`
5. Import in `agent_utils.py` and register the tool in the analyst's `bind_tools()` + `ToolNode` in `trading_graph.py`

## Data Integrity Rules (MUST follow)

- **Look-ahead bias prevention**: ALL data must be filtered to `curr_date`. Every vendor implementation filters OHLCV (`data["Date"] <= curr_date`), financials (remove future fiscal periods), and news (skip articles after `curr_date`). New tools MUST do the same.
- **Path safety**: `safe_ticker_component()` in `utils.py` MUST be called before using a ticker in any filesystem path. Validates against `../` traversal and special characters.

## tencent_sina Quirks (A-share vendor)

- Sina API returns **GBK encoding** — handled internally with `resp.encoding = "gbk"`
- `get_insider_transactions()` returns `PERMANENT_FAILURE` string (no free Chinese source for insider data) — use akshare fallback
- `_api_get()` retries up to 3x with exponential backoff for 429/5xx errors
- Ticker format: uses `sh`/`sz` prefixes internally (e.g., `sh600183`); `_detect_market()` + `_normalize_ticker()` handle conversion
- News search may fail for Chinese search terms — pair with yfinance fallback in `data_vendors["news_data"]`

## akshare_vendor Quirks (A-share supplement)

- Ticker format: `"SH600519"` or `"SZ002876"` (exchange prefix + 6-digit code); `_normalize_ticker_to_akshare()` handles conversion from `.SH`/`.SZ` suffix format
- **P0 `get_insider_transactions`**: Uses `stock_inner_trade_xq()` (East Money bulk data) — returns up to 19K rows, filters client-side by ticker
- **P1 `get_sentiment`**: Uses `stock_comment_em()` (East Money) — returns composite score, PE/PB ratios, buy/sell signals. akshare-only method, no other vendor implements this.
- **P2 financials** (`get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`): Uses `stock_*_by_report_em()` — per-stock, ~10s each. Faster than tencent_sina's all-market fetch for single stocks.
- `get_news` / `get_global_news`: NOT implemented (uses `stock_news_em()` which has pandas 3.0+pyarrow compatibility issues)
- All methods include `_MAX_ROWS = 500` truncation with summary line for large datasets
- Auto-included in A-share fallback chains: `fundamental_data: "tencent_sina,akshare"`, `sentiment_data: "akshare"`

## Config Singleton

`config.py` maintains a module-level `_config` dict, initialized from `DEFAULT_CONFIG` on import.

- `set_config(config)` — shallow merge via `dict.update()`
- `get_config()` — returns a **shallow copy** (mutating the return value does NOT affect the singleton)
- `initialize_config()` — called at module import time, so `_config` is always ready

**Don't edit `config.py` directly** — call `set_config()` or pass config to `TradingAgentsGraph()`.
