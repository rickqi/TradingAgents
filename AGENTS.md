# AGENTS.md — TradingAgents

面向 AI Agent 的仓库速查手册。只写从文件名无法直接推断的关键信息。

## 项目概述

多智能体 LLM 金融交易框架（v0.2.4）。Python 包，基于 LangGraph 构建。研究用途，非投资建议。

## 安装与配置

```bash
python -m venv .venv          # 需要 Python >= 3.10，测试过 3.13
.venv\Scripts\activate        # Windows
pip install .                  # 复制到 site-packages；实际依赖在 pyproject.toml
```

- `requirements.txt` 内容就是 `.`——安装本地包。
- `uv.lock` 存在但不需要 uv，`pip install .` 即可。
- Docker: `docker compose run --rm tradingagents`（需要 `.env`）。
- 版本号定义在 `pyproject.toml` 第 7 行 `version = "0.2.4"`。

## 环境变量与 API Key

复制 `.env.example` → `.env`，至少填一个 LLM 供应商 key：

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=...
DASHSCOPE_API_KEY=...        # Qwen（阿里）
ZHIPU_API_KEY=...             # GLM（智谱）
OPENROUTER_API_KEY=...
ALPHA_VANTAGE_API_KEY=...     # 可选，alpha_vantage 数据源
TWELVE_DATA_API_KEY=...       # 可选，twelve_data 数据源（REST API，无需额外 pip 依赖）
TUSHARE_API_KEY=...           # 可选，tushare 数据源（需 pip install tushare，基础积分即可用日线行情）
```

企业版（Azure OpenAI）：复制 `.env.enterprise.example` → `.env.enterprise`。

CLI（`cli/main.py`）启动时调用 `load_dotenv()`，先从源码根目录加载（`_CLI_ROOT/.env`），再从当前工作目录加载作为回退（`pip install .` 后 `tradingagents` 命令的 `_CLI_ROOT` 指向 site-packages，需要 CWD 回退才能找到项目目录下的 `.env`）。

## 运行方式

**CLI（交互式 TUI）：**
```bash
tradingagents                   # pip install 后的命令（analyze 是默认子命令）
python -m cli.main              # 从源码直接运行，无需安装
tradingagents --checkpoint      # SQLite 断点续跑
tradingagents --clear-checkpoints
tradingagents --diag            # 诊断模式：写入 .cli_diag.log 执行追踪
tradingagents report <DIR>      # 从分析结果生成 Word 报告
tradingagents qlib scan         # 扫描已缓存的 OHLCV 数据
tradingagents qlib convert      # 缓存 → Qlib 二进制格式
tradingagents qlib convert --with-signals  # 含 AI 信号
tradingagents qlib backfill-signals        # JSON 日志 → 信号文件
tradingagents qlib bulk-download           # 批量下载 A 股 OHLCV（腾讯 K 线 API）
tradingagents qlib bulk-download -t 000858.SZ,600519.SH  # 指定股票下载
tradingagents qlib dolt-push              # 缓存 → DoltHub 推送
tradingagents qlib dolt-push --no-push    # 仅本地提交
```

**CLI（直接模式，跳过交互提示）：**
```bash
tradingagents -t 000858.SZ                                # 最简：只传 ticker
tradingagents -t NVDA -d 2026-01-15                       # 指定日期
tradingagents -t 000858 -p deepseek --depth 2             # 指定供应商和深度
tradingagents -t 000858 -l Chinese -y                     # 自动保存，无交互提示
python -m cli.main -t 000858.SZ -y                        # 源码直接运行
```
直接模式选项：`-t/--ticker`、`-d/--date`、`-p/--provider`、`--depth`、`-l/--lang`、`-a/--analysts`、`-y/--yes`。不传 `-t` 时进入交互式 TUI。

**Python API：**
```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()  # 安全：每次获取独立深拷贝
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-v4-pro"
config["quick_think_llm"] = "deepseek-v4-flash"

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

**scripts/ 分析工具**（从项目根目录运行）：
```bash
python scripts/run_single.py 002460 --date 2026-05-02    # 单股分析
python scripts/run_a_share.py 600519.SH 2026-04-30       # A 股（tencent_sina）
python scripts/run_batch.py --stocks 600519.SH 000858.SZ --date 2026-05-09 --provider deepseek  # 批量（断点续跑）
python scripts/batch_analyze.py 002876 000062 ...          # 批量 + 报告
python scripts/turnover_screener.py --analyze 5            # 换手率筛选
python scripts/test_datasource.py                          # API 连通性测试
python scripts/smoke_structured_output.py deepseek          # 结构化输出冒烟测试
```

