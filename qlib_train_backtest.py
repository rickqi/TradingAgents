#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Qlib Model Training + Backtesting Script
=========================================
Trains LightGBM models on A-share data and compares:
  (a) OHLCV-only features
  (b) OHLCV + AI signal features

Data is loaded via direct binary reading (bypasses D.features() Python 3.13 bug).

Usage:
    D:\\codes\\TradingAgents\\.venv\\Scripts\\python.exe qlib_train_backtest.py
"""

from __future__ import annotations

import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 1.  Paths & constants
# ---------------------------------------------------------------------------

# Ensure qlib from source is importable
QLIB_SRC = r"D:\codes\qlib"
if QLIB_SRC not in sys.path:
    sys.path.insert(0, QLIB_SRC)

DATA_DIR = os.path.expanduser("~/.qlib/qlib_data/qlib_bin")
CALENDAR_PATH = os.path.join(DATA_DIR, "calendars", "day.txt")
FEATURES_DIR = os.path.join(DATA_DIR, "features")
SIGNALS_PATH = os.path.expanduser("~/.qlib/qlib_data/tradingagents_signals.parquet")

# 20 target A-share stocks (user-specified)
TARGET_STOCKS = [
    "sh688041", "sh688256", "sh688012", "sh603986", "sh688008",
    "sz300442", "sh603019", "sh688111", "sz002230", "sz002837",
    "sz002049", "sh688027", "sz300223", "sz301269", "sz002747",
    "sh688332", "sz002896", "sh688568", "sz300672", "sz300458",
]

# Broader universe for training (SH main-board stocks with pre-2020 history)
UNIVERSE_SIZE = 200  # number of stocks to use for training

OHLCV_FEATURES = ["$open", "$close", "$high", "$low", "$volume", "$amount", "$change", "$vwap"]
SIGNAL_FEATURES = ["ai_score", "trader_action", "research_rating", "price_target"]
RD_AGENT_FEATURES = ["short_term_momentum_5d", "volume_change_5d"]

TRAIN_START = "2020-01-02"
TRAIN_END   = "2023-12-29"
VALID_START = "2024-01-02"
VALID_END   = "2024-12-31"
TEST_START  = "2025-01-02"
TEST_END    = "2026-05-08"

# ---------------------------------------------------------------------------
# 2.  Helpers
# ---------------------------------------------------------------------------

def load_calendar() -> List[str]:
    """Load the qlib day calendar."""
    with open(CALENDAR_PATH, "r") as f:
        return [line.strip() for line in f if line.strip()]


def load_bin_feature(stock_dir: str, feature_name: str) -> Tuple[int, np.ndarray]:
    """Read a single .day.bin file. Returns (start_idx, values_array)."""
    path = os.path.join(stock_dir, f"{feature_name}.day.bin")
    if not os.path.exists(path):
        return -1, np.array([], dtype=np.float32)
    data = np.fromfile(path, dtype=np.float32)
    if len(data) == 0:
        return -1, np.array([], dtype=np.float32)
    start_idx = int(data[0])
    return start_idx, data[1:]


def build_stock_df(
    stock_id: str,
    calendar: List[str],
    features: List[str],
    calendar_to_idx: Dict[str, int],
) -> Optional[pd.DataFrame]:
    """
    Build a DataFrame for one stock from binary files.
    Returns DataFrame indexed by datetime (within MultiIndex), or None on failure.
    """
    stock_dir = os.path.join(FEATURES_DIR, stock_id)
    if not os.path.isdir(stock_dir):
        return None

    # Read close first to determine the date range
    close_start, close_vals = load_bin_feature(stock_dir, "close")
    if close_start < 0 or len(close_vals) == 0:
        return None

    end_idx = close_start + len(close_vals) - 1
    if end_idx >= len(calendar):
        end_idx = len(calendar) - 1

    # Date range for this stock
    stock_dates = calendar[close_start : end_idx + 1]
    if len(stock_dates) == 0:
        return None

    rows = np.full((len(stock_dates), len(features)), np.nan, dtype=np.float64)

    for col_i, feat in enumerate(features):
        clean_feat = feat.lstrip("$")  # binary files use names without $
        start_idx, vals = load_bin_feature(stock_dir, clean_feat)
        if start_idx < 0 or len(vals) == 0:
            continue
        # Align to global calendar
        for i, dt in enumerate(stock_dates):
            global_i = calendar_to_idx.get(dt)
            if global_i is None:
                continue
            local_i = global_i - start_idx
            if 0 <= local_i < len(vals):
                rows[i, col_i] = float(vals[local_i])

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(stock_dates, name="datetime"),
                      columns=features)
    df["instrument"] = stock_id
    df = df.set_index(["instrument", df.index])
    return df


def discover_universe(calendar: List[str], target_size: int) -> List[str]:
    """Find A-share stocks with sufficient history for training.
    
    Covers Shanghai main board (sh600/601/603/605), STAR Market (sh688),
    Shenzhen main board (sz000/001), SME (sz002/003), and ChiNext (sz300/301).
    Excludes indices (sh000, sz399) and Beijing stocks (bj).
    """
    cal_arr = np.array(calendar)
    train_start_idx = int(np.searchsorted(cal_arr, TRAIN_START))

    candidates = []
    for d in sorted(os.listdir(FEATURES_DIR)):
        # Include all A-share boards, exclude indices and Beijing
        if not (
            d.startswith("sh600") or d.startswith("sh601") or
            d.startswith("sh603") or d.startswith("sh605") or
            d.startswith("sh688") or d.startswith("sz000") or
            d.startswith("sz001") or d.startswith("sz002") or
            d.startswith("sz003") or d.startswith("sz300") or
            d.startswith("sz301")
        ):
            continue
        close_path = os.path.join(FEATURES_DIR, d, "close.day.bin")
        if not os.path.exists(close_path):
            continue
        data = np.fromfile(close_path, dtype=np.float32)
        if len(data) < 2:
            continue
        start_idx = int(data[0])
        vals = data[1:]
        non_nan = int((~np.isnan(vals)).sum())
        if non_nan > 200:  # at least 200 trading days of data
            candidates.append((d, start_idx, non_nan))

    # Sort by longest history first
    candidates.sort(key=lambda x: -x[2])
    universe = [c[0] for c in candidates[:target_size]]

    # Ensure ALL 20 target stocks are included
    for s in TARGET_STOCKS:
        if s not in universe and os.path.isdir(os.path.join(FEATURES_DIR, s)):
            universe.append(s)

    return universe


def load_signal_data() -> pd.DataFrame:
    """Load AI signals from parquet, return with lowercase instrument ids."""
    if not os.path.exists(SIGNALS_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(SIGNALS_PATH)
    # Normalize instrument names to lowercase
    symbols = df.index.get_level_values("symbol")
    dates = df.index.get_level_values("date")
    new_idx = pd.MultiIndex.from_arrays(
        [symbols.str.lower(), pd.DatetimeIndex(dates)],
        names=["instrument", "datetime"],
    )
    df.index = new_idx
    # Keep all signals (not just target stocks) for broader coverage
    return df


def print_header(msg: str) -> None:
    width = 70
    print(f"\n{'=' * width}")
    print(f"  {msg}")
    print(f"{'=' * width}")


def print_sub(msg: str) -> None:
    print(f"\n--- {msg} ---")


# ---------------------------------------------------------------------------
# 3.  Core pipeline
# ---------------------------------------------------------------------------

def load_ohlcv_dataframe(
    stocks: List[str],
    calendar: List[str],
    calendar_to_idx: Dict[str, int],
) -> pd.DataFrame:
    """Build OHLCV feature DataFrame for all stocks."""
    print_sub(f"Loading OHLCV data for {len(stocks)} stocks ...")
    dfs = []
    for i, stock in enumerate(stocks):
        df = build_stock_df(stock, calendar, OHLCV_FEATURES, calendar_to_idx)
        if df is not None and len(df) > 100:
            dfs.append(df)
        if (i + 1) % 50 == 0:
            print(f"  Loaded {i + 1}/{len(stocks)} stocks ...")

    if not dfs:
        raise RuntimeError("No stock data loaded!")

    combined = pd.concat(dfs)
    combined = combined.sort_index()
    print(f"  Total rows: {len(combined):,},  stocks with data: {combined.index.get_level_values(0).nunique()}")
    return combined


def add_label(df: pd.DataFrame) -> pd.DataFrame:
    """Add 2-day forward return label: Ref($close, -2) / $close - 1."""
    close = df["$close"].copy()
    # Shift by -2 within each instrument group
    label = close.groupby(level=0).shift(-2) / close - 1
    df = df.copy()
    df["LABEL0"] = label
    return df


def add_signals(df: pd.DataFrame, signal_df: pd.DataFrame) -> pd.DataFrame:
    """Merge AI signal columns into the OHLCV DataFrame."""
    if signal_df.empty:
        print("  WARNING: No signal data available, filling with NaN")
        for col in SIGNAL_FEATURES:
            df[col] = np.nan
        return df

    # Align signal data index to match df's MultiIndex format
    # signal_df has (instrument, datetime) index with columns: ai_score, trader_action, etc.
    df = df.copy()
    for col in SIGNAL_FEATURES:
        if col in signal_df.columns:
            df[col] = np.nan
            # Fill where we have signal data
            common_idx = df.index.intersection(signal_df.index)
            if len(common_idx) > 0:
                df.loc[common_idx, col] = signal_df.loc[common_idx, col]

    return df


def add_rd_agent_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RD-Agent discovered factors and add to DataFrame.

    Factor 1 — short_term_momentum_5d:
        R_5d = close_t / close_{t-5} - 1
        5-day price momentum using raw close price.

    Factor 2 — volume_change_5d:
        V_ratio = avg_volume(t-4, t) / avg_volume(t-9, t-5)
        Ratio of current 5-day rolling avg volume to prior 5-day rolling avg volume.

    Both are computed per-instrument via groupby to avoid cross-contamination.
    """
    df = df.copy()

    # --- Factor 1: short_term_momentum_5d ---
    close = df["$close"]
    close_shifted = close.groupby(level=0).shift(5)
    df["short_term_momentum_5d"] = close / close_shifted - 1.0

    # --- Factor 2: volume_change_5d ---
    volume = df["$volume"]
    rolling_5d_avg = volume.groupby(level=0).transform(
        lambda s: s.rolling(window=5, min_periods=5).mean()
    )
    rolling_5d_avg_shifted = rolling_5d_avg.groupby(level=0).shift(5)
    df["volume_change_5d"] = rolling_5d_avg / rolling_5d_avg_shifted

    # Replace inf with NaN (can occur from division by zero)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # Report NaN stats
    for col in RD_AGENT_FEATURES:
        na_count = df[col].isna().sum()
        total = len(df)
        print(f"  {col}: {na_count}/{total} NaN ({na_count/total*100:.1f}%)")

    return df


