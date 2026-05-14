"""Publish TradingAgents AI signals to DoltHub.

Tables:
  ta_signals         — Daily AI signals per stock (PK: trade_date, symbol)
  ta_signal_version  — Version metadata per publish (PK: version_id)

Usage:
    from tradingagents.qlib.ta_dolt_publisher import ta_dolt_push

    ta_dolt_push(results_path="batch_20_results.json")  # publish
    ta_dolt_push(push=False)                             # local commit only
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from tradingagents.qlib.dolt_publisher import TABLE_SCHEMAS, _find_dolt as _find_dolt_base


# ── Configuration ──────────────────────────────────────────────────────────
_DOLT_EXE_CANDIDATES = [
    r"C:\Users\szk220009\AppData\Local\Programs\dolt\dolt.exe",
    r"C:\Program Files\Dolt\bin\dolt.exe",
    "dolt",  # rely on PATH
]
DOLTHUB_REMOTE = "rickqi/tradingagents"


# ── Result ─────────────────────────────────────────────────────────────────
@dataclass
class TAPublishResult:
    """Summary statistics for a TA signal publish run."""

    num_signals: int
    trade_date: str
    pushed: bool
    commit_hash: str = ""
    repo_dir: str = ""


# ── Table schemas ──────────────────────────────────────────────────────────
TA_TABLE_SCHEMAS = {
    "ta_signals": """
        CREATE TABLE IF NOT EXISTS ta_signals (
            trade_date    VARCHAR(20)  NOT NULL,
            symbol        VARCHAR(20)  NOT NULL,
            ai_score      INT,
            trader_action INT,
            research_rating INT,
            decision      VARCHAR(20),
            price_target  DOUBLE,
            model_name    VARCHAR(50),
            provider      VARCHAR(20),
            analysts      VARCHAR(100),
            debate_rounds INT,
            analysis_time_sec DOUBLE,
            created_at    VARCHAR(30),
            PRIMARY KEY (trade_date, symbol)
        )
    """,
    "ta_signal_version": """
        CREATE TABLE IF NOT EXISTS ta_signal_version (
            version_id    VARCHAR(40)  NOT NULL,
            trade_date    VARCHAR(20)  NOT NULL,
            tickers_hash  VARCHAR(64),
            num_signals   INT,
            model_name    VARCHAR(50),
            analysts      VARCHAR(100),
            commit_hash   VARCHAR(20),
            created_at    VARCHAR(30),
            PRIMARY KEY (version_id)
        )
    """,
}


# ── Dolt CLI wrapper ───────────────────────────────────────────────────────
def _find_dolt() -> str:
    """Locate the dolt executable."""
    for candidate in _DOLT_EXE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        if shutil.which(candidate):
            return candidate
    return ""


def _dolt(dolt_exe: str, *args: str, cwd: str | None = None, check: bool = True):
    """Run a dolt CLI command, return subprocess result."""
    cmd = [dolt_exe] + list(args)
    print(f"  [dolt] {' '.join(args)}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.stdout.strip():
        for line in r.stdout.strip().splitlines()[:5]:
            print(f"         {line}")
        if r.stdout.strip().count("\n") > 5:
            print(f"         ... ({r.stdout.strip().count(chr(10))} lines total)")
    if r.returncode != 0:
        if r.stderr.strip():
            print(f"  [ERR] {r.stderr.strip()[:300]}")
        if check:
            raise RuntimeError(f"dolt exited {r.returncode}: {' '.join(args)}")
    return r


# ── Data loading ───────────────────────────────────────────────────────────
def _default_results_path() -> str:
    """Resolve the default batch_20_results.json path."""
    # 1. Relative to this file: tradingagents/qlib/ -> ../../scripts/
    ta_root = Path(__file__).resolve().parent.parent.parent
    candidate = ta_root / "scripts" / "batch_20_results.json"
    if candidate.exists():
        return str(candidate)
    # 2. Current working directory
    cwd_candidate = Path.cwd() / "batch_20_results.json"
    if cwd_candidate.exists():
        return str(cwd_candidate)
    # Return the TA root path anyway (will warn later if missing)
    return str(candidate)


def load_ta_results(results_path: str | None = None) -> list[dict]:
    """Load TA batch results from JSON, filtering out error entries.

    Parameters
    ----------
    results_path:
        Path to ``batch_20_results.json``.  ``None`` auto-discovers.

    Returns
    -------
    list[dict]
        Entries with ``error`` field being ``None``.
    """
    path = results_path or _default_results_path()
    p = Path(path)
    if not p.exists():
        print(f"  WARNING: Results file not found: {path}")
        return []

    with open(p, "r", encoding="utf-8") as f:
        all_results = json.load(f)

    valid = [r for r in all_results if r.get("error") is None]
    errors = len(all_results) - len(valid)
    print(f"  Loaded {len(valid)} signals from {p.name} ({errors} errors skipped)")
    return valid


# ── DataFrame builders ─────────────────────────────────────────────────────
def build_signals_df(
    results: list[dict],
    model_name: str = "deepseek-v4-flash",
    provider: str = "deepseek",
    analysts: str = "market,social,news,fundamentals",
    debate_rounds: int = 1,
) -> pd.DataFrame:
    """Build the ``ta_signals`` table DataFrame.

    Parameters
    ----------
    results:
        List of valid (non-error) result dicts from :func:`load_ta_results`.
    model_name:
        LLM model used for the analysis.
    provider:
        LLM provider.
    analysts:
        Comma-separated analyst list.
    debate_rounds:
        Number of debate rounds.

    Returns
    -------
    pd.DataFrame
        Columns matching the ``ta_signals`` table schema.
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows = []
    for r in results:
        price_target = r.get("price_target")
        rows.append({
            "trade_date": r.get("date", ""),
            "symbol": r.get("ticker", ""),
            "ai_score": int(r.get("ai_score", 0)),
            "trader_action": int(r.get("trader_action", 0)),
            "research_rating": int(r.get("research_rating", 0)),
            "decision": r.get("decision", ""),
            "price_target": price_target if price_target is not None else "",
            "model_name": model_name,
            "provider": provider,
            "analysts": analysts,
            "debate_rounds": debate_rounds,
            "analysis_time_sec": float(r.get("time", 0.0)),
            "created_at": now,
        })
    return pd.DataFrame(rows)


