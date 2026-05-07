# TradingAgents/graph/trading_graph.py

import logging
import os
import shutil
import sys
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news,
    get_sentiment,
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100)
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        # Universal timeout / retry — prevents indefinite hang on network issues
        timeout = self.config.get("llm_timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout
        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None:
            kwargs["max_retries"] = max_retries

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources.

        Market tools are sourced from ``market_analyst._build_market_tools()`` so
        that the ToolNode and ``bind_tools()`` always stay in sync — no duplicate
        maintenance.
        """
        # Import the single-source tool list from market_analyst
        from tradingagents.agents.analysts.market_analyst import _build_market_tools
        market_tools = _build_market_tools()

        # OpenCLI tools for other analysts (only loaded when opencli is installed)
        _opencli_news_tools = []
        _opencli_fundamentals_tools = []
        if shutil.which("opencli"):
            try:
                from tradingagents.agents.utils.opencli_tools import (
                    get_holders,
                    get_announcement,
                    get_kuaixun,
                )
                _opencli_fundamentals_tools = [get_holders]
                _opencli_news_tools = [get_announcement, get_kuaixun]
            except ImportError:
                pass

        return {
            "market": ToolNode(market_tools),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                    # Sentiment and mood data (akshare)
                    get_sentiment,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
                + _opencli_news_tools
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
                + _opencli_fundamentals_tools
            ),
        }

    @staticmethod
    def _is_chinese_ticker(ticker: str) -> bool:
        """Return True if ticker (or any ticker in a comma-separated list) looks like an A-share or HK stock code.

        A-share: 6-digit number (600183, 300308, 000001) optionally with
        .SS / .SZ / .SH suffix, or sh/sz prefix.
        HK:      5-digit number with .HK suffix or hk prefix (02149.HK).
        Handles comma-separated lists and surrounding quotes.
        """
        # Handle comma-separated tickers with optional quotes
        for part in ticker.split(","):
            t = str(part).strip().strip('"').strip("'").strip().lower()
            if not t:
                continue
            # Strip known prefixes
            for prefix in ("sh", "sz", "hk"):
                if t.startswith(prefix):
                    t = t[len(prefix):]
                    break
            # Strip exchange suffixes
            for suffix in (".sz", ".ss", ".sh", ".hk"):
                if t.endswith(suffix):
                    t = t[: -len(suffix)]
                    break
            # A-share: 6-digit number
            if len(t) == 6 and t.isdigit():
                return True
            # HK: 4-5 digit number (after stripping .HK)
            if 4 <= len(t) <= 5 and t.isdigit():
                return True
        return False

    def _auto_detect_vendor(self, ticker: str):
        """Switch data_vendors to tencent_sina if ticker is A-share / HK.

        Only switches when the current vendor config is still the default
        (yfinance).  If the user has explicitly set a vendor, we leave it.
        """
        if not self._is_chinese_ticker(ticker):
            return

        current_vendors = self.config.get("data_vendors", {})
        # Only check the 4 core categories that default to "yfinance".
        # "sentiment_data" defaults to "akshare" which would falsely trigger
        # the early return below.
        core_categories = ("core_stock_apis", "technical_indicators",
                           "fundamental_data", "news_data")
        non_default = [current_vendors.get(k, "yfinance")
                       for k in core_categories
                       if current_vendors.get(k, "yfinance") not in ("yfinance", "default")]
        if non_default:
            return

        ts = "tencent_sina"
        self.config.setdefault("data_vendors", {})
        self.config["data_vendors"] = {
            "core_stock_apis": ts,
            "technical_indicators": ts,
            "fundamental_data": f"{ts},akshare",
            "news_data": ts,
            "sentiment_data": "akshare",
        }
        # Propagate to the dataflows config module so route_to_vendor picks it up.
        set_config(self.config)
        logger.info(
            "Auto-detected A-share/HK ticker '%s' — switched data_vendors to tencent_sina",
            ticker,
        )

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        Returns (raw_return, alpha_return, actual_holding_days) or
        (None, None, None) if price data is unavailable (too recent, delisted,
        or network error).
        """
        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            stock = pd.DataFrame()
            spy = pd.DataFrame()

            is_chinese = self._is_chinese_ticker(ticker)

            # For A-share / HK tickers, skip yfinance entirely — it will
            # either return no data or hit rate limits.  Go straight to
            # the tencent_sina / East Money backend.
            if not is_chinese:
                try:
                    stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
                    spy = yf.Ticker("SPY").history(start=trade_date, end=end_str)
                except Exception:
                    stock = pd.DataFrame()
                    spy = pd.DataFrame()

            # Try A-share / HK data source (also used as fallback)
            if len(stock) < 2:
                try:
                    from tradingagents.dataflows.tencent_sina import get_YFin_data_online
                    import io as _io
                    csv_str = get_YFin_data_online(ticker, trade_date, end_str)
                    if "No data" not in csv_str and "Error" not in csv_str:
                        # Strip header lines (lines starting with #)
                        data_lines = csv_str.split("\n\n", 1)[-1] if "\n\n" in csv_str else csv_str
                        stock = pd.read_csv(
                            _io.StringIO(data_lines),
                            parse_dates=["Date"],
                            index_col="Date",
                        )
                    spy = pd.DataFrame()  # No SPY equivalent for A-shares
                except Exception:
                    pass

            if len(stock) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )

            if len(spy) >= 2:
                spy_ret = float(
                    (spy["Close"].iloc[actual_days] - spy["Close"].iloc[0])
                    / spy["Close"].iloc[0]
                )
                alpha = raw - spy_ret
            else:
                alpha = None  # No benchmark for A-shares

            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s (will retry next run): %s",
                ticker, trade_date, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(ticker, entry["date"])
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(self, company_name, trade_date):
        """Run the trading agents graph for a company on a specific date.

        When ``checkpoint_enabled`` is set in config, the graph is recompiled
        with a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        self.ticker = company_name

        # Auto-detect A-share / HK tickers and switch data vendor to tencent_sina
        # when the user hasn't explicitly configured a data vendor for those markets.
        self._auto_detect_vendor(company_name)

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(company_name, trade_date)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(self, company_name, trade_date):
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state — inject memory log context for PM.
        past_context = self.memory_log.get_past_context(company_name)
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, past_context=past_context
        )
        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    try:
                        chunk["messages"][-1].pretty_print()
                    except UnicodeEncodeError:
                        # Windows GBK console can't encode emoji characters
                        # that LLM may include in responses — print safely
                        msg = chunk["messages"][-1]
                        text = getattr(msg, "content", str(msg))
                        if isinstance(text, list):
                            text = " ".join(
                                t.get("text", "") if isinstance(t, dict) else str(t)
                                for t in text
                            )
                        safe = str(text).encode(
                            sys.stdout.encoding or "utf-8", errors="replace"
                        ).decode(sys.stdout.encoding or "utf-8", errors="replace")
                        print(safe[:500])
                    trace.append(chunk)
            final_state = trace[-1]
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        import hashlib as _hashlib
        try:
            safe_ticker = safe_ticker_component(self.ticker)
        except ValueError:
            # Long multi-ticker input: truncate + hash to fit Windows MAX_PATH
            raw = self.ticker.replace("/", "_").replace("\\", "_")
            parts = raw.split(",")
            head = "_".join(p.strip() for p in parts[:3])
            digest = _hashlib.md5(raw.encode()).hexdigest()[:8]
            safe_ticker = f"{head}_etc_{digest}"
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)