def build_handler_dataset(
    feature_df: pd.DataFrame,
    feature_cols: List[str],
    label_col: str = "LABEL0",
) -> Tuple:
    """
    Build DataHandlerLP + DatasetH from a flat DataFrame.
    The DataFrame must have MultiIndex (instrument, datetime) and columns for features + label.
    """
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset import DatasetH

    df = feature_df.dropna(subset=[label_col]).copy()

    # Drop last `hold_days` rows of each segment to prevent label leakage
    # (label uses forward prices that belong to the next segment)
    hold_days = 2  # must match the label shift in add_label()
    for seg_name, (seg_start, seg_end) in [("train", (TRAIN_START, TRAIN_END)), 
                                             ("valid", (VALID_START, VALID_END))]:
        seg_mask = (df.index.get_level_values(1) >= seg_start) & \
                   (df.index.get_level_values(1) <= seg_end)
        seg_dates = sorted(df.loc[seg_mask].index.get_level_values(1).unique())
        if len(seg_dates) > hold_days:
            drop_dates = set(seg_dates[-hold_days:])
            drop_mask = df.index.get_level_values(1).isin(drop_dates)
            # Only drop if the date is NOT also in the next segment
            df = df[~drop_mask | ~seg_mask]

    # Create MultiIndex columns: ('feature', col) and ('label', 'LABEL0')
    feat_part = df[feature_cols]
    label_part = df[[label_col]]
    mi_df = pd.concat([feat_part, label_part], axis=1, keys=["feature", "label"])
    mi_df = mi_df.dropna(subset=[("label", label_col)])

    print(f"  Dataset rows: {len(mi_df):,},  "
          f"stocks: {mi_df.index.get_level_values(0).nunique()},  "
          f"date range: {mi_df.index.get_level_values(1).min().date()} to "
          f"{mi_df.index.get_level_values(1).max().date()}")

    handler = DataHandlerLP.from_df(mi_df)

    dataset = DatasetH(
        handler=handler,
        segments={
            "train": (TRAIN_START, TRAIN_END),
            "valid": (VALID_START, VALID_END),
            "test":  (TEST_START, TEST_END),
        },
    )
    return handler, dataset


