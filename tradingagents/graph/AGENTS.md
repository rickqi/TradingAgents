# AGENTS.md — tradingagents/graph

LangGraph 编排层。构建 StateGraph、管理状态传播、检查点恢复和记忆反思。

## 目录结构

```
graph/
├── __init__.py              # 重新导出所有公开类
├── trading_graph.py         # TradingAgentsGraph — 主入口类
├── setup.py                 # GraphSetup — 构建 LangGraph StateGraph（节点 + 边）
├── propagation.py           # Propagator — 初始状态创建、图调用参数
├── signal_processing.py     # SignalProcessor — 从 PM 输出提取评级（确定性，无 LLM 调用）
├── conditional_logic.py     # ConditionalLogic — 辩论/风险辩论轮次控制
├── checkpointer.py          # 每 ticker SQLite 检查点，SHA256 thread_id
└── reflection.py            # Reflector — 基于记忆日志的决策反思
```

## 核心类

### TradingAgentsGraph（`trading_graph.py`）

主入口。`propagate(company_name, trade_date) -> (state_dict, rating_str)` 执行完整流水线。

**关键方法**：
- `_is_chinese_ticker(ticker)` — 静态方法，检测 A 股/HK（纯 6 位数字、`.SZ/.SH/.SS/.HK` 后缀、`sh/sz/hk` 前缀、逗号列表、引号包裹）
- `_auto_detect_vendor(ticker)` — config 为默认值时自动将 `data_vendors` 切换为 `tencent_sina`，再调 `set_config()` 同步
- `_resolve_pending_entries(ticker)` — 流水线运行前，为同 ticker 的待决记忆条目获取收益并生成反思
- `_fetch_returns(ticker, date, holding_days=5)` — 原始收益 + 相对 SPY 超额收益；A 股走 tencent_sina
- `_log_state(date, state)` — 完整状态写入 JSON（`~/.tradingagents/logs/{TICKER}/TradingAgentsStrategy_logs/`）
- `process_signal(text)` — 委托 `SignalProcessor.process_signal()`

### GraphSetup（`setup.py`）

`setup_graph(selected_analysts) -> StateGraph`（未编译）。构建 `StateGraph(AgentState)`，`selected_analysts` 控制哪些分析师进入图（至少 1 个）。

### Propagator（`propagation.py`）

- `create_initial_state(company_name, trade_date, past_context="") -> dict` — 完整 `AgentState` 字典（空报告 + 空辩论状态）
- `get_graph_args(callbacks=None) -> dict` — `{"stream_mode": "values", "config": {"recursion_limit": max_recur_limit}}`

### SignalProcessor（`signal_processing.py`）

`process_signal(full_signal) -> str` — 确定性评级提取（Buy/Overweight/Hold/Underweight/Sell）。先去重 DeepSeek 重复的 `FINAL TRANSACTION PROPOSAL`，再调 `agents/utils/rating.py:parse_rating()`。**不调用 LLM**，构造器的 LLM 参数仅为向后兼容。

### ConditionalLogic（`conditional_logic.py`）

- **分析师条件边**（4 个 `should_continue_{type}`）：检查 `tool_calls` → 有则 `tools_{type}`，无则 `Msg Clear {Type}`
- **辩论条件边**：`count >= 2 × max_debate_rounds` 结束；发言者交替 Bull ↔ Bear
- **风险辩论条件边**：`count >= 3 × max_risk_discuss_rounds` 结束；轮转 Aggressive → Conservative → Neutral → ...

### Reflector（`reflection.py`）

`reflect_on_final_decision(final_decision, raw_return, alpha_return) -> str` — 用 `quick_thinking_llm` 生成 2-4 句反思，存入记忆日志。

### 检查点（`checkpointer.py`）

- 每 ticker 一个 SQLite DB：`~/.tradingagents/cache/checkpoints/{TICKER}.db`
- `thread_id = SHA256(ticker.upper() + ":" + date)[:16]`
- `get_checkpointer()` 上下文管理器 yield `SqliteSaver`
- `clear_checkpoint()` 删除对应 thread 行（不删 DB）；`clear_all_checkpoints()` 删所有 `.db`

## LangGraph StateGraph 结构

### 节点（由 `selected_analysts` 动态决定）

```
START → Market Analyst → tools_market → Msg Clear Market
      → Social Analyst → tools_social → Msg Clear Social
      → News Analyst   → tools_news   → Msg Clear News
      → Fundamentals Analyst → tools_fundamentals → Msg Clear Fundamentals
      → Bull Researcher ↔ Bear Researcher（条件循环）
      → Research Manager → Trader
      → Aggressive Analyst → Conservative Analyst → Neutral Analyst（条件循环）
      → Portfolio Manager → END
```

### 条件边

