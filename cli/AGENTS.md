# AGENTS.md — cli

基于 Typer + Rich 的交互式 TUI CLI，是多智能体交易框架的用户入口。一个 `@app.callback` + 四个 `@app.command`。

## 目录结构

```
cli/
├── main.py              # 入口：app = Typer(), 回调 + 4 个命令, MessageBuffer, 流式渲染, 直接模式
├── models.py            # AnalystType 枚举 (market/social/news/fundamentals)
├── utils.py             # questionary 交互提示：供应商、模型、分析师、日期、语言等
├── config.py            # CLI_CONFIG 常量：公告 URL、超时、降级文本
├── stats_handler.py     # StatsCallbackHandler — LLM/tool 调用计数 + token 统计
├── announcements.py     # fetch_announcements() / display_announcements() — tauric.ai API
└── static/
    └── welcome.txt      # ASCII art 横幅
```

## Typer 应用结构

| 注册方式 | 名称 | 说明 |
|---------|------|------|
| `@app.callback(invoke_without_command=True)` | `main()` | 全局入口。无子命令时进入分析流程。选项：`-t`, `-d`, `-p`, `--depth`, `-l`, `-a`, `-y`, `--checkpoint`, `--clear-checkpoints`, `--diag` |
| `@app.command()` | `screen()` | OpenCLI 候选股筛选。选项：`-s`（数据源）, `-m`（模式）, `-l`（数量）, `-f`（格式） |
| `@app.command()` | `market()` | OpenCLI 命令透传。参数：`site`, `command`, `extra_args`。选项：`-f`, `-l`, `-v` |
| `@app.command()` | `report()` | 报告目录 → Word 文档。参数：`report_dir`。选项：`-o`, `-t`, `-d` |
| `@app.command()` | `qlib()` | Qlib 数据转换。参数：`action`（scan/convert/backfill-signals/bulk-download/dolt-push）。选项：`-t`, `-o`, `--with-signals`, `--freq`, `--no-push`, `--chunk-size`, `--keep-tmp` |

## 两种执行模式

**交互式 TUI**：不传 `-t` 时触发。8 步引导式输入（见下），然后用 Rich `Live` + `Layout` 流式渲染分析过程。

**直接模式**：传入 `-t ticker` 触发。流程：`-t` → `_build_selections_from_args()` → `_run_headless()` → `graph.propagate()` → 文本输出。`-y` 时自动保存，无任何交互提示。未指定的选项从 `_PROVIDER_DEFAULTS` 表按环境变量自动推断。

## 交互式 8 步流程（`get_user_selections()`）

1. Ticker（支持 A 股自动检测）
2. 分析日期
3. 输出语言
4. 选择分析师（多选）
5. 研究深度（1/3/5 轮）
6. LLM 供应商
7. 快速/深度思考模型
8. 供应商特有配置（OpenAI reasoning effort / Gemini thinking / Anthropic effort）

A 股 ticker 在步骤 1 后自动触发 OpenCLI 市场快照面板（`_show_opencli_snapshot`）。

## MessageBuffer 类

TUI 的中心状态容器，管理分析过程中的所有展示状态。

- `messages` / `tool_calls`：`deque(maxlen=100)` 有界队列
- `agent_status`：`{agent_name: pending|in_progress|completed}` 字典，按 `PIPELINE_ORDER` 顺序推进
- `report_sections`：7 个报告段（`REPORT_SECTIONS` 定义），按选中分析师动态过滤
- `completion_times`：每个智能体首次产出时的 `time.time()`，用于计算阶段耗时
- `report_summaries` / `section_order`：流式报告展示优化，已完成段显示摘要，活跃段显示最新内容
- `get_completed_reports_count()`：仅当报告段有内容 **且** 对应 finalizing agent 已 completed 才计数
- `get_agent_duration()` / `get_phase_durations()`：基于 wall-clock chaining 的耗时计算

## 流式显示布局

```
┌───────── header ──────────┐
├── progress ──┬── messages ─┤
│  (智能体状态) │  (消息/工具) │
├──────────────┴─────────────┤
│        analysis            │
│   (流式报告面板)             │
├──────── footer ────────────┤
│   统计: 智能体 | LLM | Tools │
│   Tokens | 报告 | 阶段 | 耗时 │
└────────────────────────────┘
```

`update_display()` 刷新全布局，节流间隔 1 秒（`_DISPLAY_THROTTLE`）防止闪烁。

## StatsCallbackHandler

