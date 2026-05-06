"""OpenCLI-based tools for extended market data.

Provides LangChain @tool functions that wrap opencli vendor functions.
Each tool gracefully degrades when opencli is not installed.
"""

import shutil
from typing import Annotated

from langchain_core.tools import tool


def _check_opencli_available() -> bool:
    """Check if opencli binary is available in PATH."""
    return shutil.which("opencli") is not None


@tool
def get_money_flow(
    limit: Annotated[int, "number of results to return"] = 10,
) -> str:
    """Retrieve main force capital flow rankings (主力资金净流入排行) via OpenCLI eastmoney.

    Shows which stocks have the largest net capital inflows from institutional
    and main force traders. Useful for understanding smart money movement.
    Note: This is a market-wide ranking — individual stock filtering is not supported.

    Args:
        limit: Number of top results to return.

    Returns:
        Formatted capital flow data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip money flow data"

    from tradingagents.dataflows.opencli_vendor import get_money_flow as _get_money_flow
    return _get_money_flow(limit=limit)


@tool
def get_sectors(
    sector_type: Annotated[str, "sector type: industry, concept, or region"] = "industry",
    limit: Annotated[int, "number of results to return"] = 10,
    sort_by: Annotated[str, "sort field: changePercent, turnover, volume, amount, rise, fall"] = "changePercent",
) -> str:
    """Retrieve sector rankings (板块排行) via OpenCLI eastmoney.

    Shows top-performing sectors, useful for identifying sector rotation
    and thematic trends.

    Args:
        sector_type: Type of sector classification (industry, concept, region).
        limit: Number of top sectors to return.
        sort_by: Field to sort by (changePercent, turnover, volume, amount, rise, fall).

    Returns:
        Formatted sector ranking data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip sector data"

    from tradingagents.dataflows.opencli_vendor import get_sectors as _get_sectors
    return _get_sectors(sector_type=sector_type, limit=limit, sort_by=sort_by)


@tool
def get_northbound(
    market: Annotated[str, "market: sh (Shanghai) or sz (Shenzhen)"] = "sh",
) -> str:
    """Retrieve northbound capital flow data (沪深港通北向资金) via OpenCLI eastmoney.

    Shows real-time northbound (Hong Kong → Mainland) capital flow,
    a key indicator of foreign investor sentiment toward A-shares.

    Args:
        market: Target market — sh for Shanghai, sz for Shenzhen.

    Returns:
        Formatted northbound capital flow data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip northbound data"

    from tradingagents.dataflows.opencli_vendor import get_northbound as _get_northbound
    return _get_northbound(market=market)


@tool
def get_longhu(
    symbol: Annotated[str, "optional stock symbol filter (empty for all)"] = "",
) -> str:
    """Retrieve Dragon-Tiger list (龙虎榜) via OpenCLI eastmoney.

    Shows stocks with unusual trading activity (large buy/sell orders from
    institutional seats). Important for detecting institutional interest
    and unusual market activity. Optionally filter by stock symbol.

    Args:
        symbol: Optional stock symbol to filter (empty for all stocks).

    Returns:
        Formatted Dragon-Tiger list data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip Dragon-Tiger list data"

    from tradingagents.dataflows.opencli_vendor import get_longhu as _get_longhu
    return _get_longhu(symbol=symbol)


@tool
def get_hot_rank(
    limit: Annotated[int, "number of results to return"] = 20,
) -> str:
    """Retrieve hot stock search rankings (人气热搜排行) via OpenCLI tdx.

    Shows the most searched/watched stocks by retail investors.
    NOTE: May require browser bridge cookie for authentication.

    Args:
        limit: Number of top hot stocks to return.

    Returns:
        Formatted hot stock ranking data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip hot rank data"

    from tradingagents.dataflows.opencli_vendor import get_hot_rank as _get_hot_rank
    return _get_hot_rank(limit=limit)


@tool
def get_quote(
    symbols: Annotated[str, "stock symbols, comma-separated (e.g. '600519,000858')"] = "",
) -> str:
    """Retrieve real-time stock quotes (实时行情) via OpenCLI eastmoney.

    Provides 16 data points including PE, PB, market cap, turnover rate,
    and amplitude — key metrics NOT available from basic OHLCV data.

    Args:
        symbols: Comma-separated stock symbols (e.g. '600519,000858').

    Returns:
        Formatted real-time quote data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip quote data"

    from tradingagents.dataflows.opencli_vendor import get_quote as _get_quote
    return _get_quote(symbols=symbols)


