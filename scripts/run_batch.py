#!/usr/bin/env python3
"""Run TradingAgents pipeline for a batch of stocks sequentially.

Supports incremental saves and crash resume via --start-from.

Usage:
    python scripts/run_batch.py                          # default stock list
    python scripts/run_batch.py --stocks 600519.SH 300308   # custom tickers
    python scripts/run_batch.py --start-from 3            # resume from 4th stock
    python scripts/run_batch.py --file my_stocks.json     # load from JSON file
"""
import argparse
import time

from _share_config import (
    build_ashare_config, init_trading_agents,
    save_results, load_results, completed_tickers,
)

# Default stock list — 1万元冷门潜力股
DEFAULT_STOCKS = [
    ("002876.SZ", "2026-04-30", "三利谱"),
    ("000062.SZ", "2026-04-30", "深圳华强"),
    ("002602.SZ", "2026-04-30", "世纪华通"),
    ("603208.SH", "2026-04-30", "东材科技"),
    ("603298.SH", "2026-04-30", "杭叉集团"),
    ("600744.SH", "2026-04-30", "华银电力"),
    ("603633.SH", "2026-04-30", "徕木股份"),
    ("300230.SZ", "2026-04-30", "永利股份"),
    ("002507.SZ", "2026-04-30", "涪陵榨菜"),
    ("601233.SH", "2026-04-30", "桐昆股份"),
]


def main():
    import json

    parser = argparse.ArgumentParser(description="Batch-analyze stocks with TradingAgents")
    parser.add_argument("--stocks", nargs="+", help="Tickers to analyze (e.g. 600519.SH 300308)")
    parser.add_argument("--date", default="2026-04-30", help="Analysis date for --stocks mode")
    parser.add_argument("--file", help="JSON file with stock list: [[ticker, date, name], ...]")
    parser.add_argument("--provider", default="deepseek", help="LLM provider")
    parser.add_argument("--debate-rounds", type=int, default=1, help="Research debate rounds")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N stocks (0-based)")
    parser.add_argument("--results-file", default="batch_results.json", help="Results JSON path")
    args = parser.parse_args()

    # Build stock list
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            stocks = json.load(f)  # [[ticker, date, name], ...]
    elif args.stocks:
        stocks = [(t, args.date, "") for t in args.stocks]
    else:
        stocks = DEFAULT_STOCKS

    config = build_ashare_config(
        llm_provider=args.provider,
        max_debate_rounds=args.debate_rounds,
    )

    # Load existing results for resume
    results = load_results(args.results_file)
    done = completed_tickers(results)

    print(f"Initializing TradingAgentsGraph ({args.provider})...")
    ta = init_trading_agents(config, debug=False)

    for idx, (ticker, date, name) in enumerate(stocks):
        if idx < args.start_from:
            continue
        if ticker in done:
            print(f">>> Skipping {name or ticker} ({ticker}) — already done")
            continue

        label = f"{name} ({ticker})" if name else ticker
        print(f"\n{'='*60}")
        print(f"[{idx+1}/{len(stocks)}] Analyzing {label} on {date}...")
        print(f"{'='*60}")
        start = time.time()
        try:
            state, decision = ta.propagate(ticker, date)
            elapsed = time.time() - start
            results.append({
                "ticker": ticker, "name": name, "decision": decision,
                "date": date, "time": elapsed, "error": None,
            })
            print(f"\n>>> {label}: {decision} [{elapsed:.0f}s]")
        except Exception as e:
            elapsed = time.time() - start
            results.append({
                "ticker": ticker, "name": name, "decision": f"ERROR: {e}",
                "date": date, "time": elapsed, "error": str(e),
            })
            print(f"\n>>> {label}: ERROR - {e} [{elapsed:.0f}s]")

        # Incremental save
        save_results(results, args.results_file)
        print(f"  (Saved to {args.results_file}, {len(results)} total)")

    # Summary
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        label = r.get("name") or r["ticker"]
        print(f"  {label:10s} ({r['ticker']}): {r['decision']} [{r['time']:.0f}s]")


if __name__ == "__main__":
    main()
