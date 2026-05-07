"""Twelve Data vendor implementation — REST API via requests.

Provides 9 vendor methods compatible with the TradingAgents dataflows routing
system.  All methods return formatted strings (CSV / markdown) matching the
conventions used by yfinance and alpha_vantage vendors.

API docs: https://twelvedata.com/docs
"""
import os
import json
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Annotated

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.twelvedata.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Retrieve the API key for Twelve Data from environment variables."""
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY environment variable is not set.")
    return api_key


def _make_api_request(endpoint: str, params: dict) -> dict:
    """Make an API request to Twelve Data. Returns parsed JSON.

    Raises:
        ValueError: On Twelve Data API-level errors.
        requests.HTTPError: On HTTP-level errors.
    """
    params = params.copy()
    params["apikey"] = get_api_key()
    url = f"{API_BASE_URL}/{endpoint}"
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    # Twelve Data returns {"status": "error", "message": "..."} on failures
    if data.get("status") == "error":
        raise ValueError(f"Twelve Data API error: {data.get('message', 'Unknown error')}")
    return data


def _values_to_csv(values: list[dict], columns: list[str] | None = None) -> str:
    """Convert Twelve Data *values* array (list of dicts) to a CSV string.

    Twelve Data time-series endpoints return ``{"values": [{...}, ...]}``
    where each dict has keys like ``datetime``, ``open``, ``high``, etc.
    """
    if not values:
        return ""
    if columns is None:
        columns = list(values[0].keys())
    lines = [",".join(columns)]
    for row in values:
        lines.append(",".join(str(row.get(c, "")) for c in columns))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Stock data (OHLCV)
# ---------------------------------------------------------------------------

def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Fetch daily OHLCV time-series from Twelve Data."""
    try:
        data = _make_api_request("time_series", {
            "symbol": symbol.upper(),
            "interval": "1day",
            "start_date": start_date,
            "end_date": end_date,
            "outputsize": "5000",
            "format": "JSON",
        })

        values = data.get("values", [])
        if not values:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

        # Twelve Data returns newest-first; reverse to chronological order
        values.reverse()

        columns = ["datetime", "open", "high", "low", "close", "volume"]
        csv_string = _values_to_csv(values, columns)

        # Normalise header names to match yfinance convention
        csv_string = csv_string.replace("datetime", "Date", 1)
        csv_string = csv_string.replace("open", "Open", 1)
        csv_string = csv_string.replace("high", "High", 1)
        csv_string = csv_string.replace("low", "Low", 1)
        csv_string = csv_string.replace("close", "Close", 1)
        csv_string = csv_string.replace("volume", "Volume", 1)

        header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(values)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving stock data for {symbol}: {str(e)}"


# ---------------------------------------------------------------------------
# 2. Technical indicators
# ---------------------------------------------------------------------------

# Map internal indicator names → (Twelve Data endpoint, extra params, value-key)
_INDICATOR_CONFIG = {
    "close_50_sma":  ("sma",  {"time_period": 50},  "sma"),
    "close_200_sma": ("sma",  {"time_period": 200}, "sma"),
    "close_10_ema":  ("ema",  {"time_period": 10},  "ema"),
    "macd":          ("macd", {},                    "macd"),
    "macds":         ("macd", {},                    "macd_signal"),
    "macdh":         ("macd", {},                    "macd_hist"),
    "rsi":           ("rsi",  {"time_period": 14},   "rsi"),
    "boll":          ("bbands", {},                  "middle_band"),
    "boll_ub":       ("bbands", {},                  "upper_band"),
    "boll_lb":       ("bbands", {},                  "lower_band"),
    "atr":           ("atr",  {"time_period": 14},   "atr"),
    "vwma":          ("vwma", {"time_period": 20},   "vwma"),
}

