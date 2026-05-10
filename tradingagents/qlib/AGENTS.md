# AGENTS.md — tradingagents/qlib

OHLCV 缓存 → Qlib 二进制格式转换、AI 信号提取、DoltHub 数据推送。无需 qlib 依赖。

## 目录结构

```
qlib/
├── __init__.py              # 重新导出 ticker_mapper 公共 API
├── ticker_mapper.py         # 纯函数双向 ticker 格式转换（无副作用、无外部依赖）
├── cache_scanner.py         # CachedOHLCV 数据类，扫描 ~/.tradingagents/cache/
├── converter.py             # QlibConverter + ConvertResult，OHLCV → Qlib 二进制
├── signal_extractor.py      # 从分析状态/JSON 日志提取 AI 信号
├── bulk_downloader.py       # 批量下载 A 股 OHLCV（腾讯 K 线 + 东方财富股票池）
└── dolt_publisher.py        # 缓存去重 → DoltHub 推送（dolt CLI）
```

## Ticker 格式对照表

| 系统 | 格式 | 示例 | 说明 |
|------|------|------|------|
| TradingAgents 后缀 | `{code}.{EX}` | `000858.SZ` | 主格式 |
| Qlib 前缀 | `{EX}{code}` | `SZ000858` | 大写前缀 + 6 位代码 |
| Qlib 目录名 | 小写前缀 | `sz000858` | features/ 下的目录 |
| 腾讯 K 线 | `{ex}{code}` | `sh600183` | 小写前缀，无点号 |
| Tushare | `{code}.{EX}` | `000858.SZ` | 与 TradingAgents 相同 |
| AKShare | `{EX}{code}` | `SH600519` | 大写前缀，与 Qlib 类似 |
| Yahoo Finance | `{code}.{SS/...}` | `600519.SS` | .SS = 上证，.SZ = 深证 |

交易所推断规则（裸 6 位代码）：`6/9` → SH，`0/2/3` → SZ，`4/8` → BJ。

## 关键模块

### ticker_mapper.py

纯函数模块，无副作用、无外部依赖。所有函数幂等（已转换格式原样返回）。

| 函数 | 作用 |
|------|------|
| `to_qlib_instrument(ticker)` | TradingAgents → Qlib。支持逗号分隔列表、`.SS`→`SH` 变体 |
| `from_qlib_instrument(instrument)` | Qlib → TradingAgents。接受大小写 |
| `is_ashare_ticker(ticker)` | 判断是否 A 股。逗号列表中任一匹配即返回 True |
| `ticker_from_cache_filename(filename)` | 从缓存文件名提取 ticker 部分 |
| `qlib_instrument_to_dirname(instrument)` | Qlib 标的 → 小写目录名 |

### cache_scanner.py

`CachedOHLCV` 数据类：ticker, file_path, vendor, date_start, date_end, qlib_instrument, num_rows。

| 函数 | 作用 |
|------|------|
| `scan_cache(cache_dir)` | 扫描缓存目录，返回 `list[CachedOHLCV]`，按 (ticker, vendor) 排序 |
| `scan_cache_for_tickers(tickers)` | 大小写不敏感过滤 |
| `print_scan_summary(cached)` | 打印摘要表格（纯 print，无外部格式化依赖） |

识别 3 种缓存模式：`{ticker}-YFin-data-{s}-{e}.csv`、`-Tencent-`、`-AKShare-`。

### converter.py

`QlibConverter(qlib_dir, freq="day")` 类，`ConvertResult` 数据类。

| 方法 | 作用 |
|------|------|
| `convert_from_cache(tickers, cache_dir, extra_features)` | 缓存 CSV → Qlib 二进制。`extra_features` 支持 Qlib 格式或 TradingAgents 格式的 key |
| `convert_from_dataframe(df, ...)` | 任意 DataFrame → Qlib 二进制 |

6 个基础特征：`open, high, low, close, volume, factor`。`factor = Adj Close / Close`（tencent_sina 无 Adj Close 时 factor=1.0）。

加 `extra_features` 可扩展（如 AI 信号 `ai_score, trader_action, research_rating, price_target`）。

### signal_extractor.py

| 函数 | 作用 |
|------|------|
| `extract_from_state(state)` | 从 `propagate()` 返回的内存状态提取信号 |
| `extract_from_log(log_path)` | 从单个 JSON 日志文件提取信号 |
| `batch_extract_from_logs(results_dir)` | 批量扫描所有日志，返回 DataFrame（symbol 列已转 Qlib 格式） |
| `save_signals_parquet(df, path)` | 保存为 parquet（MultiIndex: date+symbol），引擎降级：pyarrow → fastparquet → CSV |

映射常量：`RATING_MAP`（Buy=2 ~ Sell=-2），`TRADER_ACTION_MAP`（Buy=1, Hold=0, Sell=-1）。

**JSON key 不一致**：日志文件用 `"trader_investment_decision"`，内存 state 用 `"trader_investment_plan"`。`extract_from_log()` 内部做了映射。

### bulk_downloader.py

`BulkDownloadResult` 数据类：total, downloaded, skipped, failed, failed_tickers。

| 函数 | 作用 |
|------|------|
| `fetch_stock_universe(source, stock_list_file)` | 东方财富 API 获取全市场 A 股列表，过滤 ST/退市股。支持从文件读取 |
| `bulk_download(tickers, ...)` | 批量下载。自动速率控制（batch_size=20, batch_pause=10s）。`skip_existing` 跳过已缓存 |

