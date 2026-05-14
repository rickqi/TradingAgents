"""AKShare-based A-stock extended data tools.

Provides LangChain @tool functions that wrap astock_vendor functions.
Each tool gracefully degrades when akshare or requests is not installed.
"""

from typing import Annotated

from langchain_core.tools import tool


def _check_astock_available() -> bool:
    """Check if akshare and requests are importable."""
    try:
        import akshare  # noqa: F401
        import requests  # noqa: F401
        return True
    except ImportError:
        return False


@tool
def get_research_reports(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
    max_pages: Annotated[int, "maximum number of report pages to fetch"] = 3,
) -> str:
    """Retrieve research reports list with ratings and EPS forecasts (研报评级与盈利预测).

    Fetches analyst research reports covering the target stock, including
    institutional ratings (buy/neutral/sell), target prices, and EPS forecasts.
    Useful for understanding Wall Street consensus and professional analyst views.

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).
        max_pages: Maximum number of report pages to fetch (default 3).

    Returns:
        Formatted research report data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip research reports data"

    from tradingagents.dataflows.astock_vendor import get_research_reports as _get_research_reports
    return _get_research_reports(code=symbol, max_pages=max_pages)


@tool
def get_consensus_eps(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
) -> str:
    """Retrieve institutional consensus EPS estimates (机构一致预期EPS).

    Shows consensus earnings-per-share forecasts from multiple brokerages
    for the current and upcoming fiscal years. Key input for valuation
    models (forward PE, PEG ratio).

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).

    Returns:
        Formatted consensus EPS data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip consensus EPS data"

    from tradingagents.dataflows.astock_vendor import get_consensus_eps as _get_consensus_eps
    return _get_consensus_eps(code=symbol)


@tool
def get_hot_stocks_with_reasons(
    date: Annotated[str, "trade date in YYYYMMDD format (e.g. 20260515)"] = "",
) -> str:
    """Retrieve strong-performing stocks with editorial reason tags (强势股题材归因).

    Shows stocks with unusual strength along with attributed reasons
    (sector rotation, policy catalyst, earnings surprise, etc.).
    Useful for thematic investing and identifying market narrative drivers.

    Args:
        date: Trade date in YYYYMMDD format. Empty string defaults to latest available.

    Returns:
        Formatted hot stocks with reason tags or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip hot stocks with reasons data"

    from tradingagents.dataflows.astock_vendor import get_hot_stocks_with_reasons as _get_hot_stocks_with_reasons
    return _get_hot_stocks_with_reasons(date=date)


@tool
def get_concept_blocks(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
) -> str:
    """Retrieve Baidu concept/industry/region classification for a stock (百度概念板块分类).

    Shows which concept themes (题材概念), industry sectors, and geographic
    regions a stock belongs to. Essential for peer comparison and thematic
    analysis (e.g. identifying all stocks in the same AI or EV theme).

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).

    Returns:
        Formatted concept/industry/region classification or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip concept blocks data"

    from tradingagents.dataflows.astock_vendor import get_concept_blocks as _get_concept_blocks
    return _get_concept_blocks(code=symbol)


@tool
def get_fund_flow(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
    date: Annotated[str, "trade date in YYYYMMDD format (e.g. 20260515)"] = "",
) -> str:
    """Retrieve individual stock fund flow data (个股资金流向).

    Shows breakdown of capital flow into main force (主力资金) vs retail
    (散户资金), including super-large, large, medium, and small order flow.
    Key indicator for detecting institutional accumulation or distribution.

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).
        date: Trade date in YYYYMMDD format. Empty string defaults to latest available.

    Returns:
        Formatted fund flow data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip fund flow data"

    from tradingagents.dataflows.astock_vendor import get_fund_flow as _get_fund_flow
    return _get_fund_flow(code=symbol, date=date if date else None)


@tool
def get_dragon_tiger_detail(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
    trade_date: Annotated[str, "reference trade date in YYYYMMDD format"] = "",
    look_back: Annotated[int, "number of trading days to look back"] = 5,
) -> str:
    """Retrieve Dragon-Tiger board details with broker seats (龙虎榜明细席位).

    Shows detailed buy/sell data from specific broker seats (营业部席位)
    on the Dragon-Tiger board. Reveals which institutional or hot-money
    desks are active in the stock. Critical for tracking smart-money activity.

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).
        trade_date: Reference trade date in YYYYMMDD format. Empty string for latest.
        look_back: Number of trading days to look back (default 5).

    Returns:
        Formatted Dragon-Tiger seat detail data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip Dragon-Tiger detail data"

    from tradingagents.dataflows.astock_vendor import get_dragon_tiger_detail as _get_dragon_tiger_detail
    return _get_dragon_tiger_detail(code=symbol, trade_date=trade_date, look_back=look_back)


