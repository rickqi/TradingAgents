"""Bidirectional ticker format conversion for TradingAgents ↔ Qlib.

Qlib identifies Chinese A-share instruments by an uppercase exchange prefix
followed by the 6-digit stock code, e.g. ``"SH600519"``, ``"SZ000858"``,
``"BJ430047"``.  TradingAgents uses the more common ``"600519.SH"`` suffix
notation (or plain 6-digit codes).

This module provides **pure, side-effect-free** conversion functions with no
external dependencies.  All functions are fully typed and documented.

Mapping rules (exchange inference for bare 6-digit codes)::

    First digit(s)   → Exchange
    ─────────────────────────────
    6, 9             → SH  (Shanghai main board / STAR)
    0, 2, 3          → SZ  (Shenzhen main board / ChiNext)
    4, 8             → BJ  (Beijing Stock Exchange / NEEQ)
    anything else    → pass through unchanged
"""

from __future__ import annotations

import re

# ── Compiled patterns ────────────────────────────────────────────────────────

# Matches OHLCV cache filenames produced by TradingAgents data vendors.
# Examples:
#   "000858.SZ-Tencent-data-2021-05-08-2026-05-08.csv"
#   "NVDA-YFin-data-2021-05-08-2026-05-08.csv"
#   "600519.SH-AKShare-data-2021-05-08-2026-05-08.csv"
_CACHE_PATTERN = re.compile(
    r"^(.+?)-(?:YFin|Tencent|AKShare)-data-\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}\.csv$"
)

# Known exchange suffixes and their canonical form (uppercase).
_SUFFIX_MAP: dict[str, str] = {
    ".SZ": "SZ",
    ".SH": "SH",
    ".SS": "SH",   # Yahoo Finance uses .SS for Shanghai
    ".BJ": "BJ",
}

# Qlib exchange prefixes (uppercase).
_QLIB_PREFIXES = ("SH", "SZ", "BJ")


# ── Internal helpers ─────────────────────────────────────────────────────────


def _infer_exchange(code: str) -> str | None:
    """Infer the exchange from a bare 6-digit stock code.

    Parameters
    ----------
    code:
        A 6-digit string, e.g. ``"600519"``.

    Returns
    -------
    str | None
        ``"SH"``, ``"SZ"``, ``"BJ"``, or ``None`` if the code does not match
        any known A-share pattern.

    Examples
    --------
    >>> _infer_exchange("600519")
    'SH'
    >>> _infer_exchange("000858")
    'SZ'
    >>> _infer_exchange("430047")
    'BJ'
    >>> _infer_exchange("ABC") is None
    True
    """
    if not code.isdigit() or len(code) != 6:
        return None
    first = code[0]
    if first in ("6", "9"):
        return "SH"
    if first in ("0", "2", "3"):
        return "SZ"
    if first in ("4", "8"):
        return "BJ"
    return None


def _strip_and_split(ticker: str) -> tuple[str, str | None]:
    """Split a ticker into ``(code, exchange_or_None)``.

    Handles suffix format (``"600519.SH"``), prefix format (``"SH600519"``),
    and bare codes (``"600519"``).

    Returns
    -------
    tuple[str, str | None]
        ``(code, exchange)`` where *exchange* is ``None`` for bare codes or
        non-Chinese tickers.
    """
    t = ticker.strip()
    if not t:
        return (t, None)

    # Suffix format: "600519.SH", "000858.SZ"
    for suffix, exchange in _SUFFIX_MAP.items():
        if t.upper().endswith(suffix):
            code = t[: -len(suffix)]
            return (code, exchange)

    # Prefix format (already Qlib-style): "SH600519"
    upper = t.upper()
    for prefix in _QLIB_PREFIXES:
        if upper.startswith(prefix) and len(t) > 2:
            code = t[2:]
            if code.isdigit():
                return (code, prefix)

    # Bare code or non-Chinese
    return (t, None)


# ── Public API ────────────────────────────────────────────────────────────────


def to_qlib_instrument(ticker: str) -> str:
    """Convert a TradingAgents ticker to Qlib instrument format.

    Handles single tickers and comma-separated lists.  Non-Chinese tickers
    are returned unchanged.

    Parameters
    ----------
    ticker:
        A ticker string in TradingAgents format.  Accepted forms:

        - Bare 6-digit code: ``"600519"`` → ``"SH600519"``
        - Suffix notation: ``"000858.SZ"`` → ``"SZ000858"``
        - Suffix notation (Shanghai): ``"603208.SH"`` → ``"SH603208"``
        - Suffix notation (.SS variant): ``"600519.SS"`` → ``"SH600519"``
        - Beijing exchange: ``"430047.BJ"`` → ``"BJ430047"``
        - Non-Chinese: ``"NVDA"`` → ``"NVDA"``
        - Comma-separated: ``"600519,000858.SZ"`` → ``"SH600519,SZ000858"``
        - Already Qlib format: ``"SH600519"`` → ``"SH600519"`` (idempotent)

    Returns
    -------
    str
        Qlib instrument identifier(s), comma-separated if the input was
        comma-separated.

    Examples
    --------
    >>> to_qlib_instrument("600519")
    'SH600519'
    >>> to_qlib_instrument("000858")
    'SZ000858'
    >>> to_qlib_instrument("002876.SZ")
    'SZ002876'
    >>> to_qlib_instrument("600519.SH")
    'SH600519'
    >>> to_qlib_instrument("430047.BJ")
    'BJ430047'
    >>> to_qlib_instrument("NVDA")
    'NVDA'
    >>> to_qlib_instrument("600519,000858.SZ,NVDA")
    'SH600519,SZ000858,NVDA'
    >>> to_qlib_instrument("SH600519")
    'SH600519'
    """
    # Handle comma-separated input — strip quotes from each token.
    if "," in ticker:
        parts = [
            to_qlib_instrument(tok.strip().strip('"').strip("'"))
            for tok in ticker.split(",")
            if tok.strip()
        ]
        return ",".join(parts)

    code, exchange = _strip_and_split(ticker)

    if exchange is not None:
        # Suffix format resolved — rebuild with prefix.
        return f"{exchange}{code}"

    # No explicit exchange — try to infer from the code.
    if code.isdigit() and len(code) == 6:
        inferred = _infer_exchange(code)
        if inferred is not None:
            return f"{inferred}{code}"

    # Non-Chinese or unrecognised — pass through.
    return ticker


