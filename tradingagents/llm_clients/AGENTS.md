# AGENTS.md — tradingagents/llm_clients

多供应商 LLM 客户端抽象层。采用工厂模式，支持懒加载和内容归一化。

## 目录结构

```
llm_clients/
├── __init__.py           # 重新导出 BaseLLMClient, create_llm_client
├── factory.py            # create_llm_client() — 按供应商懒加载
├── base_client.py        # BaseLLMClient ABC, normalize_content(), DSML token 清理
├── openai_client.py      # OpenAI + 6 个 OpenAI 兼容供应商；DeepSeekChatOpenAI 子类
├── anthropic_client.py   # Anthropic Claude
├── google_client.py      # Google Gemini（thinking_level 映射）
├── azure_client.py       # Azure OpenAI（基于环境变量）
├── model_catalog.py      # CLI 模型选择菜单（MODEL_OPTIONS 字典）
└── validators.py         # 按供应商验证模型名称
```

## 工厂（`factory.py`）

`create_llm_client(provider, model, base_url=None, **kwargs) -> BaseLLMClient`

懒加载——导入工厂模块不会引入重型 LLM SDK。供应商模块仅在实际创建客户端时才加载。

**7 个 OpenAI 兼容供应商** → `OpenAIClient`（共享 `NormalizedChatOpenAI`）：
- `openai`, `xai`, `deepseek`, `qwen`, `glm`, `ollama`, `openrouter`

**3 个独立客户端**：
- `anthropic` → `AnthropicClient`
- `google` → `GoogleClient`
- `azure` → `AzureOpenAIClient`

## 内容归一化

所有客户端将其 langchain chat model 包装在 `Normalized*` 子类中，重写 `invoke()` 以调用 `normalize_content()`。处理以下情况：

1. **列表内容块**——OpenAI Responses API 和 Google Gemini 3 返回的 `content` 是类型字典列表（`[{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]`）。`normalize_content()` 提取并拼接文本块，丢弃 reasoning/metadata。
2. **DSML token 泄漏**——DeepSeek thinking mode 有时会将 `<｜DSML｜>` token 泄漏到 content 中。`_strip_dsml_tokens()` 通过正则表达式清除。

下游智能体可以始终假定 `response.content` 是 `str` 类型。

## DeepSeek 特殊处理（`openai_client.py`）

`DeepSeekChatOpenAI` 是 `NormalizedChatOpenAI` 的子类，专门处理两个 DeepSeek 特有的行为：

### 1. Thinking-mode 往返
DeepSeek thinking 模型返回 `reasoning_content` 时，该字段**必须在下一轮作为 assistant 消息回传**，否则 API 返回 HTTP 400。

- `_create_chat_result()` 从响应中捕获 `reasoning_content` 并存储到 `message.additional_kwargs`
- `_get_request_payload()` 将其重新附加到发出的消息中

### 2. tool_choice 限制
| 模型 | Tool Calls | `tool_choice` | `with_structured_output` |
|-------|-----------|---------------|--------------------------|
| `deepseek-v4-pro` | ✅ | ❌（thinking mode） | ✅（bind_tools 移除 tool_choice） |
| `deepseek-v4-flash` | ✅ | ❌（thinking mode） | ✅（bind_tools 移除 tool_choice） |
| `deepseek-reasoner` | ❌ | ❌ | ❌ 抛出 `NotImplementedError` |
| `deepseek-chat` | ✅ | ✅ | ✅（映射到 v4-flash） |

- `_THINKING_MODELS` = `{deepseek-v4-pro, deepseek-v4-flash}`——`bind_tools()` 移除 `tool_choice`
- `_NO_TOOL_CHOICE_MODELS` = `{deepseek-reasoner}`——`with_structured_output()` 抛出 `NotImplementedError`；智能体工厂自动降级为自由文本

**已过时模型**（`deepseek-reasoner`、`deepseek-chat`）将于 2026-07-24 退休。

## 供应商配置（`openai_client.py`）

`_PROVIDER_CONFIG` 将供应商名称映射到 `(base_url, api_key_env_var)`：

| Provider | Base URL | 环境变量 |
|----------|----------|---------|
| xai | `https://api.x.ai/v1` | `XAI_API_KEY` |
| deepseek | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| qwen | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| glm | `https://api.z.ai/api/paas/v4/` | `ZHIPU_API_KEY` |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| ollama | `http://localhost:11434/v1` | （无） |

原生 OpenAI 使用 SDK 默认值。Azure 使用 `AZURE_OPENAI_*` 环境变量。

## Google Gemini（`google_client.py`）

`thinking_level` 参数映射：
- Gemini 3 Pro：`low`、`high`（无 `minimal`）
- Gemini 3 Flash：`minimal`、`low`、`medium`、`high`
- Gemini 2.5：映射为 `thinking_budget`（`high` → -1 动态，其余 0 禁用）

## 模型验证（`validators.py`）

`validate_model(provider, model) -> bool`——根据 `model_catalog.py` 中的已知模型列表校验模型名称。

- `ollama` 和 `openrouter`：接受任意模型（始终返回 `True`）
- 未知供应商：接受任意模型
- 已知供应商：必须匹配模型目录列表
- 未知模型通过 `warn_if_unknown_model()` 发出 `RuntimeWarning`，但执行继续

## 透传参数

所有客户端将以下 kwargs 从配置转发到底层 langchain chat model：
`timeout`、`max_retries`、`reasoning_effort`、`api_key`、`callbacks`、`http_client`、`http_async_client`

供应商特有扩展：
- Anthropic：`max_tokens`、`effort`
- Google：`thinking_level`（Gemini 2.5 映射为 `thinking_budget`）

## 新增供应商

1. 如果是 OpenAI 兼容的：在 `factory.py` 的 `_OPENAI_COMPATIBLE` 元组中添加 + 在 `openai_client.py` 的 `_PROVIDER_CONFIG` 中添加。完成。
2. 如果不兼容 OpenAI：创建 `new_client.py`，实现 `NewClient(BaseLLMClient)` 的 `get_llm()` 和 `validate_model()`。将 langchain chat model 包装在 `Normalized*` 子类中。在 `factory.py` 中添加路由。
3. 在 `model_catalog.py` 的 MODEL_OPTIONS 字典中添加模型。
4. 在 `.env.example` 中注册环境变量。

## 禁止事项

- 不要为已在 `_PROVIDER_CONFIG` 中有默认值的供应商设置 `backend_url`，除非你需要自定义代理
- 不要用 `deepseek-reasoner` 做结构化输出——它会抛出 `NotImplementedError`
- 不要直接向 DeepSeek V4 thinking 模型传递 `tool_choice`——`bind_tools()` 会移除它，但直接 API 调用会失败
- 不要假设归一化之前 `response.content` 一定是字符串——`Normalized*` 子类处理了这个问题，但如果绕过 `invoke()` 你会得到原始列表块
- 不要在模块级别导入供应商模块——在 `factory.py` 中使用懒加载，避免在测试收集阶段引入 SDK
