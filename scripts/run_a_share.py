#!/usr/bin/env python3
"""Run TradingAgents pipeline for a single Chinese A-share stock.

Uses tencent_sina as primary data vendor with yfinance fallback for news.

Usage:
    python scripts/run_a_share.py                  # defaults: 300308 on 2026-04-30
    python scripts/run_a_share.py 600519.SH        # specific ticker
    python scripts/run_a_share.py 600519.SH 2026-03-15  # ticker + date
    python scripts/run_a_share.py --provider openai --debug
"""
import argparse
import time

from _share_config import build_ashare_config, init_trading_agents, convert_reports_to_word


def main():
    parser = argparse.ArgumentParser(description="Analyze a single A-share stock with TradingAgents")
    parser.add_argument("ticker", nargs="?", default="300308", help="Stock ticker (e.g. 600519.SH, 300308)")
    parser.add_argument("date", nargs="?", default="2026-04-30", help="Analysis date (YYYY-MM-DD)")
    parser.add_argument("--provider", default="deepseek", help="LLM provider (deepseek, openai, google, etc.)")
    parser.add_argument("--deep-model", default=None, help="Deep think model (default: provider-specific)")
    parser.add_argument("--quick-model", default=None, help="Quick think model (default: provider-specific)")
    parser.add_argument("--language", default="Chinese", help="Output language")
    parser.add_argument("--debate-rounds", type=int, default=1, help="Research debate rounds")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    args = parser.parse_args()

    config = build_ashare_config(
        llm_provider=args.provider,
        deep_think_llm=args.deep_model or f"{args.provider}-chat",
        quick_think_llm=args.quick_model or f"{args.provider}-chat",
        max_debate_rounds=args.debate_rounds,
        output_language=args.language,
    )

    print(f"Initializing TradingAgentsGraph ({args.provider})...")
    ta = init_trading_agents(config, debug=args.debug)

    print(f"Analyzing {args.ticker} on {args.date}...")
    start = time.time()
    state, decision = ta.propagate(args.ticker, args.date)
    elapsed = time.time() - start

    print()
    print("=" * 60)
    print(f"FINAL DECISION for {args.ticker}:")
    print("=" * 60)
    print(decision)
    print(f"\n[{elapsed:.0f}s]")

    # Convert MD reports to Word
    convert_reports_to_word(config, args.ticker, args.date)


if __name__ == "__main__":
    main()
