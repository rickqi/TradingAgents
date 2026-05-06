<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents：多智能体 LLM 金融交易框架

## 更新动态

- [2026-05] Fork 源项目增加对 **A 股支持** — 完整的 A 股市场分析，集成 tencent_sina/akshare 数据供应商，增加[OpenCLI](https://www.npmjs.com/package/@jackwener/opencli) （需安装OpenCLI）提供 11 个数据工具（行情、K 线、资金流向、北向资金、板块、龙虎榜、热搜、指数面板、快讯、持仓、公告），支持中文股票代码自动识别、每个智能体的耗时统计面板、CLI 直接模式（`-t ticker` 跳过交互提示）、`screen` 候选股筛选和 `market` 实时数据命令，以及 CLI 中的流式报告展示。

  ![1778045286797.png](assets/README/1778045286797.png)

  ![1778045422170.png](assets/README/1778045422170.png) ![1778045422167.png](assets/README/1778045422167.png) ![1778045422168.png](assets/README/1778045422168.png) ![1778045422169.png](assets/README/1778045422169.png)
- [2026-04] **TradingAgents v0.2.4** 发布，新增结构化输出智能体（Research Manager、Trader、Portfolio Manager）、LangGraph 检查点恢复、持久化决策日志、DeepSeek/Qwen/GLM/Azure 供应商支持、Docker 支持，以及 Windows UTF-8 编码修复。完整更新列表见 [CHANGELOG.md](CHANGELOG.md)。
- [2026-03] **TradingAgents v0.2.3** 发布，新增多语言支持、GPT-5.4 系列模型、统一模型目录、回测日期精度，以及代理支持。
- [2026-03] **TradingAgents v0.2.2** 发布，新增 GPT-5.4/Gemini 3.1/Claude 4.6 模型覆盖、五级评级体系、OpenAI Responses API、Anthropic effort control，以及跨平台稳定性改进。
- [2026-02] **TradingAgents v0.2.0** 发布，新增多供应商 LLM 支持（GPT-5.x、Gemini 3.x、Claude 4.x、Grok 4.x）和改进的系统架构。
- [2026-01] **Trading-R1** [技术报告](https://arxiv.org/abs/2509.11420) 发布，[Terminal](https://github.com/TauricResearch/Trading-R1) 即将上线。

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

> 🎉 **TradingAgents** 正式发布！我们收到了大量关于这项工作的咨询，感谢社区的广泛关注与热情。
>
> 因此我们决定将框架完全开源。期待与大家一起打造有影响力的项目！

<div align="center">

🚀 [TradingAgents 框架](#tradingagents-framework) | ⚡ [安装与 CLI](#installation-and-cli) | 🎬 [演示](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [包使用](#tradingagents-package) | 🤝 [贡献](#contributing) | 📄 [引用](#citation)

</div>

## TradingAgents 框架

TradingAgents 是一个多智能体交易框架，模拟了真实交易公司的运作方式。通过部署专业化的 LLM 智能体，从基本面分析师、情绪专家、技术分析师，到交易员和风险管理团队，平台协同评估市场状况并指导交易决策。此外，这些智能体通过动态讨论来确定最优策略。

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents 框架仅用于研究目的。交易表现可能因多种因素而异，包括所选的基础语言模型、模型温度、交易周期、数据质量以及其他非确定性因素。[本框架不构成金融、投资或交易建议。](https://tauric.ai/disclaimer/)

我们的框架将复杂的交易任务分解为专业化的角色。这确保了系统在市场分析和决策制定方面拥有稳健且可扩展的方法。

### 分析师团队

- 基本面分析师：评估公司财务状况和业绩指标，识别内在价值和潜在风险信号。
- 情绪分析师：使用情绪评分算法分析社交媒体和公众情绪，衡量短期市场情绪。
- 新闻分析师：监控全球新闻和宏观经济指标，解读事件对市场状况的影响。
- 技术分析师：运用技术指标（如 MACD 和 RSI）检测交易模式并预测价格走势。

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### 研究员团队

- 由看涨和看跌研究员组成，他们批判性地评估分析师团队提供的洞察。通过结构化的辩论，他们权衡潜在收益与固有风险。

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### 交易智能体

- 综合分析师和研究员的报告，做出明智的交易决策。它基于全面的市场洞察来确定交易的时机和规模。

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### 风险管理与投资组合经理

- 通过评估市场波动性、流动性及其他风险因素，持续评估投资组合风险。风险管理团队评估并调整交易策略，向投资组合经理提供评估报告以供最终决策。
- 投资组合经理批准或拒绝交易提案。如果批准，订单将发送到模拟交易所并执行。

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## 安装与 CLI

### 安装

克隆 TradingAgents：

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

在你喜欢的环境管理器中创建虚拟环境：

```bash
conda create -n tradingagents python=3.13
conda activate tradingagents
```

安装包及其依赖：

```bash
pip install .
```

### Docker

也可以使用 Docker 运行：

```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

使用 Ollama 运行本地模型：

```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### API Key 配置

TradingAgents 支持多个 LLM 供应商。设置你所选供应商的 API Key：

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen (Alibaba DashScope)
export ZHIPU_API_KEY=...           # GLM (Zhipu)
export OPENROUTER_API_KEY=...      # OpenRouter
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

对于企业级供应商（如 Azure OpenAI、AWS Bedrock），将 `.env.enterprise.example` 复制为 `.env.enterprise` 并填入你的凭证。

对于本地模型，在配置中将 `llm_provider` 设置为 `"ollama"`。

或者，将 `.env.example` 复制为 `.env` 并填入你的 Key：

```bash
cp .env.example .env
```

### CLI 使用

启动交互式 CLI：

```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```

你将看到一个界面，可以选择目标股票代码、分析日期、LLM 供应商、研究深度等。

CLI 会实时显示进度，包括每个智能体的耗时统计、流式报告以及底部的阶段级别分解。

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

界面会随着结果的加载实时展示，让你可以跟踪智能体的运行进度。

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

#### 直接模式（跳过交互提示）

通过命令行参数直接指定股票代码和分析配置，跳过交互式 TUI：

```bash
tradingagents -t 000858.SZ                                # 最简：只传 ticker
tradingagents -t NVDA -d 2026-01-15                       # 指定日期
tradingagents -t 000858 -p deepseek --depth 2             # 指定供应商和深度
tradingagents -t 000858 -l Chinese -y                     # 自动保存，无交互提示
python -m cli.main -t 000858.SZ -y                        # 源码直接运行
tradingagents -t ci -p deepseek --depth 3 -l Chinese -y   # 美股，看多/看空辩论 3 轮，报告输出中文（内部辩论仍英文），非交互模式，自动保存报告
```


| 参数           | 简写   | 说明                                                                                |
| -------------- | ------ | ----------------------------------------------------------------------------------- |
| `--ticker`   | `-t` | 股票代码（必填，传入后进入直接模式）                                                |
| `--date`     | `-d` | 分析日期（YYYY-MM-DD），默认今天                                                    |
| `--provider` | `-p` | LLM 供应商：deepseek, openai, google, anthropic, xai, qwen, glm, openrouter, ollama |
| `--depth`    |        | 研究深度/辩论轮次（1-3，默认 1）                                                    |
| `--lang`     | `-l` | 输出语言（English, Chinese 等）                                                     |
| `--analysts` | `-a` | 指定分析师（逗号分隔）：market,social,news,fundamentals                             |
| `--yes`      | `-y` | 非交互模式：自动保存报告并输出结果                                                  |

其他全局选项：`--checkpoint`（断点续跑）、`--clear-checkpoints`（重置检查点）、`--diag`（诊断模式，写入 `.cli_diag.log` 执行追踪）。

#### screen — 候选股筛选

使用 OpenCLI 从多个数据源筛选候选股票池（需已安装 opencli）：

```bash
# 涨跌幅排行（东方财富）
tradingagents screen --source eastmoney --mode rank --limit 20

# 主力资金流向
tradingagents screen -s eastmoney -m money-flow -l 10

# 板块排名
tradingagents screen -s eastmoney -m sectors

# 热度排行
tradingagents screen -s eastmoney -m hot -l 15
tradingagents screen -s tdx -m hot       # 通达信热度
tradingagents screen -s sinafinance -m rank  # 新浪涨跌排行
```

支持的筛选模式：

| 数据源          | 可用模式                       | 说明                                     |
| --------------- | ------------------------------ | ---------------------------------------- |
| `eastmoney`   | rank, money-flow, sectors, hot | 东方财富：涨跌排行、主力资金、板块、热度 |
| `sinafinance` | rank                           | 新浪财经：涨跌排行                       |
| `tdx`         | hot                            | 通达信：热度排行                         |
| `ths`         | hot                            | 同花顺：热度排行                         |

输出格式：`--format table`（默认）、`json`、`csv`、`markdown`。

#### market — 透传 OpenCLI 命令

直接调用任意 OpenCLI 金融数据命令，获取实时市场数据：

```bash
tradingagents market eastmoney quote 600519              # 实时行情
tradingagents market eastmoney kline 000858.SZ -f json   # K 线数据
tradingagents market eastmoney rank --limit 10           # 涨跌排行
tradingagents market eastmoney money-flow --limit 5      # 主力资金
tradingagents market eastmoney longhu 002876             # 龙虎榜
tradingagents market eastmoney northbound --limit 10     # 北向资金
tradingagents market tdx hot-rank --limit 10             # 热度排行
tradingagents market binance price BTCUSDT -f json       # 加密货币
```

选项：`--format/-f`（table/json/csv/markdown/yaml）、`--limit/-l`（返回数量）、`--verbose/-v`（显示详细输出）。

#### report — 生成 Word 报告

将已保存的分析结果目录（含 MD 文件）转换为专业 Word 文档：

```bash
tradingagents report reports/NVDA_20260115_120000
tradingagents report reports/NVDA_20260115_120000 -o analysis.docx
tradingagents report reports/000858_20260506_143000 -t 000858.SZ -d 2026-05-06
```

| 选项            | 说明                                                       |
| --------------- | ---------------------------------------------------------- |
| `report_dir`  | 报告目录路径（必需参数）                                   |
| `--output/-o` | 输出 .docx 路径（默认 `<report_dir>/综合分析报告.docx`） |
| `--ticker/-t` | 封面页股票代码（默认从目录名自动检测）                     |
| `--date/-d`   | 封面页分析日期（默认自动检测）                             |

### A 股市场支持

TradingAgents 开箱即支持 **A 股（中国股票市场）分析**。输入任意中文股票代码，无论是纯 6 位数字（`000858`）、带交易所后缀（`000858.SZ`、`603208.SH`），还是逗号分隔的列表，框架都会自动切换到 tencent_sina（腾讯 K 线 + 新浪行情 + 东方财富）和 akshare（基本面、情绪）数据源。

```bash
# 交互模式 — 在 CLI 中输入：
tradingagents         # then enter: 000858.SZ
python -m cli.main    # then enter: 600519

# 直接模式 — 命令行指定 ticker：
tradingagents -t 000858.SZ -y
tradingagents -t 600519 -p deepseek --depth 2 -l Chinese -y
```

```python
# 或通过 Python API：
config = DEFAULT_CONFIG.copy()
config["data_vendors"] = {
    "core_stock_apis": "tencent_sina",
    "fundamental_data": "tencent_sina,akshare",
    "news_data": "tencent_sina",
    "sentiment_data": "akshare",
}
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("000858.SZ", "2026-05-05")
```

### OpenCLI 集成（可选）

安装 [OpenCLI](https://www.npmjs.com/package/@jackwener/opencli) 可获得 11 个额外的 A 股数据工具，覆盖三个分析师：

```bash
npm install -g @jackwener/opencli
```

| Tool                 | Data Source            | Agent                | 说明                                            |
| -------------------- | ---------------------- | -------------------- | ----------------------------------------------- |
| `get_quote`        | eastmoney quote        | Market Analyst       | 实时行情：PE、PB、总市值、换手率等 16 个字段    |
| `get_kline`        | eastmoney kline        | Market Analyst       | K 线历史：可配置周期（日/周/月/分钟）和复权方式 |
| `get_money_flow`   | eastmoney money-flow   | Market Analyst       | 主力资金流向：机构净流入/流出                   |
| `get_northbound`   | eastmoney northbound   | Market Analyst       | 北向资金：沪港通/深港通外资流向                 |
| `get_sectors`      | eastmoney sectors      | Market Analyst       | 板块排名：行业/概念/地区多维度排序              |
| `get_longhu`       | eastmoney longhu       | Market Analyst       | 龙虎榜：异常机构交易活动（支持股票代码过滤）    |
| `get_hot_rank`     | tdx hot-rank           | Market Analyst       | 热门搜索排行：散户关注度                        |
| `get_index_board`  | eastmoney index-board  | Market Analyst       | 指数面板：沪深 300、上证 50、恒生、标普 500     |
| `get_kuaixun`      | eastmoney kuaixun      | Market + News        | 7×24 财经快讯：实时市场动态                    |
| `get_holders`      | eastmoney holders      | Fundamentals Analyst | 前十大机构持仓：仓位变动                        |
| `get_announcement` | eastmoney announcement | News Analyst         | 公司公告：交易所官方披露                        |

分析 A 股股票代码时，11 个工具会自动激活。如果未安装 OpenCLI，它们会被静默跳过。除了 `npm install` 之外，无需任何额外配置。

## TradingAgents 包

### 实现细节

我们基于 LangGraph 构建 TradingAgents，以确保灵活性和模块化。框架支持多个 LLM 供应商：OpenAI、Google、Anthropic、xAI、DeepSeek、Qwen（阿里 DashScope）、GLM（智谱）、OpenRouter、Ollama（本地模型），以及 Azure OpenAI（企业级）。

### Python 使用

要在代码中使用 TradingAgents，你可以导入 `tradingagents` 模块并初始化一个 `TradingAgentsGraph()` 对象。`.propagate()` 函数将返回一个决策结果。你可以运行 `main.py`，这里也有一个简单的示例：

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# 前向传播
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

你还可以调整默认配置来设置自己选择的 LLM、辩论轮数等。

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # openai, google, anthropic, xai, deepseek, qwen, glm, openrouter, ollama, azure
config["deep_think_llm"] = "gpt-5.4"     # 用于复杂推理的模型
config["quick_think_llm"] = "gpt-5.4-mini" # 用于快速任务的模型
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

查看 `tradingagents/default_config.py` 了解所有配置选项。

### 配置与定制

TradingAgents 通过 `DEFAULT_CONFIG` 字典提供灵活的配置能力。所有配置均通过 Python API 传入，CLI 模式下会自动交互式选择。

#### LLM 供应商与模型选择

框架采用**双模型架构**：复杂推理（Research Manager、Portfolio Manager）使用 `deep_think_llm`，其余智能体使用 `quick_think_llm`，两者来自同一供应商。

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"              # 供应商选择
config["deep_think_llm"] = "deepseek-v4-pro"     # 复杂推理模型
config["quick_think_llm"] = "deepseek-v4-flash"  # 快速任务模型
config["backend_url"] = None                     # None = 使用供应商默认端点
```

支持的供应商：`openai`, `google`, `anthropic`, `xai`, `deepseek`, `qwen`, `glm`, `openrouter`, `ollama`, `azure`

#### 供应商高级配置

部分供应商支持推理 effort 控制：

```python
config["google_thinking_level"] = "high"    # Google Gemini
config["openai_reasoning_effort"] = "high"  # OpenAI
config["anthropic_effort"] = "high"         # Anthropic Claude
```

#### 辩论与研究深度

控制智能体之间的辩论轮次，影响分析深度：

```python
config["max_debate_rounds"] = 2         # 研究员看涨/看跌辩论轮次（默认 1）
config["max_risk_discuss_rounds"] = 2   # 风险管理辩论轮次（默认 1）
config["max_recur_limit"] = 250         # LangGraph 递归限制（默认 250）
```

#### 数据供应商配置

支持 5 个数据供应商（`twelve_data`, `yfinance`, `alpha_vantage`, `tencent_sina`, `akshare`），按类别配置，支持逗号分隔的降级链。默认回退顺序：**twelve_data → yfinance → alpha_vantage → tencent_sina → akshare**（Twelve Data REST API 优先，避免 yfinance 限速等待；免费版 8 API credits/分钟）。

```python
# 默认配置（twelve_data 优先，yfinance 作为降级）
config["data_vendors"] = {
    "core_stock_apis": "twelve_data,yfinance",
    "technical_indicators": "twelve_data,yfinance",
    "fundamental_data": "twelve_data,yfinance",
    "news_data": "twelve_data,yfinance",
    "sentiment_data": "akshare",            # 仅 akshare 支持
}

# A 股配置（自动检测中文股票代码时也会自动切换）
config["data_vendors"] = {
    "core_stock_apis": "tencent_sina",
    "technical_indicators": "tencent_sina",
    "fundamental_data": "tencent_sina,akshare",  # 降级链：先尝试 tencent_sina
    "news_data": "tencent_sina",
    "sentiment_data": "akshare",                  # 情绪数据仅 akshare
}

# 工具级别覆盖（优先级高于类别配置）
config["tool_vendors"] = {
    "get_stock_data": "alpha_vantage",     # 仅对 get_stock_data 使用 alpha_vantage
}
```

#### 输出语言与路径配置

```python
config["output_language"] = "Chinese"      # 报告语言（内部辩论始终使用英文）
```

通过环境变量覆盖存储路径：

| 环境变量                          | 默认值                                        | 说明                 |
| --------------------------------- | --------------------------------------------- | -------------------- |
| `TRADINGAGENTS_RESULTS_DIR`     | `~/.tradingagents/logs`                     | 分析结果输出目录     |
| `TRADINGAGENTS_CACHE_DIR`       | `~/.tradingagents/cache`                    | 数据缓存和检查点目录 |
| `TRADINGAGENTS_MEMORY_LOG_PATH` | `~/.tradingagents/memory/trading_memory.md` | 决策日志路径         |

## 持久化与恢复

TradingAgents 在运行之间持久化两种状态。

### 决策日志

决策日志始终开启。每次完成的运行会将其决策追加到 `~/.tradingagents/memory/trading_memory.md`。在下一次分析同一股票代码时，TradingAgents 会获取已实现收益（原始收益和相对 SPY 的超额收益），生成一段反思总结，并将最近的同代码决策和跨代码经验教训注入到投资组合经理的提示中，确保每次分析都能延续之前的经验。

可通过 `TRADINGAGENTS_MEMORY_LOG_PATH` 覆盖路径。

### 检查点恢复

检查点恢复通过 `--checkpoint` 参数启用。启用后，LangGraph 在每个节点之后保存状态，这样崩溃或中断的运行可以从最后一个成功的步骤恢复，而不需要重新开始。在恢复运行时，你会在日志中看到 `Resuming from step N for <TICKER> on <date>`；在新运行时，你会看到 `Starting fresh`。成功完成后检查点会自动清除。

每个股票代码的 SQLite 数据库存储在 `~/.tradingagents/cache/checkpoints/<TICKER>.db`（可通过 `TRADINGAGENTS_CACHE_DIR` 覆盖基础目录）。使用 `--clear-checkpoints` 可以在运行前重置所有检查点。

```bash
tradingagents --checkpoint                      # 交互模式 + 检查点
tradingagents -t NVDA --checkpoint              # 直接模式 + 检查点
tradingagents --clear-checkpoints               # 运行前重置检查点
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
```

## 贡献

我们欢迎社区贡献！无论是修复 Bug、改进文档，还是提出新功能建议，你的参与都能让这个项目变得更好。如果你对这个研究方向感兴趣，欢迎加入我们的开源金融 AI 研究社区 [Tauric Research](https://tauric.ai/)。

以往的贡献，包括代码、设计反馈和 Bug 报告，均在 [`CHANGELOG.md`](CHANGELOG.md) 中按版本记录致谢。

## 引用

如果你发现 *TradingAgents* 对你有帮助，请引用我们的工作 :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
