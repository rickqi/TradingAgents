"""Unified, per-vendor rate limiter for TradingAgents dataflows.

Provides a ``VendorRateLimiter`` that tracks API call timestamps per vendor
and enforces configurable **minimum interval** (time between consecutive calls)
and **per-minute budget** (max calls per 60-second window).

Each vendor gets its own limit profile, tuned to the real-world constraints
of the underlying API:

+---------------+-------------------+--------------------+---------------------------+
| Vendor        | min_interval (s)  | calls_per_minute   | Rationale                 |
+===============+===================+====================+===========================+
| tencent_sina  | 0.3               | 120                | Tencent K-line is generous|
| akshare       | 0.5               | 60                 | EastMoney-backed, polite  |
| yfinance      | 1.0               | 30                 | Aggressive rate-limiting  |
| alpha_vantage | 0.5               | 5                  | Free tier: 5/min          |
| twelve_data   | —                 | —                  | Has its own credit system |
| opencli       | 0.5               | 60                 | Subprocess calls          |
| tushare       | 0.3               | 120                | Pro API: 500/min base     |
+---------------+-------------------+--------------------+---------------------------+

Design decisions
----------------
- **Per-vendor isolation**: slow vendor A won't block vendor B.
- **Thread-safe**: uses ``threading.Lock`` so the LangGraph async ToolNode
  can call data tools concurrently without data races.
- **Self-tuning cooldown**: after a 429 response the caller can flag it via
  ``mark_rate_limited()`` which adds an exponentially growing penalty.
- **Zero overhead when disabled**: if ``rate_limit_enabled`` is ``False`` in
  config, ``wait()`` returns immediately.

Usage::

    from tradingagents.dataflows.rate_limiter import get_rate_limiter

    limiter = get_rate_limiter()
    limiter.wait("tencent_sina")         # blocks until a slot is free
    ... call vendor API ...
    limiter.mark_rate_limited("tencent_sina")  # optional: signal 429

Config keys (in DEFAULT_CONFIG)::

    "rate_limit_enabled": True,
    "rate_limits": {
        "tencent_sina":  {"min_interval": 0.3, "calls_per_minute": 120},
        "akshare":       {"min_interval": 0.5, "calls_per_minute": 60},
        "yfinance":      {"min_interval": 1.0, "calls_per_minute": 30},
        "alpha_vantage": {"min_interval": 0.5, "calls_per_minute": 5},
        "opencli":       {"min_interval": 0.5, "calls_per_minute": 60},
    }
"""

from __future__ import annotations

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-vendor limit profile
# ---------------------------------------------------------------------------

@dataclass
class VendorLimit:
    """Rate-limit profile for a single vendor."""

    min_interval: float = 0.5
    """Minimum seconds between two consecutive calls."""

    calls_per_minute: int = 60
    """Maximum calls allowed within any 60-second sliding window."""

    # Runtime state (not serialised)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _timestamps: list[float] = field(default_factory=list, repr=False)
    _last_call: float = field(default=0.0, repr=False)
    _penalty: float = field(default=0.0, repr=False)
    """Exponential backoff penalty, grows on repeated 429s."""

    def wait(self) -> None:
        """Block until this vendor's rate limit allows a new call.

        1. Enforce *min_interval* (plus any active penalty).
        2. Enforce *calls_per_minute* by waiting for the oldest slot to expire.
        """
        with self._lock:
            now = time.monotonic()

            # --- 1. min_interval + penalty ---
            effective_interval = self.min_interval + self._penalty
            elapsed = now - self._last_call
            if elapsed < effective_interval:
                wait_time = effective_interval - elapsed
                logger.debug(
                    "Rate limiter: waiting %.2fs (min_interval=%.2fs + penalty=%.2fs)",
                    wait_time, self.min_interval, self._penalty,
                )
                # Release lock during sleep so other threads aren't blocked.
                self._lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._lock.acquire()
                now = time.monotonic()

            # --- 2. sliding window budget ---
            window = 60.0
            cutoff = now - window
            # Prune old timestamps
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.pop(0)

            if len(self._timestamps) >= self.calls_per_minute:
                wait_until = self._timestamps[0] + window
                wait_time = wait_until - now
                if wait_time > 0:
                    logger.info(
                        "Rate limiter: budget exhausted (%d/%d in last %.0fs), "
                        "waiting %.1fs for slot",
                        len(self._timestamps), self.calls_per_minute, window,
                        wait_time,
                    )
                    self._lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self._lock.acquire()
                    now = time.monotonic()
                    # Prune again after waking
                    cutoff = now - window
                    while self._timestamps and self._timestamps[0] < cutoff:
                        self._timestamps.pop(0)

            # Record this call
            self._timestamps.append(time.monotonic())
            self._last_call = time.monotonic()

    def mark_rate_limited(self) -> None:
        """Signal that the last call received a 429 / rate-limit response.

        Adds an exponentially growing penalty.  Call ``reset_penalty()`` after
        a successful call to reset the backoff.
        """
        with self._lock:
            if self._penalty < 0.1:
                self._penalty = 1.0  # start at 1 second
            else:
                self._penalty = min(self._penalty * 2.0, 30.0)  # cap at 30s
            logger.info(
                "Rate limiter: rate-limited response detected, penalty now %.1fs",
                self._penalty,
            )

    def reset_penalty(self) -> None:
        """Clear the backoff penalty after a successful call."""
        with self._lock:
            self._penalty = 0.0


