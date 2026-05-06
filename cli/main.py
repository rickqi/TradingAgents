from typing import Optional
import datetime
import re
import shutil
import json
import typer
from pathlib import Path
from functools import wraps
from rich.console import Console
from dotenv import load_dotenv

# Load environment variables — try project root first (source runs), then CWD (pip-installed runs)
_CLI_ROOT = Path(__file__).resolve().parent.parent  # project root when running from source
load_dotenv(_CLI_ROOT / ".env")
load_dotenv(_CLI_ROOT / ".env.enterprise", override=False)
# Fallback: also load from cwd so `tradingagents` installed via pip can find .env in the project dir
_cwd_env = Path.cwd() / ".env"
if _cwd_env.exists() and _cwd_env.resolve() != (_CLI_ROOT / ".env").resolve():
    load_dotenv(_cwd_env, override=False)
_cwd_ent = Path.cwd() / ".env.enterprise"
if _cwd_ent.exists() and _cwd_ent.resolve() != (_CLI_ROOT / ".env.enterprise").resolve():
    load_dotenv(_cwd_ent, override=False)
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from cli.models import AnalystType
from cli.utils import *
from cli.announcements import fetch_announcements, display_announcements
from cli.stats_handler import StatsCallbackHandler

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
    invoke_without_command=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    ticker: Optional[str] = typer.Option(
        None, "--ticker", "-t",
        help="Ticker symbol — skip interactive prompts and run analysis directly",
    ),
    date: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="Analysis date (YYYY-MM-DD), default: today",
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p",
        help="LLM provider: deepseek, openai, google, anthropic, xai, qwen, glm, openrouter, ollama",
    ),
    depth: Optional[int] = typer.Option(
        None, "--depth",
        help="Research depth / debate rounds (1-3, default: 1)",
    ),
    lang: Optional[str] = typer.Option(
        None, "--lang", "-l",
        help="Output language (English, Chinese, etc.)",
    ),
    analysts: Optional[str] = typer.Option(
        None, "--analysts", "-a",
        help="Comma-separated analysts: market,social,news,fundamentals (default: all)",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Non-interactive: auto-save report and print results (no prompts)",
    ),
    checkpoint: bool = typer.Option(
        False,
        "--checkpoint",
        help="Enable checkpoint/resume: save state after each node so a crashed run can resume.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
    diag: bool = typer.Option(
        False,
        "--diag",
        help="Enable diagnostic mode: write detailed execution trace to .cli_diag.log for debugging.",
    ),
):
    """TradingAgents CLI: Multi-Agents LLM Financial Trading Framework"""
    if ctx.invoked_subcommand is not None:
        return
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    run_analysis(
        checkpoint=checkpoint, diag=diag,
        cli_overrides={
            "ticker": ticker, "date": date, "provider": provider,
            "depth": depth, "lang": lang, "analysts": analysts, "yes": yes,
        } if ticker else None,
    )


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    # Fixed teams that always run (not user-selectable)
    FIXED_AGENTS = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Analyst name mapping
    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Social Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    # Report section mapping: section -> (analyst_key for filtering, finalizing_agent)
    # analyst_key: which analyst selection controls this section (None = always included)
    # finalizing_agent: which agent must be "completed" for this report to count as done
    REPORT_SECTIONS = {
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Social Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    SECTION_DISPLAY_TITLES = {
        "market_report": "Market Analysis",
        "sentiment_report": "Social Sentiment",
        "news_report": "News Analysis",
        "fundamentals_report": "Fundamentals",
        "investment_plan": "Research Decision",
        "trader_investment_plan": "Trading Plan",
        "final_trade_decision": "Portfolio Decision",
    }

    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {}
        self.current_agent = None
        self.report_sections = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

        # Per-agent timing (wall-clock chaining)
        self.completion_times: dict[str, float] = {}  # agent -> time.time() when output first detected

        # Streaming report display (optimization 3)
        self.report_summaries: dict[str, str] = {}      # section -> summary text
        self.section_order: list[str] = []               # sections in order of first appearance

    def init_for_analysis(self, selected_analysts):
        """Initialize agent status and report sections based on selected analysts.

        Args:
            selected_analysts: List of analyst type strings (e.g., ["market", "news"])
        """
        self.selected_analysts = [a.lower() for a in selected_analysts]

        # Build agent_status dynamically
        self.agent_status = {}

        # Add selected analysts
        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst_key]] = "pending"

        # Add fixed teams
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"

        # Build report_sections dynamically
        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None

        # Reset other state
        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._processed_message_ids.clear()
        self.completion_times.clear()
        self.report_summaries.clear()
        self.section_order.clear()

    def get_completed_reports_count(self):
        """Count reports that are finalized (their finalizing agent is completed).

        A report is considered complete when:
        1. The report section has content (not None), AND
        2. The agent responsible for finalizing that report has status "completed"

        This prevents interim updates (like debate rounds) from counting as completed.
        """
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            # Report is complete if it has content AND its finalizing agent is done
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def get_agent_duration(self, agent) -> str:
        """Return formatted agent duration using wall-clock chaining.

        For sequential agents: duration = completion_times[agent] - completion_times[prev_agent]
        For parallel risk group: duration = completion_times[agent] - completion_times["Trader"]
        """
        end = self.completion_times.get(agent)
        if end is None:
            return ""

        # Find the start time based on pipeline position
        start_time = None
        if agent in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"):
            # Parallel group: all start when Trader completes
            start_time = self.completion_times.get("Trader")
        elif agent == "Market Analyst":
            # First agent: use pipeline start time (stored as special key)
            start_time = self.completion_times.get("_start")
        elif agent in PIPELINE_ORDER:
            # Sequential: walk backwards to find the nearest preceding agent with a completion time
            idx = PIPELINE_ORDER.index(agent)
            for i in range(idx - 1, -1, -1):
                prev = PIPELINE_ORDER[i]
                if prev in self.completion_times:
                    start_time = self.completion_times[prev]
                    break
            # If no preceding agent found, use pipeline start
            if start_time is None:
                start_time = self.completion_times.get("_start")

        if start_time is None:
            return ""

        return _format_duration(end - start_time)

    def get_agent_durations(self) -> dict[str, float]:
        """Return all agent durations in seconds, for JSON export."""
        result = {}
        for agent in self.agent_status:
            end = self.completion_times.get(agent)
            if end is None:
                continue
            start_time = None
            if agent in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"):
                start_time = self.completion_times.get("Trader")
            elif agent == "Market Analyst":
                start_time = self.completion_times.get("_start")
            elif agent in PIPELINE_ORDER:
                idx = PIPELINE_ORDER.index(agent)
                for i in range(idx - 1, -1, -1):
                    prev = PIPELINE_ORDER[i]
                    if prev in self.completion_times:
                        start_time = self.completion_times[prev]
                        break
                if start_time is None:
                    start_time = self.completion_times.get("_start")
            if start_time is not None:
                result[agent] = round(end - start_time, 1)
        return result

    def get_phase_durations(self) -> dict[str, float]:
        """Return phase durations in seconds using completion times."""
        ct = self.completion_times

        phases = {}
        # Analysts: sequential, total = last selected analyst completion - pipeline start
        # Find the last analyst in PIPELINE_ORDER that has a completion time
        last_analyst_end = None
        for analyst in reversed(PIPELINE_ORDER[:4]):  # First 4 are analysts
            if analyst in ct:
                last_analyst_end = ct[analyst]
                break
        if last_analyst_end is not None and "_start" in ct:
            phases["Analysts"] = last_analyst_end - ct["_start"]

        # Research: Research Manager completion - last analyst completion
        if "Research Manager" in ct and last_analyst_end is not None:
            phases["Research"] = ct["Research Manager"] - last_analyst_end

        # Trade: Trader completion - Research Manager completion
        if "Trader" in ct and "Research Manager" in ct:
            phases["Trade"] = ct["Trader"] - ct["Research Manager"]

        # Risk: max risk analyst completion - Trader completion
        risk_agents = ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"]
        risk_ends = [ct[a] for a in risk_agents if a in ct]
        if risk_ends and "Trader" in ct:
            phases["Risk"] = max(risk_ends) - ct["Trader"]

        # PM: PM completion - Trader completion (PM runs during risk debate)
        if "Portfolio Manager" in ct and "Trader" in ct:
            phases["PM"] = ct["Portfolio Manager"] - ct["Trader"]

        return phases

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            # Track section appearance order
            if section_name not in self.section_order:
                self.section_order.append(section_name)
            # Update summary
            self.report_summaries[section_name] = self._extract_summary(content)
            self._update_current_report()

    @staticmethod
    def _extract_summary(content, max_chars=150) -> str:
        """Extract a short summary from report content."""
        if not content:
            return ""
        text = str(content).replace("\n", " ").strip()
        # Strip markdown headings and bold
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*{1,2}', '', text)
        if len(text) > max_chars:
            return text[:max_chars - 3] + "..."
        return text

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
               
        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # Analyst Team Reports - use .get() to handle missing sections
        analyst_sections = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]
        if any(self.report_sections.get(section) for section in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections.get("market_report"):
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections.get("sentiment_report"):
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections.get("news_report"):
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections.get("fundamentals_report"):
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )

        # Research Team Reports
        if self.report_sections.get("investment_plan"):
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        # Trading Team Reports
        if self.report_sections.get("trader_investment_plan"):
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        # Portfolio Management Decision
        if self.report_sections.get("final_trade_decision"):
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def format_tokens(n):
    """Format token count for display."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _format_duration(seconds: float) -> str:
    """Format seconds as 'M:SS' or 'H:MM:SS'."""
    total = int(seconds)
    if total >= 3600:
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        return f"{h}:{m:02d}:{s:02d}"
    else:
        m, s = divmod(total, 60)
        return f"{m}:{s:02d}"


def _render_streaming_report(message_buffer):
    """Render streaming report panel: completed=summary, active=latest content."""
    from rich.console import Group

    elements = []

    for section in message_buffer.section_order:
        title = message_buffer.SECTION_DISPLAY_TITLES.get(section, section)
        content = message_buffer.report_sections.get(section)
        if not content:
            continue

        # Determine if this section's finalizing agent is done
        section_info = message_buffer.REPORT_SECTIONS.get(section)
        finalizing_agent = section_info[1] if section_info else None
        is_done = message_buffer.agent_status.get(finalizing_agent) == "completed"

        if is_done:
            # Completed: title with duration + summary (compact)
            duration = message_buffer.get_agent_duration(finalizing_agent) if finalizing_agent else ""
            header = f"✓ {title}"
            if duration:
                header += f" ({duration})"
            elements.append(Text(header, style="bold green"))

            summary = message_buffer.report_summaries.get(section, "")
            if summary:
                elements.append(Text(f"  {summary}", style="dim"))
        else:
            # In progress: title + latest content snippet
            elements.append(Text(f"⟳ {title}", style="bold cyan"))

            text = str(content)
            if len(text) > 500:
                text = "..." + text[-500:]
            elements.append(Text(text, style="white"))

    if not elements:
        return Panel(
            "[italic]Waiting for analysis report...[/italic]",
            title="Current Report",
            border_style="green",
            padding=(1, 2),
        )

    return Panel(
        Group(*elements),
        title="Current Report",
        border_style="green",
        padding=(1, 2),
    )


def update_display(layout, spinner_text=None, stats_handler=None, start_time=None):
    # Header — plain text, no Rich markup (avoids raw tag display on Windows).
    layout["header"].update(
        Text("Welcome to TradingAgents CLI  —  Tauric Research", justify="center")
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)
    progress_table.add_column("Duration", style="dim", justify="center", width=8)

    # Group agents by team - filter to only include agents in agent_status
    all_teams = {
        "Analyst Team": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Filter teams to only include agents that are in agent_status
    teams = {}
    for team, agents in all_teams.items():
        active_agents = [a for a in agents if a in message_buffer.agent_status]
        if active_agents:
            teams[team] = active_agents

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status.get(first_agent, "pending")
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        duration_str = message_buffer.get_agent_duration(first_agent)
        progress_table.add_row(team, first_agent, status_cell, duration_str)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status.get(agent, "pending")
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            duration_str = message_buffer.get_agent_duration(agent)
            progress_table.add_row("", agent, status_cell, duration_str)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, "─" * 8, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    # OpenCLI tool names for highlighting
    _OPENCLI_TOOLS = {
        "get_money_flow", "get_northbound", "get_sectors", "get_longhu", "get_hot_rank",
        "get_quote", "get_kline", "get_index_board", "get_kuaixun", "get_holders", "get_announcement",
    }
    for timestamp, tool_name, args in message_buffer.tool_calls:
        formatted_args = format_tool_args(args)
        if tool_name in _OPENCLI_TOOLS:
            all_messages.append((timestamp, "[cyan]OpenCLI[/cyan]", f"[cyan]{tool_name}[/cyan]: {formatted_args}"))
        else:
            all_messages.append((timestamp, "Tool", f"{tool_name}: {formatted_args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        content_str = str(content) if content else ""
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    # Sort by timestamp descending (newest first)
    all_messages.sort(key=lambda x: x[0], reverse=True)

    # Calculate how many messages we can show based on available space
    max_messages = 12

    # Get the first N messages (newest ones)
    recent_messages = all_messages[:max_messages]

    # Add messages to table (already in newest-first order)
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel — streaming report with all sections
    layout["analysis"].update(_render_streaming_report(message_buffer))

    # Footer with statistics
    # Agent progress - derived from agent_status dict
    agents_completed = sum(
        1 for status in message_buffer.agent_status.values() if status == "completed"
    )
    agents_total = len(message_buffer.agent_status)

    # Report progress - based on agent completion (not just content existence)
    reports_completed = message_buffer.get_completed_reports_count()
    reports_total = len(message_buffer.report_sections)

    # Build stats parts
    stats_parts = [f"Agents: {agents_completed}/{agents_total}"]

    # LLM and tool stats from callback handler
    if stats_handler:
        stats = stats_handler.get_stats()
        stats_parts.append(f"LLM: {stats['llm_calls']}")
        stats_parts.append(f"Tools: {stats['tool_calls']}")

        # Token display with graceful fallback
        if stats["tokens_in"] > 0 or stats["tokens_out"] > 0:
            tokens_str = f"Tokens: {format_tokens(stats['tokens_in'])}\u2191 {format_tokens(stats['tokens_out'])}\u2193"
        else:
            tokens_str = "Tokens: --"
        stats_parts.append(tokens_str)

    # Report progress with active report name
    if reports_completed < reports_total:
        active_name = None
        for section in message_buffer.section_order:
            section_info = message_buffer.REPORT_SECTIONS.get(section)
            if section_info:
                _, agent = section_info
                if message_buffer.agent_status.get(agent) == "in_progress":
                    active_name = message_buffer.SECTION_DISPLAY_TITLES.get(section, section)
                    break
        if active_name:
            stats_parts.append(f"Reports: {reports_completed}/{reports_total} ⟳ {active_name}")
        else:
            stats_parts.append(f"Reports: {reports_completed}/{reports_total}")
    else:
        stats_parts.append(f"Reports: {reports_completed}/{reports_total} ✓")

    # Phase timing summary (only when all agents complete)
    all_done = all(s == "completed" for s in message_buffer.agent_status.values())
    if all_done and message_buffer.completion_times:
        phase_durations = message_buffer.get_phase_durations()
        phase_parts = []
        for phase_name, dur in phase_durations.items():
            phase_parts.append(f"{phase_name}: {_format_duration(dur)}")
        if phase_parts:
            stats_parts.append("Phase: " + " | ".join(phase_parts))

    # Elapsed time
    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = f"\u23f1 {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        stats_parts.append(elapsed_str)

    # Data source indicator — show active vendor + OpenCLI status
    from tradingagents.dataflows.config import get_config as _get_df_config
    _active_vendors = _get_df_config().get("data_vendors", {})
    _core_vendor = _active_vendors.get("core_stock_apis", "")
    # Pick the primary vendor (first in comma-separated chain)
    _primary_vendor = _core_vendor.split(",")[0] if _core_vendor else "unknown"

    _OPENCLI_TOOLS = {
        "get_money_flow", "get_northbound", "get_sectors", "get_longhu", "get_hot_rank",
        "get_quote", "get_kline", "get_index_board", "get_kuaixun", "get_holders", "get_announcement",
    }
    opencli_calls = sum(1 for _, name, _ in message_buffer.tool_calls if name in _OPENCLI_TOOLS)
    if shutil.which("opencli"):
        if opencli_calls > 0:
            stats_parts.append(f"Data: [green]{_primary_vendor}[/green] + [cyan]OpenCLI({opencli_calls})[/cyan]")
        else:
            stats_parts.append(f"Data: [green]{_primary_vendor}[/green] [dim]+ OpenCLI[/dim]")
    else:
        stats_parts.append(f"Data: [green]{_primary_vendor}[/green]")

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(" | ".join(stats_parts))

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open(Path(__file__).parent / "static" / "welcome.txt", "r", encoding="utf-8") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents: Multi-Agents LLM Financial Trading Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to TradingAgents",
        subtitle="Multi-Agents LLM Financial Trading Framework",
    )
    console.print(Align.center(welcome_box))
    console.print()

    # OpenCLI status hint
    if shutil.which("opencli"):
        opencli_hint = (
            "[bold green]OpenCLI detected[/bold green] "
            "[dim]— Extended A-share data available: capital flow, northbound, sectors, dragon-tiger list, hot rank[/dim]\n"
            "[dim]   A-share tickers will automatically use OpenCLI data. "
            "Use 'tradingagents screen' or 'tradingagents market' for standalone queries.[/dim]"
        )
    else:
        opencli_hint = (
            "[dim]OpenCLI not found — Install for extended A-share data (capital flow, northbound, sectors, etc.):[/dim]\n"
            "[dim]   npm install -g @jackwener/opencli[/dim]\n"
            "[dim]   Standard data sources (yfinance, tencent_sina) still work without it.[/dim]"
        )
    console.print(Panel(opencli_hint, title="OpenCLI Status", border_style="dim", padding=(0, 2)))
    console.print()

    # Fetch and display announcements (silent on failure)
    announcements = fetch_announcements()
    display_announcements(console, announcements)

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]Default: {default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol",
            "Enter the exact ticker symbol to analyze, including exchange suffix when needed (examples: SPY, CNC.TO, 7203.T, 0700.HK)",
            "SPY",
        )
    )
    selected_ticker = get_ticker()

    # Step 1.5: OpenCLI Market Snapshot (automatic, non-interactive)
    if _is_ashare_ticker(selected_ticker) and shutil.which("opencli"):
        _show_opencli_snapshot(selected_ticker)

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "Step 2: Analysis Date",
            "Enter the analysis date (YYYY-MM-DD)",
            default_date,
        )
    )
    analysis_date = get_analysis_date()

    # Step 3: Output language
    console.print(
        create_question_box(
            "Step 3: Output Language",
            "Select the language for analyst reports and final decision"
        )
    )
    output_language = ask_output_language()

    # Step 4: Select analysts
    console.print(
        create_question_box(
            "Step 4: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts()
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 5: Research depth
    console.print(
        create_question_box(
            "Step 5: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 6: LLM Provider
    console.print(
        create_question_box(
            "Step 6: LLM Provider", "Select your LLM provider"
        )
    )
    selected_llm_provider, backend_url = select_llm_provider()

    # Step 7: Thinking agents
    console.print(
        create_question_box(
            "Step 7: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    # Step 8: Provider-specific thinking configuration
    thinking_level = None
    reasoning_effort = None
    anthropic_effort = None

    provider_lower = selected_llm_provider.lower()
    if provider_lower == "google":
        console.print(
            create_question_box(
                "Step 8: Thinking Mode",
                "Configure Gemini thinking mode"
            )
        )
        thinking_level = ask_gemini_thinking_config()
    elif provider_lower == "openai":
        console.print(
            create_question_box(
                "Step 8: Reasoning Effort",
                "Configure OpenAI reasoning effort level"
            )
        )
        reasoning_effort = ask_openai_reasoning_effort()
    elif provider_lower == "anthropic":
        console.print(
            create_question_box(
                "Step 8: Effort Level",
                "Configure Claude effort level"
            )
        )
        anthropic_effort = ask_anthropic_effort()

    return {
        "ticker": selected_ticker,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
        "google_thinking_level": thinking_level,
        "openai_reasoning_effort": reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "output_language": output_language,
    }


def get_ticker():
    """Get ticker symbol from user input."""
    return typer.prompt("", default="SPY")


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]Error: Analysis date cannot be in the future[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]Error: Invalid date format. Please use YYYY-MM-DD[/red]"
            )


def save_report_to_disk(final_state, ticker: str, save_path: Path):
    """Save complete analysis report to disk with organized subfolders."""
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []
    # Derive analysis date from directory name (e.g. TICKER_20260503_172233)
    _date_match = re.search(r"(\d{8})", save_path.name)
    analysis_date_str = (
        f"{_date_match.group(1)[:4]}-{_date_match.group(1)[4:6]}-{_date_match.group(1)[6:8]}"
        if _date_match else datetime.datetime.now().strftime("%Y-%m-%d")
    )

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    complete_md = save_path / "complete_report.md"
    complete_md.write_text(header + "\n\n".join(sections), encoding="utf-8")

    # Convert to professional Word document (best-effort)
    try:
        from tradingagents.utils.report_converter import convert_report_dir_to_docx
        docx_path = convert_report_dir_to_docx(
            save_path, ticker=ticker, analysis_date=analysis_date_str,
        )
        console.log(f"[green]Word report generated:[/green] {docx_path}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to generate Word report: %s", e)

    return complete_md


def display_complete_report(final_state):
    """Display the complete analysis report sequentially (avoids truncation)."""
    console.print()
    console.print(Rule("Complete Analysis Report", style="bold green"))

    # I. Analyst Team Reports
    analysts = []
    if final_state.get("market_report"):
        analysts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analysts:
        console.print(Panel("[bold]I. Analyst Team Reports[/bold]", border_style="cyan"))
        for title, content in analysts:
            console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        debate = final_state["investment_debate_state"]
        research = []
        if debate.get("bull_history"):
            research.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research.append(("Research Manager", debate["judge_decision"]))
        if research:
            console.print(Panel("[bold]II. Research Team Decision[/bold]", border_style="magenta"))
            for title, content in research:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # III. Trading Team
    if final_state.get("trader_investment_plan"):
        console.print(Panel("[bold]III. Trading Team Plan[/bold]", border_style="yellow"))
        console.print(Panel(Markdown(final_state["trader_investment_plan"]), title="Trader", border_style="blue", padding=(1, 2)))

    # IV. Risk Management Team
    if final_state.get("risk_debate_state"):
        risk = final_state["risk_debate_state"]
        risk_reports = []
        if risk.get("aggressive_history"):
            risk_reports.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_reports.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_reports.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_reports:
            console.print(Panel("[bold]IV. Risk Management Team Decision[/bold]", border_style="red"))
            for title, content in risk_reports:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

        # V. Portfolio Manager Decision
        if risk.get("judge_decision"):
            console.print(Panel("[bold]V. Portfolio Manager Decision[/bold]", border_style="green"))
            console.print(Panel(Markdown(risk["judge_decision"]), title="Portfolio Manager", border_style="blue", padding=(1, 2)))


def update_research_team_status(status):
    """Update status for research team members (not Trader)."""
    research_team = ["Bull Researcher", "Bear Researcher", "Research Manager"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)


# Ordered list of analysts for status transitions
ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

# The sequential pipeline order — each agent's duration = its completion time
# minus the previous agent's completion time (wall-clock chaining).
PIPELINE_ORDER = [
    "Market Analyst",
    "Social Analyst",
    "News Analyst",
    "Fundamentals Analyst",
    "Bull Researcher",
    "Bear Researcher",
    "Research Manager",
    "Trader",
    # Risk analysts are parallel — they all start when Trader completes
    "Aggressive Analyst",
    "Conservative Analyst",
    "Neutral Analyst",
    "Portfolio Manager",
]


def update_analyst_statuses(message_buffer, chunk):
    """Update analyst statuses based on accumulated report state.

    Logic:
    - Store new report content from the current chunk if present
    - Check accumulated report_sections (not just current chunk) for status
    - Analysts with reports = completed
    - First analyst without report = in_progress
    - Remaining analysts without reports = pending
    - When all analysts done, set Bull Researcher to in_progress
    """
    selected = message_buffer.selected_analysts
    found_active = False

    for analyst_key in ANALYST_ORDER:
        if analyst_key not in selected:
            continue

        agent_name = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]

        # Capture new report content from current chunk
        if chunk.get(report_key):
            message_buffer.update_report_section(report_key, chunk[report_key])

        # Determine status from accumulated sections, not just current chunk
        has_report = bool(message_buffer.report_sections.get(report_key))

        if has_report:
            message_buffer.update_agent_status(agent_name, "completed")
        elif not found_active:
            message_buffer.update_agent_status(agent_name, "in_progress")
            found_active = True
        else:
            message_buffer.update_agent_status(agent_name, "pending")

    # When all analysts complete, transition full research team to in_progress
    if not found_active and selected:
        for agent in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
            if message_buffer.agent_status.get(agent) == "pending":
                message_buffer.update_agent_status(agent, "in_progress")

def extract_content_string(content):
    """Extract string content from various message formats.
    Returns None if no meaningful text content is found.
    """
    import ast

    def is_empty(val):
        """Check if value is empty using Python's truthiness."""
        if val is None or val == '':
            return True
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return True
            try:
                return not bool(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return False  # Can't parse = real text
        return not bool(val)

    if is_empty(content):
        return None

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        text = content.get('text', '')
        return text.strip() if not is_empty(text) else None

    if isinstance(content, list):
        text_parts = [
            item.get('text', '').strip() if isinstance(item, dict) and item.get('type') == 'text'
            else (item.strip() if isinstance(item, str) else '')
            for item in content
        ]
        result = ' '.join(t for t in text_parts if t and not is_empty(t))
        return result if result else None

    return str(content).strip() if not is_empty(content) else None


def classify_message_type(message) -> tuple[str, str | None]:
    """Classify LangChain message into display type and extract content.

    Returns:
        (type, content) - type is one of: User, Agent, Data, Control
                        - content is extracted string or None
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    content = extract_content_string(getattr(message, 'content', None))

    if isinstance(message, HumanMessage):
        if content and content.strip() == "Continue":
            return ("Control", content)
        return ("User", content)

    if isinstance(message, ToolMessage):
        return ("Data", content)

    if isinstance(message, AIMessage):
        return ("Agent", content)

    # Fallback for unknown types
    return ("System", content)


def format_tool_args(args, max_length=80) -> str:
    """Format tool arguments for terminal display."""
    result = str(args)
    if len(result) > max_length:
        return result[:max_length - 3] + "..."
    return result

def _is_ashare_ticker(ticker: str) -> bool:
    """Detect if a ticker (or comma-separated list of tickers) contains A-share symbols.

    Matches patterns like: 002876.SZ, 600519.SH, 300308.SZ, 603208.SH
    Also matches bare 6-digit numeric codes (assumed A-share).
    Handles comma-separated ticker lists (e.g. "002876.SZ,000062.SZ").
    Returns True if ANY of the tickers is an A-share symbol.
    """
    # Handle comma-separated tickers; strip surrounding quotes from each token
    tickers = [t.strip().strip('"').strip("'") for t in ticker.split(",")]
    for tick in tickers:
        t = tick.strip().upper()
        if not t:
            continue
        # With exchange suffix
        if t.endswith((".SZ", ".SH", ".SS")):
            code = t.rsplit(".", 1)[0]
            if code.isdigit() and len(code) == 6:
                return True
        # Bare numeric code (e.g. "600519")
        elif t.isdigit() and len(t) == 6:
            return True
    return False


def _fetch_opencli_json(site: str, command: str, args: list = None, timeout: int = 8) -> list[dict]:
    """Execute an opencli command and return parsed JSON rows. Returns [] on any failure."""
    import subprocess

    opencli = shutil.which("opencli")
    if not opencli:
        return []
    cmd = [opencli, site, command, "-f", "json"]
    if args:
        cmd.extend(str(a) for a in args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except Exception:
        return []


def _show_opencli_snapshot(ticker: str):
    """Display a rich market snapshot panel using OpenCLI data.

    Only called when: (1) opencli is in PATH, (2) ticker is A-share.
    Non-blocking: any failure is silently skipped.
    """
    # Extract bare code for opencli (strip .SZ/.SH suffix)
    bare_code = ticker.split(".")[0].split(",")[0].strip().strip('"').strip("'")

    # Fetch data concurrently would be ideal but subprocess is sequential
    # Fetch key data points
    quote_data = _fetch_opencli_json("eastmoney", "quote", [bare_code])
    money_data = _fetch_opencli_json("eastmoney", "money-flow", ["--limit", "5"])
    sectors_data = _fetch_opencli_json("eastmoney", "sectors", ["--limit", "5"])

    # Build snapshot content
    parts = []

    # Quote section
    if quote_data:
        q = quote_data[0] if isinstance(quote_data, list) and quote_data else quote_data
        name = q.get("name", bare_code)
        price = q.get("price", "—")
        chg_pct = q.get("changePercent", "—")
        vol = q.get("volume", "—")
        pe = q.get("peDynamic", "—")
        mkt_cap = q.get("marketCap", "—")
        chg_sign = "+" if isinstance(chg_pct, (int, float)) and chg_pct > 0 else ""
        parts.append(
            f"[bold cyan]{bare_code} {name}[/bold cyan]\n"
            f"  Price: {price}  Chg: {chg_sign}{chg_pct}%  Vol: {vol}  PE: {pe}  MC: {mkt_cap}"
        )

    # Money flow section
    if money_data and isinstance(money_data, list) and len(money_data) > 0:
        # Find our ticker in the money flow data
        matched = [m for m in money_data if str(m.get("code", "")) == bare_code]
        if matched:
            m = matched[0]
            main_net = m.get("mainNet", "—")
            main_ratio = m.get("mainNetRatio", "—")
            parts.append(
                f"[yellow]\U0001f4b0 \u4e3b\u529b\u8d44\u91d1[/yellow]: \u51c0\u6d41\u5165 {main_net}\u4e07  \u5360\u6bd4 {main_ratio}%"
            )
        else:
            parts.append("[dim]\u4e3b\u529b\u8d44\u91d1: \u672a\u5728TOP5\u6392\u884c\u4e2d[/dim]")

    # Sectors section
    if sectors_data and isinstance(sectors_data, list) and len(sectors_data) > 0:
        top_sector = sectors_data[0]
        parts.append(
            f"[green]\U0001f4c8 \u677f\u5757[/green]: {top_sector.get('name', '—')} "
            f"{top_sector.get('changePercent', '—')}%  "
            f"\u9886\u6da8: {top_sector.get('leadStock', '—')}"
        )

    if not parts:
        return  # No data available, skip snapshot entirely

    content = "\n\n".join(parts)
    content += "\n\n[dim]\u6570\u636e\u6765\u6e90: opencli (\u8fd1\u5b9e\u65f6) | \u4ec5\u4f9b\u53c2\u8003[/dim]"

    console.print()
    console.print(Panel(
        content,
        title="\U0001f4ca Market Snapshot (OpenCLI)",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


def _show_opencli_summary(ticker: str):
    """Display OpenCLI data summary after analysis completes.

    Shows aggregated data that complements the analysis.
    """
    bare_code = ticker.split(".")[0].split(",")[0].strip().strip('"').strip("'")

    parts = []

    # Fetch concise data
    money_data = _fetch_opencli_json("eastmoney", "money-flow", ["--limit", "10"])
    if money_data:
        matched = [m for m in money_data if str(m.get("code", "")) == bare_code]
        if matched:
            m = matched[0]
            parts.append(f"\U0001f4b0 \u4e3b\u529b\u8d44\u91d1: {bare_code} \u4eca\u65e5\u51c0\u6d41\u5165 {m.get('mainNet', '—')}\u4e07")
        else:
            parts.append(f"\U0001f4b0 \u4e3b\u529b\u8d44\u91d1: {bare_code} \u672a\u5728\u4eca\u65e5TOP10\u6392\u884c\u4e2d")

    north_data = _fetch_opencli_json("eastmoney", "northbound")
    if north_data:
        parts.append("\U0001f30a \u5317\u5411\u8d44\u91d1: \u6570\u636e\u5df2\u83b7\u53d6")

    longhu_data = _fetch_opencli_json("eastmoney", "longhu")
    if longhu_data:
        matched_codes = [l for l in (longhu_data if isinstance(longhu_data, list) else [])
                        if str(l.get("code", "")) == bare_code]
        if matched_codes:
            parts.append(f"\U0001f3db \u9f99\u864e\u699c: {bare_code} \u4eca\u65e5\u4e0a\u699c")
        else:
            parts.append("\U0001f3db \u9f99\u864e\u699c: \u65e0\u4e0a\u699c\u8bb0\u5f55")

    if not parts:
        return

    content = "\n".join(parts)
    content += f"\n\n[dim]\u6570\u636e\u65f6\u6548: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]"

    console.print()
    console.print(Panel(
        content,
        title="\U0001f4ca OpenCLI Data Summary",
        border_style="cyan",
        padding=(1, 2),
    ))


# ── Direct-mode helpers ──────────────────────────────────────────────────────

# Provider → (api_key_env, default_quick_model, default_deep_model)
_PROVIDER_DEFAULTS = {
    "deepseek":   ("DEEPSEEK_API_KEY",    "deepseek-v4-flash",          "deepseek-v4-pro"),
    "openai":     ("OPENAI_API_KEY",       "gpt-5.4-mini",               "gpt-5.4"),
    "google":     ("GOOGLE_API_KEY",       "gemini-3-flash-preview",     "gemini-3.1-pro-preview"),
    "anthropic":  ("ANTHROPIC_API_KEY",    "claude-sonnet-4-6",          "claude-opus-4-6"),
    "xai":        ("XAI_API_KEY",          "grok-4-1-fast-non-reasoning","grok-4-0709"),
    "qwen":       ("DASHSCOPE_API_KEY",    "qwen3.5-flash",              "qwen3.6-plus"),
    "glm":        ("ZHIPU_API_KEY",        "glm-4.7",                    "glm-5.1"),
    "openrouter": ("OPENROUTER_API_KEY",   "openai/gpt-5.4-mini",        "openai/gpt-5.4"),
}


def _get_default_provider() -> tuple:
    """Return (provider, quick_model, deep_model) for the first provider with an API key."""
    import os
    for provider, (env_var, quick, deep) in _PROVIDER_DEFAULTS.items():
        if os.environ.get(env_var):
            return provider, quick, deep
    return "openai", "gpt-5.4-mini", "gpt-5.4"  # fallback


def _build_selections_from_args(overrides: dict) -> dict:
    """Build selections dict from CLI arguments (non-interactive mode)."""
    # Provider and models
    provider_input = overrides.get("provider")
    if provider_input:
        provider = provider_input.lower()
        defaults = _PROVIDER_DEFAULTS.get(provider)
        if defaults:
            _, quick_model, deep_model = defaults
        else:
            quick_model, deep_model = "gpt-5.4-mini", "gpt-5.4"
    else:
        provider, quick_model, deep_model = _get_default_provider()

    # Date
    date_str = overrides.get("date")
    if date_str:
        # Validate format
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    else:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    # Language: default to Chinese for A-share tickers
    ticker_val = overrides["ticker"]
    lang = overrides.get("lang")
    if not lang:
        lang = "Chinese" if _is_ashare_ticker(ticker_val) else "English"

    # Analysts
    analysts_str = overrides.get("analysts")
    if analysts_str:
        valid = {"market", "social", "news", "fundamentals"}
        selected = [AnalystType(a.strip()) for a in analysts_str.split(",") if a.strip() in valid]
        if not selected:
            selected = [AnalystType(a) for a in AnalystType]
    else:
        selected = [AnalystType(a) for a in AnalystType]

    # Research depth
    depth = overrides.get("depth") or 1

    return {
        "ticker": ticker_val,
        "analysis_date": date_str,
        "analysts": selected,
        "research_depth": depth,
        "llm_provider": provider,
        "backend_url": None,
        "shallow_thinker": quick_model,
        "deep_thinker": deep_model,
        "google_thinking_level": None,
        "openai_reasoning_effort": None,
        "anthropic_effort": None,
        "output_language": lang,
    }


def _run_headless(graph, selections, config, start_time, report_dir, auto_yes, stats_handler):
    """Run analysis in headless mode (no TUI, direct text output)."""
    ticker = selections["ticker"]
    date = selections["analysis_date"]

    console.print(f"\n[bold]Analyzing {ticker} on {date}...[/bold]\n")

    try:
        final_state, decision = graph.propagate(ticker, date)
    except Exception as e:
        console.print(f"\n[bold red]Analysis failed: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return

    elapsed = time.time() - start_time

    # Display decision
    console.print(Rule(f"Analysis Complete ({elapsed:.1f}s)"))

    # Extract structured decision if available
    if decision:
        console.print(Panel(
            str(decision),
            title=f"Decision: {ticker}",
            border_style="green",
            padding=(1, 2),
        ))

    # Show timing
    agent_durations = message_buffer.get_agent_durations()
    if agent_durations:
        timing_table = Table(title="Agent Timing", show_header=True, box=box.SIMPLE)
        timing_table.add_column("Agent", style="cyan")
        timing_table.add_column("Duration", style="green", justify="right")
        for agent, dur in agent_durations.items():
            timing_table.add_row(agent, f"{dur:.1f}s")
        console.print(timing_table)

    # Save report
    if auto_yes:
        save_choice = "Y"
    else:
        save_choice = typer.prompt("\nSave report?", default="Y").strip().upper()

    if save_choice in ("Y", "YES", ""):
        from tradingagents.dataflows.utils import safe_ticker_component
        safe_ticker = ticker.replace("/", "_").replace("\\", "_")
        try:
            safe_ticker = safe_ticker_component(safe_ticker)
        except ValueError:
            safe_ticker = re.sub(r"[^A-Za-z0-9._\-\^]", "_", ticker)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = Path.cwd() / "reports" / f"{safe_ticker}_{timestamp}"
        save_path.mkdir(parents=True, exist_ok=True)

        try:
            report_file = save_report_to_disk(final_state, ticker, save_path)
            console.print(f"[green]✓ Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")

        # Save timing
        try:
            timing_data = {
                "ticker": ticker,
                "date": date,
                "total_elapsed_seconds": round(elapsed, 1),
                "agents": agent_durations,
                "stats": stats_handler.get_stats() if stats_handler else {},
            }
            with open(save_path / "timing.json", "w", encoding="utf-8") as f:
                json.dump(timing_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # Convert to Word (best-effort)
        try:
            from tradingagents.utils.report_converter import convert_report_dir_to_docx
            convert_report_dir_to_docx(save_path, ticker=ticker, analysis_date=date)
        except Exception:
            pass

    # Display full report
    if auto_yes:
        display_choice = "Y"
    else:
        display_choice = typer.prompt("\nDisplay full report?", default="Y").strip().upper()

    if display_choice in ("Y", "YES", "") and final_state:
        display_complete_report(final_state)


def run_analysis(checkpoint: bool = False, diag: bool = False, cli_overrides: dict = None):
    # Determine interactive vs headless mode
    headless = cli_overrides and cli_overrides.get("ticker")
    auto_yes = cli_overrides.get("yes", False) if cli_overrides else False

    if headless:
        selections = _build_selections_from_args(cli_overrides)
        console.print(Panel(
            f"[bold]TradingAgents Direct Mode[/bold]\n\n"
            f"[cyan]Ticker:[/cyan]   {selections['ticker']}\n"
            f"[cyan]Date:[/cyan]     {selections['analysis_date']}\n"
            f"[cyan]Provider:[/cyan] {selections['llm_provider']}\n"
            f"[cyan]Models:[/cyan]   {selections['shallow_thinker']} / {selections['deep_thinker']}\n"
            f"[cyan]Depth:[/cyan]    {selections['research_depth']}\n"
            f"[cyan]Language:[/cyan] {selections['output_language']}",
            title="Analysis Configuration",
            border_style="cyan",
        ))
    else:
        selections = get_user_selections()

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    # Provider-specific thinking configuration
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    config["checkpoint_enabled"] = checkpoint

    # Auto-detect A-share tickers and switch to Chinese data sources
    ticker_value = selections["ticker"]
    is_ashare = _is_ashare_ticker(ticker_value)
    console.print(f"[dim]Ticker input: {repr(ticker_value)}[/dim]")
    console.print(f"[dim]A-share detected: {is_ashare}[/dim]")
    if is_ashare:
        config["data_vendors"] = {
            "core_stock_apis": "tencent_sina",
            "technical_indicators": "tencent_sina",
            "fundamental_data": "tencent_sina,akshare",
            "news_data": "tencent_sina",
            "sentiment_data": "akshare",
        }
        console.print(
            "[dim]Detected A-share ticker — using tencent_sina (Tencent/Sina/EastMoney) "
            "as primary data source, akshare for fundamentals & sentiment.[/dim]"
        )
        if shutil.which("opencli"):
            console.print(
                "[green]OpenCLI active[/green] — Market Analyst can access: "
                "[cyan]capital flow[/cyan], [cyan]northbound[/cyan], [cyan]sectors[/cyan], "
                "[cyan]dragon-tiger list[/cyan], [cyan]hot rank[/cyan]"
            )
        else:
            console.print(
                "[yellow]Tip:[/yellow] Install OpenCLI to unlock A-share capital flow, "
                "northbound, sectors data for deeper analysis: "
                "[dim]npm install -g @jackwener/opencli[/dim]"
            )

    # Create stats callback handler for tracking LLM/tool calls
    stats_handler = StatsCallbackHandler()

    # Normalize analyst selection to predefined order (selection is a 'set', order is fixed)
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]

    # Initialize the graph with callbacks bound to LLMs
    graph = TradingAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )

    # Initialize message buffer with selected analysts
    message_buffer.init_for_analysis(selected_analyst_keys)

    # Track start time for elapsed display
    start_time = time.time()

    # Create result directory — sanitize ticker so characters like '/' don't
    # create unintended sub-directories (e.g. "601318.SH/02318.HK").
    from tradingagents.dataflows.utils import safe_ticker_component
    safe_ticker = selections["ticker"].replace("/", "_").replace("\\", "_")
    try:
        safe_ticker = safe_ticker_component(safe_ticker)
    except ValueError:
        # Fallback: slugify anything non-safe to underscore
        safe_ticker = re.sub(r"[^A-Za-z0-9._\-\^]", "_", selections["ticker"])

    results_dir = Path(config["results_dir"]) / safe_ticker / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")  # Replace newlines with spaces
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper
    
    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    text = "\n".join(str(item) for item in content) if isinstance(content, list) else content
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    # ── Headless mode: skip TUI, run graph.propagate() directly ──
    if headless:
        return _run_headless(graph, selections, config, start_time, report_dir, auto_yes, stats_handler)

    # Now start the display layout
    layout = create_layout()

    # Crash diagnostic log — write to file to survive Live swallowing output
    # Enabled only with --diag flag; otherwise _diag is a silent no-op.
    _diag_log = _CLI_ROOT / ".cli_diag.log"

    if diag:
        def _diag(msg):
            with open(_diag_log, "a", encoding="utf-8") as _f:
                _f.write(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')} {msg}\n")

        # Clear previous log
        with open(_diag_log, "w", encoding="utf-8") as _f:
            _f.write("")
    else:
        def _diag(msg):
            pass

    _diag("Entering Live context")

    with Live(layout, refresh_per_second=4, redirect_stdout=False, redirect_stderr=False) as live:
        _diag("Live context entered")

        # Initial display
        _diag("Before first update_display")
        update_display(layout, stats_handler=stats_handler, start_time=start_time)
        _diag("After first update_display")

        # Add initial messages
        _diag("Adding initial messages")
        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        _diag("Messages added, calling update_display")
        update_display(layout, stats_handler=stats_handler, start_time=start_time)
        _diag("update_display 2 done")

        # Update agent status to in_progress for the first analyst
        first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
        message_buffer.update_agent_status(first_analyst, "in_progress")
        update_display(layout, stats_handler=stats_handler, start_time=start_time)
        _diag("Agent status set, creating spinner")

        # Create spinner text
        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)
        _diag("Spinner set, initializing graph")

        # Initialize state and get graph args with callbacks
        # Auto-detect A-share / HK tickers so tencent_sina is used instead of
        # hitting yfinance rate limits.  propagate() does this automatically,
        # but the CLI streams the graph directly, so we must call it here.
        graph._auto_detect_vendor(selections["ticker"])
        graph._resolve_pending_entries(selections["ticker"])
        _diag("Auto detect vendor done")

        # Diagnostic: log active data vendor config
        from tradingagents.dataflows.config import get_config as get_df_config
        active_vendors = get_df_config().get("data_vendors", {})
        _diag(f"Active vendors: {active_vendors}")

        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"], selections["analysis_date"]
        )
        _diag("Initial state created")
        # Pass callbacks to graph config for tool execution tracking
        # (LLM tracking is handled separately via LLM constructor)
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])
        _diag("Graph args ready, starting stream")

        # Stream the analysis
        trace = []
        _error_msg = None
        _error_tb = None
        _interrupted = False
        message_buffer.completion_times["_start"] = time.time()
        try:
          for chunk in graph.graph.stream(init_agent_state, **args):
            # Process all messages in chunk, deduplicating by message ID
            for message in chunk.get("messages", []):
                msg_id = getattr(message, "id", None)
                if msg_id is not None:
                    if msg_id in message_buffer._processed_message_ids:
                        continue
                    message_buffer._processed_message_ids.add(msg_id)

                msg_type, content = classify_message_type(message)
                if content and content.strip():
                    message_buffer.add_message(msg_type, content)

                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tool_call in message.tool_calls:
                        if isinstance(tool_call, dict):
                            message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                        else:
                            message_buffer.add_tool_call(tool_call.name, tool_call.args)

            # Record completion times (first time agent output appears)
            now_chunk = time.time()

            # Analysts — their reports appear directly in chunks
            for analyst_key, report_key in ANALYST_REPORT_MAP.items():
                if analyst_key not in message_buffer.selected_analysts:
                    continue
                agent_name = ANALYST_AGENT_NAMES[analyst_key]
                if chunk.get(report_key) and agent_name not in message_buffer.completion_times:
                    message_buffer.completion_times[agent_name] = now_chunk

            # Research team — based on debate state content
            if chunk.get("investment_debate_state"):
                debate = chunk["investment_debate_state"]
                if debate.get("bull_history", "").strip() and "Bull Researcher" not in message_buffer.completion_times:
                    message_buffer.completion_times["Bull Researcher"] = now_chunk
                if debate.get("bear_history", "").strip() and "Bear Researcher" not in message_buffer.completion_times:
                    message_buffer.completion_times["Bear Researcher"] = now_chunk
                if debate.get("judge_decision", "").strip() and "Research Manager" not in message_buffer.completion_times:
                    message_buffer.completion_times["Research Manager"] = now_chunk

            # Trader
            if chunk.get("trader_investment_plan") and "Trader" not in message_buffer.completion_times:
                message_buffer.completion_times["Trader"] = now_chunk

            # Risk team — based on risk debate content
            if chunk.get("risk_debate_state"):
                risk = chunk["risk_debate_state"]
                if risk.get("aggressive_history", "").strip() and "Aggressive Analyst" not in message_buffer.completion_times:
                    message_buffer.completion_times["Aggressive Analyst"] = now_chunk
                if risk.get("conservative_history", "").strip() and "Conservative Analyst" not in message_buffer.completion_times:
                    message_buffer.completion_times["Conservative Analyst"] = now_chunk
                if risk.get("neutral_history", "").strip() and "Neutral Analyst" not in message_buffer.completion_times:
                    message_buffer.completion_times["Neutral Analyst"] = now_chunk
                if risk.get("judge_decision", "").strip() and "Portfolio Manager" not in message_buffer.completion_times:
                    message_buffer.completion_times["Portfolio Manager"] = now_chunk

            # Update analyst statuses based on report state (runs on every chunk)
            update_analyst_statuses(message_buffer, chunk)

            # Research Team - Handle Investment Debate State
            if chunk.get("investment_debate_state"):
                debate_state = chunk["investment_debate_state"]
                bull_hist = debate_state.get("bull_history", "").strip()
                bear_hist = debate_state.get("bear_history", "").strip()
                judge = debate_state.get("judge_decision", "").strip()

                # Only update status when there's actual content
                if bull_hist or bear_hist:
                    update_research_team_status("in_progress")
                if bull_hist:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                    )
                if bear_hist:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                    )
                if judge:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Research Manager Decision\n{judge}"
                    )
                    update_research_team_status("completed")
                    message_buffer.update_agent_status("Trader", "in_progress")

            # Trading Team
            if chunk.get("trader_investment_plan"):
                message_buffer.update_report_section(
                    "trader_investment_plan", chunk["trader_investment_plan"]
                )
                if message_buffer.agent_status.get("Trader") != "completed":
                    message_buffer.update_agent_status("Trader", "completed")
                    message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                    message_buffer.update_agent_status("Portfolio Manager", "in_progress")

            # Risk Management Team - Handle Risk Debate State
            if chunk.get("risk_debate_state"):
                risk_state = chunk["risk_debate_state"]
                agg_hist = risk_state.get("aggressive_history", "").strip()
                con_hist = risk_state.get("conservative_history", "").strip()
                neu_hist = risk_state.get("neutral_history", "").strip()
                judge = risk_state.get("judge_decision", "").strip()

                if agg_hist:
                    if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                        message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                    )
                if con_hist:
                    if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                        message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                    )
                if neu_hist:
                    if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                        message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                    )
                if judge:
                    if message_buffer.agent_status.get("Portfolio Manager") != "completed":
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Portfolio Manager Decision\n{judge}"
                        )
                        message_buffer.update_agent_status("Aggressive Analyst", "completed")
                        message_buffer.update_agent_status("Conservative Analyst", "completed")
                        message_buffer.update_agent_status("Neutral Analyst", "completed")
                        message_buffer.update_agent_status("Portfolio Manager", "completed")

            # Update the display
            update_display(layout, stats_handler=stats_handler, start_time=start_time)

            trace.append(chunk)

        except Exception as e:
            # Capture error details inside Live context (Live may swallow output)
            import traceback
            _error_msg = f"Graph execution failed: {e}"
            _error_tb = traceback.format_exc()
            _diag(f"EXCEPTION in stream: {type(e).__name__}: {e}")
            _diag(_error_tb)
        except KeyboardInterrupt:
            _interrupted = True
            _diag("KeyboardInterrupt")

        _diag(f"Stream ended. trace={len(trace)}, error={_error_msg is not None}, interrupted={_interrupted}")

        # Get final state and decision
        if not trace:
            pass  # error / interrupt handled outside Live context below
        else:
            final_state = trace[-1]
            if "final_trade_decision" not in final_state:
                console.print(
                    "[red]Analysis did not complete — no final decision available. "
                    "The graph may have failed before the Portfolio Manager ran.[/red]"
                )
                return
            decision = graph.process_signal(final_state["final_trade_decision"])

            # Update all agent statuses to completed
            for agent in message_buffer.agent_status:
                message_buffer.update_agent_status(agent, "completed")

            message_buffer.add_message(
                "System", f"Completed analysis for {selections['analysis_date']}"
            )

            # Update final report sections
            for section in message_buffer.report_sections.keys():
                if section in final_state:
                    message_buffer.update_report_section(section, final_state[section])

            update_display(layout, stats_handler=stats_handler, start_time=start_time)

    # Convert report_dir MDs to Word (best-effort, post-stream)
    try:
        from tradingagents.utils.report_converter import convert_report_dir_to_docx
        convert_report_dir_to_docx(
            report_dir, ticker=selections["ticker"],
            analysis_date=selections["analysis_date"],
        )
    except Exception:
        pass

    # Post-analysis prompts (outside Live context for clean interaction)
    if _interrupted:
        console.print("\n[yellow]Analysis interrupted by user (Ctrl+C).[/yellow]")
        return
    if not trace:
        if _error_msg:
            console.print(f"\n[bold red]{_error_msg}[/bold red]")
            console.print(f"[dim]{_error_tb}[/dim]")
        console.print("[red]No results to process.[/red]")
        return
    console.print("\n[bold cyan]Analysis Complete![/bold cyan]\n")

    # Show OpenCLI data summary if available
    if _is_ashare_ticker(selections["ticker"]) and shutil.which("opencli"):
        _show_opencli_summary(selections["ticker"])

    # Prompt to save report
    save_choice = typer.prompt("Save report?", default="Y").strip().upper()
    if save_choice in ("Y", "YES", ""):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path.cwd() / "reports" / f"{safe_ticker}_{timestamp}"
        save_path_str = typer.prompt(
            "Save path (press Enter for default)",
            default=str(default_path)
        ).strip()
        save_path = Path(save_path_str)
        try:
            report_file = save_report_to_disk(final_state, selections["ticker"], save_path)
            console.print(f"\n[green]✓ Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")

        # Save timing data (best-effort, never blocks report save)
        try:
            timing_data = {
                "ticker": selections["ticker"],
                "date": selections["analysis_date"],
                "total_elapsed_seconds": round(time.time() - start_time, 1),
                "agents": message_buffer.get_agent_durations(),
                "phases": message_buffer.get_phase_durations(),
                "stats": stats_handler.get_stats() if stats_handler else {},
            }
            timing_file = save_path / "timing.json"
            with open(timing_file, "w", encoding="utf-8") as f:
                json.dump(timing_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Timing save is best-effort

    # Prompt to display full report
    display_choice = typer.prompt("\nDisplay full report on screen?", default="Y").strip().upper()
    if display_choice in ("Y", "YES", ""):
        display_complete_report(final_state)


@app.command()
def screen(
    source: str = typer.Option("eastmoney", "--source", "-s",
        help="\u6570\u636e\u6e90: eastmoney, sinafinance, tdx, ths"),
    mode: str = typer.Option("rank", "--mode", "-m",
        help="\u7b5b\u9009\u6a21\u5f0f: rank(\u6da8\u8dcc\u6392\u884c), money-flow(\u4e3b\u529b\u8d44\u91d1), hot(\u70ed\u5ea6), sectors(\u677f\u5757)"),
    limit: int = typer.Option(20, "--limit", "-l",
        help="\u8fd4\u56de\u6570\u91cf"),
    format: str = typer.Option("table", "--format", "-f",
        help="\u8f93\u51fa\u683c\u5f0f: table, json, csv, markdown"),
):
    """\u4f7f\u7528 OpenCLI \u7b5b\u9009\u5019\u9009\u80a1\u7968\u6c60 (\u9700\u8981\u5df2\u5b89\u88c5 opencli)."""
    if not shutil.which("opencli"):
        console.print("[red]Error: opencli not found in PATH.[/red]")
        console.print("[dim]Install: npm install -g @jackwener/opencli[/dim]")
        raise typer.Exit(code=1)

    # Validate mode-source compatibility
    valid_modes = {
        "eastmoney": ["rank", "money-flow", "sectors", "hot"],
        "sinafinance": ["rank"],
        "tdx": ["hot"],
        "ths": ["hot"],
    }

    source_modes = valid_modes.get(source, [])
    if mode not in source_modes:
        console.print(f"[red]Error: mode '{mode}' not available for source '{source}'.[/red]")
        console.print(f"[dim]Available modes for {source}: {', '.join(source_modes)}[/dim]")
        raise typer.Exit(code=1)

    # Map (source, mode) to opencli command — some sources use different names
    cmd_map = {
        ("eastmoney", "rank"): "rank",
        ("eastmoney", "money-flow"): "money-flow",
        ("eastmoney", "sectors"): "sectors",
        ("eastmoney", "hot"): "hot-rank",
        ("sinafinance", "rank"): "stock-rank",
        ("tdx", "hot"): "hot-rank",
        ("ths", "hot"): "hot-rank",
    }
    opencli_cmd = cmd_map.get((source, mode), mode)

    # Build and execute opencli command
    import subprocess
    opencli_path = shutil.which("opencli")
    cmd = [opencli_path, source, opencli_cmd]
    # Some sources don't support --limit (e.g. sinafinance stock-rank)
    if source != "sinafinance":
        cmd.extend(["--limit", str(limit)])
    cmd.extend(["-f", format])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, encoding="utf-8"
        )
        if result.returncode != 0:
            console.print(f"[red]OpenCLI error: {result.stderr}[/red]")
            raise typer.Exit(code=1)

        if format == "json":
            # Parse and render as rich table
            try:
                data = json.loads(result.stdout)
                if data:
                    table = Table(
                        title=f"{source} {mode} (TOP {limit})",
                        show_header=True,
                        header_style="bold magenta",
                        box=box.ROUNDED,
                    )
                    # Add columns from first row keys
                    for key in data[0].keys():
                        table.add_column(key, justify="center")
                    # Add rows
                    for row in data:
                        table.add_row(*[str(v) for v in row.values()])
                    console.print(table)
                else:
                    console.print("[yellow]No data returned.[/yellow]")
            except json.JSONDecodeError:
                console.print(result.stdout)
        else:
            # For table/csv/markdown, pass through directly
            console.print(result.stdout)

    except subprocess.TimeoutExpired:
        console.print("[red]Error: opencli command timed out (30s).[/red]")
        raise typer.Exit(code=1)
    except FileNotFoundError:
        console.print("[red]Error: opencli not found.[/red]")
        raise typer.Exit(code=1)


@app.command()
def market(
    site: str = typer.Argument(
        ...,
        help="\u7ad9\u70b9: eastmoney, sinafinance, xueqiu, tdx, ths, binance, barchart, bloomberg",
    ),
    command: str = typer.Argument(
        ...,
        help="OpenCLI \u547d\u4ee4 (\u5982 quote, rank, kline, money-flow, sectors, longhu, northbound)",
    ),
    extra_args: Optional[list[str]] = typer.Argument(
        None,
        help="\u547d\u4ee4\u989d\u5916\u53c2\u6570 (\u5982\u80a1\u7968\u4ee3\u7801 600519)",
    ),
    format: str = typer.Option("table", "--format", "-f",
        help="\u8f93\u51fa\u683c\u5f0f: table, json, csv, markdown, yaml"),
    limit: int = typer.Option(20, "--limit", "-l",
        help="\u8fd4\u56de\u6570\u91cf"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
        help="\u663e\u793a\u8be6\u7ec6\u8f93\u51fa"),
):
    """\u900f\u4f20 OpenCLI \u8d22\u7ecf\u547d\u4ee4 (\u9700\u8981\u5df2\u5b89\u88c5 opencli).

    \u793a\u4f8b:
      tradingagents market eastmoney quote 600519 -f json
      tradingagents market eastmoney rank --limit 10
      tradingagents market eastmoney money-flow --limit 5 -f json
      tradingagents market binance price BTCUSDT -f json
      tradingagents market tdx hot-rank --limit 10
    """
    if not shutil.which("opencli"):
        console.print("[red]Error: opencli not found in PATH.[/red]")
        console.print("[dim]Install: npm install -g @jackwener/opencli[/dim]")
        raise typer.Exit(code=1)

    import subprocess

    opencli_path = shutil.which("opencli")
    cmd = [opencli_path, site, command]

    # Add extra positional args (like ticker symbol)
    if extra_args:
        cmd.extend(extra_args)

    # Commands that don't support --limit
    _NO_LIMIT = {"quote", "kline", "stock-rank", "index-board", "longhu"}
    if command not in _NO_LIMIT:
        cmd.extend(["--limit", str(limit)])
    cmd.extend(["-f", format])

    if verbose:
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, encoding="utf-8"
        )

        if result.returncode != 0:
            console.print(f"[red]Error: {result.stderr.strip()}[/red]")
            raise typer.Exit(code=1)

        if result.stdout.strip():
            console.print(result.stdout)
        else:
            console.print("[yellow]No output returned.[/yellow]")

    except subprocess.TimeoutExpired:
        console.print("[red]Error: opencli command timed out (30s).[/red]")
        raise typer.Exit(code=1)
    except FileNotFoundError:
        console.print("[red]Error: opencli not found.[/red]")
        raise typer.Exit(code=1)


@app.command()
def report(
    report_dir: str = typer.Argument(
        ...,
        help="Path to the report directory (e.g. reports/NVDA_20260115_120000).",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output", "-o",
        help="Output .docx file path. Defaults to <report_dir>/综合分析报告.docx.",
    ),
    ticker: Optional[str] = typer.Option(
        None,
        "--ticker", "-t",
        help="Ticker symbol for cover page (auto-detected from directory name if omitted).",
    ),
    date: Optional[str] = typer.Option(
        None,
        "--date", "-d",
        help="Analysis date for cover page, YYYY-MM-DD (auto-detected if omitted).",
    ),
):
    """Convert a saved report directory (with MD files) to a professional Word document."""
    from tradingagents.utils.report_converter import convert_report_dir_to_docx

    report_path = Path(report_dir)
    if not report_path.is_dir():
        console.print(f"[red]Error: Directory not found: {report_dir}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Generating Word report from:[/cyan] {report_path.resolve()}")

    try:
        docx_path = convert_report_dir_to_docx(
            report_path,
            output_path=output,
            ticker=ticker,
            analysis_date=date,
        )
        console.print(f"[green]Done. Word report saved to:[/green] {docx_path}")
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error generating report: {e}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()