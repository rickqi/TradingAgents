"""AKShare-based data fetching for Chinese A-share stocks.

Provides per-stock data via the AKShare library, which wraps East Money,
Sina, and other Chinese financial data APIs.  Covers OHLCV price history,
technical indicators (via stockstats), fundamentals, financial statements,
insider transactions, and sentiment data.

Advantages over tencent_sina:
  - Per-stock financial statement fetching (no all-market bulk download).
  - Insider transactions via stock_inner_trade_xq (fills the
    PERMANENT_FAILURE gap in tencent_sina).
  - Sentiment / stock comments via stock_comment_em.

AKShare is not used for news (stock_news_em has a pandas 3.0 bug) or
global news (not supported).
"""

import logging
import time
from datetime import datetime
from typing import Annotated

import akshare as ak
import pandas as pd
from dateutil.relativedelta import relativedelta

from .stockstats_utils import _clean_dataframe
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ticker / symbol helpers
# ---------------------------------------------------------------------------

def _normalize_ticker_to_code(ticker: str) -> str:
    """Return the raw 6-digit stock code from various input formats.

    Accepted inputs: ``"300308"``, ``"300308.SZ"``, ``"600183.SS"``,
    ``"SH600183"``, ``"sz300308"``.

    Raises ``ValueError`` if the result is not a pure digit string.
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


def _normalize_ticker_to_akshare(ticker: str) -> str:
    """Convert ticker to AKShare report-style symbol: ``SH600519``, ``SZ002876``.

    Prefix rules:
      - 6xx → SH (Shanghai main board)
      - 0xx, 3xx → SZ (Shenzhen main board / ChiNext)
    """
    code = _normalize_ticker_to_code(ticker)
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def _akshare_hist_symbol(ticker: str) -> str:
    """Return plain 6-digit code for ``akshare.stock_zh_a_hist()``."""
    return _normalize_ticker_to_code(ticker)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_money(v, default: str = "N/A") -> str:
    """Format a monetary value with Chinese units (亿, 万)."""
    if v is None or v == "-" or v == "":
        return default
    try:
        val = float(v)
        if abs(val) >= 1e8:
            return f"{val / 1e8:.2f}亿"
        elif abs(val) >= 1e4:
            return f"{val / 1e4:.2f}万"
        return f"{val:.2f}"
    except (ValueError, TypeError):
        return str(v)


def _fmt_pct(v, default: str = "N/A") -> str:
    """Format a percentage value."""
    if v is None or v == "-" or v == "":
        return default
    try:
        return f"{float(v):.2f}%"
    except (ValueError, TypeError):
        return str(v)


def _fmt_val(v, default: str = "N/A") -> str:
    """Format a generic numeric value."""
    if v is None or v == "-" or v == "":
        return default
    try:
        return f"{float(v):.4f}" if "." in str(v) else str(v)
    except (ValueError, TypeError):
        return str(v)


# ---------------------------------------------------------------------------
# 1. get_YFin_data_online — OHLCV via AKShare
# ---------------------------------------------------------------------------

def get_YFin_data_online(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Return OHLCV CSV string for a Chinese A-share via AKShare hist API."""
    symbol = str(symbol)
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    try:
        code = _akshare_hist_symbol(symbol)
    except ValueError as exc:
        return f"Error: {exc}"

    # AKShare expects YYYYMMDD format
    ak_start = start_date.replace("-", "")
    ak_end = end_date.replace("-", "")

    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=ak_start,
            end_date=ak_end,
            adjust="qfq",
        )
    except Exception as exc:
        return f"Error fetching OHLCV data for {symbol}: {exc}"

    if df is None or df.empty:
        return (
            f"No data found for symbol '{symbol}' "
            f"between {start_date} and {end_date}"
        )

    # Map Chinese column names to standard format
    col_map = {
        "日期": "Date",
        "开盘": "Open",
        "收盘": "Close",
        "最高": "High",
        "最低": "Low",
        "成交量": "Volume",
        "涨跌幅": "Change%",
        "涨跌额": "Change",
        "换手率": "Turnover%",
    }
    df = df.rename(columns=col_map)

    # Adj Close = Close for forward-adjusted (qfq) data
    df["Adj Close"] = df["Close"].round(2)

    # Round prices
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    # Select standard columns
    out_cols = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    df = df[[c for c in out_cols if c in df.columns]]

    csv_string = df.to_csv(index=False)

    header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---------------------------------------------------------------------------
