from typing import Annotated
import time
import logging

logger = logging.getLogger(__name__)

from .rate_limiter import get_rate_limiter

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .tencent_sina import (
    get_YFin_data_online as get_tencent_stock,
    get_stock_stats_indicators_window as get_tencent_indicator,
    get_fundamentals as get_tencent_fundamentals,
    get_balance_sheet as get_tencent_balance_sheet,
    get_cashflow as get_tencent_cashflow,
    get_income_statement as get_tencent_income_statement,
    get_insider_transactions as get_tencent_insider_transactions,
    get_news as get_tencent_news,
    get_global_news as get_tencent_global_news,
)
from .akshare_vendor import (
    get_YFin_data_online as get_akshare_stock,
    get_stock_stats_indicators_window as get_akshare_indicator,
    get_fundamentals as get_akshare_fundamentals,
    get_balance_sheet as get_akshare_balance_sheet,
    get_cashflow as get_akshare_cashflow,
    get_income_statement as get_akshare_income_statement,
    get_insider_transactions as get_akshare_insider_transactions,
    get_sentiment as get_akshare_sentiment,
    get_news as get_akshare_news,
    get_global_news as get_akshare_global_news,
)
from .opencli_vendor import (
    get_money_flow as opencli_get_money_flow,
    get_sectors as opencli_get_sectors,
    get_northbound as opencli_get_northbound,
    get_longhu as opencli_get_longhu,
    get_hot_rank as opencli_get_hot_rank,
)
from .twelve_data import (
    get_stock_data as get_twelve_data_stock,
    get_indicators as get_twelve_data_indicator,
    get_fundamentals as get_twelve_data_fundamentals,
    get_balance_sheet as get_twelve_data_balance_sheet,
    get_cashflow as get_twelve_data_cashflow,
    get_income_statement as get_twelve_data_income_statement,
    get_news as get_twelve_data_news,
    get_global_news as get_twelve_data_global_news,
    get_insider_transactions as get_twelve_data_insider_transactions,
)
from .tushare import (
    get_stock_data as get_tushare_stock,
    get_indicators as get_tushare_indicator,
    get_fundamentals as get_tushare_fundamentals,
    get_balance_sheet as get_tushare_balance_sheet,
    get_cashflow as get_tushare_cashflow,
    get_income_statement as get_tushare_income_statement,
)

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "sentiment_data": {
        "description": "Market sentiment and social data",
        "tools": [
            "get_sentiment",
        ]
    },
    "opencli_market": {
        "description": "Extended market data via OpenCLI (money flow, sectors, northbound, longhu, hot rank)",
        "tools": [
            "get_money_flow",
            "get_sectors",
            "get_northbound",
            "get_longhu",
            "get_hot_rank",
        ]
    },
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "tencent_sina",
    "akshare",
    "opencli",
    "twelve_data",
    "tushare",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "tencent_sina": get_tencent_stock,
        "akshare": get_akshare_stock,
        "twelve_data": get_twelve_data_stock,
        "tushare": get_tushare_stock,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "tencent_sina": get_tencent_indicator,
        "akshare": get_akshare_indicator,
        "twelve_data": get_twelve_data_indicator,
        "tushare": get_tushare_indicator,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "tencent_sina": get_tencent_fundamentals,
        "akshare": get_akshare_fundamentals,
        "twelve_data": get_twelve_data_fundamentals,
        "tushare": get_tushare_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "tencent_sina": get_tencent_balance_sheet,
        "akshare": get_akshare_balance_sheet,
        "twelve_data": get_twelve_data_balance_sheet,
        "tushare": get_tushare_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "tencent_sina": get_tencent_cashflow,
        "akshare": get_akshare_cashflow,
        "twelve_data": get_twelve_data_cashflow,
        "tushare": get_tushare_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "tencent_sina": get_tencent_income_statement,
        "akshare": get_akshare_income_statement,
        "twelve_data": get_twelve_data_income_statement,
        "tushare": get_tushare_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "tencent_sina": get_tencent_news,
        "twelve_data": get_twelve_data_news,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "tencent_sina": get_tencent_global_news,
        "twelve_data": get_twelve_data_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "tencent_sina": get_tencent_insider_transactions,
        "akshare": get_akshare_insider_transactions,
        "twelve_data": get_twelve_data_insider_transactions,
    },
    # sentiment_data
    "get_sentiment": {
        "akshare": get_akshare_sentiment,
    },
    # opencli_market
    "get_money_flow": {
        "opencli": opencli_get_money_flow,
    },
    "get_sectors": {
        "opencli": opencli_get_sectors,
    },
    "get_northbound": {
        "opencli": opencli_get_northbound,
    },
    "get_longhu": {
        "opencli": opencli_get_longhu,
    },
    "get_hot_rank": {
        "opencli": opencli_get_hot_rank,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors.
    #
    # Chinese-mode (primary = tencent_sina/akshare):
    #   Skip yfinance/alpha_vantage — no useful A-share data, rate-limiting burns
    #   minutes of wall-clock time.
    #
    # Non-Chinese-mode (primary = yfinance/alpha_vantage):
    #   Skip tencent_sina/akshare — they reject non-A-share tickers ("Cannot
    #   normalize ticker 'NVDA' to a stock code"), wasting cooldown time and
    #   producing confusing error messages in the TUI.
    _CHINESE_VENDORS = {"tencent_sina", "akshare", "tushare"}
    _WESTERN_VENDORS = {"yfinance", "alpha_vantage", "twelve_data"}
    is_chinese_mode = any(v in _CHINESE_VENDORS for v in primary_vendors)

    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = []
    for vendor in primary_vendors:
        if is_chinese_mode and vendor in _WESTERN_VENDORS:
            continue
        if not is_chinese_mode and vendor in _CHINESE_VENDORS:
            continue
        fallback_vendors.append(vendor)
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            if is_chinese_mode and vendor in _WESTERN_VENDORS:
                continue
            if not is_chinese_mode and vendor in _CHINESE_VENDORS:
                continue
            fallback_vendors.append(vendor)

    last_error = None
    rate_limiter = get_rate_limiter()

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        # Pre-call: wait for vendor's rate limit slot
        rate_limiter.wait(vendor)

        try:
            result = impl_func(*args, **kwargs)
            # Success — clear any accumulated backoff penalty
            rate_limiter.reset_penalty(vendor)
            return result
        except Exception as e:
            last_error = e
            is_rate_limit = "Rate" in str(e) or "rate" in str(e) or "429" in str(e)
            if is_rate_limit:
                # Signal 429 → limiter adds exponential penalty
                rate_limiter.mark_rate_limited(vendor)
            logger.warning("Vendor '%s' failed for '%s': %s — trying next",
                           vendor, method, e)
            continue  # Any error triggers fallback to next vendor

    # All vendors failed — return a user-friendly message instead of crashing
    return (
        f"Error: All data vendors failed for '{method}'. "
        f"Please check your configuration and try again. "
        f"(Last error: {type(last_error).__name__}: {last_error})"
    )