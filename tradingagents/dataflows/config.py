import copy

from typing import Dict, Optional

import tradingagents.default_config as default_config

# Use default config but allow it to be overridden
_config: Optional[Dict] = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: Dict):
    """Update the configuration with custom values.

    Dict-valued keys (e.g. ``data_vendors``) are merged one level deep so a
    partial update like ``{"data_vendors": {"core_stock_apis": "alpha_vantage"}}``
    keeps the other nested keys from the default; scalar keys are replaced.
    """
    global _config
    initialize_config()
    incoming = copy.deepcopy(config)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value


def get_config() -> Dict:
    """Get a shallow copy of the current configuration.

    Note: the copy is shallow — callers should not mutate nested dicts
    (e.g. ``data_vendors``). Use ``set_config()`` to apply changes.
    """
    if _config is None:
        initialize_config()
    return copy.deepcopy(_config)


def reset_config():
    """Reset the module-level config to a fresh copy of defaults.

    Called by TradingAgentsGraph.__init__() so each analysis run starts
    with a clean config regardless of what previous runs left behind.
    """
    global _config
    _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


# Initialize with default config
initialize_config()
