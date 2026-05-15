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

# Load shared stock config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "scripts"))
from stocks_config import STOCKS, STOCK_NAMES, ANALYSIS_DATE as DATE
_DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_20_results.json")


def build_config(model=None, debate_rounds=1):
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "deepseek"
    model_name = model or "deepseek-v4-flash"
    config["deep_think_llm"] = model_name
    config["quick_think_llm"] = model_name
    config["data_vendors"] = {
        "core_stock_apis": "tencent_sina",
        "technical_indicators": "tencent_sina",
        "fundamental_data": "tencent_sina,akshare",
        "news_data": "tencent_sina",
        "sentiment_data": "akshare",
    }
    config["max_debate_rounds"] = debate_rounds
    config["max_risk_discuss_rounds"] = debate_rounds
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


def completed_tickers(results, target_date=None):
    """Return set of tickers already completed. If target_date given, only count results matching that date."""
    if target_date:
        return {r["ticker"] for r in results
                if not r.get("error") and r.get("date") == target_date}
    return {r["ticker"] for r in results if not r.get("error")}


def main():
    parser = argparse.ArgumentParser(description="Batch analyze 20 stocks with TradingAgents")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N stocks (0-based)")
    parser.add_argument("--only", nargs="+", help="Only analyze these tickers")
    parser.add_argument("--date", default=DATE, help="Analysis date")
    parser.add_argument("--output", default=None, help="Custom results file path (default: batch_20_results.json)")
    parser.add_argument("--analysts", default=None,
        help="Comma-separated analyst list: market,social,news,fundamentals (default: all)")
    parser.add_argument("--model", default=None,
        help="Override LLM model for both deep and quick thinking (default: deepseek-v4-flash)")
    parser.add_argument("--debate-rounds", type=int, default=1,
        help="Number of research and risk debate rounds (default: 1)")
    args = parser.parse_args()

    # Determine stock list
    if args.only:
        stocks = [s for s in STOCKS if s in args.only]
    else:
        stocks = STOCKS[args.start_from:]

    results_file = args.output or _DEFAULT_RESULTS

    # Determine analyst selection
    selected_analysts = (
        [a.strip() for a in args.analysts.split(",") if a.strip()]
        if args.analysts
        else ["market", "social", "news", "fundamentals"]
    )
    model_display = args.model or "deepseek-v4-flash"

    print(f"{'=' * 60}")
    print(f"TradingAgents Batch Analysis")
    print(f"  Stocks: {len(stocks)}")
    print(f"  Date: {args.date}")
    print(f"  LLM: {model_display}")
    print(f"  Analysts: {', '.join(selected_analysts)}")
    print(f"  Debate rounds: {args.debate_rounds}")
    print(f"  Results: {results_file}")
    print(f"{'=' * 60}")

    config = build_config(model=args.model, debate_rounds=args.debate_rounds)
    print("Initializing TradingAgentsGraph...")
    ta = TradingAgentsGraph(selected_analysts=selected_analysts, debug=False, config=config)

    # Load results from the specified file
    p = Path(results_file)
    results = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    done = completed_tickers(results, target_date=args.date)
    print(f"Previously completed for {args.date}: {len(done)} stocks")

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

        # ETA progress
        done_count = sum(1 for r in results if not r.get("error"))
        err_count = sum(1 for r in results if r.get("error"))
        total_done = done_count + err_count
        if total_done > 0:
            elapsed_total = time.time() - total_start
            avg_s = elapsed_total / total_done
            remaining = (len(stocks) - total_done) * avg_s
            print(f"  Progress: {total_done}/{len(stocks)} | "
                  f"Avg: {avg_s:.0f}s/stock | "
                  f"ETA: {remaining/60:.1f}min remaining")

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
