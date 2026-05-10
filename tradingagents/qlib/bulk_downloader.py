"""Bulk download OHLCV data for A-share stocks via Tencent K-line API.

Uses existing ``tencent_sina`` vendor internals (``_fetch_tencent_kline``,
``_kline_to_dataframe``, ``_save_to_cache``) combined with the rate limiter
and cache scanner for incremental skip.

Output: TradingAgents cache CSV files compatible with ``tradingagents qlib convert``.

Usage::

    from tradingagents.qlib.bulk_downloader import bulk_download, fetch_stock_universe

    # Download all active A-shares (skipping already-cached tickers)
    result = bulk_download()

    # Download specific tickers
    result = bulk_download(tickers=["600519.SH", "000858.SZ"])

    # Fetch universe without downloading
    tickers = fetch_stock_universe()
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from tradingagents.dataflows.rate_limiter import get_rate_limiter
from tradingagents.dataflows.tencent_sina import (
    _fetch_tencent_kline,
    _kline_to_dataframe,
    _save_to_cache,
    _tencent_symbol,
)
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.qlib.cache_scanner import scan_cache

logger = logging.getLogger(__name__)

# Minimum date for cached data — data before this is discarded.
_CUTOFF_DATE = "2020-01-01"

# East Money stock list API — same endpoint as scripts/turnover_screener.py
_EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://eastmoney.com",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BulkDownloadResult:
    """Summary statistics for a bulk download run."""

    total: int  # total tickers attempted
    downloaded: int  # new downloads
    skipped: int  # already cached (and skipped)
    failed: int  # errors
    failed_tickers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stock universe fetching
# ---------------------------------------------------------------------------

def fetch_stock_universe(
    source: str = "eastmoney",
    stock_list_file: str | None = None,
) -> list[str]:
    """Return a list of active A-share ticker strings.

    Parameters
    ----------
    source:
        Data source for the universe.  Currently only ``"eastmoney"`` is
        supported.
    stock_list_file:
        Optional path to a text file with one ticker per line.  When
        provided, the file is read and returned directly (``source`` is
        ignored).  Supports ``.SH`` / ``.SZ`` suffixes; pure 6-digit codes
        are auto-suffixed based on the first digit.

    Returns
    -------
    list[str]
        Ticker strings like ``["600519.SH", "000858.SZ", ...]``.
    """
    # --- File-based universe ---
    if stock_list_file is not None:
        tickers: list[str] = []
        with open(stock_list_file, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                ticker = _normalize_file_ticker(line)
                if ticker:
                    tickers.append(ticker)
        return tickers

    # --- East Money API ---
    if source != "eastmoney":
        raise ValueError(f"Unsupported universe source: {source!r}")

    params = {
        "pn": 1,
        "pz": 6000,  # single page large enough for all A-shares
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",  # sort by change percent
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f12,f13,f14",
    }

    for attempt in range(3):
        try:
            resp = requests.get(
                _EASTMONEY_CLIST_URL,
                params=params,
                headers=_EASTMONEY_HEADERS,
                timeout=60,
            )
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt < 2:
                logger.warning(
                    "East Money universe fetch failed (attempt %d/3): %s — retrying in 5s",
                    attempt + 1, exc,
                )
                time.sleep(5)
            else:
                raise
    payload = resp.json()

    items = payload.get("data", {}).get("diff", [])
    tickers = []
    for item in items:
        market = item.get("f13", 0)
        code = str(item.get("f12", ""))
        name = str(item.get("f14", ""))
        # Skip ST / delisted stocks
        if "ST" in name or "退" in name:
            continue
        suffix = ".SH" if market == 1 else ".SZ"
        tickers.append(code + suffix)

    return tickers


def _normalize_file_ticker(raw: str) -> str | None:
    """Normalize a ticker from a stock-list file.

    Accepts ``600519``, ``600519.SH``, ``sh600519``, etc.
    Returns ``None`` for unrecognised lines.
    """
    t = raw.strip().strip('"').strip("'")
    if not t:
        return None

    # Already has suffix
    if t.endswith((".SH", ".SZ", ".SS")):
        # Normalise .SS → .SH (Sina convention)
        return t.replace(".SS", ".SH")

    # Prefix style: sh600183, sz000858
    low = t.lower()
    if low.startswith("sh"):
        code = t[2:]
        return f"{code}.SH" if code.isdigit() else None
    if low.startswith("sz"):
        code = t[2:]
        return f"{code}.SZ" if code.isdigit() else None

    # Pure 6-digit code — infer exchange
    if t.isdigit() and len(t) == 6:
        if t.startswith("6"):
            return f"{t}.SH"
        return f"{t}.SZ"

    return None


# ---------------------------------------------------------------------------
# Core bulk download
# ---------------------------------------------------------------------------

def bulk_download(
    tickers: list[str] | None = None,
    stock_list_file: str | None = None,
    cache_dir: str | None = None,
    skip_existing: bool = True,
    start_from: int = 0,
    batch_size: int = 20,
    batch_pause: float = 10.0,
) -> BulkDownloadResult:
    """Bulk download OHLCV data for A-share tickers.

    Parameters
    ----------
    tickers:
        Explicit ticker list.  When ``None``, the full A-share universe is
        fetched via :func:`fetch_stock_universe`.
    stock_list_file:
        Path to a text file with tickers (one per line).  Passed through to
        :func:`fetch_stock_universe` when *tickers* is ``None``.
    cache_dir:
        Override cache directory.  ``None`` uses the default from config.
    skip_existing:
        If ``True``, tickers already present in the cache are skipped.
    start_from:
        Resume from the N-th ticker (0-based).  Useful for restarting a
        failed run.
    batch_size:
        Number of tickers between pause pauses.
    batch_pause:
        Seconds to sleep between batches.

    Returns
    -------
    BulkDownloadResult
    """
    limiter = get_rate_limiter()

    # Resolve cache directory
    if cache_dir is None:
        from tradingagents.dataflows.config import get_config
        cfg = get_config()
        cache_dir = cfg.get("data_cache_dir", "")
    if not cache_dir:
        cache_dir = str(Path.home() / ".tradingagents" / "cache")

    # --- Build ticker list ---
    if tickers is not None:
        ticker_list = list(tickers)
    else:
        print("Fetching A-share stock universe from East Money...")
        ticker_list = fetch_stock_universe(
            stock_list_file=stock_list_file,
        )
    total = len(ticker_list)
    print(f"Total tickers: {total}")

    # --- Identify already-cached tickers ---
    cached_tickers: set[str] = set()
    if skip_existing:
        cached = scan_cache(cache_dir=cache_dir)
        cached_tickers = {r.ticker.upper() for r in cached}
        print(f"Already cached: {len(cached_tickers)} tickers")

    # --- Date range ---
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = _CUTOFF_DATE

    # Apply start_from offset
    if start_from > 0:
        print(f"Resuming from ticker #{start_from}")
        ticker_list = ticker_list[start_from:]

    # --- Download loop ---
    result = BulkDownloadResult(
        total=total, downloaded=0, skipped=0, failed=0,
    )
    batch_count = 0

    for idx, ticker in enumerate(ticker_list, start=1):
        global_idx = start_from + idx

        # Skip already cached
        if skip_existing and ticker.upper() in cached_tickers:
            result.skipped += 1
            continue

        try:
            rows = _download_one(ticker, start_date, end_date, limiter)
            if rows is not None:
                result.downloaded += 1
                print(f"[{global_idx}/{total}] {ticker}: {rows} rows downloaded")
            else:
                result.failed += 1
                result.failed_tickers.append(ticker)
                print(f"[{global_idx}/{total}] {ticker}: no data returned")
        except Exception as exc:
            result.failed += 1
            result.failed_tickers.append(ticker)
            logger.warning("Failed to download %s: %s", ticker, exc)
            print(f"[{global_idx}/{total}] {ticker}: ERROR - {exc}")

        # Batch pause
        batch_count += 1
        if batch_count >= batch_size:
            batch_count = 0
            if batch_pause > 0 and idx < len(ticker_list):
                print(f"  ... pausing {batch_pause:.0f}s (batch boundary) ...")
                time.sleep(batch_pause)

    # --- Summary ---
    print()
    print(f"Bulk download complete: "
          f"{result.downloaded} downloaded, "
          f"{result.skipped} skipped, "
          f"{result.failed} failed "
          f"(total {result.total})")
    if result.failed_tickers:
        preview = ", ".join(result.failed_tickers[:20])
        suffix = "..." if len(result.failed_tickers) > 20 else ""
        print(f"Failed tickers: {preview}{suffix}")

    return result


def _download_one(
    ticker: str,
    start_date: str,
    end_date: str,
    limiter,
) -> int | None:
    """Download OHLCV for a single ticker via Tencent K-line API.

    Returns the number of rows saved, or ``None`` on empty data.
    """
    # Resolve Tencent symbol (e.g. "sh600183")
    try:
        sym = _tencent_symbol(ticker)
    except ValueError as exc:
        logger.warning("Cannot resolve symbol for %s: %s", ticker, exc)
        return None

    # Fetch unadjusted K-line
    limiter.wait("tencent_sina")
    raw_unadj = _fetch_tencent_kline(sym, days=1600, fq="")

    if not raw_unadj:
        return None

    # Fetch forward-adjusted K-line for real Adj Close
    limiter.wait("tencent_sina")
    raw_qfq = _fetch_tencent_kline(sym, days=1600, fq="qfq")

    # Build DataFrame with Adj Close
    df = _kline_to_dataframe(raw_unadj, qfq_rows=raw_qfq)
    if df.empty:
        return None

    # Filter to cutoff date
    df["Date"] = df["Date"].astype(str)
    df = df[df["Date"] >= start_date]
    if df.empty:
        return None

    # Round prices
    for col in ["Open", "High", "Low", "Close", "Adj Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    # Reorder columns to match yfinance / cache format
    cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    df = df[cols]

    csv_string = df.to_csv(index=False)
    num_rows = len(df)

    # Save to cache
    _save_to_cache(ticker, start_date, end_date, csv_string, num_rows)

    return num_rows
