# AGENTS.md — TradingAgents

Quick-reference for agents working in this repo. Covers what's hard to infer from filenames alone.

## Project Overview

Multi-agent LLM financial trading framework (v0.2.4). Python package built on LangGraph. Research-oriented, not production trading advice.

## Setup & Install

```bash
# Create venv (requires Python >= 3.10, tested on 3.13)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# Install as editable package
pip install .
```

- `requirements.txt` is just `.` — it installs the local package. Real deps are in `pyproject.toml`.
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
```

Enterprise (Azure OpenAI): copy `.env.enterprise.example` → `.env.enterprise`.

`main.py` and CLI both call `load_dotenv()` at startup, which reads `.env` and `.env.enterprise`.

## Running

**CLI (interactive):**
```bash
tradingagents                   # after pip install (analyze is the default)
python -m cli.main              # from source without install
```

**CLI with checkpoint resume:**
```bash
tradingagents --checkpoint
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

**CLI with checkpoint resume:**
```bash
tradingagents --checkpoint
tradingagents --clear-checkpoints
```

**Smoke test for structured output (low cost):**
```bash
OPENAI_API_KEY=... python scripts/smoke_structured_output.py openai
DEEPSEEK_API_KEY=... python scripts/smoke_structured_output.py deepseek
```

## Testing

```bash
pip install pytest                # not in pyproject deps
pytest                            # runs all (markers: unit, integration, smoke)
pytest -m unit                    # fast isolated tests only
pytest tests/test_model_validation.py  # single file
```

- `conftest.py` auto-fills placeholder API keys — suite runs without real credentials.
- No linter/formatter/typecheck config in repo.

## Architecture

```
tradingagents/
├── graph/            # LangGraph orchestration
│   ├── trading_graph.py   # TradingAgentsGraph — main entrypoint class
│   ├── setup.py           # GraphSetup — builds the LangGraph StateGraph
│   ├── propagation.py     # Propagator — state init and graph args
│   ├── signal_processing.py  # SignalProcessor — extracts rating from PM output
│   ├── conditional_logic.py  # debate round control
│   ├── checkpointer.py       # SQLite checkpoint resume
│   └── reflection.py         # memory-log reflection on past decisions
├── agents/
│   ├── analysts/      # Market, Social, News, Fundamentals
│   ├── researchers/   # Bull, Bear (debate), Research Manager (structured output)
│   ├── trader/        # Trader (structured output — 3-tier Buy/Hold/Sell)
│   ├── managers/      # Research Manager, Portfolio Manager (5-tier rating)
│   ├── risk_mgmt/     # Aggressive, Conservative, Neutral debators
│   ├── schemas.py     # Pydantic schemas for structured output
│   └── utils/         # agent_states, agent_utils (data tools), memory
├── dataflows/         # Market data abstraction layer
│   ├── interface.py   # Vendor routing — yfinance vs alpha_vantage
│   ├── config.py      # set_config() — propagates DEFAULT_CONFIG
│   ├── y_finance.py   # yfinance implementations
│   ├── yfinance_news.py
│   └── alpha_vantage*.py  # Alpha Vantage implementations
├── llm_clients/       # Multi-provider LLM abstraction
│   ├── factory.py     # create_llm_client() — lazy imports
│   ├── openai_client.py  # OpenAI + all OpenAI-compatible (DeepSeek, xAI, Qwen, GLM, Ollama, OpenRouter)
│   ├── anthropic_client.py
│   ├── google_client.py
│   ├── azure_client.py
│   └── model_catalog.py  # CLI model selection menus
└── default_config.py  # DEFAULT_CONFIG dict — all tunable knobs

cli/                   # Interactive TUI (Typer + Rich)
  ├── main.py          # Entry point: app = Typer(), @app.command() analyze
  ├── models.py        # AnalystType enum
  └── utils.py         # TUI prompts for provider/model selection
```

### Agent Pipeline Flow