def train_model(dataset, num_boost_round=200, early_stopping_rounds=20):
    """Train LGBModel on the dataset."""
    from qlib.contrib.model.gbdt import LGBModel

    model = LGBModel(
        loss="mse",
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        learning_rate=0.05,
        num_leaves=63,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        verbose_eval=-1,  # suppress per-iteration output
    )
    print("  Training LightGBM ...")
    t0 = time.time()
    model.fit(dataset)
    elapsed = time.time() - t0
    print(f"  Training completed in {elapsed:.1f}s")
    return model


def predict_and_evaluate(model, dataset) -> pd.Series:
    """Generate predictions on test set."""
    from qlib.data.dataset.handler import DataHandlerLP

    pred = model.predict(dataset, segment="test")
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]
    return pred


# ---------------------------------------------------------------------------
# 4.  Simple backtesting (portfolio simulation)
# ---------------------------------------------------------------------------

def compute_ic_metrics(predictions: pd.Series, price_df: pd.DataFrame, label_shift: int = 2) -> Dict:
    """Compute Information Coefficient (IC) between predictions and actual returns.
    
    IC = Pearson correlation between predicted and actual returns per date.
    ICIR = mean(IC) / std(IC) — measures consistency of predictive power.
    """
    from scipy.stats import pearsonr
    
    # Get test dates from predictions
    test_dates = sorted(predictions.index.get_level_values(1).unique())
    
    ic_values = []
    for dt in test_dates:
        try:
            preds_dt = predictions.xs(dt, level=1)
        except KeyError:
            continue
        if len(preds_dt) < 5:  # Need at least 5 stocks for meaningful correlation
            continue
        
        # Compute actual forward returns for these stocks
        actual_returns = {}
        for stock in preds_dt.index:
            try:
                buy_price = price_df.loc[(stock, dt), "$close"]
                # Find sell date (label_shift trading days later)
                dt_idx = test_dates.index(dt)
                sell_idx = min(dt_idx + label_shift, len(test_dates) - 1)
                sell_dt = test_dates[sell_idx]
                sell_price = price_df.loc[(stock, sell_dt), "$close"]
                if pd.notna(buy_price) and pd.notna(sell_price) and buy_price != 0:
                    actual_returns[stock] = (sell_price - buy_price) / buy_price
            except (KeyError, IndexError):
                continue
        
        if len(actual_returns) < 5:
            continue
        
        actual_s = pd.Series(actual_returns)
        pred_s = preds_dt.reindex(actual_s.index).dropna()
        actual_s = actual_s.reindex(pred_s.index)
        
        if len(pred_s) >= 5:
            ic, _ = pearsonr(pred_s.values, actual_s.values)
            if not np.isnan(ic):
                ic_values.append(ic)
    
    if not ic_values:
        return {"mean_ic": 0.0, "ic_std": 0.0, "icir": 0.0, "ic_positive_ratio": 0.0, "n_dates": 0}
    
    ic_arr = np.array(ic_values)
    mean_ic = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr))
    icir = mean_ic / max(ic_std, 1e-8)
    ic_pos_ratio = float(np.mean(ic_arr > 0))
    
    return {
        "mean_ic": mean_ic,
        "ic_std": ic_std,
        "icir": icir,
        "ic_positive_ratio": ic_pos_ratio,
        "n_dates": len(ic_values),
    }


