#!/usr/bin/env python3
"""Generate a complete report from a saved full_states_log JSON file."""
import json
import sys
import io
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "600673.SH"
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-04-30"

    log_path = (
        Path.home()
        / f".tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json"
    )

    if not log_path.exists():
        print(f"ERROR: State log not found at {log_path}")
        sys.exit(1)

    state = json.loads(log_path.read_text(encoding="utf-8"))

    # Create report directory structure
    report_dir = Path(f"reports/{ticker}_{date.replace('-', '')}")
    report_dir.mkdir(parents=True, exist_ok=True)

    # 1_analysts
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
            (analysts_dir / filename).write_text(content, encoding="utf-8")

    # 2_research
    research_dir = report_dir / "2_research"
    research_dir.mkdir(exist_ok=True)
    debate = state.get("investment_debate_state", {})
    for key, filename in [
        ("bull_history", "bull.md"),
        ("bear_history", "bear.md"),
        ("judge_decision", "manager.md"),
    ]:
        content = debate.get(key, "")
        if content:
            (research_dir / filename).write_text(content, encoding="utf-8")

    # 3_trading
    trading_dir = report_dir / "3_trading"
    trading_dir.mkdir(exist_ok=True)
    content = state.get("trader_investment_decision", "")
    if content:
        (trading_dir / "trader.md").write_text(content, encoding="utf-8")

    # 4_risk
    risk_dir = report_dir / "4_risk"
    risk_dir.mkdir(exist_ok=True)
    risk = state.get("risk_debate_state", {})
    for key, filename in [
        ("aggressive_history", "aggressive.md"),
        ("conservative_history", "conservative.md"),
        ("neutral_history", "neutral.md"),
    ]:
        content = risk.get(key, "")
        if content:
            (risk_dir / filename).write_text(content, encoding="utf-8")

    # 5_portfolio
    portfolio_dir = report_dir / "5_portfolio"
    portfolio_dir.mkdir(exist_ok=True)
    content = risk.get("judge_decision", "")
    if content:
        (portfolio_dir / "decision.md").write_text(content, encoding="utf-8")

    # Consolidated markdown
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {now_str}\n\n"
    sections = []

    # Analyst Team
    sections.append("## I. Analyst Team Reports\n")
    for key, title in [
        ("market_report", "Market Analysis"),
        ("sentiment_report", "Social Sentiment"),
        ("news_report", "News Analysis"),
        ("fundamentals_report", "Fundamentals Analysis"),
    ]:
        if state.get(key):
            sections.append(f"### {title}\n{state[key]}\n")

    # Research
    sections.append("## II. Research Team Decision\n")
    for key, title in [
        ("bull_history", "Bull Researcher"),
        ("bear_history", "Bear Researcher"),
        ("judge_decision", "Research Manager"),
    ]:
        if debate.get(key):
            sections.append(f"### {title}\n{debate[key]}\n")

    # Trading
    sections.append("## III. Trading Team Plan\n")
    if state.get("trader_investment_decision"):
        sections.append(f"### Trader\n{state['trader_investment_decision']}\n")

    # Risk
    sections.append("## IV. Risk Management\n")
    for key, title in [
        ("aggressive_history", "Aggressive Analyst"),
        ("conservative_history", "Conservative Analyst"),
        ("neutral_history", "Neutral Analyst"),
    ]:
        if risk.get(key):
            sections.append(f"### {title}\n{risk[key]}\n")

    # Portfolio
    sections.append("## V. Portfolio Manager Decision\n")
    if risk.get("judge_decision"):
        sections.append(f"### Decision\n{risk['judge_decision']}\n")

    (report_dir / "complete_report.md").write_text(
        header + "\n".join(sections), encoding="utf-8"
    )

    print(f"Report directory: {report_dir.resolve()}")
    print(f"  complete_report.md generated")

    # Generate Word report
    try:
        from tradingagents.utils.report_converter import convert_report_dir_to_docx

        docx_path = convert_report_dir_to_docx(report_dir, ticker=ticker, analysis_date=date)
        print(f"  Word report: {docx_path}")
    except Exception as exc:
        print(f"  Word report generation failed: {exc}")


if __name__ == "__main__":
    main()