**融合预测全流程**（Qlib + TradingAgents → 21 股 × 20 天价格预测）：
```bash
# 一键运行（推荐并行 2 组）
python D:\codes\stock\docs\scripts\run_full_pipeline.py --parallel 2

# 仅重新预测（跳过 TA 分析）
python D:\codes\stock\docs\scripts\run_full_pipeline.py --skip-ta
```
详见 `docs/scripts/README.md`。

## 测试

```bash
pip install pytest                # 不在 pyproject 依赖中，需手动安装
pytest                            # 运行全部（标记：unit, integration, smoke）
pytest -m unit                    # 仅快速隔离测试
pytest tests/test_model_validation.py  # 单文件
```

- `tests/conftest.py` 通过 `monkeypatch` 自动填充占位 API key——无需真实凭证即可运行测试套件。
- 仓库中没有 linter/formatter/typecheck 配置。

## 架构

```
tradingagents/
├── graph/            # LangGraph 编排层
│   ├── trading_graph.py   # TradingAgentsGraph — 主入口类
│   ├── setup.py           # GraphSetup — 构建 LangGraph StateGraph
│   ├── propagation.py     # Propagator — 状态初始化、图参数、递归限制
│   ├── signal_processing.py  # SignalProcessor — 从 PM 输出提取评级
│   ├── conditional_logic.py  # 辩论轮次控制
│   ├── checkpointer.py       # SQLite 断点续跑
│   └── reflection.py         # 基于记忆日志的历史决策反思
├── agents/                 # → 详见 tradingagents/agents/AGENTS.md
│   ├── analysts/      # 市场、社交、新闻、基本面（4 个分析师）
│   ├── researchers/   # 看多、看空（辩论），Research Manager（结构化输出）
│   ├── trader/        # Trader（结构化输出 — 3 级 Buy/Hold/Sell）
│   ├── managers/      # Research Manager, Portfolio Manager（5 级评级）
│   ├── risk_mgmt/     # 激进、保守、中性（3 个风险辩论者）
│   ├── schemas.py     # 结构化输出的 Pydantic schema
│   └── utils/         # agent_states, agent_utils, memory, structured.py
├── dataflows/              # → 详见 tradingagents/dataflows/AGENTS.md
│   ├── interface.py   # 供应商路由 — VENDOR_METHODS, route_to_vendor() 带降级链
│   ├── config.py      # set_config() — 模块级单例，.update() 合并
│   ├── y_finance.py   # yfinance 实现
│   ├── yfinance_news.py
│   ├── tencent_sina.py   # A 股：腾讯 K 线 + 新浪行情 + 东方财富 API
│   ├── akshare_vendor.py # A 股：AKShare — 内幕交易、情绪、个股财报
│   ├── twelve_data.py    # Twelve Data — REST API，9 个方法（无需额外 pip 依赖）
│   ├── tushare.py        # Tushare Pro — REST API，6 个方法（需 pip install tushare）
│   ├── opencli_vendor.py # A 股：OpenCLI — 11 个扩展数据函数（可选，需 npm install）
│   └── alpha_vantage*.py # Alpha Vantage 实现
├── llm_clients/       # 多供应商 LLM 抽象层 → 详见 tradingagents/llm_clients/AGENTS.md
│   ├── factory.py     # create_llm_client() — 懒加载
│   ├── base_client.py # BaseLLMClient, normalize_content(), DSML token 清理
│   ├── openai_client.py  # OpenAI + 所有 OpenAI 兼容供应商；DeepSeekChatOpenAI 子类
│   ├── anthropic_client.py
│   ├── google_client.py
│   ├── azure_client.py
│   └── model_catalog.py  # CLI 模型选择菜单（MODEL_OPTIONS 字典）
├── qlib/              # Qlib 数据转换与信号提取（无需 qlib 依赖）
│   ├── ticker_mapper.py    # ticker 双向转换：TradingAgents ↔ Qlib instrument
│   ├── cache_scanner.py    # 扫描 ~/.tradingagents/cache/ 发现 OHLCV 文件
│   ├── converter.py        # OHLCV DataFrame → Qlib 二进制（calendars/instruments/features）
│   ├── signal_extractor.py # 从 JSON logs 提取 AI 信号（ai_score, trader_action 等）
│   ├── bulk_downloader.py  # 批量下载 A 股 OHLCV（腾讯 K 线 API，自动速率控制）
│   └── dolt_publisher.py   # 缓存 → DoltHub 推送（dolt CLI，版本化 SQL 数据库）
└── default_config.py  # DEFAULT_CONFIG 字典 — 所有可调参数

cli/                   # 交互式 TUI（Typer + Rich）
  ├── main.py          # 入口：app = Typer(), @app.command() analyze
  ├── models.py        # AnalystType 枚举
  ├── utils.py         # TUI 提示：供应商/模型选择
  ├── config.py        # CLI 配置工具
  ├── stats_handler.py # 每智能体耗时统计回调
  └── announcements.py # 启动公告获取

scripts/               # 用户分析工具（不是 Python 包，无 __init__.py）
  ├── _share_config.py       # 共享：Windows UTF-8 修复, build_ashare_config(), 初始化辅助
  ├── run_single.py           # 单股分析（通用）
  ├── run_a_share.py          # 单只 A 股分析
  ├── run_batch.py            # 顺序批量 + --start-from 断点续跑
  ├── batch_analyze.py        # 批量 + 每股 MD/DOCX 报告 + 汇总
  ├── turnover_screener.py    # 东方财富换手率筛选 + 分析
  ├── test_datasource.py      # A 股 API 连通性测试（独立）
  ├── generate_report_from_log.py  # 从保存的 JSON 状态重新生成报告
  └── smoke_structured_output.py   # 按供应商的结构化输出冒烟测试
```

