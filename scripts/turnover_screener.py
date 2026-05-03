#!/usr/bin/env python3
"""Screen A-share stocks by turnover rate and run TradingAgents deep analysis.

Strategy: Find the top 50 highest-turnover stocks over the last 3 months,
filter for tradability (price < 50 CNY so 1手 <= 5000 CNY, positive momentum),
then run full TradingAgents analysis on the top candidates.

Usage:
    python scripts/turnover_screener.py              # screen only
    python scripts/turnover_screener.py --analyze 5   # screen + analyze top 5
"""
import sys
import io
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
import pandas as pd


# ---------------------------------------------------------------------------
# Step 1: Fetch top N stocks by turnover rate from East Money
# ---------------------------------------------------------------------------

_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://eastmoney.com",
}


def fetch_top_turnover(top_n: int = 50) -> pd.DataFrame:
    """Fetch A-share stocks ranked by daily turnover rate (desc)."""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": top_n + 10,  # extra buffer for filtered-out rows
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f8",  # sort by turnover rate desc
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f12,f13,f14,f2,f3,f8,f9,f15,f16,f17,f6",
    }
    resp = requests.get(url, params=params, headers=_EASTMONEY_HEADERS, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    rows = []
    for item in payload["data"]["diff"]:
        market = item.get("f13", 0)
        code = str(item.get("f12", ""))
        name = str(item.get("f14", ""))
        price = item.get("f2", 0)
        if price == "-" or not price:
            continue
        price = float(price)
        pct_chg = item.get("f3", 0) or 0
        turnover = item.get("f8", 0) or 0
        pe = item.get("f9", 0) or 0
        high = item.get("f15", 0) or 0
        low = item.get("f16", 0) or 0
        open_ = item.get("f17", 0) or 0
        amount = item.get("f6", 0) or 0  # 成交额
        # Add exchange suffix
        suffix = ".SH" if market == 1 else ".SZ"
        ticker = code + suffix
        rows.append({
            "ticker": ticker,
            "code": code,
            "name": name,
            "price": price,
            "pct_chg": pct_chg,
            "turnover_pct": turnover,
            "pe_ttm": pe,
            "high": high,
            "low": low,
            "open": open_,
            "amount": amount,
        })

    df = pd.DataFrame(rows)
    return df.head(top_n)


# ---------------------------------------------------------------------------
# Step 2: Filter for 1w capital tradability
# ---------------------------------------------------------------------------

def screen_for_10k(df: pd.DataFrame) -> pd.DataFrame:
    """Filter stocks suitable for ~10,000 CNY capital.

    Criteria:
    - Price <= 50 CNY (1手 = 100 shares, so max ~5,000 per stock)
    - Turnover rate >= 3% (liquid enough to enter/exit)
    - Not ST/*ST (name contains ST)
    - Not newly listed (avoid N/首日 stocks)
    """
    mask = (
        (df["price"] >= 3.0)
        & (df["price"] <= 50.0)
        & (df["turnover_pct"] >= 3.0)
        & (~df["name"].str.contains("ST|退", na=False))
        & (~df["name"].str.startswith("N"))
    )
    filtered = df[mask].copy()
    filtered["cost_1lot"] = filtered["price"] * 100  # 1手成本
    filtered["lots_per_10k"] = (10000 / filtered["cost_1lot"]).astype(int)
    return filtered


# ---------------------------------------------------------------------------
# Step 3: Rank and select top candidates
# ---------------------------------------------------------------------------

def rank_candidates(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Score and rank candidates for TradingAgents analysis.

    Scoring (higher = more attractive):
    - Turnover rate (liquidity signal): 40% weight
    - Price momentum (pct_chg): 30% weight
    - PE reasonableness (not too high, not negative): 30% weight
    """
    scored = df.copy()

    # Normalize metrics to 0-1 range
    for col in ["turnover_pct", "pct_chg"]:
        if scored[col].max() > scored[col].min():
            scored[f"{col}_norm"] = (
                (scored[col] - scored[col].min()) / (scored[col].max() - scored[col].min())
            )
        else:
            scored[f"{col}_norm"] = 0.5

    # PE scoring: moderate PE (10-50) is better than extreme values
    def pe_score(pe):
        if pe <= 0:
            return 0.2
        elif 10 <= pe <= 30:
            return 1.0
        elif 5 <= pe < 10 or 30 < pe <= 50:
            return 0.7
        elif 50 < pe <= 100:
            return 0.4
        else:
            return 0.2

    scored["pe_score"] = scored["pe_ttm"].apply(pe_score)

    # Composite score
    scored["score"] = (
        scored["turnover_pct_norm"] * 0.4
        + scored["pct_chg_norm"] * 0.3
        + scored["pe_score"] * 0.3
    )

    return scored.nlargest(top_n, "score")


# ---------------------------------------------------------------------------
# Step 4: Run TradingAgents analysis on selected candidates
# ---------------------------------------------------------------------------

def run_analysis(candidates: pd.DataFrame, date: str = "2026-04-30"):
    """Run TradingAgents deep analysis on each candidate."""
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

    print("\nInitializing TradingAgentsGraph...")
    ta = TradingAgentsGraph(debug=False, config=config)

    results = []
    for _, row in candidates.iterrows():
        ticker = row["ticker"]
        name = row["name"]
        print(f"\n{'='*60}")
        print(f"Analyzing {name} ({ticker}) | Price: {row['price']:.2f} | Turnover: {row['turnover_pct']:.1f}%")
        print(f"{'='*60}")
        start = time.time()
        try:
            state, decision = ta.propagate(ticker, date)
            elapsed = time.time() - start
            results.append({
                "ticker": ticker, "name": name, "decision": decision,
                "price": row["price"], "turnover": row["turnover_pct"],
                "score": row.get("score", 0), "time": elapsed, "error": None,
            })
            print(f"\n>>> {name} ({ticker}): {decision} [{elapsed:.0f}s]")
        except Exception as e:
            elapsed = time.time() - start
            results.append({
                "ticker": ticker, "name": name, "decision": f"ERROR: {e}",
                "price": row["price"], "turnover": row["turnover_pct"],
                "score": row.get("score", 0), "time": elapsed, "error": str(e),
            })
            print(f"\n>>> {name} ({ticker}): ERROR - {e} [{elapsed:.0f}s]")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="A-share turnover screener + TradingAgents analysis")
    parser.add_argument("--analyze", type=int, default=0, help="Number of top candidates to run deep analysis on (0=screen only)")
    parser.add_argument("--date", type=str, default="2026-04-30", help="Analysis date (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=50, help="Number of top turnover stocks to fetch")
    args = parser.parse_args()

    # Step 1: Fetch top turnover stocks
    print(f"Fetching top {args.top} A-share stocks by turnover rate...")
    df = fetch_top_turnover(args.top)
    print(f"Got {len(df)} stocks\n")

    print("=" * 80)
    print(f"Top {min(args.top, len(df))} A-share stocks by daily turnover rate")
    print("=" * 80)
    print(df[["ticker", "name", "price", "pct_chg", "turnover_pct", "pe_ttm"]].to_string(index=False))

    # Step 2: Screen for 10k capital
    screened = screen_for_10k(df)
    print(f"\n{'=' * 80}")
    print(f"Filtered for 10,000 CNY capital: {len(screened)} stocks (price 3-50, turnover >= 3%)")
    print("=" * 80)
    if screened.empty:
        print("No stocks passed the filter. Relaxing criteria...")
        # Relax: allow higher price (up to 100)
        mask = (
            (df["price"] >= 3.0)
            & (df["price"] <= 100.0)
            & (df["turnover_pct"] >= 2.0)
            & (~df["name"].str.contains("ST|退", na=False))
        )
        screened = df[mask].copy()
        screened["cost_1lot"] = screened["price"] * 100
        screened["lots_per_10k"] = (10000 / screened["cost_1lot"]).astype(int)
        print(f"After relaxing: {len(screened)} stocks")

    if not screened.empty:
        print(screened[["ticker", "name", "price", "turnover_pct", "pe_ttm", "cost_1lot", "lots_per_10k"]].to_string(index=False))

    # Step 3: Rank candidates
    if len(screened) > 0:
        ranked = rank_candidates(screened, top_n=max(args.analyze, 10))
        print(f"\n{'=' * 80}")
        print("Ranked candidates (score = turnover*0.4 + momentum*0.3 + PE*0.3)")
        print("=" * 80)
        print(ranked[["ticker", "name", "price", "turnover_pct", "pct_chg", "pe_ttm", "score", "cost_1lot"]].to_string(index=False))

        # Save screening results
        ranked.to_csv("turnover_screen_results.csv", index=False, encoding="utf-8-sig")
        print(f"\nScreening results saved to turnover_screen_results.csv")
    else:
        ranked = pd.DataFrame()
        print("\nNo candidates to rank.")

    # Step 4: Run TradingAgents analysis
    if args.analyze > 0 and not ranked.empty:
        candidates = ranked.head(args.analyze)
        print(f"\n{'=' * 80}")
        print(f"Running TradingAgents deep analysis on top {args.analyze} candidates...")
        print("=" * 80)

        results = run_analysis(candidates, date=args.date)

        # Summary
        print(f"\n\n{'=' * 80}")
        print("FINAL ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"{'Name':<12} {'Ticker':<12} {'Price':>7} {'Turnover':>9} {'Decision':<10} {'Time':>6}")
        print("-" * 60)
        for r in results:
            print(f"{r['name']:<12} {r['ticker']:<12} {r['price']:>7.2f} {r['turnover']:>8.1f}% {r['decision']:<10} {r['time']:>5.0f}s")

        # Save results
        with open("turnover_analysis_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to turnover_analysis_results.json")


if __name__ == "__main__":
    main()