@tool
def get_kline(
    symbol: Annotated[str, "stock symbol"] = "600519",
    period: Annotated[str, "period: day, week, month, 5m, 15m, 30m, 60m"] = "day",
    adjust: Annotated[str, "adjustment: none, forward, backward"] = "forward",
    limit: Annotated[int, "number of bars"] = 30,
) -> str:
    """Retrieve K-line historical data (K线历史) via OpenCLI eastmoney.

    Supports multiple periods (daily/weekly/monthly/intraday) and price
    adjustments (forward/backward/none). Complements get_stock_data with
    more granular time period options.

    Args:
        symbol: Stock symbol (e.g. 600519).
        period: K-line period (day, week, month, 5m, 15m, 30m, 60m).
        adjust: Price adjustment (none, forward, backward).
        limit: Number of K-line bars to return.

    Returns:
        Formatted K-line data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip kline data"

    from tradingagents.dataflows.opencli_vendor import get_kline as _get_kline
    return _get_kline(symbol=symbol, period=period, adjust=adjust, limit=limit)


@tool
def get_holders(
    symbol: Annotated[str, "A-share stock code"] = "600519",
    limit: Annotated[int, "number of top holders"] = 10,
) -> str:
    """Retrieve top 10 institutional holders (十大流通股东) via OpenCLI eastmoney.

    Shows which institutions hold the largest positions and whether they're
    increasing or decreasing holdings. Important for understanding institutional
    conviction and potential supply/demand pressure.

    Args:
        symbol: A-share stock code (e.g. 600519).
        limit: Number of top holders to return.

    Returns:
        Formatted holders data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip holders data"

    from tradingagents.dataflows.opencli_vendor import get_holders as _get_holders
    return _get_holders(symbol=symbol, limit=limit)


@tool
def get_announcement(
    market: Annotated[str, "exchange: SHA, SZA, BJA (comma-separated)"] = "SHA,SZA",
    limit: Annotated[int, "number of announcements"] = 20,
) -> str:
    """Retrieve company announcements (上市公司公告) via OpenCLI eastmoney.

    Official exchange disclosures including earnings reports, material events,
    and regulatory filings. Essential for event-driven analysis.

    Args:
        market: Exchange filter, comma-separated (SHA, SZA, BJA).
        limit: Number of announcements to return.

    Returns:
        Formatted announcement data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip announcement data"

    from tradingagents.dataflows.opencli_vendor import get_announcement as _get_announcement
    return _get_announcement(market=market, limit=limit)


@tool
def get_index_board(
    group: Annotated[str, "index group: main, hk, us, all"] = "main",
) -> str:
    """Retrieve major market index board (主要市场指数) via OpenCLI eastmoney.

    Shows key indices (CSI 300, SSE 50, Hang Seng, S&P 500 etc.) with
    real-time performance. Provides market context for individual stock analysis.

    Args:
        group: Index group (main for A-share major, hk, us, all).

    Returns:
        Formatted index board data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip index board data"

    from tradingagents.dataflows.opencli_vendor import get_index_board as _get_index_board
    return _get_index_board(group=group)


@tool
def get_kuaixun(
    column: Annotated[str, "channel: 102 (important), 101 (all)"] = "102",
    limit: Annotated[int, "number of items"] = 20,
) -> str:
    """Retrieve 7x24 financial news flashes (财经快讯) via OpenCLI eastmoney.

    Real-time financial news stream covering market-moving events.
    Useful for capturing intraday developments that may affect trading decisions.

    Args:
        column: Channel ID (102 for important news, 101 for all).
        limit: Number of news items to return.

    Returns:
        Formatted financial news flash data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip kuaixun data"

    from tradingagents.dataflows.opencli_vendor import get_kuaixun as _get_kuaixun
    return _get_kuaixun(column=column, limit=limit)