### 智能体流水线

1. **分析师团队**：市场 → 社交 → 新闻 → 基本面 — 各自使用 LangGraph ToolNode 获取数据
2. **研究团队**：看多 vs 看空研究员辩论（N 轮），然后 Research Manager 生成结构化 `ResearchPlan`
3. **交易员**：阅读研究计划 + 分析师报告 → 结构化 `TraderProposal`（Buy/Hold/Sell）
4. **风险管理**：激进/保守/中性辩论者评估
5. **投资组合经理**：最终结构化 `PortfolioDecision`（5 级：Buy/Overweight/Hold/Underweight/Sell）

### 关键设计决策

- **双 LLM 模式**：`deep_think_llm` 用于复杂推理（Research Manager, Portfolio Manager），`quick_think_llm` 用于其余所有。两者来自同一供应商。
- **结构化输出带优雅降级**：Research Manager、Trader、PM 使用 `bind_structured()`/`invoke_structured_or_freetext()` → 成功时 Pydantic schema，失败时自由文本 + DSML 清理。
- **供应商抽象带降级链**：逗号分隔的供应商字符串，工具级覆盖。
- **记忆日志**：持久化在 `~/.tradingagents/memory/trading_memory.md`。下次分析同 ticker 时自动解析历史决策和已实现收益。
- **LLM 客户端工厂**：`create_llm_client()` 懒加载供应商模块。DeepSeek 有专门的 `DeepSeekChatOpenAI` 子类处理 thinking mode 往返。
- **递归限制**：`max_recur_limit`（默认 250）设置 LangGraph 的 `recursion_limit`。
- **无循环导入**：干净的 DAG：`default_config ← dataflows.config ← interface ← agent tools ← agents ← graph`。
- **`output_language` 只影响用户可见报告**（4 个分析师 + Portfolio Manager）。内部辩论（研究员、风险辩论者）保持英文以确保推理质量。

## 配置（DEFAULT_CONFIG 键）

| 键 | 默认值 | 说明 |
|---|---|---|
| `llm_provider` | `"openai"` | `openai`, `google`, `anthropic`, `xai`, `deepseek`, `qwen`, `glm`, `openrouter`, `ollama`, `azure` |
| `deep_think_llm` | `"gpt-5.4"` | 复杂推理用模型 |
| `quick_think_llm` | `"gpt-5.4-mini"` | 快速任务用模型 |
| `backend_url` | `None` | None 时各供应商使用自己的默认端点。仅在需要自定义代理时设置。 |
| `max_debate_rounds` | `1` | 研究辩论轮次 |
| `max_risk_discuss_rounds` | `1` | 风险辩论轮次 |
| `max_recur_limit` | `250` | LangGraph 递归限制 |
| `checkpoint_enabled` | `False` | 每个节点后 SQLite 断点保存 |
| `output_language` | `"English"` | 报告语言（内部辩论保持英文） |
| `data_vendors` | 各项 `"twelve_data,yfinance"` | 按类别覆盖。选项：`yfinance`, `alpha_vantage`, `tencent_sina`, `akshare`, `twelve_data`, `tushare`。支持逗号分隔降级链。`sentiment_data` 默认 `"akshare"`，`opencli_market` 默认 `"opencli"`。 |
| `tool_vendors` | `{}` | 按工具覆盖，优先级高于 `data_vendors` |

