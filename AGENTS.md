# AGENTS.md — TradingAgents

Quick-reference for agents working in this repo. Covers what's hard to infer from filenames alone.

## Project Overview

Multi-agent LLM financial trading framework (v0.2.4). Python package built on LangGraph. Research-oriented, not production trading advice.

## Setup & Install

```bash
python -m venv .venv          # requires Python >= 3.10, tested on 3.13
.venv\Scripts\activate        # Windows
pip install .                  # editable install; real deps are in pyproject.toml
```

- `requirements.txt` is just `.` — it installs the local package.
- `uv.lock` exists but `pip install .` works fine without `uv`.
- Docker alternative: `docker compose run --rm tradingagents` (needs `.env`).

## Environment & API Keys

Copy `.env.example` → `.env` and fill in at least one LLM provider key:

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=...
DASHSCOPE_API_KEY=...        # Qwen (Alibaba)
ZHIPU_API_KEY=...             # GLM
OPENROUTER_API_KEY=...
ALPHA_VANTAGE_API_KEY=...     # optional, for alpha_vantage data vendor
```

Enterprise (Azure OpenAI): copy `.env.enterprise.example` → `.env.enterprise`.

`main.py` and CLI both call `load_dotenv()` at startup, which reads `.env` and `.env.enterprise`.

## Running

**CLI (interactive TUI):**
```bash
tradingagents                   # after pip install (analyze is the default)
python -m cli.main              # from source without install
tradingagents --checkpoint      # SQLite checkpoint resume
tradingagents --clear-checkpoints
```

**Python API:**
```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-v4-pro"
config["quick_think_llm"] = "deepseek-v4-flash"

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

**scripts/ analysis tools** (run from project root):
```bash
python scripts/run_single.py 002460 --date 2026-05-02    # single stock
python scripts/run_a_share.py 600519.SH 2026-04-30       # A-share (tencent_sina)
python scripts/batch_analyze.py 002876 000062 ...          # batch + reports
python scripts/turnover_screener.py --analyze 5            # screen by turnover
python scripts/test_datasource.py                          # API connectivity test
python scripts/smoke_structured_output.py deepseek          # structured-output smoke test
```

## Testing

```bash
pip install pytest                # not in pyproject deps
pytest                            # runs all (markers: unit, integration, smoke)
pytest -m unit                    # fast isolated tests only
pytest tests/test_model_validation.py  # single file
```

- `tests/conftest.py` auto-fills placeholder API keys via `monkeypatch` — suite runs without real credentials.
- No linter/formatter/typecheck config in repo.

## Architecture

```
tradingagents/
├── graph/            # LangGraph orchestration
│   ├── trading_graph.py   # TradingAgentsGraph — main entrypoint class
│   ├── setup.py           # GraphSetup — builds the LangGraph StateGraph
│   ├── propagation.py     # Propagator — state init, graph args, recursion_limit
│   ├── signal_processing.py  # SignalProcessor — extracts rating from PM output
│   ├── conditional_logic.py  # debate round control
│   ├── checkpointer.py       # SQLite checkpoint resume
│   └── reflection.py         # memory-log reflection on past decisions
├── agents/                 # → see tradingagents/agents/AGENTS.md
│   ├── analysts/      # Market, Social, News, Fundamentals
│   ├── researchers/   # Bull, Bear (debate), Research Manager (structured output)
│   ├── trader/        # Trader (structured output — 3-tier Buy/Hold/Sell)
│   ├── managers/      # Research Manager, Portfolio Manager (5-tier rating)
│   ├── risk_mgmt/     # Aggressive, Conservative, Neutral debators
│   ├── schemas.py     # Pydantic schemas for structured output
│   └── utils/         # agent_states, agent_utils (data tools), memory, structured.py
├── dataflows/              # → see tradingagents/dataflows/AGENTS.md
│   ├── interface.py   # Vendor routing — VENDOR_METHODS, route_to_vendor() with fallback
│   ├── config.py      # set_config() — module-level singleton, .update() merge
│   ├── y_finance.py   # yfinance implementations
│   ├── yfinance_news.py
│   ├── tencent_sina.py   # A-share: Tencent K-line + Sina quotes + East Money APIs
│   ├── akshare_vendor.py # A-share: AKShare — insider transactions, sentiment, per-stock financials
│   └── alpha_vantage*.py # Alpha Vantage implementations
├── llm_clients/       # Multi-provider LLM abstraction
│   ├── factory.py     # create_llm_client() — lazy imports
│   ├── base_client.py # BaseLLMClient, normalize_content(), DSML token stripping
│   ├── openai_client.py  # OpenAI + all OpenAI-compatible; DeepSeekChatOpenAI subclass
│   ├── anthropic_client.py
│   ├── google_client.py
│   ├── azure_client.py
│   └── model_catalog.py  # CLI model selection menus (MODEL_OPTIONS dict)
└── default_config.py  # DEFAULT_CONFIG dict — all tunable knobs

cli/                   # Interactive TUI (Typer + Rich)
  ├── main.py          # Entry point: app = Typer(), @app.command() analyze
  ├── models.py        # AnalystType enum
  └── utils.py         # TUI prompts for provider/model selection

scripts/               # User-created analysis tooling (NOT a Python package, no __init__.py)
  ├── _share_config.py       # Shared: Windows UTF-8 fix, build_ashare_config(), init helpers
  ├── run_single.py           # Single stock analysis (generic)
  ├── run_a_share.py          # Single A-share stock analysis
  ├── run_batch.py            # Sequential batch with --start-from resume
  ├── batch_analyze.py        # Batch + per-stock MD/DOCX reports + summary
  ├── turnover_screener.py    # East Money turnover screener + analysis
  ├── test_datasource.py      # A-share API connectivity tester (standalone)
  ├── generate_report_from_log.py  # Regenerate reports from saved JSON state
  └── smoke_structured_output.py   # Structured-output smoke test per provider
```

