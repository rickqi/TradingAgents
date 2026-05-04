#!/usr/bin/env python3
"""Run single stock analysis with TradingAgents."""
import sys
import os

# Ensure project root is on sys.path so `scripts` package is importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# _share_config handles Windows encoding fix on import
from scripts._share_config import build_ashare_config, init_trading_agents


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run single stock analysis")
    parser.add_argument("ticker", help="Stock ticker (e.g. 002460)")
    parser.add_argument("--date", default="2026-05-02", help="Analysis date")
    parser.add_argument("--deep-model", default="deepseek-v4-flash", help="Deep think model")
    parser.add_argument("--quick-model", default="deepseek-v4-flash", help="Quick think model")
    args = parser.parse_args()

    config = build_ashare_config(
        deep_think_llm=args.deep_model,
        quick_think_llm=args.quick_model,
    )

    ta = init_trading_agents(config=config, debug=True)

    print(f"\n{'='*60}")
    print(f"  Analyzing {args.ticker} on {args.date}")
    print(f"  Deep: {args.deep_model} | Quick: {args.quick_model}")
    print(f"{'='*60}\n")

    state, decision = ta.propagate(args.ticker, args.date)

    print(f"\n{'='*60}")
    print(f"  DECISION for {args.ticker}")
    print(f"{'='*60}")
    print(decision)
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