_INDICATOR_DESCRIPTIONS = {
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
}


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Fetch technical indicator values over a look-back window from Twelve Data."""
    if indicator not in _INDICATOR_CONFIG:
        raise ValueError(
            f"Indicator {indicator} is not supported. "
            f"Please choose from: {list(_INDICATOR_CONFIG.keys())}"
        )

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    endpoint, extra_params, value_key = _INDICATOR_CONFIG[indicator]

    # Request enough data to cover the look-back window plus buffer
    params = {
        "symbol": symbol.upper(),
        "interval": "1day",
        "start_date": before.strftime("%Y-%m-%d"),
        "end_date": curr_date,
        "outputsize": str(look_back_days + 20),
        "format": "JSON",
    }
    params.update(extra_params)

    try:
        data = _make_api_request(endpoint, params)
        values = data.get("values", [])

        if not values:
            return (
                f"Error: No indicator data returned for {indicator} "
                f"from Twelve Data for {symbol}"
            )

        # Build date → value mapping, filtering to the requested window
        date_values = {}
        for v in values:
            dt_str = v.get("datetime", "")
            if not dt_str:
                continue
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            except ValueError:
                continue
            if before <= dt <= curr_date_dt:
                date_values[dt_str] = v.get(value_key, "N/A")

        # Walk the calendar from curr_date backwards to before
        ind_string = ""
        current_dt = curr_date_dt
        while current_dt >= before:
            ds = current_dt.strftime("%Y-%m-%d")
            if ds in date_values:
                ind_string += f"{ds}: {date_values[ds]}\n"
            else:
                ind_string += f"{ds}: N/A: Not a trading day (weekend or holiday)\n"
            current_dt -= timedelta(days=1)

        result_str = (
            f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + ind_string
            + "\n\n"
            + _INDICATOR_DESCRIPTIONS.get(indicator, "No description available.")
        )
        return result_str

    except Exception as e:
        return f"Error retrieving {indicator} data for {symbol}: {str(e)}"


# ---------------------------------------------------------------------------
# 3. Fundamentals
# ---------------------------------------------------------------------------

def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used by Twelve Data fundamentals)"] = None,
) -> str:
    """Get company fundamentals overview from Twelve Data."""
    try:
        # Fetch statistics and profile in parallel-ish fashion
        stats = _make_api_request("statistics", {"symbol": ticker.upper()})
        profile = _make_api_request("profile", {"symbol": ticker.upper()})

        fields = [
            ("Name", _deep_get(stats, "name") or _deep_get(profile, "name")),
            ("Sector", _deep_get(profile, "sector")),
            ("Industry", _deep_get(profile, "industry")),
            ("Market Cap", _deep_get(stats, "market_cap")),
            ("PE Ratio (TTM)", _deep_get(stats, "valuation_measures.pe_ratio_ttm")),
            ("Forward PE", _deep_get(stats, "valuation_measures.forward_pe_ratio")),
            ("PEG Ratio", _deep_get(stats, "valuation_measures.peg_ratio")),
            ("Price to Book", _deep_get(stats, "valuation_measures.price_to_book_ratio")),
            ("EPS (TTM)", _deep_get(stats, "income_statement.eps_basic")),
            ("Dividend Yield", _deep_get(stats, "basic_dividends.dividend_yield_recent")),
            ("52 Week High", _deep_get(stats, "week_52_high")),
            ("52 Week Low", _deep_get(stats, "week_52_low")),
            ("50 Day Average", _deep_get(stats, "day_50_moving_avg")),
            ("200 Day Average", _deep_get(stats, "day_200_moving_avg")),
            ("Revenue (TTM)", _deep_get(stats, "income_statement.revenue_ttm")),
            ("Gross Profit", _deep_get(stats, "income_statement.gross_profit")),
            ("EBITDA", _deep_get(stats, "income_statement.ebitda")),
            ("Net Income", _deep_get(stats, "income_statement.net_income")),
            ("Profit Margin", _deep_get(stats, "income_statement.net_profit_margin")),
            ("Operating Margin", _deep_get(stats, "income_statement.operating_income")),
            ("Return on Equity", _deep_get(stats, "income_statement.return_on_equity")),
            ("Return on Assets", _deep_get(stats, "income_statement.return_on_assets")),
            ("Debt to Equity", _deep_get(stats, "balance_sheet.debt_to_equity")),
            ("Current Ratio", _deep_get(stats, "balance_sheet.current_ratio")),
            ("Book Value", _deep_get(stats, "balance_sheet.book_value_per_share")),
            ("Free Cash Flow", _deep_get(stats, "cash_flow.free_cash_flow")),
        ]

        lines = []
        for label, value in fields:
            if value is not None and value != "" and value != "None":
                lines.append(f"{label}: {value}")

        header = f"# Company Fundamentals for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving fundamentals for {ticker}: {str(e)}"


def _deep_get(data: dict, path: str):
    """Traverse nested dicts using a dot-separated path. Returns None on miss."""
    keys = path.split(".")
    current = data
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return None
    return current


# ---------------------------------------------------------------------------
# 4–6. Financial statements (balance sheet, cash flow, income statement)
# ---------------------------------------------------------------------------

def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet data from Twelve Data."""
    return _get_financial_statement("balance_sheet", ticker, freq, curr_date,
                                    "Balance Sheet")


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement data from Twelve Data."""
    return _get_financial_statement("cash_flow", ticker, freq, curr_date,
                                    "Cash Flow")


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement data from Twelve Data."""
    return _get_financial_statement("income_statement", ticker, freq, curr_date,
                                    "Income Statement")


