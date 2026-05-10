"""
Merge two Qlib data directories into a unified one.

- Source 1 (cn_data / qlib_bin): Full A-share market data (6,091 stocks, 6,381 days, 10 features)
- Source 2 (tradingagents): 20 target stocks with 4 AI signal features (ai_score, trader_action, research_rating, price_target)

Output: ~/.qlib/qlib_data/cn_data/
  - cn_data calendar, instruments, and all feature binaries (copied as-is)
  - 4 additional AI signal feature binaries for the 20 overlapping stocks (re-indexed to cn_data calendar)
"""

import os
import shutil
import time
import numpy as np


def load_calendar(path: str) -> list[str]:
    """Load calendar dates from a day.txt file."""
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]


def load_instruments(path: str) -> dict[str, tuple[str, str]]:
    """Load instruments from all.txt. Returns {SYMBOL: (start_date, end_date)}."""
    instruments = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                instruments[parts[0]] = (parts[1], parts[2])
    return instruments


def find_signal_stocks(ta_features_dir: str) -> list[str]:
    """Find stocks in tradingagents that have AI signal features."""
    signal_stocks = []
    for stock in sorted(os.listdir(ta_features_dir)):
        stock_dir = os.path.join(ta_features_dir, stock)
        if not os.path.isdir(stock_dir):
            continue
        if os.path.exists(os.path.join(stock_dir, "ai_score.day.bin")):
            signal_stocks.append(stock)
    return signal_stocks


def reindex_signal_bin(
    src_bin_path: str,
    ta_cal: list[str],
    cn_cal: list[str],
    cn_cal_lookup: dict[str, int],
) -> np.ndarray:
    """
    Read a signal .bin from tradingagents and re-index it to the cn_data calendar.

    Qlib binary format:
      - data[0] = start_index in the source calendar
      - data[1:] = float32 feature values for consecutive calendar days

    Re-indexing:
      1. Get the first date from tradingagents calendar: ta_cal[start_idx]
      2. Find that date's index in cn_data calendar
      3. Return new array with updated start_index and same feature values
    """
    data = np.fromfile(src_bin_path, dtype="<f4")
    if len(data) < 2:
        return None

    ta_start_idx = int(data[0])
    feature_values = data[1:]

    # Map tradingagents start date to cn_data calendar index
    ta_start_date = ta_cal[ta_start_idx]
    cn_start_idx = cn_cal_lookup.get(ta_start_date)

    if cn_start_idx is None:
        print(f"    WARNING: date {ta_start_date} not found in cn_data calendar, skipping")
        return None

    # Build new binary: new start_index + same feature values
    result = np.empty(1 + len(feature_values), dtype="<f4")
    result[0] = np.float32(cn_start_idx)
    result[1:] = feature_values
    return result