环境变量覆盖：`TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`。

## 数据供应商

7 个供应商（`yfinance`, `alpha_vantage`, `tencent_sina`, `akshare`, `twelve_data`, `tushare`, `opencli`），覆盖 10 个核心工具方法 + 5 个 OpenCLI 扩展方法。支持逗号分隔降级链（如 `"tencent_sina,tushare,akshare"` 或 `"twelve_data,yfinance"`）。

| 供应商 | 类型 | pip 依赖 | API Key | 覆盖方法 | 说明 |
|---|---|---|---|---|---|
| `yfinance` | 西方 | 无 | 无 | 7 | 默认降级备选 |
| `alpha_vantage` | 西方 | 无 | `ALPHA_VANTAGE_API_KEY` | 9 | 免费版 5次/分 |
| `twelve_data` | 西方 | 无（用 requests） | `TWELVE_DATA_API_KEY` | 9 | REST API，免费版 8 credits/分 |
| `tencent_sina` | A 股 | 无 | 无 | 9 | 腾讯 K 线 + 新浪 + 东方财富 |
| `akshare` | A 股 | akshare | 无 | 8 | 唯一支持 `get_sentiment` |
| `tushare` | A 股 | tushare | `TUSHARE_API_KEY` | 6 | 日线行情 + PE/PB/市值 + 财务报表 |
| `opencli` | A 股扩展 | 无（需 npm） | 无 | 5 | 不走 VENDOR_METHODS 路由 |
| `astock` | A 股增强 | 无（纯 Python） | 无 | 10 | a-stock-data V2.1，不走 VENDOR_METHODS 路由 |

供应商路由规则：
- `_CHINESE_VENDORS = {tencent_sina, akshare, tushare}` — A 股模式时排除西方供应商
- `_WESTERN_VENDORS = {yfinance, alpha_vantage, twelve_data}` — 西方模式时排除 A 股供应商
- `opencli` 不参与自动路由，由 `agents/utils/opencli_tools.py` 直接调用

### tushare 特性

- 条件导入（`try: import tushare`），未安装时返回错误字符串，降级链自动尝试下一个供应商
- 代码格式：`ts_code` = `000858.SZ`（6位代码 + 交易所后缀），`_normalize_to_ts_code()` 负责转换
- `get_stock_data`：`pro.daily()` + `pro.adj_factor()`，前复权 Adj Close，成交量 手→股（×100）
- `get_indicators`：`pro.daily_basic()` — PE/PB/PS/换手率/量比/市值（需 ≥2000 积分）
- `get_fundamentals`：`pro.fina_indicator()` — ROE/毛利率/BPS/EPS
- `get_income_statement`/`get_balance_sheet`/`get_cashflow`：标准财务报表（需 ≥2000 积分）
- 限速：统一 rate limiter（0.3s 间隔，120次/分钟）

详见 `tradingagents/dataflows/AGENTS.md`。

## DeepSeek 模型说明

- `deepseek-v4-pro` — 旗舰，thinking mode，支持 Tool Calls + thinking mode 下的 `tool_choice`
- `deepseek-v4-flash` — 快速，thinking mode，支持 Tool Calls + thinking mode 下的 `tool_choice`
- `deepseek-reasoner` — **已过时**（2026-07-24 退休），不支持 `tool_choice`。`with_structured_output()` 抛出 `NotImplementedError`；智能体工厂自动降级为自由文本。
- `deepseek-chat` — **已过时**（2026-07-24 退休），映射到 `deepseek-v4-flash`
- Thinking mode 返回 `reasoning_content` 字段，后续 tool-call 轮次必须回传（由 `openai_client.py` 中的 `DeepSeekChatOpenAI` 子类处理）。
- Thinking mode 忽略 `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`。
- 内部 thinking token（`<｜DSML｜>`）有时泄漏到 content 中——由 `base_client.py` 和 `structured.py` 中的 `_strip_dsml_tokens()` 清理。