# 2. get_stock_stats_indicators_window — Technical indicators
# ---------------------------------------------------------------------------

def get_stock_stats_indicators_window(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Return technical indicator values for a date window using stockstats.

    Loads OHLCV data via AKShare, then delegates to stockstats for
    indicator computation.
    """
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
            f"Indicator {indicator} is not supported. "
            f"Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    try:
        indicator_data = _get_stock_stats_bulk_akshare(symbol, indicator, curr_date)

        current_dt = curr_date_dt
        date_values = []

        while current_dt >= before:
            date_str = current_dt.strftime("%Y-%m-%d")
            value = indicator_data.get(
                date_str, "N/A: Not a trading day (weekend or holiday)"
            )
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


def _get_stock_stats_bulk_akshare(
    symbol: str,
    indicator: str,
    curr_date: str,
) -> dict:
    """Calculate stockstats indicator values for all dates using AKShare OHLCV."""
    from stockstats import wrap

    data = _load_ohlcv_akshare(symbol, curr_date)
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


def _load_ohlcv_akshare(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data via AKShare, filtered to *curr_date*.

    Similar to ``load_ohlcv_tencent`` but uses AKShare's
    ``stock_zh_a_hist`` for data fetching.
    """
    import os
    from .config import get_config

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
        f"{safe_symbol}-AKShare-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        try:
            code = _akshare_hist_symbol(symbol)
        except ValueError:
            code = symbol

        ak_start = start_str.replace("-", "")
        ak_end = end_str.replace("-", "")

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=ak_start,
            end_date=ak_end,
            adjust="qfq",
        )

        if df is None or df.empty:
            raise RuntimeError(f"No OHLCV data returned from AKShare for {symbol}")

        # Map columns
        col_map = {
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
        }
        df = df.rename(columns=col_map)
        out_cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        data = df[out_cols]
        data.to_csv(data_file, index=False, encoding="utf-8")

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias
    data = data[data["Date"] <= curr_date_dt]

    return data


# ---------------------------------------------------------------------------
# 3. get_fundamentals — Key financial indicators via AKShare
# ---------------------------------------------------------------------------

