"""TradingAgents → Qlib integration pipeline.

Provides utilities for converting TradingAgents' cached OHLCV data and
AI analysis signals into Qlib binary format for quantitative model training.

Key modules:

- :mod:`ticker_mapper` — Bidirectional ticker format conversion
  (TradingAgents ↔ Qlib instrument format)
- :mod:`cache_scanner` — Discover cached OHLCV CSV files on disk
- :mod:`converter` — Convert OHLCV DataFrames to Qlib binary format
- :mod:`signal_extractor` — Extract AI trading signals from analysis results
"""

from tradingagents.qlib.ticker_mapper import (
    from_qlib_instrument,
    is_ashare_ticker,
    qlib_instrument_to_dirname,
    ticker_from_cache_filename,
    to_qlib_instrument,
)

__all__ = [
    "from_qlib_instrument",
    "is_ashare_ticker",
    "qlib_instrument_to_dirname",
    "ticker_from_cache_filename",
    "to_qlib_instrument",
]
