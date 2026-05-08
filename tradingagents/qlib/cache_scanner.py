"""TradingAgents cache scanner — discover and catalog cached OHLCV files.

Scans the TradingAgents data cache directory (``~/.tradingagents/cache`` by
default) for OHLCV CSV files produced by the three data vendors:

- **YFin** (yfinance) — ``{ticker}-YFin-data-{start}-{end}.csv``
- **Tencent** (tencent_sina) — ``{ticker}-Tencent-data-{start}-{end}.csv``
- **AKShare** (akshare) — ``{ticker}-AKShare-data-{start}-{end}.csv``

Returns structured :class:`CachedOHLCV` metadata for each file — no pandas
or numpy required; scanning is intentionally lightweight.

Usage::

    from tradingagents.qlib.cache_scanner import scan_cache, print_scan_summary

    cached = scan_cache()
    print_scan_summary(cached)

    # Filter to specific tickers
    from tradingagents.qlib.cache_scanner import scan_cache_for_tickers
    subset = scan_cache_for_tickers(["000858.SZ", "NVDA"])
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.qlib.ticker_mapper import to_qlib_instrument


# ---------------------------------------------------------------------------
# Vendor tag → (glob pattern, filename separator)
# ---------------------------------------------------------------------------
_VENDOR_SPECS: list[tuple[str, str]] = [
    ("YFin", "-YFin-data-"),
    ("Tencent", "-Tencent-data-"),
    ("AKShare", "-AKShare-data-"),
]


def _count_data_rows(path: Path) -> int:
    """Count CSV data rows (excluding header) without loading the file."""
    count = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        next(fh, None)  # skip header
        for _ in fh:
            count += 1
    return count


def _parse_filename(stem: str) -> Optional[tuple[str, str, str, str]]:
    """Extract (ticker, vendor, date_start, date_end) from a cache filename stem.

    Returns ``None`` if the filename does not match any known vendor pattern.
    """
    for vendor, sep in _VENDOR_SPECS:
        parts = stem.split(sep, 1)
        if len(parts) != 2:
            continue
        ticker = parts[0]
        remainder = parts[1]
        # remainder should be "{start_date}-{end_date}"
        # Date format is YYYY-MM-DD, so split from the right to handle
        # the case where start_date also contains dashes.
        # Pattern: "2021-05-08-2026-05-08" → split into two 10-char dates
        if len(remainder) < 21:  # "YYYY-MM-DD-YYYY-MM-DD" = 21 chars
            continue
        # The format is fixed: first 10 chars = start date, char 10 = '-', last 10 = end date
        date_start = remainder[:10]
        dash = remainder[10]
        date_end = remainder[11:21]
        if dash != "-" or len(date_start) != 10 or len(date_end) != 10:
            continue
        return ticker, vendor, date_start, date_end
    return None


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------
@dataclass
class CachedOHLCV:
    """Metadata for a single cached OHLCV file."""

    ticker: str  # TradingAgents format: "000858.SZ", "NVDA"
    file_path: Path  # Absolute path to CSV
    vendor: str  # "YFin" | "Tencent" | "AKShare"
    date_start: str  # "2021-05-08"
    date_end: str  # "2026-05-08"
    qlib_instrument: str  # "SZ000858", "NVDA"
    num_rows: int  # Number of data rows (header excluded)


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------
def scan_cache(cache_dir: str | None = None) -> list[CachedOHLCV]:
    """Scan the TradingAgents cache directory for OHLCV CSV files.

    Parameters
    ----------
    cache_dir:
        Override the default cache directory.  When ``None``, reads
        ``data_cache_dir`` from :data:`DEFAULT_CONFIG` (defaults to
        ``~/.tradingagents/cache``, overridable via
        ``TRADINGAGENTS_CACHE_DIR`` env var).

    Returns
    -------
    list[CachedOHLCV]
        Sorted by ``(ticker, vendor)``.  Files with unrecognized names are
        silently skipped.
    """
    if cache_dir is None:
        cache_dir = DEFAULT_CONFIG["data_cache_dir"]

    cache_path = Path(cache_dir)
    if not cache_path.is_dir():
        return []

    results: list[CachedOHLCV] = []

    for vendor_tag, sep in _VENDOR_SPECS:
        pattern = f"*{sep}*.csv"
        for csv_file in cache_path.glob(pattern):
            parsed = _parse_filename(csv_file.stem)
            if parsed is None:
                continue

            ticker, vendor, date_start, date_end = parsed

            try:
                num_rows = _count_data_rows(csv_file)
            except OSError:
                continue

            try:
                qlib_inst = to_qlib_instrument(ticker)
            except (ValueError, KeyError):
                qlib_inst = ""

            results.append(
                CachedOHLCV(
                    ticker=ticker,
                    file_path=csv_file.resolve(),
                    vendor=vendor,
                    date_start=date_start,
                    date_end=date_end,
                    qlib_instrument=qlib_inst,
                    num_rows=num_rows,
                )
            )

    results.sort(key=lambda r: (r.ticker.upper(), r.vendor))
    return results


def scan_cache_for_tickers(
    tickers: list[str],
    cache_dir: str | None = None,
) -> list[CachedOHLCV]:
    """Scan the cache, keeping only entries matching *tickers*.

    Matching is **case-insensitive** so that ``"000858.sz"`` matches
    ``"000858.SZ"``.

    Parameters
    ----------
    tickers:
        List of ticker strings in TradingAgents format.
    cache_dir:
        Passed through to :func:`scan_cache`.

    Returns
    -------
    list[CachedOHLCV]
        Filtered results, still sorted by ``(ticker, vendor)``.
    """
    all_cached = scan_cache(cache_dir)
    lookup = {t.upper() for t in tickers}
    return [r for r in all_cached if r.ticker.upper() in lookup]


# ---------------------------------------------------------------------------
# Pretty-print summary
# ---------------------------------------------------------------------------
def print_scan_summary(cached: list[CachedOHLCV]) -> None:
    """Print a human-readable summary of cached OHLCV files.

    Uses only standard ``print`` — no external formatting dependency.
    """
    if not cached:
        print("No cached OHLCV files found.")
        return

    total = len(cached)
    unique_tickers = sorted({r.ticker for r in cached})
    vendors_used = sorted({r.vendor for r in cached})

    print(f"Cache scan results: {total} file(s), {len(unique_tickers)} ticker(s)")
    print(f"Vendors: {', '.join(vendors_used)}")
    print()

    # Per-ticker coverage
    from collections import defaultdict

    by_ticker: dict[str, list[CachedOHLCV]] = defaultdict(list)
    for r in cached:
        by_ticker[r.ticker].append(r)

    print(f"{'Ticker':<16} {'Qlib Inst':<14} {'Vendor':<10} {'Rows':>8} {'Date Range':<24}")
    print("-" * 74)
    for ticker in unique_tickers:
        entries = by_ticker[ticker]
        for i, entry in enumerate(entries):
            ticker_col = ticker if i == 0 else ""
            inst_col = entry.qlib_instrument if i == 0 else ""
            print(
                f"{ticker_col:<16} {inst_col:<14} {entry.vendor:<10} "
                f"{entry.num_rows:>8} {entry.date_start} ~ {entry.date_end}"
            )
        if len(entries) > 1:
            print()
