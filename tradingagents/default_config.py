import copy
import os
import sys

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Immutable template — never hand out references to the nested dicts.
_DEFAULT_CONFIG_TEMPLATE = {
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
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    # Options per category: yfinance, alpha_vantage, tencent_sina, akshare
    # Comma-separated = fallback chain (first success wins)
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
        "sentiment_data": "akshare",              # akshare only (stock_comment_em)
        "opencli_market": "opencli",              # opencli only (extended market data)
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}


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
