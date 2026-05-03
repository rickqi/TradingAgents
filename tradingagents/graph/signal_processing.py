"""Extract the 5-tier portfolio rating from the Portfolio Manager's decision.

The Portfolio Manager produces a typed ``PortfolioDecision`` via structured
output and renders it to markdown that always carries a ``**Rating**: X``
header (see :func:`tradingagents.agents.schemas.render_pm_decision`).  The
deterministic heuristic in :mod:`tradingagents.agents.utils.rating` is more
than sufficient to extract that rating; no extra LLM call is needed.

This module exists for backwards compatibility with callers that expect a
``SignalProcessor.process_signal(text)`` interface.
"""

from __future__ import annotations

import re
from typing import Any

from tradingagents.agents.utils.rating import parse_rating


def _deduplicate_proposals(text: str) -> str:
    """Remove duplicate FINAL TRANSACTION PROPOSAL blocks from DeepSeek output.

    Some LLM providers (notably DeepSeek) repeat the proposal block multiple
    times in the response. This keeps only the first occurrence.
    """
    pattern = r"(FINAL TRANSACTION PROPOSAL:.*?)(?=FINAL TRANSACTION PROPOSAL:|$)"
    matches = re.findall(pattern, text, re.DOTALL)
    if len(matches) > 1:
        return matches[0].strip()
    return text


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        # The LLM argument is accepted for backwards compatibility but no
        # longer used: the PM's structured output guarantees the rating is
        # parseable from the rendered markdown without a second LLM call.
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell."""
        deduped = _deduplicate_proposals(full_signal)
        return parse_rating(deduped)
