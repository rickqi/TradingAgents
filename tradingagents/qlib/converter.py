"""Convert TradingAgents OHLCV data to Qlib binary format.

Qlib binary format per feature file:
  - Flat array of float32 little-endian
  - First 4 bytes: start_index (position in global calendar, stored as float32)
  - Remaining: feature values as float32
  - File path: features/{instrument_lower}/{field_lower}.{freq}.bin

Calendar file: plain text, one date per line (YYYY-MM-DD).
Instruments file: tab-separated SYMBOL\\tstart_date\\tend_date, no header.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from pathlib import Path

from tradingagents.qlib.ticker_mapper import to_qlib_instrument, qlib_instrument_to_dirname, from_qlib_instrument
from tradingagents.qlib.cache_scanner import scan_cache, CachedOHLCV


@dataclass
class ConvertResult:
    """Result of a Qlib data conversion."""

    qlib_dir: str
    num_instruments: int
    num_features: int
    num_calendar_days: int
    date_range: tuple[str, str]
    feature_names: list[str]
    instrument_list: list[str]


# Column mapping: TradingAgents CSV → Qlib feature name
_COLUMN_MAP: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}


class QlibConverter:
    """Convert TradingAgents OHLCV data to Qlib binary format.

    Usage::

        converter = QlibConverter("~/.qlib/qlib_data/cn_data")
        result = converter.convert_from_cache()
        print(f"Wrote {result.num_instruments} instruments, "
              f"{result.num_features} features, "
              f"{result.num_calendar_days} calendar days")
    """

    CALENDARS_DIR = "calendars"
    FEATURES_DIR = "features"
    INSTRUMENTS_DIR = "instruments"

    def __init__(self, qlib_dir: str, freq: str = "day"):
        """
        Args:
            qlib_dir: Output root directory (e.g. ``~/.qlib/qlib_data/cn_data``).
            freq: Frequency label for Qlib files (default ``"day"``).
        """
        self.qlib_dir = Path(qlib_dir).expanduser().resolve()
        self.freq = freq

        # Pre-create subdirectory structure
        (self.qlib_dir / self.CALENDARS_DIR).mkdir(parents=True, exist_ok=True)
        (self.qlib_dir / self.FEATURES_DIR).mkdir(parents=True, exist_ok=True)
        (self.qlib_dir / self.INSTRUMENTS_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert_from_cache(
        self,
        tickers: list[str] | None = None,
        cache_dir: str | None = None,
        extra_features: dict[str, pd.DataFrame] | None = None,
    ) -> ConvertResult:
        """Convert cached OHLCV files to Qlib binary format.

        Args:
            tickers: Filter to these tickers (``None`` = all cached).
            cache_dir: Override cache directory.
            extra_features: Dict of ``{ticker: DataFrame}`` with additional
                features. Each DataFrame must have a ``date`` column and
                feature columns.

        Returns:
            ConvertResult with stats.
        """
        # 1. Discover cached files
        cached_files = scan_cache(cache_dir=cache_dir)
        if not cached_files:
            print("No cached OHLCV files found.")
            return ConvertResult(
                qlib_dir=str(self.qlib_dir),
                num_instruments=0,
                num_features=0,
                num_calendar_days=0,
                date_range=("", ""),
                feature_names=[],
                instrument_list=[],
            )

        # 2. Filter by tickers if specified
        if tickers is not None:
            ticker_set = {t.upper() for t in tickers}
            cached_files = [f for f in cached_files if f.ticker.upper() in ticker_set]

        if not cached_files:
            print(f"No cached files match the specified tickers: {tickers}")
            return ConvertResult(
                qlib_dir=str(self.qlib_dir),
                num_instruments=0,
                num_features=0,
                num_calendar_days=0,
                date_range=("", ""),
                feature_names=[],
                instrument_list=[],
            )

        # 3. Deduplicate: keep only the best file per Qlib instrument.
        #    Multiple cache files may exist for the same stock:
        #      - Different ticker formats: "688256" vs "688256.SH" → same SH688256
        #      - Different download dates: different date ranges / row counts
        #    Selection priority: most rows first, then latest end_date.
        best_per_instrument: dict[str, CachedOHLCV] = {}
        for cached in cached_files:
            inst_key = cached.qlib_instrument or cached.ticker.upper()
            existing = best_per_instrument.get(inst_key)
            if existing is None:
                best_per_instrument[inst_key] = cached
            elif cached.num_rows > existing.num_rows:
                best_per_instrument[inst_key] = cached
            elif cached.num_rows == existing.num_rows and cached.date_end > existing.date_end:
                best_per_instrument[inst_key] = cached
        cached_files = list(best_per_instrument.values())
        print(f"Deduplicated: {len(best_per_instrument)} unique instruments "
              f"from cache files")

        # 4. Read and normalize each cached file
        all_frames: list[pd.DataFrame] = []
        for cached in cached_files:
            try:
                df = pd.read_csv(cached.file_path, encoding="utf-8", on_bad_lines="skip")
            except Exception as exc:
                print(f"Warning: failed to read {cached.path}: {exc}")
                continue

            if df.empty:
                continue

            df = self._normalize_ohlcv(df, cached.ticker)

            # 4. Compute factor = Adj Close / close (handle div-by-zero)
            # Note: _normalize_ohlcv renames "Close" → "close", but keeps
            # "Adj Close" as-is until factor is computed.
            adj_col = "Adj Close" if "Adj Close" in df.columns else None
            if adj_col and "close" in df.columns:
                close_vals = df["close"].replace(0, np.nan)
                df["factor"] = np.where(
                    close_vals.isna(),
                    1.0,
                    df[adj_col] / close_vals,
                )
                df = df.drop(columns=[adj_col])
            elif adj_col:
                # No close column — drop Adj Close to avoid leaking raw prices
                df = df.drop(columns=[adj_col])

            # 5. Merge extra features if provided
            #    extra_features keys may be in Qlib format (SH688041) or
            #    TradingAgents format (688041.SH) — try both directions.
            extra_key = None
            if extra_features:
                if cached.ticker in extra_features:
                    extra_key = cached.ticker
                else:
                    # Try Qlib format lookup
                    qlib_key = to_qlib_instrument(cached.ticker)
                    if qlib_key in extra_features:
                        extra_key = qlib_key
            if extra_key is not None:
                extra_df = extra_features[extra_key].copy()
                extra_df["date"] = pd.to_datetime(extra_df["date"]).dt.strftime("%Y-%m-%d")
                extra_df = extra_df.rename(columns={c: c.lower() for c in extra_df.columns if c != "date"})
                # Only merge columns that don't already exist
                new_cols = [c for c in extra_df.columns if c not in df.columns and c != "date"]
                if new_cols:
                    df = df.merge(
                        extra_df[["date"] + new_cols],
                        on="date",
                        how="left",
                    )

            all_frames.append(df)

        if not all_frames:
            print("No valid data after reading cache files.")
            return ConvertResult(
                qlib_dir=str(self.qlib_dir),
                num_instruments=0,
                num_features=0,
                num_calendar_days=0,
                date_range=("", ""),
                feature_names=[],
                instrument_list=[],
            )

        # 6. Combine into unified DataFrame
        combined = pd.concat(all_frames, ignore_index=True)

        # 7. Determine feature columns (everything except date and symbol)
        meta_cols = {"date", "symbol"}
        feature_cols = [c for c in combined.columns if c not in meta_cols]

        return self._dump_all(combined, "date", "symbol", feature_cols)

    def convert_from_dataframe(
        self,
        df: pd.DataFrame,
        date_col: str = "date",
        symbol_col: str = "symbol",
        feature_cols: list[str] | None = None,
        exclude_cols: list[str] | None = None,
    ) -> ConvertResult:
        """Convert a single DataFrame directly to Qlib binary.

        The DataFrame must have date, symbol, and feature columns (open,
        high, low, close, volume, etc.).

        Args:
            df: Input DataFrame.
            date_col: Name of the date column.
            symbol_col: Name of the symbol/ticker column.
            feature_cols: Explicit feature columns. If ``None``, all columns
                except date and symbol are used (minus ``exclude_cols``).
            exclude_cols: Columns to exclude when auto-detecting features.

        Returns:
            ConvertResult with stats.
        """
        if df.empty:
            return ConvertResult(
                qlib_dir=str(self.qlib_dir),
                num_instruments=0,
                num_features=0,
                num_calendar_days=0,
                date_range=("", ""),
                feature_names=[],
                instrument_list=[],
            )

        df = df.copy()

        # Normalize date column to string format
        df[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")

        # Normalize symbol column to uppercase
        df[symbol_col] = df[symbol_col].astype(str).str.upper()

        # Determine feature columns
        if feature_cols is not None:
            feat = list(feature_cols)
        else:
            exclude = {date_col, symbol_col}
            if exclude_cols:
                exclude.update(exclude_cols)
            feat = [c for c in df.columns if c not in exclude]

        return self._dump_all(df, date_col, symbol_col, feat)

    # ------------------------------------------------------------------
    # Core conversion logic
    # ------------------------------------------------------------------

    def _dump_all(
        self,
        df: pd.DataFrame,
        date_col: str,
        symbol_col: str,
        feature_cols: list[str],
    ) -> ConvertResult:
        """Core conversion: write Qlib binary structure.

        1. Build global calendar → ``calendars/{freq}.txt``
        2. For each unique symbol: write feature binaries
        3. Write ``instruments/all.txt``
        """
        if df.empty or not feature_cols:
            return ConvertResult(
                qlib_dir=str(self.qlib_dir),
                num_instruments=0,
                num_features=len(feature_cols),
                num_calendar_days=0,
                date_range=("", ""),
                feature_names=list(feature_cols),
                instrument_list=[],
            )

        # ---- Step 1: Build global calendar ----
        all_dates = sorted(df[date_col].unique())
        calendar_path = self.qlib_dir / self.CALENDARS_DIR / f"{self.freq}.txt"
        np.savetxt(str(calendar_path), np.array(all_dates), fmt="%s", encoding="utf-8")
        print(f"Calendar: {len(all_dates)} days → {calendar_path}")

        # Build date→index lookup
        date_to_idx = {d: i for i, d in enumerate(all_dates)}

        # ---- Step 2: Per-instrument feature files ----
        instrument_records: list[tuple[str, str, str]] = []  # (symbol_upper, start, end)
        symbols = sorted(df[symbol_col].unique())

        for symbol in symbols:
            sym_df = df[df[symbol_col] == symbol].copy()
            sym_df = sym_df.sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")

            if sym_df.empty:
                continue

            # Convert symbol to Qlib instrument name
            try:
                qlib_inst = to_qlib_instrument(symbol)
            except Exception:
                # Fallback: use uppercase symbol as-is
                qlib_inst = symbol.upper()

            inst_dirname = qlib_instrument_to_dirname(qlib_inst)
            inst_dir = self.qlib_dir / self.FEATURES_DIR / inst_dirname
            inst_dir.mkdir(parents=True, exist_ok=True)

            # Determine date range in the global calendar
            sym_dates = sym_df[date_col].values
            start_date = sym_dates[0]
            end_date = sym_dates[-1]
            start_idx = date_to_idx.get(start_date)
            end_idx = date_to_idx.get(end_date)

            if start_idx is None or end_idx is None:
                print(f"Warning: symbol {symbol} has dates outside global calendar, skipping.")
                continue

            # Build a reindexed array aligned to the global calendar
            # Only cover this symbol's date range: [start_idx, end_idx]
            calendar_span = end_idx - start_idx + 1
            sym_date_set = set(sym_dates)

            # Create a date-indexed Series for each feature for fast lookup
            sym_indexed = sym_df.set_index(date_col)

            for feat_name in feature_cols:
                if feat_name not in sym_df.columns:
                    continue

                # Build full-length values array (calendar_span elements)
                values = np.full(calendar_span, np.nan, dtype=np.float32)
                for i, date_offset in enumerate(range(start_idx, end_idx + 1)):
                    cal_date = all_dates[date_offset]
                    if cal_date in sym_date_set and cal_date in sym_indexed.index:
                        val = sym_indexed.loc[cal_date, feat_name]
                        if pd.notna(val):
                            try:
                                values[i] = np.float32(val)
                            except (ValueError, TypeError):
                                pass  # leave as NaN

                # Write binary: start_index (as float32) + values
                bin_path = inst_dir / f"{feat_name.lower()}.{self.freq}.bin"
                payload = np.hstack([np.float32(start_idx), values])
                payload.tofile(str(bin_path))

            # Record instrument range
            instrument_records.append((qlib_inst, start_date, end_date))

        # ---- Step 3: Write instruments/all.txt ----
        instruments_path = self.qlib_dir / self.INSTRUMENTS_DIR / "all.txt"
        with open(str(instruments_path), "w", encoding="utf-8") as f:
            for inst, start, end in instrument_records:
                # SYMBOL is UPPERCASE
                f.write(f"{inst.upper()}\t{start}\t{end}\n")
        print(f"Instruments: {len(instrument_records)} → {instruments_path}")

        # ---- Build result ----
        result = ConvertResult(
            qlib_dir=str(self.qlib_dir),
            num_instruments=len(instrument_records),
            num_features=len(feature_cols),
            num_calendar_days=len(all_dates),
            date_range=(all_dates[0], all_dates[-1]),
            feature_names=list(feature_cols),
            instrument_list=[rec[0] for rec in instrument_records],
        )
        print(
            f"Conversion complete: {result.num_instruments} instruments, "
            f"{result.num_features} features, "
            f"{result.num_calendar_days} calendar days "
            f"({result.date_range[0]} ~ {result.date_range[1]})"
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """Normalize a raw OHLCV DataFrame to canonical form.

        - Rename columns to lowercase Qlib names
        - Add ``symbol`` column
        - Standardize ``date`` column
        """
        df = df.copy()

        # Standardize Date column → "date"
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        elif "date" not in df.columns:
            # Try to use first column as date
            first_col = df.columns[0]
            df = df.rename(columns={first_col: "date"})

        # Parse and format dates
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df = df.dropna(subset=["date"])

        # Rename OHLCV columns using the mapping
        rename_map = {}
        for old_name, new_name in _COLUMN_MAP.items():
            if old_name in df.columns and new_name not in df.columns:
                rename_map[old_name] = new_name
        df = df.rename(columns=rename_map)

        # Keep "Adj Close" as-is for factor computation (will be dropped later)
        # Any other extra columns → lowercase
        for col in list(df.columns):
            if col not in ("date", "Adj Close") and col not in _COLUMN_MAP.values():
                if col != col.lower():
                    df = df.rename(columns={col: col.lower()})

        # Add symbol column
        df["symbol"] = ticker.upper()

        return df
