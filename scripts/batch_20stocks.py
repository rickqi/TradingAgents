"""Batch analyze 20 target stocks with TradingAgents to generate AI signals.

This script runs TradingAgents propagate() for each stock sequentially,
generating full_states_log JSON files that predict_fused.py can consume.

Usage:
    cd D:\codes\stock\TradingAgents\scripts
    ..\.venv\Scripts\python.exe batch_20stocks.py
    ..\.venv\Scripts\python.exe batch_20stocks.py --start-from 1
    ..\.venv\Scripts\python.exe batch_20stocks.py --only 688256.SH 688012.SH
"""
import sys
import os
import io
import time
import json
import argparse
from pathlib import Path
from datetime import datetime

# Fix Windows UTF-8 encoding
for attr in ("stdout", "stderr"):
    stream = getattr(sys, attr)
    if stream and getattr(stream, "encoding", "") != "utf-8":
        try:
            setattr(sys, attr, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
        except (AttributeError, ValueError):
            pass

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.qlib.signal_extractor import extract_from_state

# ── 20 target stocks ──
STOCKS = [
    "688041.SH", "688256.SH", "688012.SH", "603986.SH", "688008.SH",
    "300442.SZ", "603019.SH", "688111.SH", "002230.SZ", "002837.SZ",
    "002049.SZ", "688027.SH", "300223.SZ", "301269.SZ", "002747.SZ",
    "688332.SH", "002896.SZ", "688568.SH", "300672.SZ", "300458.SZ",
]

STOCK_NAMES = {
    "688041.SH": "海光信息", "688256.SH": "寒武纪", "688012.SH": "中微公司",
    "603986.SH": "兆易创新", "688008.SH": "澜起科技", "300442.SZ": "普丽盛",
    "603019.SH": "中科曙光", "688111.SH": "金山办公", "002230.SZ": "科大讯飞",
    "002837.SZ": "英维克", "002049.SZ": "紫光国微", "688027.SH": "天合光能",
    "300223.SZ": "北京君正", "301269.SZ": "联特科技", "002747.SZ": "尚太科技",
    "688332.SH": "联影医疗", "002896.SZ": "星帅尔", "688568.SH": "中科星图",
    "300672.SZ": "国科微", "300458.SZ": "全志科技",
}

DATE = "2026-05-08"
_DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_20_results.json")


def build_config():
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
    return config


def load_results():
    p = Path(RESULTS_FILE)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def completed_tickers(results):
    return {r["ticker"] for r in results if not r.get("error")}


def main():
    parser = argparse.ArgumentParser(description="Batch analyze 20 stocks with TradingAgents")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N stocks (0-based)")
    parser.add_argument("--only", nargs="+", help="Only analyze these tickers")
    parser.add_argument("--date", default=DATE, help="Analysis date")
    parser.add_argument("--output", default=None, help="Custom results file path (default: batch_20_results.json)")
    args = parser.parse_args()

    # Determine stock list
    if args.only:
        stocks = [s for s in STOCKS if s in args.only]
    else:
        stocks = STOCKS[args.start_from:]

    results_file = args.output or _DEFAULT_RESULTS

    print(f"{'=' * 60}")
    print(f"TradingAgents Batch Analysis")
    print(f"  Stocks: {len(stocks)}")
    print(f"  Date: {args.date}")
    print(f"  LLM: deepseek-v4-flash")
    print(f"  Results: {results_file}")
    print(f"{'=' * 60}")

    config = build_config()
    print("Initializing TradingAgentsGraph...")
    ta = TradingAgentsGraph(debug=False, config=config)

    # Load results from the specified file
    p = Path(results_file)
    results = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    done = completed_tickers(results)
    print(f"Previously completed: {len(done)} stocks")

    total_start = time.time()
    errors = 0

    for idx, ticker in enumerate(stocks):
        name = STOCK_NAMES.get(ticker, "")
        label = f"{name} ({ticker})" if name else ticker

        if ticker in done:
            print(f"\n[{idx+1}/{len(stocks)}] SKIP {label} — already done")
            continue

        print(f"\n{'=' * 50}")
        print(f"[{idx+1}/{len(stocks)}] Analyzing {label} on {args.date}...")
        print(f"{'=' * 50}")

        start = time.time()
        try:
            state, decision = ta.propagate(ticker, args.date)
            elapsed = time.time() - start

            # Extract signals
            signals = extract_from_state(state)

            result = {
                "ticker": ticker,
                "name": name,
                "decision": decision,
                "date": args.date,
                "time": round(elapsed, 1),
                "error": None,
                "ai_score": signals["ai_score"],
                "trader_action": signals["trader_action"],
                "research_rating": signals["research_rating"],
                "price_target": signals.get("price_target"),
            }
            print(f">>> {label}: {decision} (ai={signals['ai_score']}, ta={signals['trader_action']}, "
                  f"rm={signals['research_rating']}) [{elapsed:.0f}s]")

        except Exception as e:
            elapsed = time.time() - start
            result = {
                "ticker": ticker,
                "name": name,
                "decision": f"ERROR: {e}",
                "date": args.date,
                "time": round(elapsed, 1),
                "error": str(e),
            }
            errors += 1
            print(f">>> {label}: ERROR - {e} [{elapsed:.0f}s]")

        results.append(result)
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"  (Saved, {len(results)} total, {errors} errors)")

    total_elapsed = time.time() - total_start
    done_now = completed_tickers(results)

    print(f"\n\n{'=' * 60}")
    print(f"BATCH COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Total time: {total_elapsed/60:.1f} minutes")
    print(f"  Completed: {len(done_now)}/{len(STOCKS)}")
    print(f"  Errors: {errors}")
    print(f"  Results: {results_file}")
    print()

    # Summary table
    print(f"{'Stock':<12} {'Name':<8} {'Decision':<12} {'AI':>3} {'TA':>3} {'RM':>3} {'Time':>6}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x.get("ai_score", 0), reverse=True):
        if not r.get("error"):
            print(f"{r['ticker']:<12} {r.get('name',''):<8} {r['decision']:<12} "
                  f"{r.get('ai_score',0):>+3d} {r.get('trader_action',0):>+3d} "
                  f"{r.get('research_rating',0):>+3d} {r.get('time',0):>5.0f}s")
        else:
            print(f"{r['ticker']:<12} {r.get('name',''):<8} {'ERROR':<12} {'':>3} {'':>3} {'':>3} {r.get('time',0):>5.0f}s")


if __name__ == "__main__":
    main()