def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used)"] = None,
) -> str:
    """Return key financial indicators for a Chinese A-share via AKShare."""
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker_to_code(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Company Fundamentals for {ticker.upper()}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # Determine start_year (look back 5 years)
    start_year = str(datetime.now().year - 5)

    try:
        df = ak.stock_financial_analysis_indicator(
            symbol=raw_code, start_year=start_year
        )
    except Exception as exc:
        logger.warning("AKShare fundamentals request failed for %s: %s", ticker, exc)
        return header + f"Error fetching fundamentals data from AKShare: {exc}"

    if df is None or df.empty:
        return header + "No fundamentals data available for this ticker."

    # The DataFrame has dates as columns or rows depending on the API version.
    # stock_financial_analysis_indicator returns rows with a date column.
    # Take the most recent period.
    try:
        # Sort by date descending and take the first row
        if "日期" in df.columns:
            date_col = "日期"
        elif "date" in df.columns:
            date_col = "date"
        else:
            # Use the first column as date
            date_col = df.columns[0]

        df_sorted = df.sort_values(by=date_col, ascending=False)
        latest = df_sorted.iloc[0]
    except Exception as exc:
        logger.warning("Error parsing fundamentals DataFrame: %s", exc)
        return header + "Error parsing fundamentals data."

    def _get(key: str, default: str = "N/A") -> str:
        val = latest.get(key)
        if val is None or val == "-" or val == "" or pd.isna(val):
            return default
        return str(val)

    report_date = str(latest.get(date_col, "N/A"))[:10]

    lines = [
        f"Report Date: {report_date}",
        f"EPS (基本每股收益): {_get('基本每股收益')}",
        f"EPS (diluted): {_get('稀释每股收益')}",
        f"Book Value Per Share (每股净资产): {_get('每股净资产')}",
        f"Weighted ROE (加权净资产收益率): {_fmt_pct(latest.get('加权净资产收益率'))}",
        f"Gross Margin (销售毛利率): {_fmt_pct(latest.get('销售毛利率'))}",
        f"Net Margin (销售净利率): {_fmt_pct(latest.get('销售净利率'))}",
        f"Revenue Growth (营业收入同比增长率): {_fmt_pct(latest.get('营业收入同比增长率'))}",
        f"Net Profit Growth (净利润同比增长率): {_fmt_pct(latest.get('净利润同比增长率'))}",
        f"Total Asset Growth (总资产增长率): {_fmt_pct(latest.get('总资产增长率'))}",
        f"Current Ratio (流动比率): {_get('流动比率')}",
        f"Quick Ratio (速动比率): {_get('速动比率')}",
    ]

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. get_balance_sheet — Balance sheet via AKShare
# ---------------------------------------------------------------------------

def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Balance sheet data for a Chinese A-share via AKShare East Money API."""
    ticker = str(ticker)
    try:
        ak_sym = _normalize_ticker_to_akshare(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        if freq == "annual":
            df = ak.stock_balance_sheet_by_yearly_em(symbol=ak_sym)
        else:
            df = ak.stock_balance_sheet_by_report_em(symbol=ak_sym)
    except Exception as exc:
        logger.warning("AKShare balance sheet failed for %s: %s", ticker, exc)
        return header + f"Error fetching balance sheet data: {exc}"

    if df is None or df.empty:
        return header + "No balance sheet data available for this ticker."

    # Filter by curr_date to prevent look-ahead bias
    date_col = None
    for col_name in ("REPORT_DATE", "报告日期", "截止日期", "日期"):
        if col_name in df.columns:
            date_col = col_name
            break

    if date_col and curr_date:
        try:
            cutoff = pd.Timestamp(curr_date)
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[df[date_col] <= cutoff]
        except Exception:
            pass  # If date parsing fails, return all data

    if df.empty:
        return header + "No balance sheet data available for this date range."

    limit = 3 if freq == "annual" else 5
    df = df.head(limit)

    # Build output
    columns = ["Report Date", "Total Assets", "Total Current Assets",
               "Total Liabilities", "Total Current Liab", "Total Equity",
               "Total Parent Equity"]
    lines = [",".join(columns)]

    for _, row in df.iterrows():
        report_date = ""
        if date_col:
            rd = row.get(date_col, "")
            report_date = str(rd)[:10] if rd else ""

        lines.append(",".join([
            report_date,
            _fmt_money(row.get("总资产")),
            _fmt_money(row.get("流动资产合计")),
            _fmt_money(row.get("负债合计")),
            _fmt_money(row.get("流动负债合计")),
            _fmt_money(row.get("所有者权益合计")),
            _fmt_money(row.get("母公司所有者权益合计")),
        ]))

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. get_cashflow — Cash flow via AKShare
# ---------------------------------------------------------------------------

def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Cash flow data for a Chinese A-share via AKShare East Money API."""
    ticker = str(ticker)
    try:
        ak_sym = _normalize_ticker_to_akshare(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Cash Flow data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        if freq == "annual":
            df = ak.stock_cash_flow_sheet_by_yearly_em(symbol=ak_sym)
        else:
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=ak_sym)
    except Exception as exc:
        logger.warning("AKShare cash flow failed for %s: %s", ticker, exc)
        return header + f"Error fetching cash flow data: {exc}"

    if df is None or df.empty:
        return header + "No cash flow data available for this ticker."

    # Filter by curr_date
    date_col = None
    for col_name in ("REPORT_DATE", "报告日期", "截止日期", "日期"):
        if col_name in df.columns:
            date_col = col_name
            break

    if date_col and curr_date:
        try:
            cutoff = pd.Timestamp(curr_date)
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[df[date_col] <= cutoff]
        except Exception:
            pass

    if df.empty:
        return header + "No cash flow data available for this date range."

    limit = 3 if freq == "annual" else 5
    df = df.head(limit)

    columns = ["Report Date", "Net Cash from Operating", "Net Cash from Investing",
               "Net Cash from Financing", "Net Change in Cash"]
    lines = [",".join(columns)]

    for _, row in df.iterrows():
        report_date = ""
        if date_col:
            rd = row.get(date_col, "")
            report_date = str(rd)[:10] if rd else ""

        lines.append(",".join([
            report_date,
            _fmt_money(row.get("经营活动产生的现金流量净额")),
            _fmt_money(row.get("投资活动产生的现金流量净额")),
            _fmt_money(row.get("筹资活动产生的现金流量净额")),
            _fmt_money(row.get("现金及现金等价物净增加额")),
        ]))

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. get_income_statement — Income statement via AKShare
# ---------------------------------------------------------------------------

def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Income statement data for a Chinese A-share via AKShare East Money API."""
    ticker = str(ticker)
    try:
        ak_sym = _normalize_ticker_to_akshare(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Income Statement data for {ticker.upper()} ({freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        if freq == "annual":
            df = ak.stock_profit_sheet_by_yearly_em(symbol=ak_sym)
        else:
            df = ak.stock_profit_sheet_by_report_em(symbol=ak_sym)
    except Exception as exc:
        logger.warning("AKShare income statement failed for %s: %s", ticker, exc)
        return header + f"Error fetching income statement data: {exc}"

    if df is None or df.empty:
        return header + "No income statement data available for this ticker."

    # Filter by curr_date
    date_col = None
    for col_name in ("REPORT_DATE", "报告日期", "截止日期", "日期"):
        if col_name in df.columns:
            date_col = col_name
            break

    if date_col and curr_date:
        try:
            cutoff = pd.Timestamp(curr_date)
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[df[date_col] <= cutoff]
        except Exception:
            pass

    if df.empty:
        return header + "No income statement data available for this date range."

    limit = 3 if freq == "annual" else 5
    df = df.head(limit)

    columns = ["Report Date", "Operating Revenue", "Operating Cost", "Net Profit",
               "Net Profit (Parent)", "Gross Profit"]
    lines = [",".join(columns)]

    for _, row in df.iterrows():
        report_date = ""
        if date_col:
            rd = row.get(date_col, "")
            report_date = str(rd)[:10] if rd else ""

        lines.append(",".join([
            report_date,
            _fmt_money(row.get("营业总收入")),
            _fmt_money(row.get("营业总成本")),
            _fmt_money(row.get("净利润")),
            _fmt_money(row.get("母公司所有者的净利润")),
            _fmt_money(row.get("营业利润")),
        ]))

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. get_insider_transactions — Insider trades via AKShare (fills gap)
# ---------------------------------------------------------------------------

def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Insider transactions for a Chinese A-share via AKShare stock_inner_trade_xq.

    Fetches all insider trades from AKShare and filters locally by stock code.
    This fills the PERMANENT_FAILURE gap in the tencent_sina vendor.
    """
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker_to_code(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Insider Transactions data for {ticker.upper()}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        # stock_inner_trade_xq returns all insider trades at once
        df = ak.stock_inner_trade_xq()
    except Exception as exc:
        logger.warning("AKShare insider transactions failed: %s", exc)
        return header + f"Error fetching insider transactions: {exc}"

    if df is None or df.empty:
        return header + "No insider transaction data available."

    # Filter by stock code
    # The column name for stock code varies; try common names
    code_col = None
    for col_name in ("股票代码", "公司代码", "code", "stock_code"):
        if col_name in df.columns:
            code_col = col_name
            break

    if code_col is None:
        # Try to find a column containing 6-digit codes
        for col in df.columns:
            sample = df[col].dropna().astype(str).head(5)
            if any(s.isdigit() and len(s) == 6 for s in sample):
                code_col = col
                break

    if code_col is None:
        return header + "Error: Could not identify stock code column in insider trade data."

    # Normalize the code column for matching
    df["_norm_code"] = df[code_col].astype(str).str.strip().str.lower()
    # Also match without leading zeros for robustness
    filtered = df[df["_norm_code"] == raw_code]
    if filtered.empty:
        # Try matching with suffix-stripped version
        filtered = df[df["_norm_code"].str.contains(raw_code, na=False)]

    if filtered.empty:
        return header + f"No insider transactions found for {ticker.upper()}."

    # Build output
    # Identify column names dynamically
    def _find_col(possible_names: list[str]) -> str | None:
        for name in possible_names:
            if name in filtered.columns:
                return name
        return None

    trader_col = _find_col(["变动人", "交易者", "高管姓名", "name"])
    rel_col = _find_col(["变动人与高管关系", "高管职务", "职务", "relationship", "title"])
    change_col = _find_col(["变动股数", "变动数量", "交易股数", "shares"])
    price_col = _find_col(["成交均价", "变动价格", "交易价格", "price"])
    date_col = _find_col(["变动日期", "交易日期", "日期", "date"])
    change_type_col = _find_col(["变动方向", "交易方向", "买卖方向", "type"])

    parts = [header.rstrip()]
    parts.append(f"Found {len(filtered)} insider transaction(s).\n")

    # Limit output to most recent 20 transactions
    display = filtered.head(20)

    for i, (_, row) in enumerate(display.iterrows(), 1):
        parts.append(f"## Transaction {i}")
        if trader_col:
            parts.append(f"- Trader: {row.get(trader_col, 'N/A')}")
        if rel_col:
            parts.append(f"- Relationship/Title: {row.get(rel_col, 'N/A')}")
        if change_type_col:
            parts.append(f"- Change Type: {row.get(change_type_col, 'N/A')}")
        if change_col:
            val = row.get(change_col, "N/A")
            parts.append(f"- Shares Changed: {_fmt_money(val)}")
        if price_col:
            parts.append(f"- Avg Price: {row.get(price_col, 'N/A')}")
        if date_col:
            parts.append(f"- Date: {str(row.get(date_col, 'N/A'))[:10]}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 8. get_sentiment — Stock sentiment/comments via AKShare (NEW tool method)
# ---------------------------------------------------------------------------

def get_sentiment(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Return sentiment/stock comments for a Chinese A-share via AKShare.

    Uses ``stock_comment_em`` to get market-wide stock comments/ratings
    from East Money and filters for the specific ticker.
    """
    ticker = str(ticker)
    try:
        raw_code = _normalize_ticker_to_code(ticker)
    except ValueError as exc:
        return f"Error: {exc}"

    header = f"# Sentiment Data for {ticker.upper()}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        df = ak.stock_comment_em()
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("AKShare sentiment failed for %s: %s", ticker, exc)
        return header + f"Error fetching sentiment data: {exc}"

    if df is None or df.empty:
        return header + "No sentiment data available."

    # Filter by stock code column
    code_col = None
    for col_name in ("股票代码", "代码", "code"):
        if col_name in df.columns:
            code_col = col_name
            break

    if code_col is None:
        return header + "Error: Could not identify stock code column in sentiment data."

    df["_norm_code"] = df[code_col].astype(str).str.strip()
    filtered = df[df["_norm_code"] == raw_code]

    if filtered.empty:
        return header + f"No sentiment data found for {ticker.upper()}."

    row = filtered.iloc[0]

    def _find_col_val(possible_names: list[str]) -> str:
        for name in possible_names:
            if name in row.index:
                val = row[name]
                if pd.isna(val):
                    return "N/A"
                return str(val)
        return "N/A"

    # Extract key sentiment fields
    name = _find_col_val(["股票简称", "名称", "name"])
    current_price = _find_col_val(["最新价", "现价", "price"])
    change_amount = _find_col_val(["涨跌额", "change"])
    change_pct = _find_col_val(["涨跌幅", "change_pct"])
    # Composite score / recommendation fields
    composite_score = _find_col_val(["综合评分", "综合得分", "score"])
    buy_signal = _find_col_val(["买入信号", "buy_signal"])
    sell_signal = _find_col_val(["卖出信号", "sell_signal"])

    lines = [
        f"Stock: {name} ({ticker.upper()})",
        f"Current Price: {current_price}",
        f"Change: {change_amount} ({change_pct}%)",
        f"Composite Score: {composite_score}",
        f"Buy Signal: {buy_signal}",
        f"Sell Signal: {sell_signal}",
    ]

    # Include any additional numeric columns that look like scores/ratings
    extra_parts = []
    skip_cols = {code_col, "_norm_code"}
    for col in filtered.columns:
        if col in skip_cols:
            continue
        val = row.get(col)
        if val is not None and not pd.isna(val):
            col_lower = str(col).lower()
            # Skip already-included columns
            already_included = any(
                keyword in col
                for keyword in ("最新价", "涨跌额", "涨跌幅", "股票简称", "综合评分",
                                "买入信号", "卖出信号")
            )
            if not already_included:
                extra_parts.append(f"  {col}: {val}")

    if extra_parts:
        lines.append("")
        lines.append("Additional Data:")
        lines.extend(extra_parts[:20])  # Limit extra output

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 9-10. get_news / get_global_news — Stubs (AKShare limitations)
# ---------------------------------------------------------------------------

def get_news(
    ticker: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """News for a Chinese A-share — not available via AKShare.

    AKShare's ``stock_news_em`` has a pandas 3.0 compatibility bug,
    so this returns a message pointing to the tencent_sina vendor.
    """
    return (
        f"AKShare does not provide news data for {ticker}. "
        "Use tencent_sina vendor for A-share news."
    )


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles"] = 10,
) -> str:
    """Global/macro news — not available via AKShare."""
    return "AKShare does not provide global news data. Use tencent_sina vendor instead."
