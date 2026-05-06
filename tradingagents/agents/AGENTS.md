# AGENTS.md — tradingagents/agents

12 个由 LLM 驱动的智能体，接入 LangGraph 流水线。每个模块导出一个 `create_*` 工厂函数。

## 目录结构

```
agents/
├── __init__.py              # 重新导出所有 create_* 函数（通配符）
├── schemas.py               # Pydantic 模型 + render_* 辅助函数
├── analysts/                # 4 个分析师 — 使用 quick_think_llm，bind_tools()
│   ├── market_analyst.py    # → create_market_analyst(llm)  | 工具: get_stock_data, get_indicators
│   ├── social_media_analyst.py # → create_social_media_analyst(llm) | 工具: get_news, get_sentiment
│   ├── news_analyst.py      # → create_news_analyst(llm)    | 工具: get_news, get_global_news
│   └── fundamentals_analyst.py # → create_fundamentals_analyst(llm) | 工具: get_fundamentals, balance_sheet, cashflow, income_statement
├── researchers/             # 2 个辩论者 — 使用 quick_think_llm，普通 invoke
│   ├── bull_researcher.py   # → create_bull_researcher(llm)
│   └── bear_researcher.py   # → create_bear_researcher(llm)
├── managers/                # 2 个结构化输出智能体
│   ├── research_manager.py  # → create_research_manager(llm) | deep_think_llm | schema: ResearchPlan
│   └── portfolio_manager.py # → create_portfolio_manager(llm) | deep_think_llm | schema: PortfolioDecision
├── trader/                  # 1 个结构化输出智能体
│   └── trader.py            # → create_trader(llm) | quick_think_llm | schema: TraderProposal
├── risk_mgmt/               # 3 个辩论者 — 使用 quick_think_llm，普通 invoke
│   ├── aggressive_debator.py   # → create_aggressive_debator(llm)
│   ├── conservative_debator.py # → create_conservative_debator(llm)
│   └── neutral_debator.py      # → create_neutral_debator(llm)
└── utils/
    ├── agent_states.py      # AgentState, InvestDebateState, RiskDebateState TypedDicts
    ├── agent_utils.py       # create_msg_delete(), get_language_instruction(), 工具重新导出
    ├── structured.py        # bind_structured(), invoke_structured_or_freetext()
    ├── memory.py            # TradingMemoryLog — 持久化决策日志
    ├── core_stock_tools.py  # @tool get_stock_data
    ├── technical_indicators_tools.py # @tool get_indicators
    ├── fundamental_data_tools.py # @tool get_fundamentals, balance_sheet, cashflow, income_statement
    ├── news_data_tools.py   # @tool get_news, get_global_news, get_insider_transactions
    ├── sentiment_tools.py   # @tool get_sentiment（仅 akshare）
    └── rating.py            # 评级提取辅助函数
```

## 工厂函数约定

每个智能体遵循：`def create_X(llm) -> callable_node`

返回的闭包接受 `state: dict`（匹配 `AgentState`）并返回一个部分状态更新字典。

**唯一例外**：`create_trader()` 使用 `functools.partial` — 内部函数签名为 `(state, name)`，partial 固定了 `name="Trader"`。

## 流水线顺序（在 `graph/setup.py` 中连接）

```
Market Analyst → Social Analyst → News Analyst → Fundamentals Analyst
    ↓ （每个通过 create_msg_delete() 清除消息）
Bull ↔ Bear 辩论（N 轮，由 max_debate_rounds 控制）
    ↓
Research Manager（结构化: ResearchPlan）← deep_think_llm
    ↓
Trader（结构化: TraderProposal）← quick_think_llm
    ↓
Aggressive → Conservative → Neutral 风险辩论（M 轮）
    ↓
Portfolio Manager（结构化: PortfolioDecision）← deep_think_llm
```

## 各智能体使用的 LLM

