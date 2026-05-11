import copy
import os
import sys

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


# Immutable template — never hand out references to the nested dicts.
_DEFAULT_CONFIG_TEMPLATE = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # LLM HTTP timeout / retry — prevents indefinite hang on network issues.
    # timeout: seconds before raising ConnectTimeout/ReadTimeout (default: 120).
    # max_retries: number of retries on transient failures (default: 2).
    "llm_timeout": 120,
    "llm_max_retries": 2,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 250,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    # Options per category: yfinance, alpha_vantage, tencent_sina, akshare, twelve_data, tushare
    # Comma-separated = fallback chain (first success wins)
    "data_vendors": {
        "core_stock_apis": "twelve_data,yfinance",
        "technical_indicators": "twelve_data,yfinance",
        "fundamental_data": "twelve_data,yfinance",
        "news_data": "twelve_data,yfinance",
        "sentiment_data": "akshare",              # akshare only (stock_comment_em)
        "opencli_market": "opencli",              # opencli only (extended market data)
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Unified per-vendor rate limiting
    # When enabled, route_to_vendor() automatically throttles calls to each
    # vendor according to the limits below.  Vendors with their own internal
    # rate limiter (e.g. twelve_data) are intentionally omitted.
    "rate_limit_enabled": True,
    "rate_limits": {
        # "vendor_name": {"min_interval": seconds, "calls_per_minute": int}
        # User overrides here are merged with the defaults in rate_limiter.py.
        # Uncomment to override:
        # "tencent_sina":  {"min_interval": 0.3, "calls_per_minute": 120},
        # "akshare":       {"min_interval": 0.5, "calls_per_minute": 60},
        # "yfinance":      {"min_interval": 1.0, "calls_per_minute": 30},
        # "alpha_vantage": {"min_interval": 0.5, "calls_per_minute": 5},
        # "opencli":       {"min_interval": 0.5, "calls_per_minute": 60},
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",    # NSE India (Nifty 50)
        ".BO":  "^BSESN",   # BSE India (Sensex)
        ".T":   "^N225",    # Tokyo (Nikkei 225)
        ".HK":  "^HSI",     # Hong Kong (Hang Seng)
        ".L":   "^FTSE",    # London (FTSE 100)
        ".TO":  "^GSPTSE",  # Toronto (TSX Composite)
        ".AX":  "^AXJO",    # Australia (ASX 200)
        "":     "SPY",      # default for US-listed tickers (no suffix)
    },
})


def get_default_config() -> dict:
    """Return a deep copy of the default config, safe to mutate freely.

    Every call returns an independent copy — mutating the result never
    affects subsequent calls or the module-level template.
    """
    return copy.deepcopy(_DEFAULT_CONFIG_TEMPLATE)


# ---------------------------------------------------------------------------
# Module-level DEFAULT_CONFIG that is safe to use with .copy()
# ---------------------------------------------------------------------------
# The problem: ``from tradingagents.default_config import DEFAULT_CONFIG``
# captures a *reference* to the dict at import time.  If code later does
# ``config = DEFAULT_CONFIG.copy()`` (shallow) and mutates nested dicts like
# ``data_vendors``, the mutation leaks back into DEFAULT_CONFIG and poisons
# every subsequent call in the same process.
#
# Fix: replace this module in ``sys.modules`` with a wrapper whose
# ``__getattr__`` returns a **fresh deep copy** on every attribute access
# of ``DEFAULT_CONFIG``.  ``from ... import DEFAULT_CONFIG`` still works
# (Python calls ``__getattr__`` on the module during the import binding),
# but each binding gets its own independent copy.
#
# ``get_default_config()`` remains available as an explicit alternative.
# ---------------------------------------------------------------------------

class _SafeConfigModule(type(sys)):
    """Module subclass that returns a fresh deep copy for DEFAULT_CONFIG."""

    def __getattr__(self, name):
        if name == "DEFAULT_CONFIG":
            return get_default_config()
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")


_this = sys.modules[__name__]
_new = _SafeConfigModule(__name__)
_new.__dict__.update(
    {k: v for k, v in _this.__dict__.items() if not k.startswith("__")}
)
# Preserve dunder attributes from the real module
_new.__file__ = __file__
_new.__package__ = __package__
_new.__spec__ = __spec__
sys.modules[__name__] = _new
