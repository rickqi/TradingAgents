"""OpenCLI vendor — subprocess wrapper for @jackwener/opencli financial data commands.

Provides extended market data not available from yfinance/tencent_sina/akshare:
- Main force capital flow (主力资金净流入) via eastmoney
- Northbound capital flow (北向资金) via eastmoney
- Sector rankings (板块排行) via eastmoney
- Dragon-Tiger list (龙虎榜) via eastmoney
- Hot stock rankings (人气排行) via tdx
- Crypto prices via binance

All commands use public APIs (no browser needed) except tdx hot-rank which needs cookie/browser bridge.
"""

import json
import logging
import shutil
import subprocess
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Optional

logger = logging.getLogger(__name__)

# Maximum rows to include in output before truncation
_MAX_ROWS = 500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_opencli_path() -> Optional[str]:
    """Return the path to the opencli binary, or None if not found."""
    return shutil.which("opencli")


def _strip_exchange_suffix(ticker: str) -> str:
    """Strip exchange suffix (.SH/.SZ/.SS/.HK) from a single ticker.

    OpenCLI expects plain 6-digit A-share codes (e.g. ``688041``),
    not the TradingAgents format with exchange suffix (``688041.SH``).
    """
    t = ticker.strip()
    for suffix in (".SH", ".SZ", ".SS", ".HK", ".sh", ".sz", ".ss", ".hk"):
        if t.endswith(suffix):
            return t[:-len(suffix)]
    return t


def _normalize_symbols(symbols: str) -> str:
    """Normalize a comma-separated symbol list by stripping exchange suffixes.

    Handles both single symbols (``"688041.SH"``) and comma-separated
    (``"600519.SH,000858.SZ"``).
    """
    if not symbols:
        return symbols
    parts = [_strip_exchange_suffix(s) for s in symbols.split(",")]
    return ",".join(parts)


def _run_opencli(
    site: str,
    command: str,
    args: list[str] | None = None,
    timeout: int = 15,
) -> list[dict]:
    """Run an opencli command and return parsed JSON output.

    Args:
        site: The data source site (e.g. "eastmoney", "tdx", "binance").
        command: The command to run (e.g. "money-flow", "sectors").
        args: Additional CLI arguments.
        timeout: Subprocess timeout in seconds.

    Returns:
        List of dicts parsed from JSON output.

    Raises:
        FileNotFoundError: If opencli is not in PATH.
        subprocess.TimeoutExpired: If the command exceeds timeout.
        json.JSONDecodeError: If output is not valid JSON.
    """
    opencli_path = _get_opencli_path()
    if opencli_path is None:
        raise FileNotFoundError(
            "opencli binary not found in PATH. "
            "Install with: npm install -g @jackwener/opencli"
        )

    cmd = [opencli_path, site, command, "-f", "json"]
    if args:
        cmd.extend(args)

    logger.debug("Running opencli: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"opencli {site} {command} failed (exit {result.returncode}): {stderr}"
        )

    output = result.stdout.strip()
    if not output:
        return []

    data = json.loads(output)
    if isinstance(data, dict):
        # Some commands return a single object — wrap in a list
        return [data]
    if isinstance(data, list):
        return data
    return []


def _format_data_table(data: list[dict], title: str) -> str:
    """Convert a list of JSON row dicts into a readable text report.

    Truncates output at _MAX_ROWS with a summary line.
    """
    if not data:
        return f"# {title}\nNo data available.\n"

    header = f"# {title}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    header += f"# Total records: {len(data)}\n\n"

    # Determine columns from first row
    columns = list(data[0].keys())

    # Build a simple CSV-like table for LLM consumption
    lines = [",".join(columns)]

    truncated = False
    display_data = data
    if len(data) > _MAX_ROWS:
        display_data = data[:_MAX_ROWS]
        truncated = True

    for row in display_data:
        vals = []
        for col in columns:
            val = row.get(col, "")
            val = str(val).replace(",", ";")  # avoid CSV conflicts
            vals.append(val)
        lines.append(",".join(vals))

    if truncated:
        lines.append(f"\n... truncated {len(data) - _MAX_ROWS} rows (showing first {_MAX_ROWS})")

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# Public vendor functions — each returns str (formatted text report)
# ---------------------------------------------------------------------------