# ---------------------------------------------------------------------------
# Global rate limiter singleton
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS: dict[str, dict] = {
    "tencent_sina":  {"min_interval": 0.3, "calls_per_minute": 120},
    "akshare":       {"min_interval": 0.5, "calls_per_minute": 60},
    "yfinance":      {"min_interval": 1.0, "calls_per_minute": 30},
    "alpha_vantage": {"min_interval": 0.5, "calls_per_minute": 5},
    "opencli":       {"min_interval": 0.5, "calls_per_minute": 60},
    "tushare":       {"min_interval": 0.3, "calls_per_minute": 120},
}

_instance: Optional[VendorRateLimiter] = None
_instance_lock = threading.Lock()


class VendorRateLimiter:
    """Process-wide, per-vendor rate limiter.

    Use :func:`get_rate_limiter` to obtain the singleton.
    """

    def __init__(self, limits: dict[str, dict] | None = None,
                 enabled: bool = True) -> None:
        self.enabled = enabled
        limits = limits or _DEFAULT_LIMITS
        self._vendors: dict[str, VendorLimit] = {}
        for vendor, cfg in limits.items():
            self._vendors[vendor] = VendorLimit(
                min_interval=cfg.get("min_interval", 0.5),
                calls_per_minute=cfg.get("calls_per_minute", 60),
            )

    def wait(self, vendor: str) -> None:
        """Block until *vendor* allows a new API call.

        No-op when the limiter is disabled or the vendor is not registered
        (e.g. ``"twelve_data"`` manages its own credits).
        """
        if not self.enabled:
            return
        vl = self._vendors.get(vendor)
        if vl is None:
            return  # vendor manages its own throttling
        vl.wait()

    def mark_rate_limited(self, vendor: str) -> None:
        """Signal that *vendor* returned a rate-limit response."""
        vl = self._vendors.get(vendor)
        if vl is not None:
            vl.mark_rate_limited()

    def reset_penalty(self, vendor: str) -> None:
        """Clear backoff penalty for *vendor* after a successful call."""
        vl = self._vendors.get(vendor)
        if vl is not None:
            vl.reset_penalty()

    def get_vendor_stats(self, vendor: str) -> dict:
        """Return debugging info for *vendor*'s rate-limit state."""
        vl = self._vendors.get(vendor)
        if vl is None:
            return {"registered": False}
        with vl._lock:
            return {
                "registered": True,
                "min_interval": vl.min_interval,
                "calls_per_minute": vl.calls_per_minute,
                "calls_in_window": len(vl._timestamps),
                "penalty": vl._penalty,
                "last_call_ago": time.monotonic() - vl._last_call if vl._last_call else None,
            }


def get_rate_limiter() -> VendorRateLimiter:
    """Return the process-wide :class:`VendorRateLimiter` singleton.

    Configuration is read from ``DEFAULT_CONFIG`` on first call.  Subsequent
    calls return the same instance regardless of config changes.
    """
    global _instance
    if _instance is not None:
        return _instance

    with _instance_lock:
        if _instance is not None:
            return _instance

        # Read config (lazy import to avoid circular dependency at module load)
        from .config import get_config
        cfg = get_config()

        enabled = cfg.get("rate_limit_enabled", True)
        limits = cfg.get("rate_limits", {})

        # Merge user overrides with defaults
        merged = dict(_DEFAULT_LIMITS)
        for vendor, override in limits.items():
            if vendor in merged:
                merged[vendor].update(override)
            else:
                merged[vendor] = override

        _instance = VendorRateLimiter(limits=merged, enabled=enabled)
        return _instance


def reset_rate_limiter() -> None:
    """Discard the singleton (useful for testing)."""
    global _instance
    with _instance_lock:
        _instance = None