### Agent Pipeline Flow

1. **Analyst Team** (parallelizable): Market → Social → News → Fundamentals — each uses LangGraph ToolNode for data fetching
2. **Research Team**: Bull Researcher vs Bear Researcher debate (N rounds), then Research Manager produces structured `ResearchPlan`
3. **Trader**: Reads research plan + analyst reports → structured `TraderProposal` (Buy/Hold/Sell)
4. **Risk Management**: Aggressive/Conservative/Neutral debators evaluate
5. **Portfolio Manager**: Final structured `PortfolioDecision` (5-tier: Buy/Overweight/Hold/Underweight/Sell)

### Key Design Decisions

- **Two LLMs per run**: `deep_think_llm` for complex reasoning (Research Manager, Portfolio Manager), `quick_think_llm` for everything else. Both from same provider.
- **Structured output with graceful fallback**: Research Manager, Trader, PM use `bind_structured()`/`invoke_structured_or_freetext()` → Pydantic schema on success, free-text + DSML stripping on failure. See `tradingagents/agents/AGENTS.md`.
- **Vendor abstraction with fallback chains**: Comma-separated vendor strings, tool-level overrides. See `tradingagents/dataflows/AGENTS.md`.
- **Memory log**: Persistent at `~/.tradingagents/memory/trading_memory.md`. Auto-resolves prior decisions with realised returns on next same-ticker run.
- **LLM client factory**: `create_llm_client()` lazy-imports provider modules. DeepSeek gets `DeepSeekChatOpenAI` subclass for thinking-mode round-trip.
- **Recursion limit**: `max_recur_limit` (default 250) sets LangGraph's `recursion_limit` in `propagation.py`.
- **No circular imports**: Clean DAG: `default_config ← dataflows.config ← interface ← agent tools ← agents ← graph`.

## Config (DEFAULT_CONFIG keys)

| Key | Default | Notes |
|-----|---------|-------|
| `llm_provider` | `"openai"` | `openai`, `google`, `anthropic`, `xai`, `deepseek`, `qwen`, `glm`, `openrouter`, `ollama`, `azure` |
| `deep_think_llm` | `"gpt-5.4"` | Model for complex reasoning |
| `quick_think_llm` | `"gpt-5.4-mini"` | Model for quick tasks |
| `backend_url` | `None` | Per-provider default used when None. Set only for custom proxies. |
| `max_debate_rounds` | `1` | Research debate rounds |
| `max_risk_discuss_rounds` | `1` | Risk debate rounds |
| `max_recur_limit` | `250` | LangGraph recursion limit |
| `checkpoint_enabled` | `False` | SQLite checkpoint after each node |
| `output_language` | `"English"` | Report language (internal debate stays English) |
| `data_vendors` | all `"yfinance"` | Per-category override. Options: `yfinance`, `alpha_vantage`, `tencent_sina`, `akshare`. Supports comma-separated fallback chains. `sentiment_data` defaults to `"akshare"`. |
| `tool_vendors` | `{}` | Per-tool override, takes precedence over `data_vendors` |
| `google_thinking_level` | `None` | `"high"`, `"minimal"`, etc. |
| `openai_reasoning_effort` | `None` | `"medium"`, `"high"`, `"low"` |
| `anthropic_effort` | `None` | `"high"`, `"medium"`, `"low"` |

