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
    symbol: Annotated[str, "stock symbol filter (empty for all)"] = "",
    limit: Annotated[int, "number of results"] = 10,
    period: Annotated[str, "time period: today, 5d, 10d"] = "today",
) -> str:
    """主力资金净流入排行 (eastmoney money-flow). Public API, no browser."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--limit", str(limit)]
    if symbol:
        args.extend(["--symbol", symbol])
    if period != "today":
        args.extend(["--period", period])

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
    market: Annotated[str, "market: sh (Shanghai) or sz (Shenzhen)"] = "sh",
) -> str:
    """沪深港通北向资金分时净流入 (eastmoney northbound). Public API."""
    if _get_opencli_path() is None:
        return "Error: opencli not found in PATH. Install with: npm install -g @jackwener/opencli"

    args = ["--market", market]

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
    sort_by: Annotated[str, "sort field: changePercent, turnover, volume"] = "changePercent",
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


def get_longhu() -> str:
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