def simple_backtest(
    predictions: pd.Series,
    price_df: pd.DataFrame,
    top_k: int = 5,
    hold_days: int = 2,
    initial_capital: float = 1_000_000.0,
    transaction_cost_rate: float = 0.003,
) -> Dict:
    """
    Simple top-k portfolio backtest.

    - Each rebalance day: select top-k stocks by predicted return
    - Hold for `hold_days` trading days
    - Equal-weight portfolio
    - Returns performance metrics dict
    """
    print_sub(f"Running simple backtest (top_k={top_k}, hold_days={hold_days})")

    if predictions.empty:
        print("  WARNING: Empty predictions, cannot backtest")
        return {
            "cum_return": 0.0, "ann_return": 0.0,
            "max_drawdown": 0.0, "sharpe": 0.0, "n_trades": 0,
        }

    # Get close prices for the test period
    test_dates = sorted(predictions.index.get_level_values(1).unique())
    if len(test_dates) == 0:
        print("  WARNING: No test dates")
        return {
            "cum_return": 0.0, "ann_return": 0.0,
            "max_drawdown": 0.0, "sharpe": 0.0, "n_trades": 0,
        }

    print(f"  Test period: {test_dates[0].date()} to {test_dates[-1].date()} "
          f"({len(test_dates)} trading days)")

    # Build daily returns series for portfolio
    portfolio_values = [initial_capital]
    portfolio_dates = [test_dates[0]]
    capital = initial_capital
    n_trades = 0

    rebalance_idx = 0
    while rebalance_idx < len(test_dates):
        dt = test_dates[rebalance_idx]

        # Get predictions for this date
        try:
            preds_dt = predictions.xs(dt, level=1)
        except KeyError:
            rebalance_idx += 1
            continue

        if len(preds_dt) == 0:
            rebalance_idx += 1
            continue

        # Select top-k
        top_stocks = preds_dt.nlargest(min(top_k, len(preds_dt))).index.tolist()
        if not top_stocks:
            rebalance_idx += 1
            continue

        n_trades += 1

        # Calculate hold period return
        sell_idx = min(rebalance_idx + hold_days, len(test_dates) - 1)
        buy_dt = dt
        sell_dt = test_dates[sell_idx]

        # Get close prices
        stock_returns = []
        for stock in top_stocks:
            try:
                buy_price = price_df.loc[(stock, buy_dt), "$close"]
                sell_price = price_df.loc[(stock, sell_dt), "$close"]
                if pd.notna(buy_price) and pd.notna(sell_price) and buy_price != 0:
                    ret = (sell_price - buy_price) / buy_price
                    stock_returns.append(ret)
            except (KeyError, IndexError):
                continue

        avg_return = np.mean(stock_returns) if stock_returns else 0.0
        # Deduct transaction cost (A-share: stamp tax 0.05% sell + commission 0.025% each side + slippage)
        avg_return -= transaction_cost_rate
        capital *= (1 + avg_return)

        # Record portfolio value at sell date
        if sell_idx < len(test_dates):
            portfolio_dates.append(test_dates[sell_idx])
            portfolio_values.append(capital)

        rebalance_idx = sell_idx + 1

    # Ensure final value is recorded
    if portfolio_dates[-1] != test_dates[-1]:
        portfolio_dates.append(test_dates[-1])
        portfolio_values.append(capital)

    # Calculate metrics
    cum_return = (capital - initial_capital) / initial_capital

    # Annualized return
    n_days = len(test_dates)
    n_years = n_days / 252.0
    ann_return = (1 + cum_return) ** (1 / max(n_years, 0.01)) - 1 if n_years > 0 else 0.0

    # Max drawdown
    values = np.array(portfolio_values)
    peaks = np.maximum.accumulate(values)
    drawdowns = (peaks - values) / peaks
    max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Sharpe ratio (assuming daily risk-free rate = 0)
    if len(values) > 1:
        daily_returns = np.diff(values) / values[:-1]
        sharpe = float(np.mean(daily_returns) / max(np.std(daily_returns), 1e-8) * np.sqrt(252 / hold_days))
    else:
        sharpe = 0.0

    return {
        "cum_return": cum_return,
        "ann_return": ann_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "n_trades": n_trades,
        "final_capital": capital,
    }


