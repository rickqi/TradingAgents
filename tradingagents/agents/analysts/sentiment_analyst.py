"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

The agent does not use tool-calling; the data is in the prompt from
turn 0. The LLM produces the sentiment report in a single invocation.

See: https://github.com/TauricResearch/TradingAgents/issues/557
"""

from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.guba_vendor import fetch_guba_sentiment
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _is_ashare_ticker(ticker: str) -> bool:
    """Quick check if ticker looks like a Chinese A-share or HK stock."""
    t = str(ticker).strip().strip('"').strip("'").strip().lower()
    for part in t.split(","):
        part = part.strip()
        if not part:
            continue
        for prefix in ("sh", "sz", "hk"):
            if part.startswith(prefix):
                part = part[len(prefix):]
                break
        for suffix in (".sz", ".ss", ".sh", ".hk"):
            if part.endswith(suffix):
                part = part[: -len(suffix)]
                break
        if len(part) == 6 and part.isdigit():
            return True
        if 4 <= len(part) <= 5 and part.isdigit():
            return True
    return False


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a sentiment report in a
    single LLM call.
    """

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = build_instrument_context(ticker)

        # Pre-fetch data sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)

        # A-share: use East Money social sentiment (not GFW-blocked)
        is_ashare = _is_ashare_ticker(ticker)
        if is_ashare:
            stocktwits_block = fetch_guba_sentiment(ticker)
            reddit_block = "<Reddit/StockTwits skipped: not available for A-share tickers>"
        else:
            stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
            reddit_block = fetch_reddit_posts(ticker)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
            is_ashare=is_ashare,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # No bind_tools — the data is already in the prompt; a single LLM
        # call produces the report directly.
        chain = prompt | llm
        result = chain.invoke(state["messages"])

        return {
            "messages": [result],
            "sentiment_report": result.content,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    is_ashare: bool = False,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    if is_ashare:
        return _build_ashare_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )
    return _build_western_system_message(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        news_block=news_block,
        stocktwits_block=stocktwits_block,
        reddit_block=reddit_block,
    )


def _build_western_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — r/wallstreetbets, r/stocks, r/investing (past 7 days)
Community discussion. Engagement signal via upvote score and comment count. Subreddit character matters (r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight Reddit posts by engagement.** A 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this caveat explicitly. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output

Produce a sentiment report covering, in order:

1. **Overall sentiment direction** — Bullish / Bearish / Neutral / Mixed — with a brief confidence note based on data quality and sample size.
2. **Source-by-source breakdown** — what each of news / StockTwits / Reddit is telling you, with specific evidence (cite message counts, ratios, notable posts).
3. **Divergences, alignments, and key narratives** across sources.
4. **Catalysts and risks** surfaced by the data.
5. **Markdown table** at the end summarizing key sentiment signals, their direction, source, and supporting evidence.

    {get_language_instruction()}"""


def _build_ashare_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Assemble the sentiment-analyst system message for A-share tickers.

    Uses East Money (东方财富) quantitative sentiment indicators instead of
    Reddit/StockTwits (which are GFW-blocked and have no A-share content).
    """
    return f"""You are a financial market sentiment analyst for Chinese A-share stocks. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on news and East Money quantitative sentiment data that has already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### 东方财富社交情绪指标 — East Money quantitative sentiment
Quantitative sentiment indicators from East Money's stock comment system. Includes:
- 综合得分 (composite score), 关注指数 (attention index), 机构参与度 (institutional participation)
- 参与意愿 (participation desire) with 5-day moving average and change rate
- Score trend and institutional participation trend over recent 30 days

Read the composite score and attention index as gauges of retail/institutional interest:
- 综合得分 > 70: strong positive sentiment; < 40: bearish
- 关注指数 > 80: high retail attention (potential contrarian warning if score is extreme)
- 参与意愿 rising rapidly + 关注指数 high: momentum play, watch for exhaustion
- 机构参与度 > 50: institutional money active (more reliable signal)

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### A股社交情绪详情
Additional A-share sentiment data including score trends and institutional participation trends.
Use these time-series to identify sentiment shifts and momentum changes.

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices for A-share)

1. **Read the composite score (综合评分) as the primary sentiment gauge.** Scores above 70 indicate broad optimism; below 40 indicate pessimism. Track the score trend — a declining composite score from 75→65→55 signals deteriorating sentiment even if still nominally positive.

2. **Interpret the attention index (关注指数) as a crowd-signal.** Very high attention (>80) combined with extreme scores (either direction) often signals crowded positioning and contrarian risk. Low attention with strong scores is a quieter, potentially more reliable signal.

3. **Track participation desire (参与意愿) changes for momentum signals.** Rapid increases in 参与意愿 combined with rising 关注指数 indicate growing retail FOMO — often a late-cycle signal. Declining 参与意愿 after a peak suggests exhaustion.

4. **Weight institutional participation (机构参与度) more heavily than retail signals.** 机构参与度 > 50 means institutional money is actively involved — a more reliable and persistent signal than retail attention alone. Track the trend: rising institutional participation is constructive; declining suggests smart money is exiting.

5. **Cross-reference news with sentiment data.** If news is bearish but composite score remains high, sentiment may not have caught up. Conversely, strong news + low scores = potential mispricing opportunity.

6. **Use the time-series trends to identify inflection points.** A sudden drop in composite score combined with rising 关注指数 is a classic sentiment reversal pattern. Conversely, a score recovery on declining attention may be a stealth turnaround.

7. **Be honest about data limits.** If any East Money data returned "<unavailable>" or placeholder text, flag this explicitly and reduce confidence accordingly.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output

Produce a sentiment report covering, in order:

1. **Overall sentiment direction** — Bullish / Bearish / Neutral / Mixed — with a brief confidence note based on data quality.
2. **Source-by-source breakdown** — what the news and each East Money indicator (综合评分, 关注指数, 参与意愿, 机构参与度) is telling you, with specific values and trends.
3. **Sentiment inflection points and momentum changes** — identify any notable shifts in the time-series data.
4. **Divergences** between news framing and quantitative sentiment indicators.
5. **Catalysts and risks** surfaced by the data.
6. **Markdown table** at the end summarizing key sentiment signals, their direction, source, and supporting evidence.

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