def get_money_flow(
    limit: Annotated[int, "number of results"] = 10,
    range: Annotated[str, "time range: today, 5d, 10d"] = "today",
) -> str:
    """主力资金净流入排行 (eastmoney money-flow). Public API, no browser."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--limit", str(limit)]
    if range != "today":
        args.extend(["--range", range])

    try:
        data = _run_opencli("eastmoney", "money-flow", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney money-flow timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching money flow data: {exc}"

    if not data:
        return "# Main Force Capital Flow (主力资金净流入)\nNo data available."

    return _format_data_table(data, "Main Force Capital Flow (主力资金净流入)")


def get_northbound(
    direction: Annotated[str, "direction: north (inflow to A-share) or south (inflow to HK)"] = "north",
    limit: Annotated[int, "number of recent minutes"] = 10,
) -> str:
    """沪深港通北向/南向资金分时净流入 (eastmoney northbound). Public API."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--direction", direction, "--limit", str(limit)]

    try:
        data = _run_opencli("eastmoney", "northbound", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney northbound timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching northbound data: {exc}"

    if not data:
        return "# Northbound Capital Flow (北向资金)\nNo data available."

    return _format_data_table(data, "Northbound Capital Flow (北向资金)")


def get_sectors(
    sector_type: Annotated[str, "sector type: industry, concept, region"] = "industry",
    sort_by: Annotated[str, "sort field: change, drop, money-flow, out-flow, turnover"] = "change",
    limit: Annotated[int, "number of results"] = 10,
) -> str:
    """板块排行 (eastmoney sectors). Public API."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = [
        "--type", sector_type,
        "--sort", sort_by,
        "--limit", str(limit),
    ]

    try:
        data = _run_opencli("eastmoney", "sectors", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney sectors timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching sector data: {exc}"

    if not data:
        return "# Sector Rankings (板块排行)\nNo data available."

    return _format_data_table(data, "Sector Rankings (板块排行)")


def get_longhu(
    symbol: Annotated[str, "optional stock symbol filter (empty for all)"] = "",
) -> str:
    """龙虎榜明细 (eastmoney longhu). Public API."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    try:
        data = _run_opencli("eastmoney", "longhu", timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney longhu timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching Dragon-Tiger list data: {exc}"

    if not data:
        return "# Dragon-Tiger List (龙虎榜)\nNo data available."

    if symbol:
        data = [
            row for row in data
            if str(row.get("code", "")) == symbol
            or str(row.get("code", "")).zfill(6) == symbol.zfill(6)
        ]
        if not data:
            return f"# Dragon-Tiger List (龙虎榜)\nNo data found for symbol {symbol}."

    return _format_data_table(data, "Dragon-Tiger List (龙虎榜)")


def get_hot_rank(
    limit: Annotated[int, "number of results"] = 20,
) -> str:
    """人气热搜排行 (tdx hot-rank). NOTE: requires browser bridge cookie."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--limit", str(limit)]

    try:
        data = _run_opencli("tdx", "hot-rank", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli tdx hot-rank timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching hot rank data: {exc}"

    if not data:
        return "# Hot Stock Rankings (人气热搜排行)\nNo data available."

    return _format_data_table(data, "Hot Stock Rankings (人气热搜排行)")


def get_quote(
    symbols: Annotated[str, "stock symbols, comma-separated (e.g. '600519,000858')"] = "",
) -> str:
    """个股实时行情 (eastmoney quote). Public API.
    Returns 16 fields: price, changePercent, PE, PB, marketCap, turnoverRate, etc."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    normalized = _normalize_symbols(symbols) if symbols else ""
    args = [normalized] if normalized else []

    try:
        data = _run_opencli("eastmoney", "quote", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney quote timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching quote data: {exc}"

    if not data:
        return "# Real-Time Stock Quotes (个股实时行情)\nNo data available."

    return _format_data_table(data, "Real-Time Stock Quotes (个股实时行情)")


def get_kline(
    symbol: Annotated[str, "stock symbol (e.g. 600519)"] = "600519",
    period: Annotated[str, "K-line period: day, week, month, 5m, 15m, 30m, 60m"] = "day",
    adjust: Annotated[str, "adjustment: none, forward, backward"] = "forward",
    limit: Annotated[int, "number of K-line bars to return"] = 30,
) -> str:
    """K线历史数据 (eastmoney kline). Public API.
    Returns OHLCV + amplitude + changePercent + turnoverRate."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = [
        _strip_exchange_suffix(symbol),
        "--period", period,
        "--adjust", adjust,
        "--limit", str(limit),
    ]

    try:
        data = _run_opencli("eastmoney", "kline", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney kline timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching kline data: {exc}"

    if not data:
        return f"# K-Line Data ({symbol} {period})\nNo data available."

    return _format_data_table(data, f"K-Line Data ({symbol} {period})")


def get_holders(
    symbol: Annotated[str, "A-share stock code (e.g. 600519)"] = "600519",
    limit: Annotated[int, "number of top holders to return"] = 10,
) -> str:
    """十大流通股东 (eastmoney holders). Public API.
    Returns rank, reportDate, name, holdNum, floatRatio, change."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = [
        _strip_exchange_suffix(symbol),
        "--limit", str(limit),
    ]

    try:
        data = _run_opencli("eastmoney", "holders", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney holders timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching holders data: {exc}"

    if not data:
        return f"# Top 10 Holders (十大流通股东 - {symbol})\nNo data available."

    return _format_data_table(data, f"Top 10 Holders (十大流通股东 - {symbol})")


def get_announcement(
    market: Annotated[str, "exchange filter: SHA, SZA, BJA (comma-separated)"] = "SHA,SZA",
    limit: Annotated[int, "number of announcements to return"] = 20,
) -> str:
    """上市公司公告 (eastmoney announcement). Public API.
    Returns time, code, name, title, category, url."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = [
        "--market", market,
        "--limit", str(limit),
    ]

    try:
        data = _run_opencli("eastmoney", "announcement", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney announcement timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching announcement data: {exc}"

    if not data:
        return "# Company Announcements (上市公司公告)\nNo data available."

    return _format_data_table(data, "Company Announcements (上市公司公告)")


def get_index_board(
    group: Annotated[str, "index group: main (A-share major), hk, us, all"] = "main",
) -> str:
    """主要市场指数行情 (eastmoney index-board). Public API.
    Returns code, name, price, changePercent, etc for major indices."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--group", group]

    try:
        data = _run_opencli("eastmoney", "index-board", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney index-board timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching index board data: {exc}"

    if not data:
        return "# Market Index Board (主要市场指数)\nNo data available."

    return _format_data_table(data, "Market Index Board (主要市场指数)")


def get_kuaixun(
    column: Annotated[str, "channel: 102 (important), 101 (all)"] = "102",
    limit: Annotated[int, "number of news items"] = 20,
) -> str:
    """7x24 财经快讯 (eastmoney kuaixun). Public API.
    Returns real-time financial news flashes."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = [
        "--column", str(column),
        "--limit", str(limit),
    ]

    try:
        data = _run_opencli("eastmoney", "kuaixun", args, timeout=15)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli eastmoney kuaixun timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching kuaixun data: {exc}"

    if not data:
        return "# 7x24 Financial News (财经快讯)\nNo data available."

    return _format_data_table(data, "7x24 Financial News (财经快讯)")


def get_crypto_price(
    symbol: Annotated[str, "crypto symbol, e.g. BTCUSDT, ETHUSDT"] = "BTCUSDT",
) -> str:
    """加密货币行情 (binance price). Public API."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--symbol", symbol]

    try:
        data = _run_opencli("binance", "price", args, timeout=10)
    except FileNotFoundError:
        return "Error: opencli not found in PATH."
    except subprocess.TimeoutExpired:
        return "Error: opencli binance price timed out."
    except (json.JSONDecodeError, RuntimeError) as exc:
        return f"Error fetching crypto price data: {exc}"

    if not data:
        return f"# Crypto Price ({symbol})\nNo data available."

    return _format_data_table(data, f"Crypto Price ({symbol})")