| 源节点 | 条件函数 | 路由目标 |
|--------|---------|---------|
| 每个分析师 | `should_continue_{type}` | `tools_{type}`（有 tool_calls）或 `Msg Clear {Type}`（无） |
| Bull Researcher | `should_continue_debate` | Bear Researcher（继续）或 Research Manager（结束） |
| Bear Researcher | `should_continue_debate` | Bull Researcher（继续）或 Research Manager（结束） |
| Aggressive Analyst | `should_continue_risk_analysis` | Conservative Analyst（继续）或 Portfolio Manager（结束） |
| Conservative Analyst | `should_continue_risk_analysis` | Neutral Analyst（继续）或 Portfolio Manager（结束） |
| Neutral Analyst | `should_continue_risk_analysis` | Aggressive Analyst（继续）或 Portfolio Manager（结束） |

### AgentState 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | list | LangGraph MessagesState，贯穿全图 |
| `company_of_interest` | str | 分析目标 ticker |
| `trade_date` | str | 分析日期 |
| `sender` | str | 当前消息发送者 |
| `market_report` | str | Market Analyst 输出 |
| `sentiment_report` | str | Social Media Analyst 输出 |
| `news_report` | str | News Analyst 输出 |
| `fundamentals_report` | str | Fundamentals Analyst 输出 |
| `investment_debate_state` | InvestDebateState | 看多/看空辩论状态 |
| `investment_plan` | str | Research Manager 方案 |
| `trader_investment_plan` | str | Trader 提案 |
| `risk_debate_state` | RiskDebateState | 风险辩论状态 |
| `final_trade_decision` | str | Portfolio Manager 最终决策 |
| `past_context` | str | 记忆日志上下文 |
| `opencli_snapshot` | str | OpenCLI 预分析快照 |

## 配置传递链

```
DEFAULT_CONFIG（深拷贝）
  → TradingAgentsGraph.__init__(config)
    → set_config(config)                        # dataflows.config 模块级单例
    → create_llm_client(provider, model)        # llm_clients 工厂
    → GraphSetup / Propagator / ConditionalLogic # 参数化构建
```

`_auto_detect_vendor()` 会修改 `self.config["data_vendors"]` 并再次调用 `set_config()` 同步到 dataflows 层。

## 执行流程（`propagate()`）

1. `_auto_detect_vendor(ticker)` — A 股自动切换数据源
2. `_resolve_pending_entries(ticker)` — 解决待决记忆条目（获取收益 + 生成反思）
3. 可选：编译带检查点的图（`checkpoint_enabled` 时）
4. `Propagator.create_initial_state()` — 构建初始状态
5. `graph.stream()` 或 `graph.invoke()` — 执行 LangGraph 图
6. `_log_state()` — 写入 JSON 日志
7. `memory_log.store_decision()` — 存储决策到记忆日志（延迟反思）
8. 可选：`clear_checkpoint()` — 清除检查点
9. `process_signal()` → 返回 `(state, rating)`

## 关键设计决策

- **`_is_chinese_ticker()` 必须与 `cli/main.py:_is_ashare_ticker()` 保持同步** — 两者处理相同的输入格式（纯数字、后缀、前缀、逗号分隔、引号）。修改一方时必须同步另一方。
- **无循环导入 DAG**：`default_config ← dataflows.config ← interface ← agent tools ← agents ← graph`。graph 处于依赖链末端，不向上导入。
- **检查点编译是临时的**：`propagate()` 开始时编译带 checkpointer 的图，结束时重新编译无 checkpointer 的版本。`_checkpointer_ctx` 用上下文管理器确保 SQLite 连接关闭。
- **ToolNode 单一来源**：Market Analyst 的工具列表由 `market_analyst._build_market_tools()` 生成，`_create_tool_nodes()` 直接使用，保证 `bind_tools()` 和 ToolNode 始终同步。
- **记忆反思是延迟的**：当前运行的决策不会立即反思。下一次分析同 ticker 时，`_resolve_pending_entries()` 才获取已实现收益并生成反思。
- **`selected_analysts` 允许子集**：可只选 `["market", "news"]` 等，未选的分析师不进入图。

## 禁止事项

- 不要在 graph 模块中直接导入 `dataflows.interface` 以外的 dataflows 子模块 — 通过 `set_config()` 传递配置
- 不要修改 `_is_chinese_ticker()` 的检测逻辑时忘记同步 CLI 的 `_is_ashare_ticker()`
- 不要假设 `SignalProcessor` 调用 LLM — 它是确定性的，LLM 参数仅为向后兼容保留
- 不要在 `setup_graph()` 返回已编译的图 — 返回未编译的 `StateGraph`，由 `trading_graph.py` 按需编译（带或不带 checkpointer）
- 不要让 `selected_analysts` 为空列表 — `setup_graph()` 会抛出 `ValueError`
- 不要在 `propagate()` 的 `finally` 块中遗漏 checkpointer 清理 — SQLite 连接泄漏会锁文件
