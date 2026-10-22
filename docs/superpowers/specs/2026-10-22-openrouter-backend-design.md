# OpenRouter backend: design

Status: draft, 2026-10-22. Builds on Batch A (prompt caching, dated prompts, error categories,
request snapshots), so it is implemented after Batch A merges.

## Goal

Let people run the app on an OpenRouter key instead of an Anthropic key. Some people already
have OpenRouter credit, or want one bill across providers, or want to try other models.

## Approach: the same client, a different endpoint

OpenRouter has an Anthropic-format Messages endpoint (`POST https://openrouter.ai/api/v1/messages`).
Its reference lists the features this app depends on:

| Feature the app uses | OpenRouter Messages endpoint |
|---|---|
| Strict tools (`strict: true`), `tool_choice: auto` | Supported. Forced `tool_choice` is a 400 on Sonnet 5.5 there too, as it is direct. |
| `cache_control` (block level and top level) | Supported. Minimum cacheable prompt is 512 tokens on the 5.5 models. |
| Anthropic `web_search_20250305` server tool | Supported, plus OpenRouter's own `openrouter:web_search`. |
| `pause_turn`, `refusal`, `max_tokens` stop reasons | All in its stop-reason enum. |
| Thinking blocks passed back unchanged | Required. Sonnet and Haiku 5.5 blocks are bound to the account, and OpenRouter keeps replays on a compatible provider. |
| `usage` | Anthropic's fields, plus `cost` (what OpenRouter charged), `cost_details`, `is_byok`, and `server_tool_use.web_search_requests`. |

So the plan is to point the existing Anthropic SDK clients at OpenRouter, rather than write a
second client. `AnthropicLLMClient` and `AnthropicResearcherClient` take a base URL, a credential,
and model names from config. Everything above them (structured output, the tutor's gated tools,
research continuations, usage recording) stays as it is.

## Configuration

- `AA_LLM_BACKEND=openrouter` selects it. `anthropic` stays the default.
- `OPENROUTER_API_KEY` holds the key. `llm/keys.py` gets the same "missing or placeholder"
  checks it has for `ANTHROPIC_API_KEY`.
- Base URL `https://openrouter.ai/api` (the SDK adds `/v1/messages`).
- Model names use OpenRouter slugs. Defaults: `anthropic/claude-sonnet-5.5` (reasoning) and
  `anthropic/claude-haiku-5.5` (copy). `AA_MODEL_REASONING` and `AA_MODEL_COPY` override them.
- `GET /api/setup` and the Setup card name the backend in use and which key is missing.
- Works in Docker, unlike the Agent SDK backend.

## Cost

OpenRouter reports what it charged in `usage.cost`. Record that number on the usage row and
prefer it over the price table. Two benefits:

- Any model gets a real cost, so the daily limit works for models the app has no price for.
  Today those calls are refused while a limit is set.
- The number matches the OpenRouter bill, including its fees.

This needs one nullable column on `llmusage` (for example `reported_cost_usd`). Rows from the
Anthropic backend leave it empty and keep using the price table.

## Privacy

Requests now pass through OpenRouter as well as the model provider. The README's privacy line
and `docs/COSTS.md` must say so when this backend is on. Send OpenRouter's provider preference
that excludes providers that store prompts (`provider.data_collection: "deny"`) by default.
Verify the exact field before relying on it.

## Errors

Map OpenRouter's errors into Batch A's categories: `payment_required` (402) becomes
`out_of_credits`, its rate limits become `rate_limited`, and an unknown slug becomes
`model_unavailable`. The plain messages name OpenRouter, not Anthropic, when this backend is on.

## Other models

Claude models through OpenRouter get full support. Other models (DeepSeek, GPT, Gemini) are
allowed but marked experimental on the Setup card:

- Strict tool use and Anthropic's web search tool may not work for them. Research falls back
  to `openrouter:web_search` when the model isn't an Anthropic one.
- Their structured output goes through the same strict tool plus one retry. If that fails twice,
  the call fails with `invalid_output`, as it does today.
- A small capability table per model family (strict tools, Anthropic web search, thinking
  blocks) keeps these differences in data, not scattered `if` checks. This is the "model
  catalog" idea from kew.

## Tests

- No live calls in the suite. The scripted client is unchanged.
- Request snapshots (from Batch A) gain the OpenRouter variants of each surface: base URL,
  model slug, provider preferences.
- Usage tests: `usage.cost` is recorded and preferred, and the budget check uses it.
- Error mapping tests for the OpenRouter error shapes.
- Before merge, with your approval, one short live check against OpenRouter (a few cents):
  a tutor turn, one structured grade, and one research search with web search. This confirms
  the auth header (the SDK's `auth_token`, sent as `Authorization: Bearer`, is the expected
  one; the reference page did not show it) and the `usage.cost` field.

## Decisions (2026-10-22)

1. Defaults through OpenRouter are `anthropic/claude-sonnet-5.5` and `anthropic/claude-haiku-5.5`.
2. Other models are in the first version, marked experimental: on the Setup card, wherever a
   model is chosen or named, and on the Usage page's per-model rows. The capability table is
   the one source for that flag.
3. No second (OpenAI-format) client for now. OpenRouter's Messages endpoint accepts any model
   and converts the request and response, and the OpenAI format would lose thinking-block
   replay, server web search with `pause_turn`, and `cache_control`. If a model we want fails
   on the Messages endpoint, add an OpenAI-format client (the `openai` SDK against OpenRouter,
   or LiteLLM) as one more `llm/` registry entry; engines don't change. The Vercel AI SDK is
   TypeScript, and the LLM layer is Python, so it's not a fit.
4. The live check before merge includes one non-Claude model, to learn early whether the
   Messages endpoint is enough for them.
