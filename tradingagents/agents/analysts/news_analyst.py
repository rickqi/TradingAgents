import shutil
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.config import get_config


def _is_chinese_ticker(ticker: str) -> bool:
    """Return True if ticker looks like an A-share or HK stock code."""
    t = str(ticker).strip().lower()
    for suffix in (".sz", ".sh", ".ss", ".hk"):
        if t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    return t.isdigit() and 4 <= len(t) <= 6


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
        ]

        # Add OpenCLI tools for A-share tickers
        if shutil.which("opencli") and _is_chinese_ticker(state["company_of_interest"]):
            from tradingagents.agents.utils.opencli_tools import get_announcement, get_kuaixun
            tools.extend([get_announcement, get_kuaixun])

        # Add a-stock-data dragon tiger tool for A-share tickers
        if _is_chinese_ticker(state["company_of_interest"]):
            try:
                from tradingagents.agents.utils.astock_tools import get_dragon_tiger_detail
                tools.append(get_dragon_tiger_detail)
            except ImportError:
                pass

        opencli_guidance = ""
        if shutil.which("opencli") and _is_chinese_ticker(state["company_of_interest"]):
            opencli_guidance = " When analyzing A-share stocks, you may also use `get_announcement(market, limit)` for official company announcements and `get_kuaixun(column, limit)` for real-time financial news flashes."

        astock_guidance = ""
        if _is_chinese_ticker(state["company_of_interest"]):
            astock_guidance = (
                " You also have access to `get_dragon_tiger_detail(symbol, trade_date, look_back)` for Dragon-Tiger board (龙虎榜) data — "
                "shows unusual institutional trading activity with buy/sell seat details and institution statistics. "
                "Use this to detect institutional interest in the stock."
            )

        system_message = (
            "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(ticker, start_date, end_date) for company-specific news (you MUST pass the exact ticker symbol as the first argument, never a company name or industry keyword), and get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
        + opencli_guidance
        + astock_guidance
        + get_language_instruction(),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