def benchmark_backtest(
    price_df: pd.DataFrame,
    target_stocks: List[str],
    initial_capital: float = 1_000_000.0,
    transaction_cost_rate: float = 0.003,
) -> Dict:
    """Equal-weight buy-and-hold benchmark for target stocks.
    
    Buy at TEST_START close, hold until TEST_END close.
    Deducts one-time transaction cost for entry.
    """
    test_dates = sorted(price_df.index.get_level_values(1).unique())
    test_dates = [d for d in test_dates if str(d.date()) >= TEST_START and str(d.date()) <= TEST_END]
    if len(test_dates) < 2:
        return {"cum_return": 0.0, "ann_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "n_trades": 1,
                "final_capital": initial_capital}
    
    buy_dt = test_dates[0]
    sell_dt = test_dates[-1]
    
    stock_returns = []
    for stock in target_stocks:
        try:
            buy_price = price_df.loc[(stock, buy_dt), "$close"]
            sell_price = price_df.loc[(stock, sell_dt), "$close"]
            if pd.notna(buy_price) and pd.notna(sell_price) and buy_price != 0:
                ret = (sell_price - buy_price) / buy_price - transaction_cost_rate
                stock_returns.append(ret)
        except (KeyError, IndexError):
            continue
    
    avg_return = np.mean(stock_returns) if stock_returns else 0.0
    capital = initial_capital * (1 + avg_return)
    cum_return = avg_return
    
    n_days = len(test_dates)
    n_years = n_days / 252.0
    ann_return = (1 + cum_return) ** (1 / max(n_years, 0.01)) - 1 if n_years > 0 else 0.0
    
    # Approximate max drawdown (since we only have start/end, assume peak at start)
    max_drawdown = 0.0  # Buy-and-hold has no rebalancing, single period
    
    # Sharpe: approximate daily returns assuming linear growth
    sharpe = 0.0  # Can't compute meaningful Sharpe from single buy-and-hold
    
    return {
        "cum_return": cum_return,
        "ann_return": ann_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "n_trades": 1,
        "final_capital": capital,
    }


