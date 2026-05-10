"""Publish TradingAgents cached OHLCV data to DoltHub.

Reads deduplicated cache CSVs from ``~/.tradingagents/cache``, converts to
DoltHub-compatible CSV format, and publishes via ``dolt`` CLI.

Target: https://www.dolthub.com/repositories/rickqi/tradingagents

Tables created:
  a_stock_eod_price   — Daily OHLCV + Adj Close (PK: tradedate, symbol)
  trade_calendar      — Trading calendar          (PK: trade_date)
  stock_list          — Stock universe with dates  (PK: symbol)

Usage::

    from tradingagents.qlib.dolt_publisher import dolt_push

    dolt_push()                           # all cached tickers
    dolt_push(tickers=["000858.SZ"])      # specific tickers
    dolt_push(push=False)                 # local commit only

Prerequisites:
  1. Dolt installed:     winget install DoltHub.Dolt
  2. Dolt authenticated:  dolt login
  3. Repo exists:        https://www.dolthub.com/repositories/rickqi/tradingagents
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from tradingagents.qlib.cache_scanner import CachedOHLCV, scan_cache


# ── Configuration ──────────────────────────────────────────────────────────
_DOLT_EXE_CANDIDATES = [
    r"C:\Program Files\Dolt\bin\dolt.exe",
    "dolt",  # rely on PATH
]
DOLTHUB_REMOTE = "rickqi/tradingagents"
CHUNK_ROWS = 500_000


# ── Result ─────────────────────────────────────────────────────────────────
@dataclass
class DoltPublishResult:
    """Summary statistics for a Dolt publish run."""

    total_instruments: int
    total_rows: int
    pushed: bool
    commit_hash: str = ""
    repo_dir: str = ""


# ── Table schemas ──────────────────────────────────────────────────────────
TABLE_SCHEMAS = {
    "a_stock_eod_price": """
        CREATE TABLE IF NOT EXISTS a_stock_eod_price (
            tradedate  DATE NOT NULL,
            symbol     VARCHAR(20) NOT NULL,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     DOUBLE,
            adjclose   DOUBLE,
            vendor     VARCHAR(20),
            PRIMARY KEY (tradedate, symbol)
        )
    """,
    "trade_calendar": """
        CREATE TABLE IF NOT EXISTS trade_calendar (
            trade_date VARCHAR(20) NOT NULL,
            is_open    INT,
            PRIMARY KEY (trade_date)
        )
    """,
    "stock_list": """
        CREATE TABLE IF NOT EXISTS stock_list (
            symbol     VARCHAR(20) NOT NULL,
            start_date VARCHAR(20),
            end_date   VARCHAR(20),
            vendor     VARCHAR(20),
            PRIMARY KEY (symbol)
        )
    """,
}


# ── Dolt CLI wrapper ───────────────────────────────────────────────────────
def _find_dolt() -> str:
    """Locate the dolt executable."""
    for candidate in _DOLT_EXE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        # Check if on PATH
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


# ── Step 1: Deduplicate cache + read best CSVs ────────────────────────────
def _deduplicate_cache(
    cached_files: list[CachedOHLCV],
) -> list[CachedOHLCV]:
    """Keep only the best file per Qlib instrument (most rows, latest end_date)."""
    best: dict[str, CachedOHLCV] = {}
    for c in cached_files:
        key = c.qlib_instrument or c.ticker.upper()
        existing = best.get(key)
        if existing is None:
            best[key] = c
        elif c.num_rows > existing.num_rows:
            best[key] = c
        elif c.num_rows == existing.num_rows and c.date_end > existing.date_end:
            best[key] = c
    return list(best.values())


def read_cache_to_frames(
    tickers: list[str] | None = None,
    cache_dir: str | None = None,
) -> tuple[pd.DataFrame, list[str], list[dict]]:
    """Read deduplicated cache CSVs into DataFrames.

    Returns:
        price_df:   (tradedate, symbol, open, high, low, close, volume, adjclose, vendor)
        calendar:   sorted list of unique date strings
        stock_list: list of dicts {symbol, start_date, end_date, vendor}
    """
    cached_files = scan_cache(cache_dir=cache_dir)
    if not cached_files:
        return pd.DataFrame(), [], []

    # Filter by tickers
    if tickers is not None:
        ticker_set = {t.upper() for t in tickers}
        cached_files = [f for f in cached_files if f.ticker.upper() in ticker_set]

    if not cached_files:
        return pd.DataFrame(), [], []

    # Deduplicate
    best_files = _deduplicate_cache(cached_files)
    print(f"  Deduplicated: {len(best_files)} instruments from {len(cached_files)} cache files")

    dfs: list[pd.DataFrame] = []
    stock_list: list[dict] = []
    all_dates: set[str] = set()

    t0 = time.time()
    for i, cached in enumerate(best_files):
        try:
            df = pd.read_csv(cached.file_path, encoding="utf-8", on_bad_lines="skip")
        except Exception as exc:
            print(f"  Warning: failed to read {cached.file_path.name}: {exc}")
            continue

        if df.empty:
            continue

        # Normalize columns
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        elif "date" not in df.columns:
            first_col = df.columns[0]
            df = df.rename(columns={first_col: "date"})

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df = df.dropna(subset=["date"])

        if df.empty:
            continue

        # Determine symbol in Qlib format
        symbol = cached.qlib_instrument or cached.ticker.upper()

        # Build output row
        row = {"tradedate": df["date"], "symbol": symbol, "vendor": cached.vendor}
        for col in ["Open", "open"]:
            if col in df.columns:
                row["open"] = df[col].astype(float)
                break
        for col in ["High", "high"]:
            if col in df.columns:
                row["high"] = df[col].astype(float)
                break
        for col in ["Low", "low"]:
            if col in df.columns:
                row["low"] = df[col].astype(float)
                break
        for col in ["Close", "close"]:
            if col in df.columns:
                row["close"] = df[col].astype(float)
                break
        for col in ["Volume", "volume"]:
            if col in df.columns:
                row["volume"] = df[col].astype(float)
                break
        # Adj Close
        if "Adj Close" in df.columns:
            row["adjclose"] = df["Adj Close"].astype(float)
        else:
            row["adjclose"] = row.get("close", pd.Series(dtype=float))

        stock_df = pd.DataFrame(row)
        # Drop rows where close is NaN (non-trading days)
        stock_df = stock_df.dropna(subset=["close"])
        dfs.append(stock_df)

        # Track dates
        all_dates.update(stock_df["tradedate"].tolist())

        # Stock list entry
        stock_list.append({
            "symbol": symbol,
            "start_date": stock_df["tradedate"].min(),
            "end_date": stock_df["tradedate"].max(),
            "vendor": cached.vendor,
        })

        if (i + 1) % 100 == 0 or i == len(best_files) - 1:
            rows_so_far = sum(len(d) for d in dfs)
            elapsed = time.time() - t0
            print(f"  Read {i+1}/{len(best_files)} stocks | {rows_so_far:,} rows | {elapsed:.1f}s")

    price_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    calendar = sorted(all_dates)
    print(f"\n  Total: {len(price_df):,} rows from {len(dfs)} instruments")

    return price_df, calendar, stock_list


# ── Step 2: Generate CSV chunks ────────────────────────────────────────────
def _generate_csvs(
    price_df: pd.DataFrame,
    calendar: list[str],
    stock_list: list[dict],
    tmpdir: str,
    chunk_size: int = CHUNK_ROWS,
) -> list[tuple[str, str, bool]]:
    """Export DataFrames to chunked CSV files for dolt import.

    Returns list of (table_name, csv_path, is_first_for_table) tuples.
    """
    csv_files: list[tuple[str, str, bool]] = []

    # 2a. Stock price data — chunked
    n_total = len(price_df)
    n_chunks = max(1, (n_total + chunk_size - 1) // chunk_size)
    print(f"\n  Price data: {n_total:,} rows -> {n_chunks} chunk(s) of <={chunk_size:,} rows")

    for i in range(n_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, n_total)
        chunk_df = price_df.iloc[start:end]
        path = os.path.join(tmpdir, f"price_{i:04d}.csv")
        chunk_df.to_csv(path, index=False)
        csv_files.append(("a_stock_eod_price", path, i == 0))
        print(f"    chunk {i+1}/{n_chunks}: {len(chunk_df):,} rows -> {os.path.basename(path)}")

    # 2b. Calendar
    cal_df = pd.DataFrame({"trade_date": calendar, "is_open": 1})
    cal_path = os.path.join(tmpdir, "calendar.csv")
    cal_df.to_csv(cal_path, index=False)
    csv_files.append(("trade_calendar", cal_path, True))
    print(f"    calendar: {len(cal_df)} rows")

    # 2c. Stock list
    sl_df = pd.DataFrame(stock_list)
    sl_path = os.path.join(tmpdir, "stock_list.csv")
    sl_df.to_csv(sl_path, index=False)
    csv_files.append(("stock_list", sl_path, True))
    print(f"    stock_list: {len(sl_df)} rows")

    return csv_files


# ── Step 3: Dolt clone + schema + import + commit + push ───────────────────
def _dolt_publish(
    dolt_exe: str,
    csv_files: list[tuple[str, str, bool]],
    tmpdir: str,
    push: bool = True,
) -> DoltPublishResult:
    """Clone DoltHub repo, create tables, import CSV, commit, and push."""
    repo_dir = os.path.join(tmpdir, "tradingagents")
    # Count instruments from stock_list CSV (not price chunks)
    total_instruments = 0
    for t, p, _ in csv_files:
        if t == "stock_list":
            total_instruments = sum(1 for _ in open(p, encoding="utf-8")) - 1  # minus header
    total_rows = 0

    # 3a. Clone or init
    print(f"\n{'='*60}")
    print("Step 3: Initialize Dolt repo")
    print(f"{'='*60}")
    if os.path.isdir(repo_dir):
        shutil.rmtree(repo_dir, ignore_errors=True)
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

    # 3b. Create tables with explicit schema
    print(f"\n{'='*60}")
    print("Step 4: Create tables")
    print(f"{'='*60}")
    for table_name, ddl in TABLE_SCHEMAS.items():
        _dolt(dolt_exe, "sql", "-q", ddl.strip(), cwd=repo_dir)
        print(f"  Created: {table_name}")

    # 3c. Import CSV chunks
    print(f"\n{'='*60}")
    print("Step 5: Import data")
    print(f"{'='*60}")
    for table_name, csv_path, _is_first in csv_files:
        print(f"\n  Importing {os.path.basename(csv_path)} -> {table_name}")
        _dolt(dolt_exe, "table", "import", "-u", table_name, csv_path, cwd=repo_dir)
        if table_name == "a_stock_eod_price":
            chunk_df = pd.read_csv(csv_path, nrows=0)
            total_rows += sum(1 for _ in open(csv_path, encoding="utf-8")) - 1

    # 3d. Commit
    print(f"\n{'='*60}")
    print("Step 6: Commit")
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
            f"A-share daily OHLCV data import ({total_rows:,} rows)",
            cwd=repo_dir,
        )
        # Parse commit hash from "commit <hash>" line in dolt log output
        # Dolt may emit ANSI color codes, so strip them
        import re
        log_r = _dolt(dolt_exe, "log", "-n", "1", cwd=repo_dir, check=False)
        for line in (log_r.stdout or "").splitlines():
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if clean.startswith("commit "):
                commit_hash = clean.split()[1][:12]
                break
        print(f"  Committed: {commit_hash}")

    # 3e. Push
    if push:
        print(f"\n{'='*60}")
        print("Step 7: Push to DoltHub")
        print(f"{'='*60}")
        br_result = _dolt(dolt_exe, "branch", "--show-current", cwd=repo_dir, check=False)
        branch = (br_result.stdout or "").strip() or "main"
        _dolt(dolt_exe, "push", "-u", "origin", branch, cwd=repo_dir)
        print(f"\n  DONE! -> https://www.dolthub.com/repositories/{DOLTHUB_REMOTE}")
    else:
        print("\n  [--no-push] Skipping push. Data committed locally.")
        print(f"  Repo: {repo_dir}")
        br_result = _dolt(dolt_exe, "branch", "--show-current", cwd=repo_dir, check=False)
        branch = (br_result.stdout or "").strip() or "main"
        print(f"  To push: cd {repo_dir} && {dolt_exe} push -u origin {branch}")

    return DoltPublishResult(
        total_instruments=total_instruments,
        total_rows=total_rows,
        pushed=push,
        commit_hash=commit_hash,
        repo_dir=repo_dir,
    )


# ── Public API ─────────────────────────────────────────────────────────────
def dolt_push(
    tickers: list[str] | None = None,
    cache_dir: str | None = None,
    push: bool = True,
    chunk_size: int = CHUNK_ROWS,
    keep_tmp: bool = False,
) -> DoltPublishResult:
    """Publish cached OHLCV data to DoltHub.

    Parameters
    ----------
    tickers:
        Filter to these tickers (``None`` = all cached).
    cache_dir:
        Override cache directory.
    push:
        If ``True``, push to DoltHub after committing. If ``False``, only
        commit locally.
    chunk_size:
        Rows per CSV chunk for dolt import.
    keep_tmp:
        Keep temp directory after completion (for debugging).

    Returns:
        DoltPublishResult with stats.
    """
    dolt_exe = _find_dolt()
    if not dolt_exe:
        raise FileNotFoundError(
            "dolt not found. Install: winget install DoltHub.Dolt"
        )

    print(f"  Dolt: {dolt_exe}")
    print(f"  Remote: {DOLTHUB_REMOTE}")
    print(f"  Push: {push}")

    # Step 1-2: Read cache + generate CSV
    print(f"\n{'='*60}")
    print("Step 1-2: Read cache -> CSV")
    print(f"{'='*60}")
    price_df, calendar, stock_list = read_cache_to_frames(tickers, cache_dir)

    if price_df.empty:
        print("No data to publish.")
        return DoltPublishResult(
            total_instruments=0, total_rows=0, pushed=False,
        )

    tmpdir = tempfile.mkdtemp(prefix="dolt_publish_")
    print(f"  Temp dir: {tmpdir}")

    try:
        csv_files = _generate_csvs(price_df, calendar, stock_list, tmpdir, chunk_size)
        result = _dolt_publish(dolt_exe, csv_files, tmpdir, push=push)
        return result
    finally:
        if not keep_tmp:
            shutil.rmtree(tmpdir, ignore_errors=True)
            print(f"\n  Cleaned up temp dir: {tmpdir}")
        else:
            print(f"\n  Temp dir kept: {tmpdir}")