## Windows 注意事项

- 所有文件 I/O 使用显式 `encoding="utf-8"`（v0.2.4 修复 cp1252 错误）。
- 含特殊字符（`.`、`-`）的 ticker 通过 `safe_ticker_component()` 清理后用于文件路径。
- `scripts/_share_config.py` 导入时自动将 stdout/stderr 修复为 UTF-8。
- **`debug=True` 的 pretty_print() 在 GBK 控制台上可能崩溃**（LLM 返回 emoji 时）——`trading_graph.py:438` 有 `try/except UnicodeEncodeError` 降级。如反复崩溃，设置 `PYTHONIOENCODING=utf-8` 运行。

## ⚠️ pip install . vs python -m cli.main（关键）

- `pip install .` 将源码复制到 `site-packages`——修改项目源码后不会生效，除非重新安装。
- `python -m cli.main` 从项目根目录运行，加载的是**项目源码**（因为 `.` 在 `sys.path` 上）。绕过已安装的副本。
- **修改代码后，始终用 `python -m cli.main` 测试**，或每次修改后重新 `pip install .`。
- 必须先激活 `.venv` 再 `pip install .`，否则会安装到系统 Python 的用户目录。

## A 股自动检测

CLI 和 `TradingAgentsGraph` 都会自动检测 A 股 ticker 并切换数据供应商为 `tencent_sina` + `tushare` + `akshare`。检测支持：
- 纯 6 位数字：`002876`, `600519`
- 带交易所后缀：`002876.SZ`, `603208.SH`
- 逗号分隔列表：`002876.SZ,000062.SZ,603208.SH`
- 带引号输入：`"002876.SZ","000062.SZ"`（自动去除引号）

检测发生在两处：`cli/main.py:_is_ashare_ticker()`（CLI）和 `tradingagents/graph/trading_graph.py:_is_chinese_ticker()`（图）。两处必须处理相同的输入格式。

中文模式激活时，`route_to_vendor()` 从降级链中排除 `yfinance`、`alpha_vantage` 和 `twelve_data`。

## scripts/ 导入机制

`scripts/` **没有 `__init__.py`**——不是 Python 包。两种导入模式并存：

- **裸导入**（`from _share_config import ...`）：`run_a_share.py`, `run_batch.py`, `batch_analyze.py`, `turnover_screener.py`。Python 将脚本所在目录加入 `sys.path`，所以能找到同目录的模块。从项目根运行：`python scripts/run_a_share.py ...`
- **包相对导入**（`sys.path.insert(0, project_root)` + `from scripts._share_config import ...`）：仅 `run_single.py`。
- **独立脚本**（无 `_share_config`）：`test_datasource.py`, `smoke_structured_output.py`, `generate_report_from_log.py`。

## DEFAULT_CONFIG 的深拷贝保护

`default_config.py` 使用 `_SafeConfigModule` 替换模块自身——每次访问 `DEFAULT_CONFIG` 都返回一个**独立的深拷贝**。所以 `config = DEFAULT_CONFIG.copy()` 是安全的（即使 `.copy()` 是浅拷贝，拿到的源本身就是新的深拷贝）。这修复了旧版本中嵌套 dict（如 `data_vendors`）被意外共享的问题。

## 开发约定

- **智能体工厂**：每个智能体模块导出 `create_*` 函数，接收 LLM 并返回可调用节点函数。新增智能体遵循此模式。
- **Pydantic schema**：新增结构化输出智能体 → 在 `schemas.py` 添加 schema 及 render helper。
- **数据工具**：新增数据源 → 在 `dataflows/interface.py` 的 VENDOR_METHODS 字典添加供应商方法，然后在 `trading_graph.py` 的相应 ToolNode 中注册。
- **新增数据供应商**：创建 `vendor_name.py`，实现所需方法（签名与现有供应商一致）。在 `interface.py` 中导入并注册到 VENDOR_METHODS + VENDOR_LIST。如是 A 股供应商，加入 `_CHINESE_VENDORS`。如是可选 pip 依赖，用条件导入（`try: import xxx`）。
- **新增 LLM 供应商**：OpenAI 兼容的加到 `openai_client.py` 的 `_PROVIDER_CONFIG`；不兼容的新建客户端文件到 `llm_clients/`。在 `factory.py` 注册，在 `model_catalog.py` 添加模型。
- **配置传递**：不要直接编辑 `dataflows/config.py`——使用 `set_config()` 或传 config 给 `TradingAgentsGraph()`。
- **供应商方法错误处理**：所有方法用 try/except 包裹，失败时返回 `"Error ..."` 字符串（不抛异常），让 `route_to_vendor()` 降级链自动尝试下一个供应商。

