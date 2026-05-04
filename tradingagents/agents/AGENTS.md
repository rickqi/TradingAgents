# AGENTS.md — tradingagents/agents

12 LLM-powered agents wired into a LangGraph pipeline. Each exports a `create_*` factory.

## Structure

```
agents/
├── __init__.py              # Re-exports all create_* functions (wildcard)
├── schemas.py               # Pydantic models + render_* helpers
├── analysts/                # 4 analysts — use quick_think_llm, bind_tools()
│   ├── market_analyst.py    # → create_market_analyst(llm)  | tools: get_stock_data, get_indicators
│   ├── social_media_analyst.py # → create_social_media_analyst(llm) | tools: get_news
│   ├── news_analyst.py      # → create_news_analyst(llm)    | tools: get_news, get_global_news
│   └── fundamentals_analyst.py # → create_fundamentals_analyst(llm) | tools: get_fundamentals, balance_sheet, cashflow, income_statement
├── researchers/             # 2 debators — use quick_think_llm, plain invoke
│   ├── bull_researcher.py   # → create_bull_researcher(llm)
│   └── bear_researcher.py   # → create_bear_researcher(llm)
├── managers/                # 2 structured-output agents
│   ├── research_manager.py  # → create_research_manager(llm) | deep_think_llm | schema: ResearchPlan
│   └── portfolio_manager.py # → create_portfolio_manager(llm) | deep_think_llm | schema: PortfolioDecision
├── trader/                  # 1 structured-output agent
│   └── trader.py            # → create_trader(llm) | quick_think_llm | schema: TraderProposal
├── risk_mgmt/               # 3 debators — use quick_think_llm, plain invoke
│   ├── aggressive_debator.py   # → create_aggressive_debator(llm)
│   ├── conservative_debator.py # → create_conservative_debator(llm)
│   └── neutral_debator.py      # → create_neutral_debator(llm)
└── utils/
    ├── agent_states.py      # AgentState, InvestDebateState, RiskDebateState TypedDicts
    ├── agent_utils.py       # create_msg_delete(), get_language_instruction(), tool re-exports
    ├── structured.py        # bind_structured(), invoke_structured_or_freetext()
    ├── memory.py            # TradingMemoryLog — persistent decision log
    ├── core_stock_tools.py  # @tool get_stock_data
    ├── technical_indicators_tools.py # @tool get_indicators
    ├── fundamental_data_tools.py # @tool get_fundamentals, balance_sheet, cashflow, income_statement
    ├── news_data_tools.py   # @tool get_news, get_global_news, get_insider_transactions
    └── rating.py            # Rating extraction helpers
```

## Factory Contract

Every agent follows: `def create_X(llm) -> callable_node`

The returned closure takes `state: dict` (matching `AgentState`) and returns a partial state update dict.

**One exception**: `create_trader()` uses `functools.partial` — the inner function has signature `(state, name)` and partial fixes `name="Trader"`.

## Pipeline Order (wired in `graph/setup.py`)

```
Market Analyst → Social Analyst → News Analyst → Fundamentals Analyst
    ↓ (each clears messages via create_msg_delete())
Bull ↔ Bear debate (N rounds, controlled by max_debate_rounds)
    ↓
Research Manager (structured: ResearchPlan) ← deep_think_llm
    ↓
Trader (structured: TraderProposal) ← quick_think_llm
    ↓
Aggressive → Conservative → Neutral risk debate (M rounds)
    ↓
Portfolio Manager (structured: PortfolioDecision) ← deep_think_llm
```

## Which LLM Each Agent Gets

| Agent | LLM | Why |
|-------|-----|-----|
| All 4 analysts | `quick_think_llm` | Data fetching + report writing, not deep reasoning |
| Bull & Bear researchers | `quick_think_llm` | Debate repetition, speed matters |
| Research Manager | `deep_think_llm` | Synthesizes debate into structured plan |
| Trader | `quick_think_llm` | Reads plan + reports, 3-tier decision |
| Risk debators (3) | `quick_think_llm` | Debate repetition |
| Portfolio Manager | `deep_think_llm` | Final 5-tier decision, most important |

## Structured Output Pattern

Only Research Manager, Trader, and Portfolio Manager use structured output:

```python
# At creation time (inside create_*)
structured_llm = bind_structured(llm, Schema, "Agent Name")  # may be None

# At invocation time (inside the node function)
result = invoke_structured_or_freetext(
    structured_llm,  # None if provider doesn't support it
    llm,             # plain LLM for fallback
    prompt,
    render_schema,   # Pydantic → markdown
    "Agent Name",
)
```

**Fallback chain**: `with_structured_output()` → if `NotImplementedError`/`AttributeError`, `structured_llm = None` → at invocation, try structured call → on ANY failure, fall back to `llm.invoke()` + strip DSML tokens → always returns a `str`.

## Pydantic Schemas (`schemas.py`)

| Schema | Fields | Used By | Render Helper |
|--------|--------|---------|---------------|
| `ResearchPlan` | `recommendation` (PortfolioRating), `rationale`, `strategic_actions` | Research Manager | `render_research_plan()` |
| `TraderProposal` | `action` (TraderAction: Buy/Hold/Sell), `reasoning`, optional `entry_price`/`stop_loss`/`position_sizing` | Trader | `render_trader_proposal()` |
| `PortfolioDecision` | `rating` (PortfolioRating: 5-tier), `executive_summary`, `investment_thesis`, optional `price_target`/`time_horizon` | Portfolio Manager | `render_pm_decision()` |

**Enums**: `PortfolioRating` = Buy/Overweight/Hold/Underweight/Sell. `TraderAction` = Buy/Hold/Sell.

## Adding a New Agent

1. Create `create_new_agent(llm)` in the appropriate subdirectory — follow the closure pattern
2. If structured output needed: add Pydantic schema to `schemas.py` with `render_*()` helper, use `bind_structured`/`invoke_structured_or_freetext`
3. Import in `agents/__init__.py` (wildcard re-export makes it available everywhere)
4. Wire into `graph/setup.py`: create node, add to StateGraph, set conditional edges
5. If new state fields needed: add to `AgentState` in `utils/agent_states.py`

## Agent Prompt Gotchas

- `agent_utils.py` enforces `"CRITICAL: Use this exact ticker string"` in every analyst prompt — prevents LLM from substituting company names in tool calls
- Market analyst prompt says `"do not select both rsi and stochrsi"` — prevents redundant indicators
- `create_msg_delete()` clears all messages between analyst nodes (Anthropic compatibility)
- `output_language` config key is read via `get_config()` inside `get_language_instruction()` and appended to prompts

## State TypedDicts

- **`AgentState`**: `messages`, `market_report`, `sentiment_report`, `news_report`, `fundamentals_report`, `investment_debate_state`, `trader_investment_plan`, `risk_debate_state`, `final_sales_proposal`, `rec_result`
- **`InvestDebateState`**: `history`, `bull_history`, `bear_history`, `count`, `current_response`
- **`RiskDebateState`**: `history`, `aggressive_history`, `conservative_history`, `neutral_history`, `count`, `current_response`
