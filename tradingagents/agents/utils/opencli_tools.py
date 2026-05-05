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
    symbol: Annotated[str, "stock symbol filter (empty string for all stocks)"] = "",
    limit: Annotated[int, "number of results to return"] = 10,
) -> str:
    """Retrieve main force capital flow rankings (主力资金净流入排行) via OpenCLI eastmoney.

    Shows which stocks have the largest net capital inflows from institutional
    and main force traders. Useful for understanding smart money movement.

    Args:
        symbol: Optional stock symbol to filter (empty for all stocks).
        limit: Number of top results to return.

    Returns:
        Formatted capital flow data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip money flow data"

    from tradingagents.dataflows.opencli_vendor import get_money_flow as _get_money_flow
    return _get_money_flow(symbol=symbol, limit=limit)


@tool
def get_sectors(
    sector_type: Annotated[str, "sector type: industry, concept, or area"] = "industry",
    limit: Annotated[int, "number of results to return"] = 10,
) -> str:
    """Retrieve sector rankings (板块排行) via OpenCLI eastmoney.

    Shows top-performing sectors by change percentage, useful for
    identifying sector rotation and thematic trends.

    Args:
        sector_type: Type of sector classification (industry, concept, area).
        limit: Number of top sectors to return.

    Returns:
        Formatted sector ranking data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip sector data"

    from tradingagents.dataflows.opencli_vendor import get_sectors as _get_sectors
    return _get_sectors(sector_type=sector_type, limit=limit)


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
def get_longhu() -> str:
    """Retrieve Dragon-Tiger list (龙虎榜) via OpenCLI eastmoney.

    Shows stocks with unusual trading activity (large buy/sell orders from
    institutional seats). Important for detecting institutional interest
    and unusual market activity.

    Returns:
        Formatted Dragon-Tiger list data or error message.
    """
    if not _check_opencli_available():
        return "OpenCLI not available — skip Dragon-Tiger list data"

    from tradingagents.dataflows.opencli_vendor import get_longhu as _get_longhu
    return _get_longhu()


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
