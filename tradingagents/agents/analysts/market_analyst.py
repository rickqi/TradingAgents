import shutil
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config

import logging
logger = logging.getLogger(__name__)


def _is_chinese_ticker(ticker: str) -> bool:
    """Return True if ticker looks like an A-share or HK stock code.

    A-share: 6-digit number (600519, 002876) optionally with .SZ/.SH/.SS suffix.
    HK:      4-5 digit number with .HK suffix (00700.HK).
    """
    t = str(ticker).strip().lower()
    for suffix in (".sz", ".sh", ".ss", ".hk"):
        if t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    return t.isdigit() and 4 <= len(t) <= 6


def _build_market_tools(include_opencli: bool = True):
    """Build the market analyst tool list.

    Args:
        include_opencli: If False, exclude OpenCLI extended market data tools
            even when opencli is installed.  Used to prevent the LLM from
            calling Chinese-market tools when analyzing non-A-share tickers.
            ToolNode (graph) always passes True so the tools remain executable.
    """
    tools = [
        get_stock_data,
        get_indicators,
    ]

    if include_opencli and shutil.which("opencli"):
        try:
            from tradingagents.agents.utils.opencli_tools import (
                get_money_flow,
                get_sectors,
                get_northbound,
                get_longhu,
                get_hot_rank,
                get_quote,
                get_kline,
                get_index_board,
                get_kuaixun,
            )
            tools.extend([
                get_money_flow, get_sectors, get_northbound, get_longhu, get_hot_rank,
                get_quote, get_kline, get_index_board, get_kuaixun,
            ])
            logger.info("OpenCLI detected — added 9 extended market data tools to Market Analyst")
        except ImportError:
            pass

    # a-stock-data tools (pure Python, always available)
    if include_opencli:
        try:
            from tradingagents.agents.utils.astock_tools import (
                get_hot_stocks_with_reasons,
                get_northbound_realtime,
                get_industry_ranking,
                get_full_market_dragon_tiger,
                get_fund_flow,
            )
            tools.extend([
                get_hot_stocks_with_reasons, get_northbound_realtime,
                get_industry_ranking, get_full_market_dragon_tiger, get_fund_flow,
            ])
            logger.info("a-stock-data — added 5 signal tools to Market Analyst")
        except ImportError:
            pass

    return tools


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        ticker = state["company_of_interest"]

        # Determine if OpenCLI tools are available for prompt tailoring.
        # Tools are always bound (ToolNode needs them for A-shares), but the
        # guidance prompt is only included for A-share/HK tickers so the LLM
        # doesn't use Chinese-market data to "infer" about US stocks.
        has_opencli = shutil.which("opencli") is not None
        is_chinese = _is_chinese_ticker(ticker)

        # For non-A-share tickers, exclude OpenCLI tools from bind_tools() so
        # the LLM cannot discover or call them.  ToolNode still has the full
        # set (via _build_market_tools(include_opencli=True) in trading_graph.py).
        tools = _build_market_tools(include_opencli=is_chinese)

        opencli_tools_guidance = ""
        if has_opencli and is_chinese:
            opencli_tools_guidance = """
**Extended Market Data (OpenCLI):** You also have access to extended market data tools that provide information NOT available from standard stock data:
- `get_money_flow(symbol, limit)`: Main force capital flow (主力资金净流入) — shows institutional smart money inflows/outflows. Use this to understand if large players are accumulating or distributing.
- `get_northbound(market)`: Northbound capital flow (北向资金) via Shanghai/Shenzhen Connect — shows foreign investor sentiment toward A-shares. Use "sh" for Shanghai or "sz" for Shenzhen.
- `get_sectors(sector_type, limit)`: Sector rankings (板块排行) — shows which industry/concept/area sectors are leading. Use to understand sector rotation and thematic trends.
- `get_longhu(symbol)`: Dragon-Tiger list (龙虎榜) — shows stocks with unusual institutional trading activity. Important for detecting seat-level institutional interest. Optionally filter by stock symbol.
- `get_hot_rank(limit)`: Hot stock rankings (人气排行) — shows most searched/watched stocks by retail investors.
- `get_quote(symbols)`: Real-time stock quotes (实时行情) with 16 metrics including PE, PB, market cap, turnover rate. Use this FIRST to get current valuation context before deeper analysis.
- `get_kline(symbol, period, adjust, limit)`: K-line historical data (K线) with configurable period (day/week/month/intraday) and price adjustment. Use for pattern analysis and trend confirmation.
- `get_index_board(group)`: Major market index board (指数行情) showing CSI 300, SSE 50, etc. Use to understand overall market direction.
- `get_kuaixun(column, limit)`: 7x24 financial news flashes (财经快讯). Use for real-time market-moving events that may affect intraday analysis.

When analyzing A-share stocks, consider using these tools AFTER getting stock data and indicators to enrich your report with capital flow and sector context. Call them if they would add meaningful insight to your analysis. Do NOT call all of them unconditionally — only call the ones relevant to the stock being analyzed."""

        astock_tools_guidance = ""
        if is_chinese:
            astock_tools_guidance = """
**a-stock-data Enhanced Signals:** You also have access to enhanced A-share signal tools:
- `get_hot_stocks_with_reasons(date)`: Today's strong stocks with editorial reason tags (题材归因) from THS editors — tells you WHY stocks are moving, not just which ones.
- `get_northbound_realtime()`: Real-time northbound capital flow (北向资金) minute-level data with local cache history — more detailed than OpenCLI version.
- `get_industry_ranking(top_n)`: ~90 THS industry sectors ranked by performance (行业横向对比) with turnover and leader stocks.
- `get_full_market_dragon_tiger(trade_date)`: All stocks on daily dragon-tiger board (全市场龙虎榜) with net buy rankings.
- `get_fund_flow(symbol, date)`: Individual stock minute-level fund flow (个股资金流向) — main force/retail/super-large order breakdown.

Use these for market context and signal enrichment when analyzing A-share stocks."""

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names. Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + opencli_tools_guidance
            + astock_tools_guidance
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
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
            "market_report": report,
        }

    return market_analyst_node
