#!/usr/bin/env python3
"""Batch-analyze stocks with TradingAgents and generate individual + summary reports.

Combines the batch analysis capability with report generation:
  1. Runs TradingAgents propagate() for each stock
  2. Generates per-stock reports in reports/ directory (MD + DOCX)
  3. Generates a summary report with all decisions

Usage:
    python scripts/batch_analyze.py                          # default 10 stocks
    python scripts/batch_analyze.py --stocks 600519.SH 300308  # custom stocks
    python scripts/batch_analyze.py --start-from 3            # resume from 4th
    python scripts/batch_analyze.py --skip-analysis            # only generate reports from logs
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from _share_config import (
    build_ashare_config, init_trading_agents,
    save_results, load_results, completed_tickers,
    DEFAULT_STOCKS,
)

# ---------------------------------------------------------------------------
# Report generation (from state dict)
# ---------------------------------------------------------------------------

def generate_stock_report(state: dict, ticker: str, date: str, reports_root: str = "reports") -> Path:
    """Generate per-stock report directory with MD + DOCX from TradingAgents state.

    Args:
        state: The full state dict returned by ta.propagate().
        ticker: Stock ticker (e.g. 600519.SH).
        date: Analysis date (e.g. 2026-04-30).
        reports_root: Root directory for reports.

    Returns:
        Path to the report directory.
    """
    report_dir = Path(reports_root) / f"{ticker}_{date.replace('-', '')}"
    report_dir.mkdir(parents=True, exist_ok=True)

    # --- 1_analysts ---
    analysts_dir = report_dir / "1_analysts"
    analysts_dir.mkdir(exist_ok=True)
    for key, filename in [
        ("market_report", "market.md"),
        ("sentiment_report", "sentiment.md"),
        ("news_report", "news.md"),
        ("fundamentals_report", "fundamentals.md"),
    ]:
        content = state.get(key, "")
        if content:
            (analysts_dir / filename).write_text(str(content), encoding="utf-8")

    # --- 2_research ---
    research_dir = report_dir / "2_research"
    research_dir.mkdir(exist_ok=True)
    debate = state.get("investment_debate_state", {})
    if isinstance(debate, dict):
        for key, filename in [
            ("bull_history", "bull.md"),
            ("bear_history", "bear.md"),
            ("judge_decision", "manager.md"),
        ]:
            content = debate.get(key, "")
            if content:
                (research_dir / filename).write_text(str(content), encoding="utf-8")

    # --- 3_trading ---
    trading_dir = report_dir / "3_trading"
    trading_dir.mkdir(exist_ok=True)
    content = state.get("trader_investment_decision", "")
    if content:
        (trading_dir / "trader.md").write_text(str(content), encoding="utf-8")

    # --- 4_risk ---
    risk_dir = report_dir / "4_risk"
    risk_dir.mkdir(exist_ok=True)
    risk = state.get("risk_debate_state", {})
    if isinstance(risk, dict):
        for key, filename in [
            ("aggressive_history", "aggressive.md"),
            ("conservative_history", "conservative.md"),
            ("neutral_history", "neutral.md"),
        ]:
            content = risk.get(key, "")
            if content:
                (risk_dir / filename).write_text(str(content), encoding="utf-8")

    # --- 5_portfolio ---
    portfolio_dir = report_dir / "5_portfolio"
    portfolio_dir.mkdir(exist_ok=True)
    if isinstance(risk, dict):
        content = risk.get("judge_decision", "")
        if content:
            (portfolio_dir / "decision.md").write_text(str(content), encoding="utf-8")

    # --- Consolidated markdown ---
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {now_str}\nDate: {date}\n\n"
    sections = []

    sections.append("## I. Analyst Team Reports\n")
    for key, title in [
        ("market_report", "Market Analysis"),
        ("sentiment_report", "Social Sentiment"),
        ("news_report", "News Analysis"),
        ("fundamentals_report", "Fundamentals Analysis"),
    ]:
        if state.get(key):
            sections.append(f"### {title}\n{state[key]}\n")

    sections.append("## II. Research Team Decision\n")
    if isinstance(debate, dict):
        for key, title in [
            ("bull_history", "Bull Researcher"),
            ("bear_history", "Bear Researcher"),
            ("judge_decision", "Research Manager"),
        ]:
            if debate.get(key):
                sections.append(f"### {title}\n{debate[key]}\n")

    sections.append("## III. Trading Team Plan\n")
    if state.get("trader_investment_decision"):
        sections.append(f"### Trader\n{state['trader_investment_decision']}\n")

    sections.append("## IV. Risk Management\n")
    if isinstance(risk, dict):
        for key, title in [
            ("aggressive_history", "Aggressive Analyst"),
            ("conservative_history", "Conservative Analyst"),
            ("neutral_history", "Neutral Analyst"),
        ]:
            if risk.get(key):
                sections.append(f"### {title}\n{risk[key]}\n")

    sections.append("## V. Portfolio Manager Decision\n")
    if isinstance(risk, dict) and risk.get("judge_decision"):
        sections.append(f"### Decision\n{risk['judge_decision']}\n")

    (report_dir / "complete_report.md").write_text(
        header + "\n".join(sections), encoding="utf-8"
    )

    # --- Word report ---
    try:
        from tradingagents.utils.report_converter import convert_report_dir_to_docx
        docx_path = convert_report_dir_to_docx(report_dir, ticker=ticker, analysis_date=date)
        print(f"  Word report: {docx_path}")
    except Exception as exc:
        print(f"  Word report failed: {exc}")

    return report_dir


# ---------------------------------------------------------------------------
# Summary report generation
# ---------------------------------------------------------------------------

def generate_summary_report(results: list, reports_root: str = "reports"):
    """Generate a summary MD+DOCX report across all analyzed stocks."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build summary
    sections = [
        f"# TradingAgents 批量分析汇总报告\n\n",
        f"生成时间: {now_str}\n",
        f"分析股票数: {len(results)}\n\n",
        "---\n\n",
        "## 决策总览\n\n",
        "| # | 股票代码 | 名称 | 价格 | TradingAgents 决策 | 耗时 |\n",
        "|---|---------|------|------|-------------------|------|\n",
    ]

    for i, r in enumerate(results, 1):
        ticker = r["ticker"]
        name = r.get("name", "")
        price = r.get("price", "N/A")
        decision = r.get("decision", "N/A")
        elapsed = r.get("time", 0)
        if isinstance(price, (int, float)):
            price_str = f"{price:.2f}"
        else:
            price_str = str(price)
        sections.append(f"| {i} | {ticker} | {name} | {price_str} | {decision} | {elapsed:.0f}s |\n")

    # Individual stock sections
    sections.append("\n---\n\n## 各股详细分析\n\n")
    for r in results:
        ticker = r["ticker"]
        name = r.get("name", "")
        decision = r.get("decision", "N/A")
        date = r.get("date", "2026-04-30")
        report_dir_name = f"{ticker}_{date.replace('-', '')}"
        report_path = Path(reports_root) / report_dir_name

        sections.append(f"### {name} ({ticker})\n\n")
        sections.append(f"- **决策**: {decision}\n")
        sections.append(f"- **详细报告**: `{report_path}/complete_report.md`\n\n")

        # Read complete_report.md if available and append key sections
        md_path = report_path / "complete_report.md"
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            # Extract Portfolio Manager Decision section (most actionable)
            pm_marker = "## V. Portfolio Manager Decision"
            if pm_marker in content:
                pm_section = content[content.index(pm_marker):]
                # Trim to next top-level heading if exists
                next_h2 = pm_section.find("\n## ", 1)
                if next_h2 > 0:
                    pm_section = pm_section[:next_h2]
                sections.append(f"<details>\n<summary>Portfolio Manager 决策详情</summary>\n\n")
                sections.append(pm_section)
                sections.append("\n</details>\n\n")

    summary_path = Path(reports_root) / "summary_report.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("".join(sections), encoding="utf-8")
    print(f"\nSummary report: {summary_path}")

    # Try to convert summary to Word
    try:
        from tradingagents.utils.report_converter import convert_md_to_docx
        docx_path = convert_md_to_docx(str(summary_path))
        if docx_path:
            print(f"Summary Word report: {docx_path}")
    except Exception as exc:
        print(f"Summary Word report failed: {exc}")

    return summary_path