`langchain_core.callbacks.BaseCallbackHandler` 子类，线程安全（`threading.Lock`）。

追踪 4 项指标：`llm_calls`、`tool_calls`、`tokens_in`、`tokens_out`。传入 `TradingAgentsGraph(callbacks=[stats_handler])`，LLM 和 ToolNode 执行时自动回调。Footer 面板实时展示。

## 环境变量加载策略

模块顶层执行，加载顺序：

1. `_CLI_ROOT/.env`（项目根目录，源码运行时生效）
2. `_CLI_ROOT/.env.enterprise`（企业版，`override=False`）
3. `CWD/.env`（回退，`pip install` 后从工作目录加载）
4. `CWD/.env.enterprise`（企业版回退）

`_CLI_ROOT = Path(__file__).resolve().parent.parent`，即项目根目录。每个路径去重检查（`resolve()` 比较），避免重复加载。

## A 股自动检测

`_is_ashare_ticker(ticker)` 匹配规则：
- `.SZ` / `.SH` / `.SS` 后缀 + 6 位数字前缀
- 纯 6 位数字（如 `000858`）
- 逗号分隔列表中任一匹配即返回 `True`
- 自动去除引号（`"002876.SZ","000062.SZ"`）

**必须与 `tradingagents/graph/trading_graph.py:_is_chinese_ticker()` 保持同步**。两处处理相同的输入格式。检测到 A 股后自动切换 `data_vendors` 为 `tencent_sina` + `akshare`。

## 直接模式默认值（`_PROVIDER_DEFAULTS`）

| 供应商 | 环境变量 | 快速模型 | 深度模型 |
|--------|---------|---------|---------|
| deepseek | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` | `deepseek-v4-pro` |
| openai | `OPENAI_API_KEY` | `gpt-5.4-mini` | `gpt-5.4` |
| google | `GOOGLE_API_KEY` | `gemini-3-flash-preview` | `gemini-3.1-pro-preview` |
| anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | `claude-opus-4-6` |
| xai | `XAI_API_KEY` | `grok-4-1-fast-non-reasoning` | `grok-4-0709` |
| qwen | `DASHSCOPE_API_KEY` | `qwen3.5-flash` | `qwen3.6-plus` |
| glm | `ZHIPU_API_KEY` | `glm-4.7` | `glm-5.1` |
| openrouter | `OPENROUTER_API_KEY` | `openai/gpt-5.4-mini` | `openai/gpt-5.4` |

`_get_default_provider()` 按表顺序扫描环境变量，第一个有 key 的供应商胜出。A 股 ticker 默认语言自动切换为 `Chinese`。

## 报告保存流程

`save_report_to_disk(final_state, ticker, save_path)` 输出目录结构：

```
{TICKER}_{timestamp}/
├── complete_report.md          # 合并报告
├── timing.json                 # 耗时统计（仅 TUI 模式）
├── 1_analysts/                 # market.md, sentiment.md, news.md, fundamentals.md
├── 2_research/                 # bull.md, bear.md, manager.md
├── 3_trading/                  # trader.md
├── 4_risk/                     # aggressive.md, conservative.md, neutral.md
└── 5_portfolio/                # decision.md
```

保存后自动尝试调用 `report_converter.convert_report_dir_to_docx()` 生成 Word 文档（best-effort，失败不阻塞）。

## 关键辅助函数

- `update_analyst_statuses()`：每轮 chunk 更新分析师状态，有报告=completed，第一个无报告=in_progress
- `classify_message_type()`：将 LangChain 消息分为 User/Agent/Data/Control 四类
- `_show_opencli_snapshot()`：A 股 ticker 输入后自动展示实时行情/资金/板块快照
- `_show_opencli_summary()`：分析完成后展示 OpenCLI 数据摘要
- `format_tool_args()`：工具参数截断到 80 字符用于终端展示

## 禁止事项

- 不要修改 `_is_ashare_ticker()` 时忘记同步 `trading_graph.py:_is_chinese_ticker()`
- 不要在 TUI 模式下使用阻塞式 `input()` 或 `print()`，会破坏 Rich Live 渲染
- 不要硬编码模型名称，应从 `_PROVIDER_DEFAULTS` 或 `model_catalog.get_model_options()` 获取
- 不要在 `utils.py` 的 questionary 函数中使用 `exit()` 以外的退出方式（已被主流程依赖）
- 不要假设 `opencli` 已安装，所有 OpenCLI 调用必须先检查 `shutil.which("opencli")`
