#!/usr/bin/env python3
"""Run TradingAgents pipeline for a Chinese A-share stock using tencent_sina vendor."""
import sys
import io

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-chat"
config["quick_think_llm"] = "deepseek-chat"
config["data_vendors"] = {
    "core_stock_apis": "tencent_sina",
    "technical_indicators": "tencent_sina",
    "fundamental_data": "tencent_sina",
    "news_data": "tencent_sina",
}
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["output_language"] = "Chinese"

print("Initializing TradingAgentsGraph with tencent_sina vendor...")
ta = TradingAgentsGraph(debug=True, config=config)

ticker = sys.argv[1] if len(sys.argv) > 1 else "300308"
date = sys.argv[2] if len(sys.argv) > 2 else "2026-04-30"

print(f"Starting propagate for {ticker} on {date}...")
state, decision = ta.propagate(ticker, date)

print()
print("=" * 60)
print(f"FINAL DECISION for {ticker}:")
print("=" * 60)
print(decision)

# Convert any generated MD reports to Word format
try:
    import os
    from tradingagents.utils.report_converter import convert_all_md_in_dir
    results_dir = os.path.join(config.get("results_dir", os.path.expanduser("~/.tradingagents/logs")), ticker, date)
    reports_dir = os.path.join(results_dir, "reports")
    if os.path.isdir(reports_dir):
        converted = convert_all_md_in_dir(reports_dir)
        if converted:
            print(f"\nConverted {len(converted)} report(s) to Word format in {reports_dir}")
except Exception:
    pass