Env overrides: `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`.

## Data Vendors

Four vendors (`yfinance`, `alpha_vantage`, `tencent_sina`, `akshare`), covering 10 tool methods. Supports comma-separated fallback chains (e.g. `"tencent_sina,akshare"`). `sentiment_data` category (akshare-only) provides quantitative sentiment scores via `get_sentiment`. See `tradingagents/dataflows/AGENTS.md` for full details.

## DeepSeek Model Notes

- `deepseek-v4-pro` — flagship, thinking mode, supports Tool Calls + `tool_choice` in thinking mode
- `deepseek-v4-flash` — fast, thinking mode, supports Tool Calls + `tool_choice` in thinking mode
- `deepseek-reasoner` — **legacy** (retires 2026-07-24), does NOT support `tool_choice`. `with_structured_output()` raises `NotImplementedError`; agent factories auto-fallback to free-text.
- `deepseek-chat` — **legacy** (retires 2026-07-24), maps to `deepseek-v4-flash`
- Thinking mode returns `reasoning_content` field that must be echoed back in subsequent tool-call turns (handled by `DeepSeekChatOpenAI` subclass in `openai_client.py`).
- Thinking mode ignores `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`.
- Internal thinking tokens (`<｜DSML｜>`) sometimes leak into content — stripped by `_strip_dsml_tokens()` in `base_client.py` and `structured.py`.

## Windows Gotchas

- All file I/O uses explicit `encoding="utf-8"` (v0.2.4 fix for cp1252 errors).
- Ticker symbols with special chars (`.`, `-`) are sanitized for filesystem paths via `safe_ticker_component()`.
- `scripts/_share_config.py` auto-fixes stdout/stderr to UTF-8 on import if encoding is not already UTF-8.

## scripts/ Import Quirks

`scripts/` has **no `__init__.py`** — it is NOT a Python package. Two import patterns coexist:

- **Bare import** (`from _share_config import ...`): `run_a_share.py`, `run_batch.py`, `batch_analyze.py`, `turnover_screener.py`. Works because Python adds the script's directory to `sys.path`. Run from project root: `python scripts/run_a_share.py ...`
- **Package-relative** (`sys.path.insert(0, project_root)` + `from scripts._share_config import ...`): only `run_single.py`.
- **Standalone** (no `_share_config`): `test_datasource.py`, `smoke_structured_output.py`, `generate_report_from_log.py`.

## Patterns to Follow

- **Agent factories**: Each agent module exports a `create_*` function that takes an LLM and returns a callable node function. Follow this pattern for new agents.
- **Pydantic schemas**: New structured-output agents → add schema to `schemas.py` with render helper.
- **Data tools**: New data sources → add vendor methods to `dataflows/interface.py` VENDOR_METHODS dict, then add to the appropriate ToolNode in `trading_graph.py`.
- **New LLM providers**: Add to `_PROVIDER_CONFIG` in `openai_client.py` (if OpenAI-compatible) or create new client in `llm_clients/`. Register in `factory.py`. Add models to `model_catalog.py`.
- **Config propagation**: Don't edit `dataflows/config.py` directly — use `set_config()` or pass config to `TradingAgentsGraph()`. `get_config()` returns a shallow copy.

## What Not to Do

- Don't set `backend_url` to an OpenAI URL when using non-OpenAI providers (each provider falls back to its own endpoint).
- Don't use `deepseek-reasoner` for structured output — it doesn't support `tool_choice`. Use `deepseek-v4-pro` or `deepseek-v4-flash` instead.
- Don't edit `dataflows/config.py` directly — use `set_config()` or pass config to `TradingAgentsGraph()`.
- Don't suppress type errors with `as any`, `@ts-ignore`, or empty catch blocks.
