#!/usr/bin/env python3
"""Shared configuration and utilities for A-share analysis scripts.

All scripts under scripts/ import from this module to avoid duplicating:
  - A-share TradingAgents config builder
  - Windows UTF-8 encoding fix
  - JSON result incremental save/load
  - Report conversion helper
"""
import sys
import io
import json
import os
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Windows UTF-8 encoding fix (called at module import)
# ---------------------------------------------------------------------------

def fix_windows_encoding():
    """Replace stdout/stderr with UTF-8 wrappers to avoid cp1252 errors."""
    if sys.platform == "win32":
        for attr in ("stdout", "stderr"):
            stream = getattr(sys, attr)
            if stream is None:
                continue
            # Already UTF-8? Skip to avoid double-wrapping.
            if getattr(stream, "encoding", "") == "utf-8":
                continue
            try:
                buf = stream.buffer
                setattr(sys, attr, io.TextIOWrapper(buf, encoding="utf-8", errors="replace"))
            except (AttributeError, ValueError):
                pass


# Auto-fix on import
fix_windows_encoding()


# ---------------------------------------------------------------------------
# A-share TradingAgents config builder
# ---------------------------------------------------------------------------

def build_ashare_config(
    llm_provider: str = "deepseek",
    deep_think_llm: str = "deepseek-v4-flash",
    quick_think_llm: str = "deepseek-v4-flash",
    news_vendors: str = "tencent_sina",
    max_debate_rounds: int = 1,
    max_risk_discuss_rounds: int = 1,
    output_language: str = "Chinese",
    debug: bool = False,
) -> dict:
    """Build a DEFAULT_CONFIG override for A-share analysis.

    Args:
        llm_provider: LLM provider name (deepseek, openai, google, etc.).
        deep_think_llm: Model for complex reasoning agents.
        quick_think_llm: Model for quick tasks.
        news_vendors: Comma-separated vendor priority for news data.
            Defaults to ``\"tencent_sina\"`` only. Do NOT include yfinance here —
            it has no useful A-share data and its rate-limiting burns minutes of
            wall-clock time per failed call.
        max_debate_rounds: Research debate rounds.
        max_risk_discuss_rounds: Risk debate rounds.
        output_language: Report language (internal debate stays English).
        debug: Enable verbose TradingAgents debug output.

    Returns:
        Config dict ready for TradingAgentsGraph(config=...).
    """
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = llm_provider
    config["deep_think_llm"] = deep_think_llm
    config["quick_think_llm"] = quick_think_llm
    config["data_vendors"] = {
        "core_stock_apis": "tencent_sina",
        "technical_indicators": "tencent_sina",
        "fundamental_data": "tencent_sina,akshare",
        "news_data": news_vendors,
        "sentiment_data": "akshare",
    }
    config["max_debate_rounds"] = max_debate_rounds
    config["max_risk_discuss_rounds"] = max_risk_discuss_rounds
    config["output_language"] = output_language
    return config


def init_trading_agents(config: Optional[dict] = None, debug: bool = False):
    """Initialize TradingAgentsGraph with the given config.

    Args:
        config: Config dict. If None, builds default A-share config.
        debug: Override config debug flag.

    Returns:
        TradingAgentsGraph instance.
    """
    from dotenv import load_dotenv
    load_dotenv()

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    if config is None:
        config = build_ashare_config()

    return TradingAgentsGraph(debug=debug, config=config)


# ---------------------------------------------------------------------------
# Incremental JSON result save/load (for batch analysis)
# ---------------------------------------------------------------------------

def save_results(results: list, path: str = "analysis_results.json"):
    """Save analysis results to JSON (overwrites file)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def load_results(path: str = "analysis_results.json") -> list:
    """Load previously saved results (for resume)."""
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def completed_tickers(results: list) -> set:
    """Return set of tickers that completed without error."""
    return {r["ticker"] for r in results if not r.get("error")}


# ---------------------------------------------------------------------------
# Report conversion helper
# ---------------------------------------------------------------------------

def convert_reports_to_word(config: dict, ticker: str, date: str):
    """Convert any generated MD reports in the results dir to Word format.

    Non-critical: silently ignores errors.
    """
    try:
        from tradingagents.utils.report_converter import convert_all_md_in_dir

        results_dir = os.path.join(
            config.get("results_dir", os.path.expanduser("~/.tradingagents/logs")),
            ticker,
            date,
        )
        reports_dir = os.path.join(results_dir, "reports")
        if os.path.isdir(reports_dir):
            converted = convert_all_md_in_dir(reports_dir)
            if converted:
                print(f"Converted {len(converted)} report(s) to Word in {reports_dir}")
    except Exception:
        pass