def from_qlib_instrument(instrument: str) -> str:
    """Convert a Qlib instrument identifier to TradingAgents format.

    Parameters
    ----------
    instrument:
        A Qlib instrument string, e.g. ``"SH600519"``.
        Also accepts lowercase (as found in directory names):
        ``"sh600519"`` → ``"600519.SH"``.
        Non-prefixed values (e.g. ``"NVDA"``) are returned unchanged.

    Returns
    -------
    str
        Ticker in TradingAgents suffix notation.

    Examples
    --------
    >>> from_qlib_instrument("SH600519")
    '600519.SH'
    >>> from_qlib_instrument("SZ000858")
    '000858.SZ'
    >>> from_qlib_instrument("BJ430047")
    '430047.BJ'
    >>> from_qlib_instrument("sh600519")
    '600519.SH'
    >>> from_qlib_instrument("NVDA")
    'NVDA'
    """
    if not instrument:
        return instrument

    upper = instrument.upper()
    for prefix in _QLIB_PREFIXES:
        if upper.startswith(prefix) and len(instrument) > 2:
            code = instrument[2:]
            # Only convert if the remainder is a digit string (A-share code).
            if code.isdigit():
                return f"{code}.{prefix}"

    # No recognised prefix — pass through.
    return instrument


def is_ashare_ticker(ticker: str) -> bool:
    """Check whether *ticker* is an A-share (Chinese) stock identifier.

    Recognises:
    - Bare 6-digit codes: ``"600519"``
    - Suffix notation: ``"000858.SZ"``, ``"603208.SH"``, ``"430047.BJ"``
    - Qlib prefix notation: ``"SH600519"``, ``"SZ000858"``
    - Comma-separated lists (returns ``True`` if **any** element is A-share)

    Parameters
    ----------
    ticker:
        A ticker string, possibly comma-separated.

    Returns
    -------
    bool
        ``True`` if *ticker* looks like an A-share stock.

    Examples
    --------
    >>> is_ashare_ticker("600519")
    True
    >>> is_ashare_ticker("000858.SZ")
    True
    >>> is_ashare_ticker("SH600519")
    True
    >>> is_ashare_ticker("NVDA")
    False
    >>> is_ashare_ticker("600519,NVDA")
    True
    >>> is_ashare_ticker("NVDA,AAPL")
    False
    """
    for part in ticker.split(","):
        t = part.strip().strip('"').strip("'").strip()
        if not t:
            continue
        code, exchange = _strip_and_split(t)
        # Explicit exchange → definitely A-share.
        if exchange is not None:
            return True
        # Bare 6-digit code → assume A-share.
        if code.isdigit() and len(code) == 6:
            return True
    return False


def ticker_from_cache_filename(filename: str) -> str:
    """Extract the TradingAgents ticker from an OHLCV cache filename.

    Parameters
    ----------
    filename:
        A cache filename (basename only, no directory component).
        Expected patterns include:

        - ``"000858.SZ-Tencent-data-2021-05-08-2026-05-08.csv"``
        - ``"NVDA-YFin-data-2021-05-08-2026-05-08.csv"``
        - ``"600519.SH-AKShare-data-2021-05-08-2026-05-08.csv"``

    Returns
    -------
    str
        The ticker portion, e.g. ``"000858.SZ"`` or ``"NVDA"``.
        Returns *filename* unchanged if the pattern does not match.

    Examples
    --------
    >>> ticker_from_cache_filename("000858.SZ-Tencent-data-2021-05-08-2026-05-08.csv")
    '000858.SZ'
    >>> ticker_from_cache_filename("NVDA-YFin-data-2021-05-08-2026-05-08.csv")
    'NVDA'
    >>> ticker_from_cache_filename("600519.SH-AKShare-data-2021-05-08-2026-05-08.csv")
    '600519.SH'
    >>> ticker_from_cache_filename("random.txt")
    'random.txt'
    """
    match = _CACHE_PATTERN.match(filename)
    if match:
        return match.group(1)
    return filename


def qlib_instrument_to_dirname(instrument: str) -> str:
    """Return the lowercase directory name Qlib uses for *instrument*.

    Qlib stores per-instrument feature data in lowercase directories under
    ``qlib_data/instruments/``, e.g. ``"sh600519"``.

    Parameters
    ----------
    instrument:
        A Qlib instrument identifier, e.g. ``"SH600519"``.
        Non-Chinese tickers are lowercased as-is.

    Returns
    -------
    str
        Lowercase directory name.

    Examples
    --------
    >>> qlib_instrument_to_dirname("SH600519")
    'sh600519'
    >>> qlib_instrument_to_dirname("SZ000858")
    'sz000858'
    >>> qlib_instrument_to_dirname("BJ430047")
    'bj430047'
    >>> qlib_instrument_to_dirname("NVDA")
    'nvda'
    """
    return instrument.lower()