def build_version_record(
    results: list[dict],
    model_name: str = "deepseek-v4-flash",
    analysts: str = "market,social,news,fundamentals",
) -> dict:
    """Build a single ``ta_signal_version`` row.

    Parameters
    ----------
    results:
        List of valid result dicts.
    model_name:
        LLM model used.
    analysts:
        Comma-separated analyst list.

    Returns
    -------
    dict
        One row for the ``ta_signal_version`` table.
    """
    trade_date = results[0].get("date", "") if results else ""
    tickers = sorted(r.get("ticker", "") for r in results)
    tickers_str = ",".join(tickers)
    tickers_hash = hashlib.md5(tickers_str.encode()).hexdigest()

    version_id = f"{trade_date}_{tickers_hash[:8]}"
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "version_id": version_id,
        "trade_date": trade_date,
        "tickers_hash": tickers_hash,
        "num_signals": len(results),
        "model_name": model_name,
        "analysts": analysts,
        "commit_hash": "",  # filled after commit
        "created_at": now,
    }


# ── Persistent repo directory ────────────────────────────────────────────
_PERSISTENT_REPO_DIR = Path.home() / ".dolt" / "ta_publisher" / "tradingagents"


# ── Dolt publish ───────────────────────────────────────────────────────────
def _dolt_publish_ta(
    dolt_exe: str,
    signals_csv: str,
    version_csv: str,
    push: bool = True,
    fresh_clone: bool = False,
) -> TAPublishResult:
    """Clone/pull DoltHub repo, create tables, import CSV, commit, and push."""
    repo_dir = str(_PERSISTENT_REPO_DIR)
    num_signals = 0

    # Read signals count from CSV
    with open(signals_csv, "r", encoding="utf-8") as f:
        num_signals = sum(1 for _ in f) - 1  # minus header

    # Read trade_date from signals CSV
    signals_df = pd.read_csv(signals_csv, nrows=1, encoding="utf-8")
    trade_date = signals_df["trade_date"].iloc[0] if not signals_df.empty else ""

    # ── Clone, pull, or init ──────────────────────────────────
    print(f"\n{'='*60}")
    print("  Initialize Dolt repo (persistent)")
    print(f"{'='*60}")

    has_dolt_dir = os.path.isdir(os.path.join(repo_dir, ".dolt"))

    if fresh_clone and os.path.isdir(repo_dir):
        print(f"  [fresh-clone] Removing existing repo: {repo_dir}")
        shutil.rmtree(repo_dir, ignore_errors=True)
        has_dolt_dir = False

    if has_dolt_dir:
        # Existing persistent repo — pull latest (fast, only diffs)
        print(f"  Existing repo found — pulling latest changes")
        _dolt(dolt_exe, "pull", "origin", "main", cwd=repo_dir, check=False)
    else:
        # Fresh clone
        os.makedirs(repo_dir, exist_ok=True)
        clone_result = _dolt(dolt_exe, "clone", DOLTHUB_REMOTE, repo_dir, check=False)
        if clone_result.returncode != 0:
            if os.path.isdir(repo_dir):
                shutil.rmtree(repo_dir, ignore_errors=True)
            os.makedirs(repo_dir, exist_ok=True)
            print("  Remote empty or not clonable -- initializing locally")
            _dolt(
                dolt_exe,
                "init", "--name", "rickqi", "--email", "rickqi@users.noreply.github.com",
                cwd=repo_dir,
            )
            _dolt(
                dolt_exe,
                "remote", "add", "origin",
                f"https://doltremoteapi.dolthub.com/{DOLTHUB_REMOTE}",
                cwd=repo_dir,
            )
    print(f"  Repo dir: {repo_dir}")

    # ── Create tables ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Create tables")
    print(f"{'='*60}")
    # Existing OHLCV tables (from dolt_publisher.py)
    for table_name, ddl in TABLE_SCHEMAS.items():
        _dolt(dolt_exe, "sql", "-q", ddl.strip(), cwd=repo_dir)
        print(f"  Ensured: {table_name}")
    # New TA signal tables
    for table_name, ddl in TA_TABLE_SCHEMAS.items():
        _dolt(dolt_exe, "sql", "-q", ddl.strip(), cwd=repo_dir)
        print(f"  Created: {table_name}")

    # ── Import CSV ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Import data")
    print(f"{'='*60}")
    print(f"\n  Importing {os.path.basename(signals_csv)} -> ta_signals")
    _dolt(dolt_exe, "table", "import", "-u", "ta_signals", signals_csv, cwd=repo_dir)

    print(f"\n  Importing {os.path.basename(version_csv)} -> ta_signal_version")
    _dolt(dolt_exe, "table", "import", "-u", "ta_signal_version", version_csv, cwd=repo_dir)

    # ── Commit ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Commit")
    print(f"{'='*60}")
    _dolt(dolt_exe, "add", "-A", cwd=repo_dir)

    commit_hash = ""
    status = _dolt(dolt_exe, "status", cwd=repo_dir, check=False)
    if "nothing to commit" in (status.stdout or ""):
        print("  No changes to commit.")
    else:
        _dolt(
            dolt_exe,
            "commit", "-m",
            f"TA AI signals import ({trade_date}, {num_signals} signals)",
            cwd=repo_dir,
        )
        log_r = _dolt(dolt_exe, "log", "-n", "1", cwd=repo_dir, check=False)
        for line in (log_r.stdout or "").splitlines():
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if clean.startswith("commit "):
                commit_hash = clean.split()[1][:12]
                break
        print(f"  Committed: {commit_hash}")

    # ── Push ───────────────────────────────────────────────────
    if push:
        print(f"\n{'='*60}")
        print("  Push to DoltHub")
        print(f"{'='*60}")
        br_result = _dolt(dolt_exe, "branch", "--show-current", cwd=repo_dir, check=False)
        branch = (br_result.stdout or "").strip() or "main"
        _dolt(dolt_exe, "push", "-u", "origin", branch, cwd=repo_dir)
        print(f"\n  DONE! -> https://www.dolthub.com/repositories/{DOLTHUB_REMOTE}")
    else:
        print("\n  [--no-push] Skipping push. Data committed locally.")
        print(f"  Repo: {repo_dir}")

    return TAPublishResult(
        num_signals=num_signals,
        trade_date=str(trade_date),
        pushed=push,
        commit_hash=commit_hash,
        repo_dir=repo_dir,
    )


