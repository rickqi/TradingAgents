"""Extract AI trading signals from TradingAgents analysis results.

Reads TradingAgents' JSON state logs and/or in-memory state dicts, extracts
structured trading signals (ratings, scores, price targets), and outputs
DataFrames suitable for Qlib feature integration.

Typical usage::

    # From a single analysis run (in-memory state)
    signals = extract_from_state(state_dict)

    # Batch-extract from all saved logs
    df = batch_extract_from_logs()
    save_signals_parquet(df, "ai_signals.parquet")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.qlib.ticker_mapper import is_ashare_ticker, to_qlib_instrument

# ---------------------------------------------------------------------------
# Mapping constants
# ---------------------------------------------------------------------------

RATING_MAP: dict[str, int] = {
    "Buy": 2,
    "Overweight": 1,
    "Hold": 0,
    "Underweight": -1,
    "Sell": -2,
}

TRADER_ACTION_MAP: dict[str, int] = {
    "Buy": 1,
    "Hold": 0,
    "Sell": -1,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RE_TRADER_ACTION = re.compile(
    r"FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*",
    re.IGNORECASE,
)

_RE_RESEARCH_REC = re.compile(
    r"\*\*Recommendation\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)",
    re.IGNORECASE,
)

_RE_PRICE_TARGET = re.compile(
    r"\*\*Price Target\*\*:\s*([\d.]+)",
    re.IGNORECASE,
)


def _extract_pm_rating(text: str) -> str:
    """Extract the 5-tier rating from Portfolio Manager markdown output."""
    return parse_rating(text)


def _extract_trader_action(text: str) -> str:
    """Extract the trader action (Buy/Hold/Sell) from Trader markdown output."""
    if not text:
        return "Hold"
    m = _RE_TRADER_ACTION.search(text)
    if m:
        return m.group(1).capitalize()
    return "Hold"


def _extract_research_recommendation(text: str) -> str:
    """Extract the research recommendation from Research Manager markdown output."""
    if not text:
        return "Hold"
    m = _RE_RESEARCH_REC.search(text)
    if m:
        return m.group(1).capitalize()
    # Fallback: use the shared rating parser which finds any 5-tier word.
    return parse_rating(text)


def _extract_price_target(text: str) -> float:
    """Extract the price target from Portfolio Manager markdown output."""
    if not text:
        return float("nan")
    m = _RE_PRICE_TARGET.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return float("nan")
    return float("nan")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_from_state(state: dict) -> dict:
    """Extract signals from a ``propagate()`` return state dict.

    Parameters
    ----------
    state : dict
        The agent state dictionary returned by
        :meth:`TradingAgentsGraph.propagate`.  Expected keys:
        ``company_of_interest``, ``trade_date``,
        ``final_trade_decision``, ``trader_investment_plan``,
        ``investment_plan``.

    Returns
    -------
    dict
        A flat dict with keys: ``date``, ``symbol``, ``ai_score``,
        ``trader_action``, ``research_rating``, ``price_target``.
    """
    pm_text = state.get("final_trade_decision", "")
    trader_text = state.get("trader_investment_plan", "")
    research_text = state.get("investment_plan", "")

    rating = _extract_pm_rating(pm_text)
    action = _extract_trader_action(trader_text)
    research_rating = _extract_research_recommendation(research_text)
    price_target = _extract_price_target(pm_text)

    return {
        "date": state.get("trade_date", ""),
        "symbol": state.get("company_of_interest", ""),
        "ai_score": RATING_MAP.get(rating, 0),
        "trader_action": TRADER_ACTION_MAP.get(action, 0),
        "research_rating": RATING_MAP.get(research_rating, 0),
        "price_target": price_target,
    }


def extract_from_log(log_path: str | Path) -> dict:
    """Read a single ``full_states_log_{date}.json`` file and extract signals.

    The JSON uses ``"trader_investment_decision"`` (not ``"trader_investment_plan"``).
    This function maps JSON keys to the format expected by :func:`extract_from_state`.

    Parameters
    ----------
    log_path : str or Path
        Path to a ``full_states_log_*.json`` file.

    Returns
    -------
    dict
        Same shape as :func:`extract_from_state`.
    """
    log_path = Path(log_path)
    with open(log_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Map JSON key names to state dict key names expected by extract_from_state.
    state = {
        "company_of_interest": data.get("company_of_interest", ""),
        "trade_date": data.get("trade_date", ""),
        "final_trade_decision": data.get("final_trade_decision", ""),
        "trader_investment_plan": data.get("trader_investment_decision", ""),
        "investment_plan": data.get("investment_plan", ""),
    }

    return extract_from_state(state)


def batch_extract_from_logs(results_dir: str | None = None) -> pd.DataFrame:
    """Scan all JSON log files and return a combined signals DataFrame.

    Parameters
    ----------
    results_dir : str or None
        Root directory to search. Defaults to
        ``DEFAULT_CONFIG["results_dir"]`` (``~/.tradingagents/logs``).

    Returns
    -------
    pd.DataFrame
        Columns: ``date``, ``symbol``, ``ai_score``, ``trader_action``,
        ``research_rating``, ``price_target``.  Sorted by (date, symbol).
        The ``symbol`` column is converted to Qlib instrument format via
        :func:`to_qlib_instrument`.
    """
    if results_dir is None:
        from tradingagents.default_config import DEFAULT_CONFIG
        results_dir = DEFAULT_CONFIG["results_dir"]

    root = Path(results_dir)
    pattern = "**/TradingAgentsStrategy_logs/full_states_log_*.json"
    log_files = sorted(root.glob(pattern))

    rows: list[dict] = []
    for lf in log_files:
        try:
            row = extract_from_log(lf)
        except Exception:
            # Skip corrupted or incompatible log files silently.
            continue
        # Convert ticker to Qlib instrument format.
        row["symbol"] = to_qlib_instrument(row["symbol"])
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=["date", "symbol", "ai_score", "trader_action",
                      "research_rating", "price_target"],
        )

    df = pd.DataFrame(rows)
    df.sort_values(by=["date", "symbol"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def save_signals_parquet(df: pd.DataFrame, output_path: str) -> None:
    """Save the signals DataFrame to parquet with proper MultiIndex.

    Sets a MultiIndex of (date as datetime, symbol) and writes to parquet.
    Falls back to CSV if parquet engines are unavailable.

    Parameters
    ----------
    df : pd.DataFrame
        Signals DataFrame from :func:`batch_extract_from_logs`.
    output_path : str
        Destination file path. ``.parquet`` extension recommended.
    """
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index(["date", "symbol"])

    output_path = str(output_path)

    # Try parquet with pyarrow, then fastparquet, then fall back to CSV.
    for engine in ("pyarrow", "fastparquet"):
        try:
            out.to_parquet(output_path, engine=engine)
            return
        except Exception:
            continue

    # Fallback: save as CSV.
    csv_path = output_path.rsplit(".", 1)[0] + ".csv"
    out.to_csv(csv_path)
