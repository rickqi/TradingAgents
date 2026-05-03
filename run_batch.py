#!/usr/bin/env python3
"""Run TradingAgents pipeline for all target stocks sequentially."""
import sys
import io
import json
import time

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

# Stocks to analyze
stocks = [
    ("600183", "2026-04-30", "生益科技"),
    ("002371", "2026-04-30", "北方华创"),
    ("02149", "2026-04-30", "贝克微"),
    ("600941", "2026-04-30", "中国移动"),
]

print("Initializing TradingAgentsGraph...")
ta = TradingAgentsGraph(debug=False, config=config)

results = {}
for ticker, date, name in stocks:
    print(f"\n{'='*60}")
    print(f"Analyzing {name} ({ticker}) on {date}...")
    print(f"{'='*60}")
    start = time.time()
    try:
        state, decision = ta.propagate(ticker, date)
        elapsed = time.time() - start
        results[ticker] = {"name": name, "decision": decision, "time": elapsed}
        print(f"\n>>> {name} ({ticker}): {decision} [{elapsed:.0f}s]")
    except Exception as e:
        elapsed = time.time() - start
        results[ticker] = {"name": name, "decision": f"ERROR: {e}", "time": elapsed}
        print(f"\n>>> {name} ({ticker}): ERROR - {e} [{elapsed:.0f}s]")

print(f"\n\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for ticker, r in results.items():
    print(f"  {r['name']:8s} ({ticker}): {r['decision']} [{r['time']:.0f}s]")

# Save results
with open("batch_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nResults saved to batch_results.json")