# ---------------------------------------------------------------------------
# 5.  Main
# ---------------------------------------------------------------------------

def main():
    print_header("Qlib Model Training + Backtesting")

    # ------------------------------------------------------------------
    # Init qlib
    # ------------------------------------------------------------------
    print_sub("Initializing Qlib")
    import qlib
    qlib.init(provider_uri=DATA_DIR, region="cn")
    print("  Qlib initialized.")

    # ------------------------------------------------------------------
    # Load calendar
    # ------------------------------------------------------------------
    calendar = load_calendar()
    calendar_to_idx = {d: i for i, d in enumerate(calendar)}
    print(f"  Calendar: {calendar[0]} to {calendar[-1]} ({len(calendar)} days)")

    # ------------------------------------------------------------------
    # Discover universe
    # ------------------------------------------------------------------
    print_header("Step 1: Discovering stock universe")
    universe = discover_universe(calendar, UNIVERSE_SIZE)
    # Ensure target stocks are included
    for s in TARGET_STOCKS:
        if s not in universe:
            universe.append(s)
    print(f"  Universe size: {len(universe)} stocks")

    # ------------------------------------------------------------------
    # Load OHLCV data
    # ------------------------------------------------------------------
    print_header("Step 2: Loading OHLCV data (direct binary reading)")
    ohlcv_df = load_ohlcv_dataframe(universe, calendar, calendar_to_idx)

    # Add label
    ohlcv_df = add_label(ohlcv_df)
    print(f"  After adding label: {len(ohlcv_df):,} rows")

    # ------------------------------------------------------------------
    # Load signal data
    # ------------------------------------------------------------------
    print_header("Step 3: Loading AI signal data")
    signal_df = load_signal_data()
    if not signal_df.empty:
        print(f"  Signal data: {len(signal_df)} rows, "
              f"{signal_df.index.get_level_values(0).nunique()} stocks, "
              f"{signal_df.index.get_level_values(1).nunique()} dates")
        print(f"  Signal stocks: {sorted(signal_df.index.get_level_values(0).unique().tolist())}")
        print(f"  Signal sparsity: {signal_df.isna().sum().sum()}/{signal_df.size} NaN")
    else:
        print("  No signal data found. Will create synthetic signals for comparison.")

    # ------------------------------------------------------------------
    # Model A: OHLCV only
    # ------------------------------------------------------------------
    print_header("Step 4a: Training Model A (OHLCV only)")
    _, dataset_a = build_handler_dataset(ohlcv_df, OHLCV_FEATURES)
    model_a = train_model(dataset_a)
    pred_a = predict_and_evaluate(model_a, dataset_a)
    print(f"  Predictions: {len(pred_a)} values")
    if not pred_a.empty:
        print(f"  Pred range: [{pred_a.min():.4f}, {pred_a.max():.4f}], "
              f"mean={pred_a.mean():.4f}")

    # ------------------------------------------------------------------
    # Model B: OHLCV + AI signals
    # ------------------------------------------------------------------
    print_header("Step 4b: Training Model B (OHLCV + AI signals)")
    extended_df = add_signals(ohlcv_df, signal_df)

    # Feature columns for model B
    all_features = OHLCV_FEATURES + SIGNAL_FEATURES

    # For stocks without signal data, fill with 0 (LightGBM handles NaN natively
    # but we also want to be explicit)
    for col in SIGNAL_FEATURES:
        na_count = extended_df[col].isna().sum()
        total = len(extended_df)
        print(f"  {col}: {na_count}/{total} NaN ({na_count/total*100:.1f}%)")

    _, dataset_b = build_handler_dataset(extended_df, all_features)
    model_b = train_model(dataset_b)
    pred_b = predict_and_evaluate(model_b, dataset_b)
    print(f"  Predictions: {len(pred_b)} values")
    if not pred_b.empty:
        print(f"  Pred range: [{pred_b.min():.4f}, {pred_b.max():.4f}], "
              f"mean={pred_b.mean():.4f}")

    # ------------------------------------------------------------------
    # Model C: OHLCV + RD-Agent factors
    # ------------------------------------------------------------------
    print_header("Step 4c: Training Model C (OHLCV + RD-Agent factors)")
    rd_agent_df = add_rd_agent_factors(ohlcv_df)

    ohlcv_plus_rd_features = OHLCV_FEATURES + RD_AGENT_FEATURES

    _, dataset_c = build_handler_dataset(rd_agent_df, ohlcv_plus_rd_features)
    model_c = train_model(dataset_c)
    pred_c = predict_and_evaluate(model_c, dataset_c)
    print(f"  Predictions: {len(pred_c)} values")
    if not pred_c.empty:
        print(f"  Pred range: [{pred_c.min():.4f}, {pred_c.max():.4f}], "
              f"mean={pred_c.mean():.4f}")

    # ------------------------------------------------------------------
    # Backtesting
    # ------------------------------------------------------------------
    print_header("Step 5: Backtesting")

    # Filter price data for test period
    test_mask = (ohlcv_df.index.get_level_values(1) >= TEST_START) & \
                (ohlcv_df.index.get_level_values(1) <= TEST_END)
    test_price_df = ohlcv_df.loc[test_mask, ["$close"]]

    print("\n  === Model A (OHLCV only) ===")
    metrics_a = simple_backtest(pred_a, ohlcv_df, top_k=5, hold_days=2)

    print("\n  === Model B (OHLCV + AI signals) ===")
    metrics_b = simple_backtest(pred_b, ohlcv_df, top_k=5, hold_days=2)

    print("\n  === Model C (OHLCV + RD-Agent factors) ===")
    metrics_c = simple_backtest(pred_c, ohlcv_df, top_k=5, hold_days=2)

    # Compute IC metrics for each model
    print("\n  === Computing IC Metrics ===")
    ic_a = compute_ic_metrics(pred_a, ohlcv_df, label_shift=2)
    ic_b = compute_ic_metrics(pred_b, ohlcv_df, label_shift=2)
    ic_c = compute_ic_metrics(pred_c, ohlcv_df, label_shift=2)
    print(f"  Model A IC: {ic_a['mean_ic']:.4f} (ICIR={ic_a['icir']:.2f})")
    print(f"  Model B IC: {ic_b['mean_ic']:.4f} (ICIR={ic_b['icir']:.2f})")
    print(f"  Model C IC: {ic_c['mean_ic']:.4f} (ICIR={ic_c['icir']:.2f})")

    # Update metrics dicts with IC for CSV export
    metrics_a.update(ic_a)
    metrics_b.update(ic_b)
    metrics_c.update(ic_c)

    # Benchmark: equal-weight buy-and-hold of 20 target stocks
    print("\n  === Benchmark (Buy & Hold 20 target stocks) ===")
    metrics_bench = benchmark_backtest(ohlcv_df, TARGET_STOCKS)
    print(f"  Benchmark cumulative return: {metrics_bench['cum_return']:.2%}")
    print(f"  Benchmark annualized return: {metrics_bench['ann_return']:.2%}")
    print(f"  Benchmark final capital: {metrics_bench['final_capital']:,.0f}")

    # ------------------------------------------------------------------
    # Results summary
    # ------------------------------------------------------------------
    print_header("Step 6: Results Summary")

    print(f"""
+==============================================================================+
|                    MODEL COMPARISON RESULTS                                  |
+==============================================================================+
|  Metric              | Model A (OHLCV)   | Model B (OHLCV+AI) | Model C (RD-Agent) |
+==============================================================================+
|  Cumulative Return   | {metrics_a['cum_return']:>10.2%}       | {metrics_b['cum_return']:>10.2%}        | {metrics_c['cum_return']:>10.2%}        |
|  Annualized Return   | {metrics_a['ann_return']:>10.2%}       | {metrics_b['ann_return']:>10.2%}        | {metrics_c['ann_return']:>10.2%}        |
|  Max Drawdown        | {metrics_a['max_drawdown']:>10.2%}       | {metrics_b['max_drawdown']:>10.2%}        | {metrics_c['max_drawdown']:>10.2%}        |
|  Sharpe Ratio        | {metrics_a['sharpe']:>10.2f}        | {metrics_b['sharpe']:>10.2f}         | {metrics_c['sharpe']:>10.2f}         |
|  # Trades            | {metrics_a['n_trades']:>10d}        | {metrics_b['n_trades']:>10d}         | {metrics_c['n_trades']:>10d}         |
|  Final Capital       | {metrics_a['final_capital']:>13,.0f}    | {metrics_b['final_capital']:>13,.0f}     | {metrics_c['final_capital']:>13,.0f}     |
|  Mean IC             | {ic_a['mean_ic']:>10.4f}        | {ic_b['mean_ic']:>10.4f}         | {ic_c['mean_ic']:>10.4f}         |
|  ICIR                | {ic_a['icir']:>10.2f}        | {ic_b['icir']:>10.2f}         | {ic_c['icir']:>10.2f}         |
|  IC > 0 Ratio        | {ic_a['ic_positive_ratio']:>10.1%}        | {ic_b['ic_positive_ratio']:>10.1%}         | {ic_c['ic_positive_ratio']:>10.1%}         |
+==============================================================================+
|  Benchmark (Buy&Hold): Cum Ret={metrics_bench['cum_return']:.2%}  Ann Ret={metrics_bench['ann_return']:.2%}  Capital={metrics_bench['final_capital']:,.0f}  |
+==============================================================================+
|  Universe: {len(universe)} stocks  |  Test: {TEST_START} to {TEST_END}                      |
|  Features A: {len(OHLCV_FEATURES)} OHLCV  |  Features B: {len(all_features)} (OHLCV+AI)  |  Features C: {len(ohlcv_plus_rd_features)} (OHLCV+RD-Agent) |
+==============================================================================+
""")

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------
    results_dir = os.path.join(os.path.dirname(__file__), "qlib_results")
    os.makedirs(results_dir, exist_ok=True)

    # Save predictions
    pred_a.to_csv(os.path.join(results_dir, "predictions_ohlcv.csv"))
    pred_b.to_csv(os.path.join(results_dir, "predictions_ohlcv_ai.csv"))
    pred_c.to_csv(os.path.join(results_dir, "predictions_ohlcv_rd_agent.csv"))

    # Save metrics
    metrics_df = pd.DataFrame([metrics_a, metrics_b, metrics_c],
                              index=["Model_A_OHLCV", "Model_B_OHLCV_AI", "Model_C_OHLCV_RD_Agent"])
    metrics_df.to_csv(os.path.join(results_dir, "backtest_metrics.csv"))

    # Save signal coverage info
    signal_info = {
        "target_stocks": TARGET_STOCKS,
        "signal_dates": [],
        "total_signal_rows": len(signal_df) if not signal_df.empty else 0,
        "features_ohlcv": OHLCV_FEATURES,
        "features_with_signals": all_features,
        "features_rd_agent": ohlcv_plus_rd_features,
        "rd_agent_factors": RD_AGENT_FEATURES,
    }
    if not signal_df.empty:
        signal_info["signal_dates"] = [
            str(d.date()) for d in sorted(signal_df.index.get_level_values(1).unique())
        ]

    import json
    with open(os.path.join(results_dir, "experiment_info.json"), "w") as f:
        json.dump(signal_info, f, indent=2, default=str)

    print(f"  Results saved to: {results_dir}")
    print_header("Done!")


if __name__ == "__main__":
    main()