# ── DoltHub SQL API (client-side, read-only) ───────────────────────────────
def query_dolthub(
    sql: str,
    repo: str = "rickqi/tradingagents",
    branch: str = "main",
) -> dict:
    """Query DoltHub via SQL API (no dolt CLI needed, read-only).

    Parameters
    ----------
    sql:
        SQL query string.
    repo:
        DoltHub repo in ``owner/name`` format.
    branch:
        Branch name (default ``main``).

    Returns
    -------
    dict
        Parsed JSON response from DoltHub.
    """
    import requests

    url = f"https://www.dolthub.com/api/v1alpha1/{repo}/{branch}"
    resp = requests.get(url, params={"q": sql}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Version comparison ────────────────────────────────────────────────────
class VersionStatus:
    """Possible outcomes of a local-vs-remote TA signal comparison."""

    MATCH = "match"
    DATE_MISMATCH = "date_mismatch"
    TICKERS_MISMATCH = "tickers_mismatch"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"


def check_remote_signals(
    results_path: str | None = None,
    repo: str = "rickqi/tradingagents",
    branch: str = "main",
) -> dict:
    """Compare local TA signals with the latest version on DoltHub.

    Parameters
    ----------
    results_path:
        Path to ``batch_20_results.json``.  ``None`` auto-discovers.
    repo:
        DoltHub repo in ``owner/name`` format.
    branch:
        Branch name (default ``main``).

    Returns
    -------
    dict
        Comparison result with keys: ``status`` (VersionStatus value),
        ``local_date``, ``remote_date``, ``local_tickers``, ``num_local``,
        ``num_remote``, ``differences`` (list of divergent ticker entries).
    """
    import requests

    # 1. Load local results
    results = load_ta_results(results_path)
    if not results:
        return {
            "status": VersionStatus.NO_REMOTE,
            "local_date": "",
            "remote_date": "",
            "local_tickers": [],
            "num_local": 0,
            "num_remote": 0,
            "differences": [],
            "error": "No valid local TA results found",
        }

    local_date = results[0].get("date", "")
    local_tickers = sorted(r.get("ticker", "") for r in results)
    local_hash = hashlib.md5(",".join(local_tickers).encode()).hexdigest()

    # 2. Query remote latest version
    try:
        resp = query_dolthub(
            "SELECT * FROM ta_signal_version ORDER BY created_at DESC LIMIT 1",
            repo=repo,
            branch=branch,
        )
    except requests.RequestException as exc:
        return {
            "status": VersionStatus.NO_REMOTE,
            "local_date": local_date,
            "remote_date": "",
            "local_tickers": local_tickers,
            "num_local": len(results),
            "num_remote": 0,
            "differences": [],
            "error": f"DoltHub query failed: {exc}",
        }

    rows = resp.get("rows", [])
    if not rows:
        return {
            "status": VersionStatus.NO_REMOTE,
            "local_date": local_date,
            "remote_date": "",
            "local_tickers": local_tickers,
            "num_local": len(results),
            "num_remote": 0,
            "differences": [],
        }

    remote_version = rows[0]
    remote_date = remote_version.get("trade_date", "")
    remote_hash = remote_version.get("tickers_hash", "")

    # 3. Compare dates
    if remote_date != local_date:
        return {
            "status": VersionStatus.DATE_MISMATCH,
            "local_date": local_date,
            "remote_date": remote_date,
            "local_tickers": local_tickers,
            "num_local": len(results),
            "num_remote": remote_version.get("num_signals", 0),
            "differences": [],
        }

    # 4. Compare tickers hash
    if remote_hash != local_hash:
        return {
            "status": VersionStatus.TICKERS_MISMATCH,
            "local_date": local_date,
            "remote_date": remote_date,
            "local_tickers": local_tickers,
            "num_local": len(results),
            "num_remote": remote_version.get("num_signals", 0),
            "differences": [],
        }

    # 5. Compare individual signals
    try:
        signals_resp = query_dolthub(
            f"SELECT * FROM ta_signals WHERE trade_date = '{local_date}'",
            repo=repo,
            branch=branch,
        )
        remote_signals = {r["symbol"]: r for r in signals_resp.get("rows", [])}
    except requests.RequestException:
        remote_signals = {}

    differences = []
    for r in results:
        ticker = r.get("ticker", "")
        remote = remote_signals.get(ticker)
        if remote is None:
            differences.append({
                "ticker": ticker,
                "field": "missing_remote",
                "local": r.get("decision", ""),
                "remote": None,
            })
        elif (
            int(r.get("ai_score", 0)) != int(remote.get("ai_score", 0))
            or int(r.get("trader_action", 0)) != int(remote.get("trader_action", 0))
            or int(r.get("research_rating", 0)) != int(remote.get("research_rating", 0))
        ):
            differences.append({
                "ticker": ticker,
                "field": "signal_mismatch",
                "local": {
                    "ai_score": r.get("ai_score", 0),
                    "trader_action": r.get("trader_action", 0),
                    "research_rating": r.get("research_rating", 0),
                },
                "remote": {
                    "ai_score": int(remote.get("ai_score", 0)),
                    "trader_action": int(remote.get("trader_action", 0)),
                    "research_rating": int(remote.get("research_rating", 0)),
                },
            })

    status = VersionStatus.MATCH if not differences else VersionStatus.DIVERGED
    return {
        "status": status,
        "local_date": local_date,
        "remote_date": remote_date,
        "local_tickers": local_tickers,
        "num_local": len(results),
        "num_remote": len(remote_signals),
        "differences": differences,
        "remote_version_id": remote_version.get("version_id", ""),
        "remote_created_at": remote_version.get("created_at", ""),
    }


# ── Public API ─────────────────────────────────────────────────────────────
def ta_dolt_push(
    results_path: str | None = None,
    push: bool = True,
    keep_tmp: bool = False,
    fresh_clone: bool = False,
    model_name: str = "deepseek-v4-flash",
    analysts: str = "market,social,news,fundamentals",
) -> TAPublishResult | None:
    """Publish TA AI signals to DoltHub.

    Reads ``batch_20_results.json``, filters out errors, builds signal
    and version DataFrames, exports to CSV, then clones/pulls the DoltHub
    repo, creates/updates tables, commits and pushes.

    Uses a persistent local repo at ``~/.dolt/ta_publisher/tradingagents/``
    to avoid re-cloning the entire remote on every run.  Subsequent runs
    only pull the diff (seconds instead of minutes).

    Parameters
    ----------
    results_path:
        Path to ``batch_20_results.json``.  ``None`` auto-discovers.
    push:
        If ``True``, push to DoltHub after committing.
    keep_tmp:
        Keep temp directory after completion (for debugging).
    fresh_clone:
        If ``True``, delete the persistent local repo and re-clone
        from scratch.  Use when the local repo is corrupted or out
        of sync.
    model_name:
        LLM model name to record in the signal metadata.
    analysts:
        Comma-separated analyst list to record.

    Returns
    -------
    TAPublishResult or None
        Summary stats, or ``None`` if no valid signals found.
    """
    dolt_exe = _find_dolt()
    if not dolt_exe:
        raise FileNotFoundError(
            "dolt not found. Install: winget install DoltHub.Dolt"
        )

    print(f"  Dolt: {dolt_exe}")
    print(f"  Remote: {DOLTHUB_REMOTE}")
    print(f"  Push: {push}")

    # Step 1: Load results
    print(f"\n{'='*60}")
    print("  Load TA results")
    print(f"{'='*60}")
    results = load_ta_results(results_path)
    if not results:
        print("  No TA results to publish.")
        return None

    # Step 2: Build DataFrames
    print(f"\n{'='*60}")
    print("  Build signal DataFrames")
    print(f"{'='*60}")
    signals_df = build_signals_df(results, model_name=model_name, analysts=analysts)
    version = build_version_record(results, model_name=model_name, analysts=analysts)
    version_df = pd.DataFrame([version])

    print(f"  Signals: {len(signals_df)} rows")
    print(f"  Version: {version['version_id']}")
    print(f"  Trade date: {version['trade_date']}")

    # Step 3: Generate CSV and publish
    tmpdir = tempfile.mkdtemp(prefix="ta_dolt_")
    print(f"  Temp dir: {tmpdir}")

    try:
        signals_csv = os.path.join(tmpdir, "ta_signals.csv")
        version_csv = os.path.join(tmpdir, "ta_signal_version.csv")
        signals_df.to_csv(signals_csv, index=False)
        version_df.to_csv(version_csv, index=False)
        print(f"  CSV: {signals_csv}")
        print(f"  CSV: {version_csv}")

        result = _dolt_publish_ta(dolt_exe, signals_csv, version_csv, push=push, fresh_clone=fresh_clone)
        return result
    finally:
        if not keep_tmp:
            shutil.rmtree(tmpdir, ignore_errors=True)
            print(f"\n  Cleaned up temp dir: {tmpdir}")
        else:
            print(f"\n  Temp dir kept: {tmpdir}")