## 禁止事项

- 不要在使用非 OpenAI 供应商时将 `backend_url` 设为 OpenAI URL（每个供应商有自己的默认端点）。
- 不要用 `deepseek-reasoner` 做结构化输出——它不支持 `tool_choice`。用 `deepseek-v4-pro` 或 `deepseek-v4-flash`。
- 不要直接编辑 `dataflows/config.py`——用 `set_config()` 或传 config 给 `TradingAgentsGraph()`。
- 不要用 `as any`、`@ts-ignore` 或空 catch 块压制类型错误。
- 不要忘记在通过 `tradingagents` 命令测试时代码修改后重新 `pip install .`（用 `python -m cli.main` 则不需要）。
- 不要使用旧的 `ta2qlib.py` 或 `csv_to_qlib_bin.py`——已删除，统一用 `tradingagents qlib` 命令。
- 不要在供应商方法中抛异常——返回错误字符串，让 `route_to_vendor()` 降级链处理。
- 不要把 `tushare` 加到 `pyproject.toml` 依赖——使用条件导入（`try: import tushare`）。

## Qlib 数据转换

`tradingagents/qlib/` 模块将已缓存的 OHLCV 数据和 AI 分析信号转换为 Qlib 二进制格式，用于量化模型训练和回测。**无需安装 qlib 依赖**——转换使用纯 numpy 写入 Qlib 兼容的二进制文件。

旧的独立脚本 `ta2qlib.py`、`csv_to_qlib_bin.py` 和 `qlib_csv_output/` 目录已删除——统一使用 `tradingagents qlib` 命令。

### CLI 用法

```bash
tradingagents qlib scan                              # 查看缓存状态
tradingagents qlib scan -t 000858.SZ                 # 指定股票
tradingagents qlib convert                           # 全部缓存 → Qlib 二进制
tradingagents qlib convert -t 000858.SZ,600036.SH    # 指定股票
tradingagents qlib convert --with-signals             # 含 AI 分析信号
tradingagents qlib convert -o /path/to/output         # 自定义输出目录
tradingagents qlib backfill-signals                   # JSON 日志 → 信号文件
tradingagents qlib bulk-download                      # 全市场 A 股（跳过已缓存）
tradingagents qlib bulk-download -t 000858.SZ,600519.SH  # 指定股票下载
tradingagents qlib dolt-push                          # 全部缓存 → DoltHub
tradingagents qlib dolt-push -t 000858.SZ             # 指定股票推送
tradingagents qlib dolt-push --no-push                # 仅本地提交，不推送
```

### Python API

```python
from tradingagents.qlib.converter import QlibConverter
from tradingagents.qlib.signal_extractor import extract_from_state, batch_extract_from_logs

# 转换缓存数据
converter = QlibConverter("~/.qlib/qlib_data/cn_data", freq="day")
result = converter.convert_from_cache(tickers=["000858.SZ"])
print(result.num_instruments, result.feature_names)

# 提取 AI 信号（从 propagate() 返回值）
state, decision = ta.propagate("000858.SZ", "2026-05-06")
signals = extract_from_state(state)
# signals = {"date": "2026-05-06", "symbol": "SZ000858", "ai_score": 2, ...}

# 批量从 JSON 日志提取
signals_df = batch_extract_from_logs()  # 扫描 ~/.tradingagents/logs/
```

### 数据流

```
东方财富 API / 指定列表       →  bulk_download  →  ~/.tradingagents/cache/
  全市场 A 股代码                                    {TICKER}-Tencent-data-*.csv
  (腾讯 K 线 API, 自动速率控制)                       (OHLCV + Adj Close)

~/.tradingagents/cache/              →  QlibConverter  →  ~/.qlib/qlib_data/tradingagents/
  {TICKER}-Tencent-data-*.csv           calendars/day.txt
  {TICKER}-YFin-data-*.csv              instruments/all.txt
  {TICKER}-AKShare-data-*.csv           features/{inst_lower}/{field}.day.bin

~/.tradingagents/logs/               →  signal_extractor  →  ~/.qlib/qlib_data/tradingagents_signals.parquet
  {TICKER}/TradingAgentsStrategy_logs/     (date, symbol, ai_score, ...)
    full_states_log_{date}.json

~/.tradingagents/cache/              →  dolt_push  →  DoltHub (rickqi/tradingagents)
  去重后每只股票取最佳文件                  a_stock_eod_price (日 OHLCV + Adj Close)
                                          trade_calendar   (交易日历)
                                          stock_list       (标的列表+起止日期)
```

