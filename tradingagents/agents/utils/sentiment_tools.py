"""Sentiment data tools for LangGraph agent tool nodes."""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_sentiment(
    ticker: Annotated[str, "Ticker symbol of the company"],
) -> str:
    """
    Retrieve market sentiment and social data for a given stock ticker.
    Uses the configured sentiment_data vendor (akshare).
    Args:
        ticker (str): Ticker symbol
    Returns:
        str: A formatted string containing sentiment scores and market commentary
    """
    # Check if ticker looks like A-share/HK (numeric code)
    t_clean = ticker.strip().upper()
    for suffix in ('.SZ', '.SH', '.SS', '.HK'):
        if t_clean.endswith(suffix):
            t_clean = t_clean[:-len(suffix)]
            break
    if not (t_clean.isdigit() and len(t_clean) >= 4):
        return f"Sentiment data is only available for A-share (Chinese) stocks. Ticker '{ticker}' is not an A-share stock."

    return route_to_vendor("get_sentiment", ticker)
