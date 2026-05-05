import copy
import tradingagents.default_config as default_config
from typing import Dict, Optional

# Use default config but allow it to be overridden
_config: Optional[Dict] = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: Dict):
    """Replace the configuration with a fresh template merged with *config*.

    Every call starts from a clean deepcopy of DEFAULT_CONFIG_TEMPLATE so
    that leftover values from a previous analysis run cannot leak into the
    next one.  This is critical because the CLI runs multiple analyses in a
    single process (e.g. batch_analyze.py or repeated TUI runs).
    """
    global _config
    _config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    _config.update(config)


def get_config() -> Dict:
    """Get a shallow copy of the current configuration.

    Note: the copy is shallow — callers should not mutate nested dicts
    (e.g. ``data_vendors``). Use ``set_config()`` to apply changes.
    """
    if _config is None:
        initialize_config()
    return _config.copy()


def reset_config():
    """Reset the module-level config to a fresh copy of defaults.

    Called by TradingAgentsGraph.__init__() so each analysis run starts
    with a clean config regardless of what previous runs left behind.
    """
    global _config
    _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


# Initialize with default config
initialize_config()
