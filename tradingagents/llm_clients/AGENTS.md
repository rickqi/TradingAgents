# AGENTS.md — tradingagents/llm_clients

Multi-provider LLM client abstraction. Factory pattern with lazy imports and content normalization.

## Structure

```
llm_clients/
├── __init__.py           # Re-exports BaseLLMClient, create_llm_client
├── factory.py            # create_llm_client() — lazy imports by provider
├── base_client.py        # BaseLLMClient ABC, normalize_content(), DSML token stripping
├── openai_client.py      # OpenAI + 6 OpenAI-compatible providers; DeepSeekChatOpenAI subclass
├── anthropic_client.py   # Anthropic Claude
├── google_client.py      # Google Gemini (thinking_level mapping)
├── azure_client.py       # Azure OpenAI (env-var driven)
├── model_catalog.py      # CLI model selection menus (MODEL_OPTIONS dict)
└── validators.py         # Model name validation per provider
```

## Factory (`factory.py`)

`create_llm_client(provider, model, base_url=None, **kwargs) -> BaseLLMClient`

Lazy imports — importing the factory does NOT pull in heavy LLM SDKs. Provider modules are loaded only when a client is actually created.

**7 OpenAI-compatible providers** → `OpenAIClient` (shares `NormalizedChatOpenAI`):
- `openai`, `xai`, `deepseek`, `qwen`, `glm`, `ollama`, `openrouter`

**3 dedicated clients**:
- `anthropic` → `AnthropicClient`
- `google` → `GoogleClient`
- `azure` → `AzureOpenAIClient`

## Content Normalization

All clients wrap their langchain chat model in a `Normalized*` subclass that overrides `invoke()` to call `normalize_content()`. This handles:

1. **List content blocks** — OpenAI Responses API and Google Gemini 3 return `content` as a list of typed dicts (`[{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]`). `normalize_content()` extracts and joins text blocks, discarding reasoning/metadata.
2. **DSML token leakage** — DeepSeek thinking mode sometimes leaks `<｜DSML｜>` tokens into content. `_strip_dsml_tokens()` removes these via regex.

Downstream agents can always assume `response.content` is a `str`.

## DeepSeek Quirks (`openai_client.py`)

`DeepSeekChatOpenAI` is a `NormalizedChatOpenAI` subclass that handles two DeepSeek-specific behaviors:

### 1. Thinking-mode round-trip
When DeepSeek thinking models return `reasoning_content`, that field **must be echoed back** in the assistant message on the next turn, or the API returns HTTP 400.

- `_create_chat_result()` captures `reasoning_content` from the response and stores it in `message.additional_kwargs`
- `_get_request_payload()` re-attaches it to outgoing messages

### 2. Tool choice restrictions
| Model | Tool Calls | `tool_choice` | `with_structured_output` |
|-------|-----------|---------------|--------------------------|
| `deepseek-v4-pro` | ✅ | ❌ (thinking mode) | ✅ (bind_tools strips tool_choice) |
| `deepseek-v4-flash` | ✅ | ❌ (thinking mode) | ✅ (bind_tools strips tool_choice) |
| `deepseek-reasoner` | ❌ | ❌ | ❌ raises `NotImplementedError` |
| `deepseek-chat` | ✅ | ✅ | ✅ (maps to v4-flash) |

- `_THINKING_MODELS` = `{deepseek-v4-pro, deepseek-v4-flash}` — `bind_tools()` strips `tool_choice`
- `_NO_TOOL_CHOICE_MODELS` = `{deepseek-reasoner}` — `with_structured_output()` raises `NotImplementedError`; agent factories auto-fallback to free-text

**Legacy models** (`deepseek-reasoner`, `deepseek-chat`) retire 2026-07-24.

## Provider Config (`openai_client.py`)

`_PROVIDER_CONFIG` maps provider name → `(base_url, api_key_env_var)`:

| Provider | Base URL | Env Var |
|----------|----------|---------|
| xai | `https://api.x.ai/v1` | `XAI_API_KEY` |
| deepseek | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| qwen | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| glm | `https://api.z.ai/api/paas/v4/` | `ZHIPU_API_KEY` |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| ollama | `http://localhost:11434/v1` | (none) |

Native OpenAI uses its SDK defaults. Azure uses `AZURE_OPENAI_*` env vars.

## Google Gemini (`google_client.py`)

`thinking_level` kwarg mapping:
- Gemini 3 Pro: `low`, `high` (no `minimal`)
- Gemini 3 Flash: `minimal`, `low`, `medium`, `high`
- Gemini 2.5: maps to `thinking_budget` (`high` → -1 dynamic, else 0 disable)

## Model Validation (`validators.py`)

`validate_model(provider, model) -> bool` — checks model name against known lists from `model_catalog.py`.

- `ollama` and `openrouter`: any model accepted (return `True` always)
- Unknown providers: any model accepted
- Known providers: must match model catalog list
- Unknown models get a `RuntimeWarning` via `warn_if_unknown_model()`, but execution continues

## Passthrough Kwargs

All clients forward these kwargs from config to the underlying langchain chat model:
`timeout`, `max_retries`, `reasoning_effort`, `api_key`, `callbacks`, `http_client`, `http_async_client`

Provider-specific additions:
- Anthropic: `max_tokens`, `effort`
- Google: `thinking_level` (mapped to `thinking_budget` for Gemini 2.5)

## Adding a New Provider

1. If OpenAI-compatible: add to `_OPENAI_COMPATIBLE` tuple in `factory.py` + `_PROVIDER_CONFIG` in `openai_client.py`. Done.
2. If not OpenAI-compatible: create `new_client.py` with `NewClient(BaseLLMClient)` implementing `get_llm()` and `validate_model()`. Wrap the langchain chat model in a `Normalized*` subclass. Add route in `factory.py`.
3. Add models to `model_catalog.py` MODEL_OPTIONS dict.
4. Register env var in `.env.example`.

## What Not to Do

- Don't set `backend_url` for a provider that already has a default in `_PROVIDER_CONFIG` unless you need a custom proxy
- Don't use `deepseek-reasoner` for structured output — it raises `NotImplementedError`
- Don't pass `tool_choice` directly to DeepSeek V4 thinking models — `bind_tools()` strips it, but direct API calls will fail
- Don't assume `response.content` is always a string before normalization — the `Normalized*` subclass handles this, but if you bypass `invoke()` you'll get raw list blocks
- Don't import provider modules at module level — use lazy imports in `factory.py` to avoid pulling in SDKs during test collection
