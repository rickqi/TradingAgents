"""Run TradingAgents analysis on a single stock to generate AI signals.

Usage:
    D:\codes\stock\TradingAgents\.venv\Scripts\python.exe test_single_analysis.py 688041.SH 2026-05-08
"""
import sys
import os
import time

# Fix encoding on Windows
import io
for attr in ("stdout", "stderr"):
    stream = getattr(sys, attr)
    if stream and getattr(stream, "encoding", "") != "utf-8":
        try:
            setattr(sys, attr, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
        except (AttributeError, ValueError):
            pass

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.qlib.signal_extractor import extract_from_state


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "688041.SH"
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-05-08"

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "deepseek"
    config["deep_think_llm"] = "deepseek-v4-flash"
    config["quick_think_llm"] = "deepseek-v4-flash"
    config["data_vendors"] = {
        "core_stock_apis": "tencent_sina",
        "technical_indicators": "tencent_sina",
        "fundamental_data": "tencent_sina,akshare",
        "news_data": "tencent_sina",
        "sentiment_data": "akshare",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"

    print(f"Initializing TradingAgentsGraph (deepseek)...")
    ta = TradingAgentsGraph(debug=False, config=config)

    print(f"Analyzing {ticker} on {date}...")
    start = time.time()
    state, decision = ta.propagate(ticker, date)
    elapsed = time.time() - start
    print(f"Decision: {decision} [{elapsed:.0f}s]")

    signals = extract_from_state(state)
    print(f"Signals:")
    print(f"  ai_score: {signals['ai_score']}")
    print(f"  trader_action: {signals['trader_action']}")
    print(f"  research_rating: {signals['research_rating']}")
    print(f"  price_target: {signals.get('price_target', 'N/A')}")
    print(f"  symbol: {signals['symbol']}")
    print(f"  date: {signals['date']}")


if __name__ == "__main__":
    main()
