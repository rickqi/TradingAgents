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
    return route_to_vendor("get_sentiment", ticker)