def _get_financial_statement(
    endpoint: str,
    ticker: str,
    freq: str,
    curr_date: str | None,
    label: str,
) -> str:
    """Generic handler for financial statement endpoints."""
    try:
        period = "quarterly" if freq.lower().startswith("q") else "annual"
        data = _make_api_request(endpoint, {
            "symbol": ticker.upper(),
            "period": period,
        })

        # Twelve Data returns a list of reports under the endpoint key
        # e.g. {"balance_sheet": [{...}, ...]}
        reports = data.get(endpoint, data.get("reports", []))
        if isinstance(reports, dict):
            # Sometimes the response wraps differently
            reports = [reports]

        if not reports:
            return f"No {label.lower()} data found for symbol '{ticker}'"

        # Filter out reports dated after curr_date to prevent look-ahead bias
        if curr_date:
            reports = [
                r for r in reports
                if r.get("fiscal_date Ending", r.get("date", r.get("fiscal_date_ending", ""))) <= curr_date
            ]

        if not reports:
            return f"No {label.lower()} data found for symbol '{ticker}' on or before {curr_date}"

        # Convert to CSV via DataFrame
        df = pd.DataFrame(reports)
        csv_string = df.to_csv(index=False)

        header = f"# {label} data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving {label.lower()} for {ticker}: {str(e)}"


# ---------------------------------------------------------------------------
# 7. News (ticker-specific)
# ---------------------------------------------------------------------------

def get_news(
    ticker: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Fetch ticker-specific news from Twelve Data."""
    try:
        data = _make_api_request("news", {
            "symbol": ticker.upper(),
            "start_date": start_date,
            "end_date": end_date,
        })

        articles = data.get("data", data.get("news", []))
        if not articles:
            return f"No news found for symbol '{ticker}' between {start_date} and {end_date}"

        lines = []
        for i, article in enumerate(articles[:20], 1):
            title = article.get("title", "No title")
            source = article.get("source", article.get("source_name", "Unknown"))
            date_str = article.get("published_at", article.get("date", ""))
            url = article.get("url", "")
            summary = article.get("summary", article.get("description", ""))

            lines.append(f"### {i}. {title}")
            lines.append(f"Source: {source} | Date: {date_str}")
            if summary:
                lines.append(f"Summary: {summary[:300]}")
            if url:
                lines.append(f"URL: {url}")
            lines.append("")

        header = f"# News for {ticker.upper()} from {start_date} to {end_date}\n"
        header += f"# Total articles: {len(articles)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving news for {ticker}: {str(e)}"


# ---------------------------------------------------------------------------
# 8. Global news (market-level)
# ---------------------------------------------------------------------------

def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles"] = 5,
) -> str:
    """Fetch global market news from Twelve Data.

    Twelve Data does not have a dedicated global-news endpoint.  We attempt to
    use the ``/news`` endpoint without a ticker filter, which may return
    general market news depending on the plan.  If that fails, the fallback
    chain in ``interface.py`` will try the next vendor.
    """
    try:
        start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days)

        data = _make_api_request("news", {
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": curr_date,
        })

        articles = data.get("data", data.get("news", []))
        if not articles:
            return "No global news data available from Twelve Data for this period."

        lines = []
        for i, article in enumerate(articles[:limit], 1):
            title = article.get("title", "No title")
            source = article.get("source", article.get("source_name", "Unknown"))
            date_str = article.get("published_at", article.get("date", ""))
            summary = article.get("summary", article.get("description", ""))

            lines.append(f"### {i}. {title}")
            lines.append(f"Source: {source} | Date: {date_str}")
            if summary:
                lines.append(f"Summary: {summary[:300]}")
            lines.append("")

        header = f"# Global Market News from {start_dt.strftime('%Y-%m-%d')} to {curr_date}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving global news: {str(e)}"


# ---------------------------------------------------------------------------
# 9. Insider transactions
# ---------------------------------------------------------------------------

def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Fetch insider transaction data from Twelve Data."""
    try:
        data = _make_api_request("insider_transactions", {
            "symbol": ticker.upper(),
        })

        transactions = data.get("insider_transactions",
                                data.get("transactions", data.get("data", [])))
        if isinstance(transactions, dict):
            transactions = [transactions]
        if not transactions:
            return f"No insider transactions data found for symbol '{ticker}'"

        # Convert to CSV via DataFrame
        df = pd.DataFrame(transactions)
        csv_string = df.to_csv(index=False)

        header = f"# Insider Transactions data for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving insider transactions for {ticker}: {str(e)}"