1. **Analyst Team** (parallelizable): Market → Social → News → Fundamentals — each uses LangGraph ToolNode for data fetching
2. **Research Team**: Bull Researcher vs Bear Researcher debate (N rounds), then Research Manager produces structured `ResearchPlan`
3. **Trader**: Reads research plan + analyst reports → structured `TraderProposal` (Buy/Hold/Sell)
4. **Risk Management**: Aggressive/Conservative/Neutral debators evaluate
5. **Portfolio Manager**: Final structured `PortfolioDecision` (5-tier: Buy/Overweight/Hold/Underweight/Sell)

### Key Design Decisions

- **Two LLMs per run**: `deep_think_llm` for complex reasoning agents, `quick_think_llm` for fast tasks. Both created from same provider.
- **Structured output**: Research Manager, Trader, and Portfolio Manager use `llm.with_structured_output(PydanticSchema)` — provider-specific method (json_schema for OpenAI, tool-use for Anthropic, etc.). Render helpers convert back to markdown.
- **Vendor abstraction**: `dataflows/interface.py` routes tool calls to yfinance or Alpha Vantage based on config. Tool-level `tool_vendors` overrides category-level `data_vendors`.
- **Memory log**: Persistent at `~/.tradingagents/memory/trading_memory.md`. Auto-resolves prior decisions with realised returns on next same-ticker run.
- **LLM client factory**: `create_llm_client()` lazy-imports provider modules. DeepSeek gets special `DeepSeekChatOpenAI` subclass for thinking-mode round-trip.

## Config (DEFAULT_CONFIG keys)

| Key | Default | Notes |
|-----|---------|-------|
| `llm_provider` | `"openai"` | `openai`, `google`, `anthropic`, `xai`, `deepseek`, `qwen`, `glm`, `openrouter`, `ollama`, `azure` |
| `deep_think_llm` | `"gpt-5.4"` | Model for complex reasoning |
| `quick_think_llm` | `"gpt-5.4-mini"` | Model for quick tasks |
| `backend_url` | `None` | Per-provider default used when None. Set only for custom proxies. |
| `max_debate_rounds` | `1` | Research debate rounds |
| `max_risk_discuss_rounds` | `1` | Risk debate rounds |
| `checkpoint_enabled` | `False` | SQLite checkpoint after each node |
| `output_language` | `"English"` | Report language (internal debate stays English) |
| `data_vendors` | all `"yfinance"` | Override per-category: `alpha_vantage` |
| `tool_vendors` | `{}` | Per-tool override, takes precedence over `data_vendors` |

Env overrides: `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`.

## Windows Gotchas

- All file I/O uses explicit `encoding="utf-8"` (v0.2.4 fix for cp1252 errors).
- Ticker symbols with special chars (`.`, `-`) are sanitized for filesystem paths via `safe_ticker_component()`.

## Patterns to Follow

- **Agent factories**: Each agent module exports a `create_*` function that takes an LLM and returns a callable node function. Follow this pattern for new agents.
- **Pydantic schemas**: New structured-output agents → add schema to `schemas.py` with render helper.
- **Data tools**: New data sources → add vendor methods to `dataflows/interface.py` VENDOR_METHODS dict, then add to the appropriate ToolNode in `trading_graph.py`.
- **New LLM providers**: Add to `_PROVIDER_CONFIG` in `openai_client.py` (if OpenAI-compatible) or create new client in `llm_clients/`. Register in `factory.py`. Add models to `model_catalog.py`.

## What Not to Do

- Don't set `backend_url` to an OpenAI URL when using non-OpenAI providers (v0.2.4 fixed this default; each provider now falls back to its own endpoint).
- `deepseek-reasoner` does not support structured output (`with_structured_output` raises `NotImplementedError`). Agent factories auto-fallback to free-text.
- Don't edit `dataflows/config.py` directly — use `set_config()` or pass config to `TradingAgentsGraph()`.