def main():
    start_time = time.time()
    home = os.path.expanduser("~")

    # Paths
    cn_dir = os.path.join(home, ".qlib", "qlib_data", "qlib_bin")
    ta_dir = os.path.join(home, ".qlib", "qlib_data", "tradingagents")
    out_dir = os.path.join(home, ".qlib", "qlib_data", "cn_data")

    SIGNAL_FEATURES = ["ai_score", "trader_action", "research_rating", "price_target"]

    # ── Step 1: Validate source directories ──────────────────────────────
    print("=" * 60)
    print("Qlib Data Merger")
    print("=" * 60)

    for path, label in [(cn_dir, "cn_data"), (ta_dir, "tradingagents")]:
        if not os.path.isdir(path):
            print(f"ERROR: {label} directory not found: {path}")
            return
    print(f"  cn_data source:      {cn_dir}")
    print(f"  tradingagents source: {ta_dir}")
    print(f"  Output directory:    {out_dir}")

    # ── Step 2: Load calendars ───────────────────────────────────────────
    print("\n[1/6] Loading calendars...")
    cn_cal_path = os.path.join(cn_dir, "calendars", "day.txt")
    ta_cal_path = os.path.join(ta_dir, "calendars", "day.txt")

    cn_cal = load_calendar(cn_cal_path)
    ta_cal = load_calendar(ta_cal_path)
    cn_cal_lookup = {date: idx for idx, date in enumerate(cn_cal)}

    print(f"  cn_data calendar:      {cn_cal[0]} ~ {cn_cal[-1]} ({len(cn_cal)} days)")
    print(f"  tradingagents calendar: {ta_cal[0]} ~ {ta_cal[-1]} ({len(ta_cal)} days)")

    # ── Step 3: Find signal stocks ───────────────────────────────────────
    print("\n[2/6] Identifying signal stocks...")
    ta_features_dir = os.path.join(ta_dir, "features")
    signal_stocks = find_signal_stocks(ta_features_dir)
    print(f"  Found {len(signal_stocks)} stocks with AI signals")

    # Verify all signal stocks exist in cn_data
    cn_features_dir = os.path.join(cn_dir, "features")
    cn_stocks = set(os.listdir(cn_features_dir))
    missing = [s for s in signal_stocks if s not in cn_stocks]
    if missing:
        print(f"  WARNING: {len(missing)} signal stocks not in cn_data: {missing}")
        signal_stocks = [s for s in signal_stocks if s in cn_stocks]
    print(f"  {len(signal_stocks)} signal stocks confirmed in cn_data")

    # ── Step 4: Copy cn_data as base ─────────────────────────────────────
    print("\n[3/6] Copying cn_data as base...")
    if os.path.exists(out_dir):
        print(f"  Removing existing output directory: {out_dir}")
        import stat
        def _remove_readonly(func, path, excinfo):
            """Handle read-only files on Windows."""
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(out_dir, onexc=_remove_readonly)

    shutil.copytree(cn_dir, out_dir)
    print(f"  Copied cn_data -> {out_dir}")

    # Verify copied stock count
    out_features_dir = os.path.join(out_dir, "features")
    out_stocks = os.listdir(out_features_dir)
    print(f"  {len(out_stocks)} stock directories copied")

    # ── Step 5: Re-index and write AI signal binaries ────────────────────
    print(f"\n[4/6] Merging AI signal features for {len(signal_stocks)} stocks...")
    total_signals_written = 0
    total_bytes_written = 0

    for i, stock in enumerate(signal_stocks):
        stock_out_dir = os.path.join(out_features_dir, stock)
        stock_ta_dir = os.path.join(ta_features_dir, stock)

        signals_for_stock = 0
        for feature in SIGNAL_FEATURES:
            src_bin = os.path.join(stock_ta_dir, f"{feature}.day.bin")
            if not os.path.exists(src_bin):
                print(f"    {stock}: {feature}.day.bin not found, skipping")
                continue

            reindexed = reindex_signal_bin(src_bin, ta_cal, cn_cal, cn_cal_lookup)
            if reindexed is None:
                continue

            dst_bin = os.path.join(stock_out_dir, f"{feature}.day.bin")
            reindexed.tofile(dst_bin)
            signals_for_stock += 1
            total_bytes_written += len(reindexed) * 4

        total_signals_written += signals_for_stock
        non_nan_counts = []
        for feature in SIGNAL_FEATURES:
            src_bin = os.path.join(stock_ta_dir, f"{feature}.day.bin")
            if os.path.exists(src_bin):
                data = np.fromfile(src_bin, dtype="<f4")
                non_nan_counts.append(f"{feature}={int((~np.isnan(data[1:])).sum())}")

        print(
            f"  [{i + 1:2d}/{len(signal_stocks)}] {stock}: "
            f"{signals_for_stock} signals written ({', '.join(non_nan_counts)})"
        )

    # ── Step 6: Update instruments (verify) ──────────────────────────────
    print(f"\n[5/6] Verifying instruments...")
    out_inst_path = os.path.join(out_dir, "instruments", "all.txt")
    instruments = load_instruments(out_inst_path)
    print(f"  Total instruments: {len(instruments)}")

    # Check all signal stocks are in instruments
    signal_in_instruments = [s.upper() for s in signal_stocks if s.upper() in instruments]
    print(f"  Signal stocks in instruments: {len(signal_in_instruments)}/{len(signal_stocks)}")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n[6/6] Final verification...")
    final_stocks = os.listdir(out_features_dir)
    final_calendar = load_calendar(os.path.join(out_dir, "calendars", "day.txt"))

    # Count feature files for signal stocks
    sample_signal = signal_stocks[0] if signal_stocks else None
    if sample_signal:
        sample_features = os.listdir(os.path.join(out_features_dir, sample_signal))
        print(f"  Sample signal stock ({sample_signal}): {len(sample_features)} features")

    # Count feature files for a regular stock
    regular_stocks = [s for s in final_stocks if s not in signal_stocks]
    if regular_stocks:
        sample_regular = regular_stocks[0]
        regular_features = os.listdir(os.path.join(out_features_dir, sample_regular))
        print(f"  Sample regular stock ({sample_regular}): {len(regular_features)} features")

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("MERGE COMPLETE")
    print("=" * 60)
    print(f"  Output:            {out_dir}")
    print(f"  Calendar:          {final_calendar[0]} ~ {final_calendar[-1]} ({len(final_calendar)} days)")
    print(f"  Total stocks:      {len(final_stocks)}")
    print(f"  Signal stocks:     {len(signal_stocks)} ({len(SIGNAL_FEATURES)} extra features each)")
    print(f"  Signals written:   {total_signals_written} files ({total_bytes_written / 1024:.1f} KB)")
    print(f"  Time:              {elapsed:.1f}s")


if __name__ == "__main__":
    main()
