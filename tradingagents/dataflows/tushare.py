"""Tushare Pro 数据供应商 — A 股日线行情 + 财务报表 + 技术指标

Tushare Pro API (https://tushare.pro) 提供 A 股金融数据。
需要 TUSHARE_API_KEY 环境变量和 pip install tushare。
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded Tushare Pro API singleton
# ---------------------------------------------------------------------------

_pro_api = None


def _get_pro_api():
    """Return a lazily-initialised Tushare pro_api instance.

    Raises ImportError if tushare is not installed.
    Raises ValueError if TUSHARE_API_KEY is not set.
    """
    global _pro_api
    if _pro_api is None:
        try:
            import tushare as ts
        except ImportError:
            raise ImportError(
                "tushare is not installed. Run: pip install tushare"
            )
        token = os.getenv("TUSHARE_API_KEY")
        if not token:
            raise ValueError(
                "TUSHARE_API_KEY environment variable is not set"
            )
        _pro_api = ts.pro_api(token)
    return _pro_api


# ---------------------------------------------------------------------------
# Ticker normalisation: TradingAgents formats → Tushare ts_code
# ---------------------------------------------------------------------------

def _normalize_to_ts_code(ticker: str) -> str:
    """Convert various ticker formats to Tushare ts_code.

    Supported inputs::

        000858         → 000858.SZ  (0/3 开头 = 深市)
        600519         → 600519.SH  (6 开头 = 沪市)
        830799         → 830799.BJ  (8/4 开头 = 北交所)
        000858.SZ      → 000858.SZ  (already correct)
        sh600183       → 600183.SH  (strip prefix, add correct suffix)
        " 000858.SZ "  → 000858.SZ  (strip whitespace + quotes)

    """
    t = str(ticker).strip().strip('"').strip("'").upper()

    # Strip known lowercase prefixes (already uppercased above, but handle both)
    t_lower = t.lower()
    for prefix in ("sh", "sz", "bj"):
        if t_lower.startswith(prefix):
            t = t[len(prefix):]
            break

    # If already has a suffix like .SZ / .SH / .BJ, return as-is
    if "." in t:
        return t

    # Pure code → determine exchange
    code = t.strip()
    if not code.isdigit():
        raise ValueError(f"Cannot normalize ticker '{ticker}' to a Tushare ts_code")

    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    else:
        # Default to SZ for unknown patterns
        return f"{code}.SZ"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _to_tushare_date(date_str: str) -> str:
    """Convert ``YYYY-MM-DD`` to ``YYYYMMDD``."""
    return date_str.replace("-", "")


def _from_tushare_date(date_str: str) -> str:
    """Convert ``YYYYMMDD`` to ``YYYY-MM-DD``."""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _safe_api():
    """Try to get pro_api; return None + error string on failure."""
    try:
        return _get_pro_api(), None
    except (ImportError, ValueError) as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# 1. get_stock_data — OHLCV with forward-adjusted close
# ---------------------------------------------------------------------------

def get_stock_data(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Fetch daily OHLCV time-series from Tushare Pro.

    Returns CSV with columns: Date,Open,High,Low,Close,Adj Close,Volume.
    Adj Close is forward-adjusted (前复权) using adj_factor.
    Volume is converted from 手 (lots of 100) to shares.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving stock data for {symbol}: {err}"

        ts_code = _normalize_to_ts_code(symbol)
        start_td = _to_tushare_date(start_date)
        end_td = _to_tushare_date(end_date)

        # Fetch daily bars + adjustment factors
        df_daily = pro.daily(ts_code=ts_code, start_date=start_td, end_date=end_td)
        if df_daily is None or df_daily.empty:
            return (
                f"No data found for symbol '{symbol}' "
                f"between {start_date} and {end_date}"
            )

        df_adj = pro.adj_factor(ts_code=ts_code, start_date=start_td, end_date=end_td)

        # Merge adj_factor
        if df_adj is not None and not df_adj.empty:
            # adj_factor columns: ts_code, trade_date, adj_factor
            df_daily = df_daily.merge(
                df_adj[["trade_date", "adj_factor"]],
                on="trade_date",
                how="left",
            )
            # Forward-adjust: Adj Close = close * adj_factor / latest_adj_factor
            latest_adj = df_daily["adj_factor"].iloc[0]  # newest first
            df_daily["Adj Close"] = (
                df_daily["close"] * df_daily["adj_factor"] / latest_adj
            ).round(2)
        else:
            df_daily["Adj Close"] = df_daily["close"]

        # Tushare returns newest-first → reverse to chronological
        df_daily = df_daily.sort_values("trade_date").reset_index(drop=True)

        # Volume: Tushare vol is in 手 (100 shares) → convert to shares
        df_daily["Volume"] = (df_daily["vol"] * 100).astype(int)

        # Format date
        df_daily["Date"] = df_daily["trade_date"].apply(_from_tushare_date)

        # Select & rename columns
        out = df_daily[["Date", "open", "high", "low", "close", "Adj Close", "Volume"]]
        out = out.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
        })

        csv_string = out.to_csv(index=False)

        header = f"# Stock data for {symbol} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(out)}\n"
        header += (
            f"# Data retrieved on: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving stock data for {symbol}: {e}"


# ---------------------------------------------------------------------------
# 2. get_indicators — daily_basic (PE, PB, turnover, etc.)
# ---------------------------------------------------------------------------

def get_indicators(
    symbol: Annotated[str, "ticker symbol"],
    indicator: Annotated[str, "technical indicator"],
    curr_date: Annotated[str, "current date YYYY-mm-dd"],
    look_back_days: Annotated[int, "look back days"],
) -> str:
    """Fetch daily basic indicators from Tushare Pro.

    Returns PE, PB, PS, PE_TTM, PS_TTM, DV_RATIO, turnover_rate,
    volume_ratio, total_mv, circ_mv over the look-back window.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving indicators for {symbol}: {err}"

        ts_code = _normalize_to_ts_code(symbol)
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before_dt = curr_dt - timedelta(days=look_back_days)

        start_td = _to_tushare_date(before_dt.strftime("%Y-%m-%d"))
        end_td = _to_tushare_date(curr_date)

        df = pro.daily_basic(
            ts_code=ts_code, start_date=start_td, end_date=end_td
        )
        if df is None or df.empty:
            return (
                f"No indicator data found for {symbol} "
                f"from {before_dt.strftime('%Y-%m-%d')} to {curr_date}"
            )

        # Sort chronological
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["Date"] = df["trade_date"].apply(_from_tushare_date)

        # Key fields to display
        fields = [
            "pe", "pe_ttm", "pb", "ps", "ps_ttm",
            "dv_ratio", "turnover_rate", "volume_ratio",
            "total_mv", "circ_mv",
        ]

        # Build output lines
        lines = []
        for _, row in df.iterrows():
            date_str = row["Date"]
            parts = [f"{date_str}:"]
            for f in fields:
                val = row.get(f)
                if pd.notna(val):
                    parts.append(f"  {f}={val}")
            lines.append("\n".join(parts))

        result = "\n".join(lines)

        # Description block
        desc = (
            "\n\n## Daily Basic Indicators Description\n"
            "- pe: Price-to-Earnings ratio (市盈率)\n"
            "- pe_ttm: Trailing 12-month P/E (滚动市盈率)\n"
            "- pb: Price-to-Book ratio (市净率)\n"
            "- ps: Price-to-Sales ratio (市销率)\n"
            "- ps_ttm: Trailing 12-month P/S\n"
            "- dv_ratio: Dividend yield (股息率 %)\n"
            "- turnover_rate: Turnover rate (换手率 %)\n"
            "- volume_ratio: Volume ratio (量比)\n"
            "- total_mv: Total market value (总市值, 万元)\n"
            "- circ_mv: Circulating market value (流通市值, 万元)\n"
        )

        header = (
            f"## Daily basic indicators for {symbol} "
            f"from {before_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        )

        return header + result + desc

    except Exception as e:
        return f"Error retrieving {indicator} data for {symbol}: {e}"


# ---------------------------------------------------------------------------
# 3. get_fundamentals — fina_indicator (ROE, margins, etc.)
# ---------------------------------------------------------------------------

def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Fetch financial indicators from Tushare Pro (fina_indicator).

    Returns the latest 4 quarters of ROE, gross/net profit margins, EPS, etc.
    Filters by ``ann_date <= curr_date`` when provided to prevent look-ahead.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving fundamentals for {ticker}: {err}"

        ts_code = _normalize_to_ts_code(ticker)
        df = pro.fina_indicator(ts_code=ts_code)

        if df is None or df.empty:
            return f"No fundamentals data found for {ticker}"

        # Filter by ann_date to prevent look-ahead bias
        if curr_date and "ann_date" in df.columns:
            curr_td = _to_tushare_date(curr_date)
            df = df[df["ann_date"] <= curr_td]

        if df.empty:
            return f"No fundamentals data found for {ticker} on or before {curr_date}"

        # Take latest 4 reports
        df = df.head(4).reset_index(drop=True)

        # Key columns
        keep_cols = [
            "ann_date", "end_date",
            "roe", "roe_waa",
            "grossprofit_margin", "netprofit_margin",
            "op_yoy", "dp_yoy",
            "basic_eps", "diluted_eps",
            "bps",
            "current_ratio", "quick_ratio",
            "debt_to_assets",
        ]
        # Only keep columns that exist
        cols = [c for c in keep_cols if c in df.columns]
        out = df[cols].copy()

        csv_string = out.to_csv(index=False)

        header = f"# Financial Indicators for {ticker}\n"
        header += (
            f"# Data retrieved on: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving fundamentals for {ticker}: {e}"


# ---------------------------------------------------------------------------
# 4. get_income_statement
# ---------------------------------------------------------------------------

def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "quarterly or annual"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Fetch income statement from Tushare Pro.

    Key fields: total_revenue, revenue, oper_cost, sell_exp, admin_exp,
    fin_exp, operate_profit, total_profit, n_income, basic_eps, diluted_eps.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving income statement for {ticker}: {err}"

        ts_code = _normalize_to_ts_code(ticker)
        df = pro.income(ts_code=ts_code)

        if df is None or df.empty:
            return f"No income statement data found for {ticker}"

        # Filter by ann_date to prevent look-ahead bias
        if curr_date and "ann_date" in df.columns:
            curr_td = _to_tushare_date(curr_date)
            df = df[df["ann_date"] <= curr_td]

        if df.empty:
            return (
                f"No income statement data found for {ticker} "
                f"on or before {curr_date}"
            )

        # Limit rows
        limit = 4 if freq.lower().startswith("q") else 2
        df = df.head(limit).reset_index(drop=True)

        keep_cols = [
            "ann_date", "end_date", "report_type",
            "total_revenue", "revenue", "oper_cost",
            "sell_exp", "admin_exp", "fin_exp",
            "operate_profit", "total_profit",
            "n_income", "basic_eps", "diluted_eps",
        ]
        cols = [c for c in keep_cols if c in df.columns]
        out = df[cols].copy()

        csv_string = out.to_csv(index=False)

        header = f"# Income Statement data for {ticker} ({freq})\n"
        header += (
            f"# Data retrieved on: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {e}"


# ---------------------------------------------------------------------------
# 5. get_balance_sheet
# ---------------------------------------------------------------------------

def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "quarterly or annual"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Fetch balance sheet from Tushare Pro.

    Key fields: total_assets, total_liab, total_hldr_eqy_exc_min_int,
    total_cur_assets, total_cur_liab, money_cap, accounts_receiv,
    inventories, fix_assets_total.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving balance sheet for {ticker}: {err}"

        ts_code = _normalize_to_ts_code(ticker)
        df = pro.balancesheet(ts_code=ts_code)

        if df is None or df.empty:
            return f"No balance sheet data found for {ticker}"

        # Filter by ann_date to prevent look-ahead bias
        if curr_date and "ann_date" in df.columns:
            curr_td = _to_tushare_date(curr_date)
            df = df[df["ann_date"] <= curr_td]

        if df.empty:
            return (
                f"No balance sheet data found for {ticker} "
                f"on or before {curr_date}"
            )

        # Limit rows
        limit = 4 if freq.lower().startswith("q") else 2
        df = df.head(limit).reset_index(drop=True)

        keep_cols = [
            "ann_date", "end_date", "report_type",
            "total_assets", "total_liab",
            "total_hldr_eqy_exc_min_int",
            "total_cur_assets", "total_cur_liab",
            "money_cap", "accounts_receiv",
            "inventories", "fix_assets_total",
        ]
        cols = [c for c in keep_cols if c in df.columns]
        out = df[cols].copy()

        csv_string = out.to_csv(index=False)

        header = f"# Balance Sheet data for {ticker} ({freq})\n"
        header += (
            f"# Data retrieved on: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {e}"


# ---------------------------------------------------------------------------
# 6. get_cashflow
# ---------------------------------------------------------------------------

def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "quarterly or annual"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Fetch cash flow statement from Tushare Pro.

    Key fields: netc_operate_cf, netc_invest_cf, netc_finance_cf,
    c_pay_acqu_asset, c_recv_invest_cash, n_cashflow_act,
    surplus_reserve, undistr_profit.
    """
    try:
        pro, err = _safe_api()
        if err:
            return f"Error retrieving cashflow for {ticker}: {err}"

        ts_code = _normalize_to_ts_code(ticker)
        df = pro.cashflow(ts_code=ts_code)

        if df is None or df.empty:
            return f"No cash flow data found for {ticker}"

        # Filter by ann_date to prevent look-ahead bias
        if curr_date and "ann_date" in df.columns:
            curr_td = _to_tushare_date(curr_date)
            df = df[df["ann_date"] <= curr_td]

        if df.empty:
            return (
                f"No cash flow data found for {ticker} "
                f"on or before {curr_date}"
            )

        # Limit rows
        limit = 4 if freq.lower().startswith("q") else 2
        df = df.head(limit).reset_index(drop=True)

        keep_cols = [
            "ann_date", "end_date", "report_type",
            "netc_operate_cf", "netc_invest_cf", "netc_finance_cf",
            "c_pay_acqu_asset", "c_recv_invest_cash",
            "n_cashflow_act",
            "surplus_reserve", "undistr_profit",
        ]
        cols = [c for c in keep_cols if c in df.columns]
        out = df[cols].copy()

        csv_string = out.to_csv(index=False)

        header = f"# Cash Flow data for {ticker} ({freq})\n"
        header += (
            f"# Data retrieved on: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving cashflow for {ticker}: {e}"