默认输出目录：`~/.qlib/qlib_data/tradingagents/`（可通过 `-o` 覆盖）。Qlib 加载时使用 `qlib.init(provider_uri="~/.qlib/qlib_data/tradingagents", region="cn")`。

### Qlib 二进制格式

- 每个 `.bin` 文件：`float32` 小端序数组，首个值为全局日历索引，其余为特征值
- 列名映射：`Open→open, High→high, Low→low, Close→close, Volume→volume, Adj Close→factor`
- `factor = Adj Close / Close`（tencent_sina 为 1.0）
- 停牌日自动 NaN（对齐全局日历后缺失日期为 NaN）
- 标的格式：`SH600519`、`SZ000858`（大写前缀 + 6 位代码），目录名小写

### 信号字段

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `ai_score` | int (-2~+2) | Portfolio Manager | Buy=2, Overweight=1, Hold=0, Underweight=-1, Sell=-2 |
| `trader_action` | int (-1~+1) | Trader | Buy=1, Hold=0, Sell=-1 |
| `research_rating` | int (-2~+2) | Research Manager | 同 ai_score 量程 |
| `price_target` | float | Portfolio Manager | 目标价（可能为 NaN） |

### `--with-signals` 注意事项

- `converter.py` 的 `extra_features` 匹配需要同时尝试 TradingAgents 格式（`688041.SH`）和 Qlib 格式（`SH688041`）作为 key — `signal_extractor` 返回的是 Qlib 格式，缓存文件用的是 TradingAgents 格式。
- AI 信号只在运行过分析的那天有值，其余日期为 NaN。`--with-signals` 不做前向填充。
- 多 ticker 分析（如 `SH600050,00762.HK`）会在 JSON log 的 `company_of_interest` 中产生逗号分隔值，导致 `symbol` 列出现合并符号——这是数据质量问题，不是 bug。

### 缓存去重机制

`converter.py` 和 `dolt_publisher.py` 都会自动去重缓存文件：

- **问题**：同一股票可能有多份缓存（`688256` 无后缀 vs `688256.SH` 有后缀；不同下载日期产生不同行数）。
- **策略**：按 Qlib instrument（`SH688256`）分组，选行数最多的文件；行数相同时选 `date_end` 最新的。
- **代码位置**：`converter.py` L133-142 和 `dolt_publisher.py` `_deduplicate_cache()`。

### 批量下载（bulk-download）

- `bulk_downloader.py` 使用腾讯 K 线 API 下载 OHLCV，自动速率控制（批次间暂停 10s）。
- `fetch_stock_universe()` 从东方财富 API 获取全市场 A 股代码列表。
- 下载结果保存到 `~/.tradingagents/cache/`，格式与正常分析缓存一致（`{TICKER}-Tencent-data-{start}-{end}.csv`）。
- `skip_existing=True` 时跳过已缓存股票（按 ticker 匹配）。

### DoltHub 推送（dolt-push）

- `dolt_publisher.py` 直接从缓存 CSV 读取（**不需要先 Qlib 转换**），去重后生成 CSV，通过 `dolt` CLI 推送到 `rickqi/tradingagents`。
- **前置条件**：`winget install DoltHub.Dolt` + `dolt login`。
- **推送流程**：`dolt clone` → 创建表（显式 schema）→ `dolt table import -u` → `dolt commit` → `dolt push`。
- **DoltHub 表结构**：
  - `a_stock_eod_price`（PK: `tradedate, symbol`）：日 OHLCV + `adjclose` + `vendor`
  - `trade_calendar`（PK: `trade_date`）：交易日历
  - `stock_list`（PK: `symbol`）：标的列表 + 起止日期 + vendor
- `dolt log --format=%H` 不受支持（与 git 不同）——代码中通过解析 `dolt log -n 1` 输出获取 commit hash，并用 `re.sub` 清理 ANSI 转义码。
- `BulkDownloadResult` 是 `@dataclass`，`downloaded`/`skipped`/`failed` 初始化时必须全部传入（无默认值）。
