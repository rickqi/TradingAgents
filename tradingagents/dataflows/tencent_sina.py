"""Tencent/Sina/EastMoney-based data fetching for Chinese A-share stocks.

Provides free-market data via Tencent Finance K-line API, Sina realtime
quotes, and East Money financial-data APIs.  Covers OHLCV price history,
technical indicators (via stockstats), fundamentals, financial statements,
and news.  Insider transactions remain unavailable through free APIs.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from io import StringIO
from typing import Annotated
from urllib.parse import quote

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .config import get_config
from .stockstats_utils import _clean_dataframe
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# East Money API shared helpers
# ---------------------------------------------------------------------------

_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://eastmoney.com",
}


def _api_get(url: str, headers: dict | None = None, timeout: int = 15,
             max_retries: int = 3, base_delay: float = 2.0) -> requests.Response:
    """HTTP GET with exponential backoff on rate-limit (429) and server errors.

    Retries up to *max_retries* times for HTTP 429 / 5xx responses.
    Other status codes raise immediately via ``raise_for_status()``.
    """
    _headers = headers or _EASTMONEY_HEADERS
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=_headers, timeout=timeout)
            if resp.status_code == 429 and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Rate-limited (429) on %s, retrying in %.0fs (attempt %d/%d)",
                               url.split("?")[0], delay, attempt + 1, max_retries)
                time.sleep(delay)
                continue
            if resp.status_code >= 500 and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Server error (%d) on %s, retrying in %.0fs",
                               resp.status_code, url.split("?")[0], delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Connection error on %s, retrying in %.0fs",
                               url.split("?")[0], delay)
                time.sleep(delay)
            continue
    raise last_exc or requests.exceptions.HTTPError(f"All {max_retries} retries failed for {url}")


def _eastmoney_code(ticker: str) -> str:
    """Convert a raw stock code to East Money format: ``SH600183``, ``SZ300308``."""
    code = _normalize_ticker(ticker)
    if code.startswith(("6",)):
        return f"SH{code}"
    return f"SZ{code}"


def _fetch_eastmoney_datacenter(report_name: str, security_code: str, page_size: int = 5) -> list:
    """Fetch rows from the East Money DataCenter API.

    Returns the ``result.data`` list, or an empty list on any failure.
    """
    url = (
        "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        f"?reportName={report_name}"
        "&columns=ALL"
        f"&filter=(SECURITY_CODE%3D%22{security_code}%22)"
        "&pageNumber=1"
        f"&pageSize={page_size}"
        "&sortColumns=REPORT_DATE&sortTypes=-1"
    )
    try:
        resp = _api_get(url)
        payload = resp.json()
        if payload.get("code") == 0 and "result" in payload:
            return payload["result"].get("data") or []
        return []
    except Exception as exc:
        logger.warning("East Money DataCenter request failed (%s): %s", report_name, exc)
        return []


def _parse_jsonp(text: str) -> dict:
    """Strip a JSONP callback wrapper like ``jQuery(...)`` and return parsed JSON."""
    m = re.search(r"\((\{.*\})\)", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Maybe it's plain JSON already
    return json.loads(text)

# ---------------------------------------------------------------------------
# Ticker / symbol helpers
# ---------------------------------------------------------------------------

def _detect_market(ticker: str) -> str:
    """Detect market type from ticker string.

    Returns: "HK" for Hong Kong, "A" for A-share.
    """
    t = str(ticker).strip()
    # HK suffixes
    for suffix in (".HK", ".hk"):
        if t.endswith(suffix):
            return "HK"
    # HK prefix
    if t.lower().startswith("hk"):
        return "HK"
    return "A"


def _normalize_ticker(ticker: str) -> str:
    """Return the raw stock code from various input formats.

    Accepted A-share inputs: ``"300308"``, ``"300308.SZ"``, ``"600183.SS"``,
    ``"sh600183"``, ``"sz300308"``.
    Accepted HK inputs: ``"02149"``, ``"02149.HK"``, ``"hk02149"``.

    Also accepts integer inputs (e.g. ``600183``) which the LLM may pass
    for purely-numeric stock codes.
    """
    t = str(ticker).strip().lower()
    # Strip known prefixes
    for prefix in ("sh", "sz", "hk"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    # Strip exchange suffixes
    for suffix in (".sz", ".ss", ".sh", ".hk"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if not t.isdigit():
        raise ValueError(
            f"Cannot normalize ticker '{ticker}' to a stock code"
        )
    return t


def _tencent_symbol(ticker: str) -> str:
    """Convert ticker to Tencent API symbol (e.g. ``sh600183``, ``hk02149``)."""
    code = _normalize_ticker(ticker)
    market = _detect_market(ticker)
    if market == "HK":
        return f"hk{code}"
    if code.startswith(("6",)):
        return f"sh{code}"
    # 0xx, 3xx, 68x (ChiNext / SZ board)
    return f"sz{code}"


# ---------------------------------------------------------------------------
# Tencent K-line API
# ---------------------------------------------------------------------------

_TENCENT_A_KLINE_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param={sym},day,,,{days},qfq"
)
_TENCENT_HK_KLINE_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
    "?param={sym},day,,,{days},qfq"
)


def _fetch_tencent_kline(sym: str, days: int = 1200) -> list[list]:
    """Fetch daily K-line data from Tencent and return raw list of entries.

    A-share entry: ``[date_str, open, close, high, low, volume]``.
    HK entry: ``[date_str, open, close, high, low, volume, ...]`` (extra fields ignored).
    """
    is_hk = sym.startswith("hk") and not sym.startswith("hk0") == False  # 5-digit HK codes
    is_hk = sym.startswith("hk")
    url_template = _TENCENT_HK_KLINE_URL if is_hk else _TENCENT_A_KLINE_URL
    url = url_template.format(sym=sym, days=days)

    resp = _api_get(url, headers=None, timeout=15)
    payload = resp.json()

    # Navigate JSON structure
    data_section = payload.get("data", {})
    stock_data = data_section.get(sym, {})
    # Prefer qfqday (forward-adjusted), fall back to day
    raw_rows = stock_data.get("qfqday") or stock_data.get("day") or []

    return raw_rows


def _kline_to_dataframe(raw_rows: list[list]) -> pd.DataFrame:
    """Convert Tencent K-line rows to a standard OHLCV DataFrame.

    Tencent field order: ``[date, open, CLOSE, HIGH, LOW, volume]`` —
    close comes before high/low.
    """
    records = []
    for row in raw_rows:
        if len(row) < 6:
            continue
        date_str, open_p, close_p, high_p, low_p, vol = row[:6]
        records.append(
            {
                "Date": date_str,
                "Open": float(open_p),
                "High": float(high_p),
                "Low": float(low_p),
                "Close": float(close_p),
                "Volume": int(float(vol)),
            }
        )
    df = pd.DataFrame(records)
    if not df.empty:
        df["Adj Close"] = df["Close"]
    return df


# ---------------------------------------------------------------------------
# Sina realtime quotes
# ---------------------------------------------------------------------------

_SINA_HQ_URL = "https://hq.sinajs.cn/list={sym}"
_SINA_HK_URL = "https://hq.sinajs.cn/list={sym}"
_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}


def _fetch_sina_quote(sym: str) -> dict | None:
    """Fetch realtime quote from Sina and return parsed field dict.

    Works for both A-shares (sh/sz prefix) and HK stocks (hk prefix → rt_hk prefix for Sina).
    """
    is_hk = sym.startswith("hk")
    if is_hk:
        # Sina HK quote uses rt_hk prefix, e.g. rt_hk02149
        sina_sym = f"rt_{sym}"
    else:
        sina_sym = sym

    url = _SINA_HQ_URL.format(sym=sina_sym)
    try:
        resp = _api_get(url, headers=_SINA_HEADERS, timeout=10)
        resp.encoding = "gbk"
        text = resp.text
    except Exception as exc:
        logger.warning("Sina quote request failed for %s: %s", sym, exc)
        return None

    # Parse: var hq_str_sh600183="field0,field1,...";
    var_name = f"var hq_str_{sina_sym}="
    for line in text.strip().splitlines():
        line = line.strip()
        if not line.startswith(var_name):
            continue
        value_part = line[len(var_name):].strip().strip('";')
        fields = value_part.split(",")
        if is_hk:
            # HK quote format: name, open, prev_close, high, low, current_price, ...
            # Different field count/layout than A-share
            if len(fields) < 13:
                return None
            return {
                "name": fields[1] if len(fields) > 1 else "",
                "open": fields[2] if len(fields) > 2 else "N/A",
                "prev_close": fields[3] if len(fields) > 3 else "N/A",
                "high": fields[4] if len(fields) > 4 else "N/A",
                "low": fields[5] if len(fields) > 5 else "N/A",
                "current": fields[6] if len(fields) > 6 else "N/A",
                "volume": fields[12] if len(fields) > 12 else "N/A",
                "amount": fields[11] if len(fields) > 11 else "N/A",
                "date": fields[17] if len(fields) > 17 else "",
                "time": "",  # HK doesn't have separate time field
            }
        else:
            if len(fields) < 32:
                return None
            return {
                "name": fields[0],
                "open": fields[1],
                "prev_close": fields[2],
                "current": fields[3],
                "high": fields[4],
                "low": fields[5],
                "volume": fields[8],
                "amount": fields[9],
                "date": fields[30] if len(fields) > 30 else "",
                "time": fields[31] if len(fields) > 31 else "",
            }
    return None


# ---------------------------------------------------------------------------
# 1. get_YFin_data_online
# ---------------------------------------------------------------------------

def get_YFin_data_online(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return OHLCV CSV string for a Chinese A-share via Tencent K-line API."""
    symbol = str(symbol)
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    try:
        sym = _tencent_symbol(symbol)
    except ValueError as exc:
        return f"Error: {exc}"

    # Estimate days needed (include buffer for non-trading days)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    span_days = (end_dt - start_dt).days
    fetch_days = max(span_days + 120, 400)

    try:
        raw = _fetch_tencent_kline(sym, days=fetch_days)
    except Exception as exc:
        return f"Error fetching K-line data for {symbol}: {exc}"

    if not raw:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    df = _kline_to_dataframe(raw)
    if df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    # Filter to requested date range
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

    if df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    # Round prices
    for col in ["Open", "High", "Low", "Close", "Adj Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    # Reorder columns to match yfinance output
    df = df[["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]]

    csv_string = df.to_csv(index=False)

    header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---------------------------------------------------------------------------
# 2. get_stock_stats_indicators_window
# ---------------------------------------------------------------------------

def get_stock_stats_indicators_window(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Return technical indicator values for a date window using stockstats."""
    symbol = str(symbol)
    best_ind_params = {
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    try:
        indicator_data = _get_stock_stats_bulk_tencent(symbol, indicator, curr_date)

        current_dt = curr_date_dt
        date_values = []

        while current_dt >= before:
            date_str = current_dt.strftime("%Y-%m-%d")
            value = indicator_data.get(date_str, "N/A: Not a trading day (weekend or holiday)")
            date_values.append((date_str, value))
            current_dt = current_dt - relativedelta(days=1)

        ind_string = ""
        for date_str, value in date_values:
            ind_string += f"{date_str}: {value}\n"

    except Exception as exc:
        logger.warning("Error getting bulk stockstats data: %s", exc)
        ind_string = ""
        temp_dt = curr_date_dt
        while temp_dt >= before:
            ind_string += f"{temp_dt.strftime('%Y-%m-%d')}: N/A\n"
            temp_dt = temp_dt - relativedelta(days=1)

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )

    return result_str


def _get_stock_stats_bulk_tencent(
    symbol: str,
    indicator: str,
    curr_date: str,
) -> dict:
    """Calculate stockstats indicator values for all dates using Tencent OHLCV data."""
    from stockstats import wrap

    data = load_ohlcv_tencent(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Trigger indicator calculation
    df[indicator]

    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]
        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)

    return result_dict


# ---------------------------------------------------------------------------
# 3. get_fundamentals
# ---------------------------------------------------------------------------

def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used)"] = None,
) -> str:
    """Return key financial indicators for a Chinese A-share via East Money API."""
    ticker = str(ticker)
    try:
        em_code = _eastmoney_code(ticker)
        raw_code = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Company Fundamentals for {ticker.upper()}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # --- Fetch key financial indicators from East Money ZYZB API ---
    try:
        url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"
            f"/ZYZBAjaxNew?type=0&code={em_code}"
        )
        resp = _api_get(url)
        payload = resp.json()
        data_arr = payload.get("data") or []
    except Exception as exc:
        logger.warning("East Money fundamentals request failed for %s: %s", ticker, exc)
        return header + "Error fetching fundamentals data from East Money."

    if not data_arr:
        return header + "No fundamentals data available for this ticker."

    # Use the most recent report period
    latest = data_arr[0] if isinstance(data_arr, list) else data_arr

    def _val(key: str, default="N/A"):
        v = latest.get(key)
        if v is None or v == "-" or v == "":
            return default
        try:
            return f"{float(v):.4f}" if "." in str(v) else str(v)
        except (ValueError, TypeError):
            return str(v)

    def _pct(key: str, default="N/A"):
        v = latest.get(key)
        if v is None or v == "-" or v == "":
            return default
        try:
            return f"{float(v) * 100:.2f}%"
        except (ValueError, TypeError):
            return str(v)

    def _money(key: str, default="N/A"):
        v = latest.get(key)
        if v is None or v == "-" or v == "":
            return default
        try:
            val = float(v)
            if abs(val) >= 1e8:
                return f"{val / 1e8:.2f} (亿)"
            elif abs(val) >= 1e4:
                return f"{val / 1e4:.2f} (万)"
            return f"{val:.2f}"
        except (ValueError, TypeError):
            return str(v)

    report_date = latest.get("REPORT_DATE", "N/A")
    if isinstance(report_date, str) and len(report_date) >= 10:
        report_date = report_date[:10]

    # Also grab company name from Sina
    sym = _tencent_symbol(ticker)
    quote = _fetch_sina_quote(sym)
    company_name = quote.get("name", "N/A") if quote else "N/A"

    lines = [
        f"Name: {company_name}",
        f"Report Date: {report_date}",
        f"Basic EPS: {_val('BASIC_EPS')}",
        f"Diluted EPS: {_val('DILUTED_EPS')}",
        f"Book Value Per Share (MGJZC): {_val('MGJZC')}",
        f"Weighted Avg ROE: {_pct('WEIGHT_AVG_ROE')}",
        f"Revenue (YYZSR): {_money('YYZSR')}",
        f"Revenue YoY% (YSTZ): {_pct('YSTZ')}",
        f"Net Profit: {_money('PARENT_NETPROFIT')}",
        f"Net Profit YoY% (SJLTZ): {_pct('SJLTZ')}",
        f"Gross Margin: {_pct('XSMLL')}",
        f"Net Margin: {_pct('XSJLL')}",
        f"Total Assets: {_money('TOTAL_ASSETS')}",
        f"Total Equity: {_money('TOTAL_EQUITY')}",
        f"Operating Cash Flow Per Share: {_val('MGJYXJJE')}",
    ]

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 4-6. Financial statements (East Money DataCenter API)
# ---------------------------------------------------------------------------

def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Balance sheet data for a Chinese A-share via East Money DataCenter API."""
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    page_size = 5 if freq == "quarterly" else 3
    rows = _fetch_eastmoney_datacenter("RPT_DMSK_FN_BALANCE", raw_code, page_size)

    if not rows:
        return header + "No balance sheet data available for this ticker."

    def _fmt(v, default="N/A"):
        if v is None or v == "-" or v == "":
            return default
        try:
            val = float(v)
            if abs(val) >= 1e8:
                return f"{val / 1e8:.2f}亿"
            return f"{val:.2f}"
        except (ValueError, TypeError):
            return str(v)

    columns = ["Report Date", "Total Assets", "Total Current Assets", "Total Liabilities",
               "Total Current Liab", "Total Equity", "Total Parent Equity"]
    lines = [",".join(columns)]

    for row in rows[:page_size]:
        report_date = str(row.get("REPORT_DATE", ""))[:10]
        lines.append(",".join([
            report_date,
            _fmt(row.get("TOTAL_ASSETS")),
            _fmt(row.get("TOTAL_CURRENT_ASSETS")),
            _fmt(row.get("TOTAL_LIABILITIES")),
            _fmt(row.get("TOTAL_CURRENT_LIAB")),
            _fmt(row.get("TOTAL_EQUITY")),
            _fmt(row.get("TOTAL_PARENT_EQUITY")),
        ]))

    return header + "\n".join(lines)


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Cash flow data for a Chinese A-share via East Money DataCenter API."""
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Cash Flow data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    page_size = 5 if freq == "quarterly" else 3
    rows = _fetch_eastmoney_datacenter("RPT_DMSK_FN_CASHFLOW", raw_code, page_size)

    if not rows:
        return header + "No cash flow data available for this ticker."

    def _fmt(v, default="N/A"):
        if v is None or v == "-" or v == "":
            return default
        try:
            val = float(v)
            if abs(val) >= 1e8:
                return f"{val / 1e8:.2f}亿"
            return f"{val:.2f}"
        except (ValueError, TypeError):
            return str(v)

    columns = ["Report Date", "Net Cash from Operating", "Net Cash from Investing",
               "Net Cash from Financing", "Net Change in Cash"]
    lines = [",".join(columns)]

    for row in rows[:page_size]:
        report_date = str(row.get("REPORT_DATE", ""))[:10]
        lines.append(",".join([
            report_date,
            _fmt(row.get("NETCASH_OPERATE")),
            _fmt(row.get("NETCASH_INVEST")),
            _fmt(row.get("NETCASH_FINANCE")),
            _fmt(row.get("CCE_ADD")),
        ]))

    return header + "\n".join(lines)


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Income statement data for a Chinese A-share via East Money DataCenter API."""
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Income Statement data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    page_size = 5 if freq == "quarterly" else 3
    rows = _fetch_eastmoney_datacenter("RPT_DMSK_FN_INCOME", raw_code, page_size)

    if not rows:
        return header + "No income statement data available for this ticker."

    def _fmt(v, default="N/A"):
        if v is None or v == "-" or v == "":
            return default
        try:
            val = float(v)
            if abs(val) >= 1e8:
                return f"{val / 1e8:.2f}亿"
            return f"{val:.2f}"
        except (ValueError, TypeError):
            return str(v)

    columns = ["Report Date", "Operating Revenue", "Operating Cost", "Net Profit",
               "Net Profit (Parent)", "Gross Profit"]
    lines = [",".join(columns)]

    for row in rows[:page_size]:
        report_date = str(row.get("REPORT_DATE", ""))[:10]
        lines.append(",".join([
            report_date,
            _fmt(row.get("OPERATE_INCOME")),
            _fmt(row.get("OPERATE_COST")),
            _fmt(row.get("NETPROFIT")),
            _fmt(row.get("PARENT_NETPROFIT")),
            _fmt(row.get("OPERATE_INCOME_GROSS")),
        ]))

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. get_insider_transactions
# ---------------------------------------------------------------------------

def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Insider transactions — not available for A-shares."""
    ticker = str(ticker)
    header = f"# Insider Transactions data for {ticker.upper()}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return (
        header
        + "ERROR: PERMANENT_FAILURE. The data source fundamentally does not support this ticker format. "
        "Retrying with different parameters will NOT work. "
        "Stop calling this tool and proceed with analysis using available data only."
    )


# ---------------------------------------------------------------------------
# 8-9. News
# ---------------------------------------------------------------------------

def _eastmoney_stock_announcements(code: str, page_size: int = 15) -> list:
    """Fetch company announcements/news from East Money.

    Uses the stable np-anotice-stock API which returns real filings and news.
    Returns a list of dicts with keys: title, content, source, url, date.
    """
    # Determine market prefix for the API
    try:
        em_code = _eastmoney_code(code)
    except ValueError:
        em_code = code

    url = (
        "https://np-anotice-stock.eastmoney.com/api/security/ann"
        f"?page_size={page_size}&page_index=1&ann_type=A"
        f"&stock_list={_normalize_ticker(code)}&f_node=0&s_node=0"
    )
    try:
        resp = _api_get(url)
        payload = resp.json()
    except Exception as exc:
        logger.warning("East Money announcements failed for '%s': %s", code, exc)
        return []

    articles = []
    try:
        items = payload.get("data", {}).get("list", [])
    except (AttributeError, TypeError):
        return []

    for item in items[:page_size]:
        title = item.get("title", "")
        # Extract announcement type from columns
        cols = item.get("columns", [])
        art_type = cols[0].get("column_name", "") if cols else ""
        date_str = item.get("display_time", "")[:19]  # "2026-04-28 17:55:07:283"
        # Build URL for the announcement detail page
        art_code = item.get("art_code", "")
        art_url = (
            f"https://data.eastmoney.com/notices/detail/{_normalize_ticker(code)}/{art_code}.html"
            if art_code
            else ""
        )
        articles.append({
            "title": f"[{art_type}] {title}" if art_type else title,
            "content": "",
            "source": "东方财富",
            "url": art_url,
            "date": date_str[:10] if date_str else "",  # Just the date part
        })

    return articles


def _eastmoney_news_search(keyword: str, limit: int = 15) -> list:
    """Search East Money news articles by keyword.

    Returns a list of dicts with keys: title, content, source, url, date.
    Falls back to East Money stock announcements API when keyword search
    is unavailable.
    """
    param = json.dumps(
        {"uid": "", "keyword": keyword, "type": ["cmsArticleWeb"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    url = (
        "https://search-api-web.eastmoney.com/search/jsonp"
        f"?cb=jQuery&param={quote(param)}"
    )
    try:
        resp = _api_get(url)
        payload = _parse_jsonp(resp.text)
    except Exception as exc:
        logger.warning("East Money news search failed for '%s': %s", keyword, exc)
        return []

    articles = []
    try:
        item_list = (
            payload.get("result", {})
            .get("cmsArticleWeb", {})
            .get("list", [])
        )
    except (AttributeError, TypeError):
        return []

    for item in item_list[:limit]:
        title = item.get("title", "").replace("<em>", "").replace("</em>", "")
        content = item.get("content", "")
        # Strip HTML-like highlight tags from content
        content = content.replace("<em>", "").replace("</em>", "")
        source = item.get("source", "东方财富")
        article_url = item.get("url", "")
        date_str = item.get("date", "")
        articles.append({
            "title": title,
            "content": content[:300] if content else "",
            "source": source,
            "url": article_url,
            "date": date_str,
        })

    return articles


def get_news(
    ticker: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Stock-specific news for a Chinese A-share via East Money announcements API."""
    ticker = str(ticker)
    # Use East Money stock announcements (most reliable)
    articles = _eastmoney_stock_announcements(ticker, page_size=20)

    # Also try keyword search as supplement
    keyword = ticker
    try:
        sym = _tencent_symbol(ticker)
        quote = _fetch_sina_quote(sym)
        if quote and quote.get("name"):
            keyword = quote["name"]
    except Exception:
        pass

    search_articles = _eastmoney_news_search(keyword, limit=10)
    time.sleep(0.5)  # small gap between sequential East Money calls
    articles.extend(search_articles)

    if not articles:
        return (
            f"# News for {ticker.upper()} ({start_date} to {end_date})\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"No news articles found for {keyword} via East Money."
        )

    # Filter by date range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    filtered = []
    for art in articles:
        try:
            art_date = datetime.strptime(art["date"][:10], "%Y-%m-%d")
            if start_dt <= art_date <= end_dt:
                filtered.append(art)
        except (ValueError, TypeError, IndexError):
            # Keep articles with unparseable dates
            filtered.append(art)

    # Use filtered if non-empty, otherwise use all
    display = filtered if filtered else articles[:10]

    header = (
        f"# News for {ticker.upper()} ({keyword}) from {start_date} to {end_date}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    parts = []
    for i, art in enumerate(display[:15], 1):
        parts.append(f"## {i}. {art['title']}")
        parts.append(f"- Source: {art['source']}")
        parts.append(f"- Date: {art['date']}")
        if art["content"]:
            parts.append(f"- Summary: {art['content']}")
        if art["url"]:
            parts.append(f"- URL: {art['url']}")
        parts.append("")

    return header + "\n".join(parts)


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles"] = 10,
) -> str:
    """Global/macro news for Chinese markets via East Money search API."""
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_str = start_dt.strftime("%Y-%m-%d")

    # Search with broad market keywords
    all_articles = []
    for keyword in ("A股", "股市", "宏观经济"):
        articles = _eastmoney_news_search(keyword, limit=10)
        all_articles.extend(articles)
        time.sleep(1.0)  # avoid rapid-fire requests to same API

    # Deduplicate by title
    seen_titles = set()
    unique = []
    for art in all_articles:
        if art["title"] not in seen_titles:
            seen_titles.add(art["title"])
            unique.append(art)

    # Filter by date range
    filtered = []
    for art in unique:
        try:
            art_date = datetime.strptime(art["date"][:10], "%Y-%m-%d")
            if start_dt <= art_date <= curr_dt:
                filtered.append(art)
        except (ValueError, TypeError, IndexError):
            filtered.append(art)

    display = filtered[:limit] if filtered else unique[:limit]

    header = (
        f"# Global Market News ({start_str} to {curr_date})\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    if not display:
        return header + "No global news articles found via East Money."

    parts = []
    for i, art in enumerate(display, 1):
        parts.append(f"## {i}. {art['title']}")
        parts.append(f"- Source: {art['source']}")
        parts.append(f"- Date: {art['date']}")
        if art["content"]:
            parts.append(f"- Summary: {art['content']}")
        if art["url"]:
            parts.append(f"- URL: {art['url']}")
        parts.append("")

    return header + "\n".join(parts)


# ---------------------------------------------------------------------------
# OHLCV loader for stockstats (used by technical indicators)
# ---------------------------------------------------------------------------

def load_ohlcv_tencent(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data from Tencent with caching, filtered to *curr_date*.

    Mirrors ``load_ohlcv()`` but uses the Tencent K-line API instead of
    yfinance.
    """
    safe_symbol = safe_ticker_component(symbol)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-Tencent-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        try:
            sym = _tencent_symbol(symbol)
        except ValueError:
            # Fall back to treating symbol as-is if it can't be normalized
            sym = symbol

        # Fetch ~5 years of data
        fetch_days = 1300
        raw = _fetch_tencent_kline(sym, days=fetch_days)
        data = _kline_to_dataframe(raw)

        if data.empty:
            raise RuntimeError(f"No OHLCV data returned from Tencent for {symbol}")

        data.to_csv(data_file, index=False, encoding="utf-8")

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias
    data = data[data["Date"] <= curr_date_dt]

    return data