| 智能体 | LLM | 原因 |
|-------|-----|------|
| 全部 4 个分析师 | `quick_think_llm` | 数据获取 + 报告撰写，不需要深度推理 |
| 看多 & 看空研究员 | `quick_think_llm` | 辩论有重复性，速度更重要 |
| Research Manager | `deep_think_llm` | 将辩论综合为结构化方案 |
| Trader | `quick_think_llm` | 阅读方案 + 报告，三级决策 |
| 风险辩论者（3 个）| `quick_think_llm` | 辩论有重复性 |
| Portfolio Manager | `deep_think_llm` | 最终五级决策，最为关键 |

## 结构化输出模式

仅 Research Manager、Trader 和 Portfolio Manager 使用结构化输出：

```python
# 创建时（在 create_* 内部）
structured_llm = bind_structured(llm, Schema, "Agent Name")  # 可能为 None

# 调用时（在节点函数内部）
result = invoke_structured_or_freetext(
    structured_llm,  # 如果供应商不支持则为 None
    llm,             # 用于回退的普通 LLM
    prompt,
    render_schema,   # Pydantic → markdown
    "Agent Name",
)
```

**降级链**：`with_structured_output()` → 若抛出 `NotImplementedError`/`AttributeError`，则 `structured_llm = None` → 调用时尝试结构化调用 → 任意失败则回退到 `llm.invoke()` + 清理 DSML token → 始终返回 `str`。

## Pydantic Schema（`schemas.py`）

| Schema | 字段 | 使用者 | 渲染辅助函数 |
|--------|------|--------|-------------|
| `ResearchPlan` | `recommendation`（PortfolioRating）、`rationale`、`strategic_actions` | Research Manager | `render_research_plan()` |
| `TraderProposal` | `action`（TraderAction: Buy/Hold/Sell）、`reasoning`、可选 `entry_price`/`stop_loss`/`position_sizing` | Trader | `render_trader_proposal()` |
| `PortfolioDecision` | `rating`（PortfolioRating: 五级）、`executive_summary`、`investment_thesis`、可选 `price_target`/`time_horizon` | Portfolio Manager | `render_pm_decision()` |

**枚举**：`PortfolioRating` = Buy/Overweight/Hold/Underweight/Sell。`TraderAction` = Buy/Hold/Sell。

## 新增智能体

1. 在对应子目录中创建 `create_new_agent(llm)` — 遵循闭包模式
2. 如需结构化输出：在 `schemas.py` 中添加 Pydantic schema 及 `render_*()` 辅助函数，使用 `bind_structured`/`invoke_structured_or_freetext`
3. 在 `agents/__init__.py` 中导入（通配符重新导出使其在所有地方可用）
4. 在 `graph/setup.py` 中接入：创建节点、添加到 StateGraph、设置条件边
5. 如需新的状态字段：在 `utils/agent_states.py` 的 `AgentState` 中添加

## 智能体提示注意事项

- `agent_utils.py` 在每个分析师提示中强制包含 `"CRITICAL: Use this exact ticker string"` — 防止 LLM 在工具调用中替换为公司名称
- Market analyst 提示要求 `"do not select both rsi and stochrsi"` — 防止冗余指标
- `create_msg_delete()` 在分析师节点之间清除所有消息（兼容 Anthropic）
- `output_language` 配置键通过 `get_config()` 在 `get_language_instruction()` 中读取并附加到提示中
- `get_language_instruction()` 仅附加到 **4 个分析师 + Portfolio Manager** 的提示中 — 内部辩论智能体（Bull/Bear、风险辩论者、Research Manager、Trader）保持英文以确保推理质量。这是有意为之的设计。
- `get_sentiment` 工具仅 akshare 提供 — 其他供应商未实现此方法。仅连接到 social_media_analyst 的工具列表。

## 状态 TypedDict

- **`AgentState`**：`messages`、`market_report`、`sentiment_report`、`news_report`、`fundamentals_report`、`investment_debate_state`、`trader_investment_plan`、`risk_debate_state`、`final_sales_proposal`、`rec_result`
- **`InvestDebateState`**：`history`、`bull_history`、`bear_history`、`count`、`current_response`
- **`RiskDebateState`**：`history`、`aggressive_history`、`conservative_history`、`neutral_history`、`count`、`current_response`