**⚠️ 使用 tencent_sina 私有内部函数**：`_fetch_tencent_kline`, `_kline_to_dataframe`, `_save_to_cache`, `_tencent_symbol`。这些不是公共 API，tencent_sina 内部重构时需同步检查。

每只股票做两次 K 线请求：未复权（OHLCV）+ 前复权（qfq，用于真实 Adj Close）。数据截止日期 `_CUTOFF_DATE = "2020-01-01"`。

### dolt_publisher.py

`DoltPublishResult` 数据类：total_instruments, total_rows, pushed, commit_hash, repo_dir。

| 函数 | 作用 |
|------|------|
| `dolt_push(tickers, push, chunk_size, keep_tmp)` | 主入口：读缓存 → 去重 → 生成 CSV → dolt clone → 建表 → import → commit → push |
| `read_cache_to_frames(tickers, cache_dir)` | 读取去重后的缓存，返回 (price_df, calendar, stock_list) |

## 数据流

```
东方财富 API / 指定列表  →  bulk_download  →  ~/.tradingagents/cache/
                                                 {TICKER}-Tencent-data-*.csv

~/.tradingagents/cache/       →  QlibConverter  →  ~/.qlib/qlib_data/tradingagents/
  *-Tencent-*.csv                                  calendars/day.txt
  *-YFin-*.csv                                     instruments/all.txt
  *-AKShare-*.csv                                  features/{inst_lower}/{field}.day.bin

~/.tradingagents/logs/        →  signal_extractor  →  *_signals.parquet
  {TICKER}/.../full_states_log_*.json

~/.tradingagents/cache/       →  dolt_push  →  DoltHub (rickqi/tradingagents)
```

## Qlib 二进制格式

- 每个特征文件：`float32` 小端序数组
- 第一个值 = 该标的在全局日历中的 `start_index`（存为 float32）
- 其余值 = 特征值，对齐全局日历后缺失日期为 NaN
- 文件路径：`features/{inst_lower}/{field}.{freq}.bin`
- 日历文件：纯文本，每行一个日期（YYYY-MM-DD）
- 标的文件：`instruments/all.txt`，tab 分隔 `SYMBOL\tstart_date\tend_date`

## AI 信号字段

| 字段 | 类型 | 量程 | 来源 |
|------|------|------|------|
| `ai_score` | int | -2 ~ +2 | Portfolio Manager（Buy=2, Overweight=1, Hold=0, Underweight=-1, Sell=-2） |
| `trader_action` | int | -1 ~ +1 | Trader（Buy=1, Hold=0, Sell=-1） |
| `research_rating` | int | -2 ~ +2 | Research Manager（同 ai_score 量程） |
| `price_target` | float | NaN ~ ∞ | Portfolio Manager 目标价（仅分析过的日期有值） |

## DoltHub 表结构

| 表 | 主键 | 关键列 |
|----|------|--------|
| `a_stock_eod_price` | (tradedate, symbol) | tradedate DATE, symbol VARCHAR(20), open/high/low/close/volume DOUBLE, adjclose DOUBLE, vendor VARCHAR(20) |
| `trade_calendar` | trade_date | trade_date VARCHAR(20), is_open INT |
| `stock_list` | symbol | symbol VARCHAR(20), start_date, end_date, vendor |

推送流程：`dolt clone` → `CREATE TABLE` → `dolt table import -u`（分块 CSV）→ `dolt commit` → `dolt push`。`dolt log --format=%H` 不受支持，代码通过正则解析输出并清理 ANSI 转义码获取 commit hash。

## 去重逻辑

**converter.py 和 dolt_publisher.py 各自独立实现了相同的去重策略**，未抽公共函数：

1. 按 Qlib instrument 分组（不同 ticker 格式映射到同一标的：`688256` vs `688256.SH` → 同一个 `SH688256`）
2. 每组选行数最多的文件
3. 行数相同时选 `date_end` 最新的

## 错误处理

- 所有模块用 try/except 包裹 I/O 操作，失败时打印 warning 并跳过（不抛异常）
- `save_signals_parquet()` 引擎降级：pyarrow → fastparquet → CSV 回退
- `_download_one()` 解析失败返回 None，上层计入 `result.failed`
- `dolt_push()` 找不到 dolt 可执行文件时抛 `FileNotFoundError`

## 设计决策

- **ticker_mapper 零依赖**：纯标准库，无 pandas/numpy，可被任何模块安全导入
- **`__init__.py` 只重新导出 ticker_mapper**：不导出 converter/signal 等（避免导入链过重）
- **binary 格式手写**：用 numpy `tofile` 直接写 float32 数组，不依赖 qlib SDK
- **bulk_downloader 耦合私有 API**：直接调用 `tencent_sina` 的 `_fetch_tencent_kline` 等下划线函数，而非通过 `route_to_vendor()`。这是有意为之：需要两次 K 线请求（未复权 + 前复权）获取真实 Adj Close，公共 API 不支持此模式

## 禁止事项

- 不要假定 tencent_sina 的私有函数签名稳定，重构时需检查 bulk_downloader
- 不要对 AI 信号做前向填充（`--with-signals` 只写入分析当天的值）
- 不要在 `extra_features` 的 key 格式上只尝试一种格式（converter 需同时尝试 TradingAgents 和 Qlib 两种 key）
- 不要用 `dolt log --format=%H`（不支持），用正则解析 `dolt log -n 1` 输出
- 不要忘记 DoltHub 推送时处理 ANSI 转义码（`re.sub(r"\x1b\[[0-9;]*m", ...)`）
