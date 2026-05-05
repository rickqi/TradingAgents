from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.sentiment_tools import (
    get_sentiment,
)
from tradingagents.agents.utils.opencli_tools import (
    get_money_flow,
    get_sectors,
    get_northbound,
    get_longhu,
    get_hot_rank,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "CRITICAL: Use this exact ticker string as the first argument in EVERY tool call "
        "(get_news, get_fundamentals, get_stock_data, etc.). "
        "Never substitute the ticker with a company name, industry keyword, concept, "
        "or any translated text. For example, if the ticker is `002876.SZ`, you MUST "
        "call get_news(`002876.SZ`, ...) — NOT get_news('偏光片', ...) or get_news('polarizer', ...). "
        "Preserving any exchange suffix (e.g. `.SZ`, `.SH`, `.TO`, `.HK`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