@tool
def get_lockup_expiry(
    symbol: Annotated[str, "6-digit A-share stock code (e.g. 000858, 600519)"],
    trade_date: Annotated[str, "reference trade date in YYYYMMDD format"] = "",
    forward_days: Annotated[int, "number of calendar days to look forward"] = 90,
) -> str:
    """Retrieve lockup/share-restriction expiry calendar (限售解禁日历).

    Shows upcoming lockup expiry dates and the number of shares being
    released. Large lockup expiries can create significant selling pressure.
    Essential risk factor for recently IPO'd or restructured stocks.

    Args:
        symbol: 6-digit A-share stock code (e.g. 000858, 600519).
        trade_date: Reference trade date in YYYYMMDD format. Empty string for today.
        forward_days: Number of calendar days to look forward (default 90).

    Returns:
        Formatted lockup expiry data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip lockup expiry data"

    from tradingagents.dataflows.astock_vendor import get_lockup_expiry as _get_lockup_expiry
    return _get_lockup_expiry(code=symbol, trade_date=trade_date, forward_days=forward_days)


@tool
def get_industry_ranking(
    top_n: Annotated[int, "number of top/bottom industries to show"] = 10,
) -> str:
    """Retrieve industry sector rankings across ~90 sectors (行业板块涨跌幅排名).

    Shows performance rankings for all ~90 Shenwan industry sectors,
    sorted by daily change. Useful for sector rotation analysis and
    identifying the strongest/weakest industry groups.

    Args:
        top_n: Number of top and bottom industries to show (default 10).

    Returns:
        Formatted industry ranking data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip industry ranking data"

    from tradingagents.dataflows.astock_vendor import get_industry_ranking as _get_industry_ranking
    return _get_industry_ranking(top_n=top_n)


@tool
def get_northbound_realtime() -> str:
    """Retrieve northbound capital real-time flow data (北向资金实时流向).

    Shows real-time net inflow/outflow of northbound capital (Hong Kong
    and foreign investors buying A-shares via Stock Connect). A key
    sentiment indicator — heavy northbound buying often signals foreign
    institutional conviction.

    Returns:
        Formatted northbound real-time flow data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip northbound realtime data"

    from tradingagents.dataflows.astock_vendor import get_northbound_realtime as _get_northbound_realtime
    return _get_northbound_realtime()


@tool
def get_full_market_dragon_tiger(
    trade_date: Annotated[str, "trade date in YYYYMMDD format (e.g. 20260515)"] = "",
) -> str:
    """Retrieve full market Dragon-Tiger board for a given date (全市场龙虎榜).

    Shows all stocks that appeared on the Dragon-Tiger board (龙虎榜) for
    the specified date, along with buy/sell amounts and net values.
    Useful for market-wide unusual activity screening.

    Args:
        trade_date: Trade date in YYYYMMDD format. Empty string defaults to latest.

    Returns:
        Formatted full market Dragon-Tiger data or skip message.
    """
    if not _check_astock_available():
        return "akshare/requests not available — skip full market Dragon-Tiger data"

    from tradingagents.dataflows.astock_vendor import get_full_market_dragon_tiger as _get_full_market_dragon_tiger
    return _get_full_market_dragon_tiger(trade_date=trade_date)