# ---------------------------------------------------------------------------
# Main: analyze + report
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Batch-analyze stocks and generate reports")
    parser.add_argument("--stocks", nargs="+", help="Tickers to analyze")
    parser.add_argument("--date", default="2026-04-30", help="Analysis date")
    parser.add_argument("--file", help="JSON file with stock list: [[ticker, date, name], ...]")
    parser.add_argument("--provider", default="deepseek", help="LLM provider")
    parser.add_argument("--debate-rounds", type=int, default=1, help="Research debate rounds")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N stocks (0-based)")
    parser.add_argument("--results-file", default="reports/batch_results.json", help="Results JSON path")
    parser.add_argument("--reports-dir", default="reports", help="Root directory for reports")
    parser.add_argument("--skip-analysis", action="store_true",
                        help="Only generate reports from existing results JSON (no API calls)")
    args = parser.parse_args()

    # Build stock list
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            stocks = json.load(f)
    elif args.stocks:
        stocks = [(t, args.date, "") for t in args.stocks]
    else:
        stocks = DEFAULT_STOCKS

    # Ensure reports dir exists
    Path(args.reports_dir).mkdir(parents=True, exist_ok=True)

    # --- Skip analysis mode: just regenerate reports ---
    if args.skip_analysis:
        results = load_results(args.results_file)
        if not results:
            print(f"No results found in {args.results_file}. Run analysis first.")
            return
        print(f"Regenerating reports for {len(results)} stocks from {args.results_file}...")
        for r in results:
            if r.get("error"):
                continue
            ticker = r["ticker"]
            date = r.get("date", args.date)
            # Find state log
            log_path = (
                Path.home()
                / f".tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json"
            )
            if log_path.exists():
                state = json.loads(log_path.read_text(encoding="utf-8"))
                print(f"\nGenerating report for {r.get('name', ticker)} ({ticker})...")
                generate_stock_report(state, ticker, date, args.reports_dir)
            else:
                print(f"  No state log found for {ticker}, skipping report")
        generate_summary_report(results, args.reports_dir)
        return

    # --- Full analysis mode ---
    config = build_ashare_config(
        llm_provider=args.provider,
        max_debate_rounds=args.debate_rounds,
    )

    results = load_results(args.results_file)
    done = completed_tickers(results)

    print(f"Initializing TradingAgentsGraph ({args.provider})...")
    ta = init_trading_agents(config, debug=False)

    for idx, (ticker, date, name) in enumerate(stocks):
        if idx < args.start_from:
            continue
        if ticker in done:
            print(f"\n>>> Skipping {name or ticker} ({ticker}) — already done")
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

            # Generate per-stock report
            print(f"Generating report for {ticker}...")
            generate_stock_report(state, ticker, date, args.reports_dir)

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

    # Generate summary report
    print(f"\n{'='*60}")
    print("Generating summary report...")
    print(f"{'='*60}")
    generate_summary_report(results, args.reports_dir)

    # Print summary table
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    for r in results:
        label = r.get("name") or r["ticker"]
        print(f"  {label:10s} ({r['ticker']}): {r['decision']} [{r['time']:.0f}s]")
    print(f"\nReports saved to {args.reports_dir}/")


if __name__ == "__main__":
    main()
