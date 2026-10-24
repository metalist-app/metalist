# AI Providers: OpenAI, Anthropic and Google, Bring Your Own Key

MetaList's AI runs on the user's own API key for one of three providers: OpenAI, Anthropic
(Claude models) or Google (Gemini models). AI stays optional; MetaList is complete without
it. Agreed with the maintainer 2026-10-23 and built on `feature/ai-providers` (merged
2026-10-24). What is not built yet (eval runs for Claude and Gemini, the demo vault, hosted
questions): `docs/future-plans/ai-providers-remaining.md`.

Vocabulary as in `docs/AI-SUMMARY.md`: users see **vault**; code and APIs say **namespace**.

## Why bring your own key

Calls go from the vault's own process straight to the provider the user chose, under the
user's account with that provider. MetaList never supplies, pays for, relays or proxies AI
for anyone. The planned hosted MetaList runs each vault in its own process and works the
same way, so no AI key belonging to MetaList exists anywhere in the code or a deployment.

## 1. Three providers, three adapters

Features ask `app/services/ai_setup.py` whether an AI is set up (`describe_ai_setup`) and
for a connection (`connect_to_ai`: provider, label, base URL, inference adapter wrapped in
`PrivacyGuardedInference`), never for a key. Each adapter implements `InferenceAdapter`
(`app/services/agent/inference.py`): `provider_label`, `inspect_context_window`,
`infer_structured`, `stream_text`, `stream_tool_turn`. The SDKs load on first use
(`ai_setup._adapter`).

| Provider | Adapter | How |
|---|---|---|
| OpenAI | `OpenAIInferenceAdapter` (`openai_inference.py`) | Responses API for tool turns, `store: false`, Instructor with strict schemas (`strict_structured_outputs.py`). |
| Anthropic | `AnthropicInferenceAdapter` (`anthropic_inference.py`) | Native `anthropic` SDK, pinned 1.12.1 (newest release at least two weeks old), its HTTP stack held to older releases by `[tool.uv] constraint-dependencies` in `pyproject.toml`. Streaming Messages; strict tools with `tool_choice: auto`; adaptive thinking with effort from the thinking level (Off and Low both "low": Opus 5.5 cannot turn thinking off); thinking blocks handed back as `provider_state`; top-level prompt caching; structured replies through `output_config.format` with MetaList's own retry (`structured_retry_messages`). System messages before the first reply become `system`, later ones stay mid-conversation; an empty assistant reply is left out. Not Anthropic's OpenAI-compatible endpoint: it ignores strict tools, has no prompt caching and returns no thinking. |
| Google | `OpenAICompatibleInferenceAdapter` with the `GEMINI` row (`openai_compatible_inference.py`) | Google's OpenAI-compatible Chat Completions endpoint (it has no Responses API), no new dependency. Extra fields on a streamed tool call (Gemini's thought signatures) are kept in `provider_state` and sent back with that call. Structured replies through Instructor with strict schemas. A later OpenAI-dialect provider is one more `OpenAICompatibleProvider` row. |

No LiteLLM or other multi-provider wrapper: three adapters are small, and this is the most
privacy-sensitive outbound path in the app. Grok (xAI) is not planned.

What each adapter normalizes: tool-call formatting and results, structured output and its
retries, stop reasons (a length stop fails visibly: `OutputLimitReached`), the silence
limit and `provider_started`, and token usage.

- **Answer length:** no limit of MetaList's own (2026-10-24). OpenAI and Google are sent
  none; Claude, whose API requires one, gets its models' maximum
  (`CLAUDE_MODEL_MAX_OUTPUT_TOKENS`, 128,000). See `docs/ui/ai-chat.md`.
- **Silence limits:** OpenAI 15 s at Off and Low (measured), 60 s Medium, 120 s High;
  Anthropic and Google 30/60/120 s (`UNMEASURED_SILENCE_LIMIT_SECONDS`, not measured).
  Claude streams pings while it thinks, so its silence means a broken connection. Google's
  overloaded models hang without a byte (3.8 Flash, 2026-10-24: no answer in two minutes
  while 3.5 Flash-Lite answered in 3 s), so Google's silence message says the model may be
  busy, and its HTTP 503 says the model is busy right now.

## 2. Catalog: providers and models are part of MetaList

Decided 2026-10-23: no configuration file. `app/services/ai_catalog.py` lists each
provider's label, API address, billing page, models, default model and context size; the
browser's copy is `app/static/js/modules/ai-chat/ai-providers.js` (a test checks they
match).

| Provider (UI name) | Models | Default |
|---|---|---|
| OpenAI | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | Luna |
| Anthropic | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` | Sonnet 5.5 |
| Google | `gemini-4-argon`, `gemini-3.8-flash`, `gemini-3.5-flash-lite` | 3.8 Flash |

- **API addresses are never editable,** so a key goes only to its provider and a hosted
  outbound allowlist can be built from the catalog.
- **A request's model must be one MetaList ships** (`require_shipped_model`). Saved
  preferences only need a well-formed name, so a release that drops a model never breaks
  loading a vault.
- **No typed-in models** (2026-10-23, the maintainer). A model is offered only once it has
  been tested with MetaList's prompts in the regression evals: a new model may behave
  differently, may need model-specific prompts, or may be too weak for reliable results.
  New models arrive with MetaList updates; the old `pref.ai.<provider>.added_models`
  preferences are dropped when a vault loads.
- **Offered before their evals** (2026-10-23, the maintainer): Claude and Gemini are shown
  everywhere although their eval pass rates are not recorded yet.
- **Names in text, no logos** (2026-10-23). Providers are named by company (OpenAI,
  Anthropic, Google), models by their own names. OpenAI's brand guidance points away from
  its logo in an app built on its API, Anthropic requires approval, and Google's product
  icons are "ask first"; revisit only with each company's written permission and files.
- **Prompts stay provider-neutral.** A per-provider prompt overlay is allowed only where an
  eval case requires it, with the reason recorded next to it.

## 3. Keys: one encrypted slot per provider, per vault

`app/services/ai_credentials.py` (replaced `openai_credentials.py`).

- Each provider has its own key in the vault: `app_settings` columns `openai_api_key_*`,
  `anthropic_api_key_*` and `gemini_api_key_*`, encrypted with the namespace DEK (database
  version 11, `add_ai_provider_credential_columns`; `docs/security/README.md`). Plaintext
  namespaces hold keys only in server session memory. Erasing a vault's encryption clears
  every provider's key. Switching provider never asks for a key again.
- Keys are write-only from the browser, never returned, never in traces, debug or history.
- Routes: `/api2/ai/{provider}/credential`, registered providers only (OpenAI's URL is
  unchanged). Route models take `AiProvider`.
- Key formats: OpenAI `sk-`, Anthropic `sk-ant-`, Google `AIza` or `AQ.` (Google's newer
  keys, 2026-10-24).
- AI Agent Settings has one folder tab per provider: the key, a link to that provider's
  usage and billing page, and for Google a warning under the key (checked 2026-10-23
  against Google's terms): on unpaid quota Google uses prompts and responses to improve its
  products and human reviewers may read them, except in the EEA, Switzerland and the UK.

## 4. Picking the model: only in the chat

Agreed 2026-10-23. AI Agent Settings no longer picks a model or provider. The chat's model
picker lists the models of every provider with a key, each under its provider's name, and
picking a model picks its provider (`GET /api2/ai/model-choices`, a read, so it never holds the one mutation slot). The last model and
thinking level picked are the next default (`pref.ai.provider`, `pref.ai.<provider>_model`).
The reading limit is one number for every provider (**Max token window**).

Switching provider keeps the conversation (2026-10-24): one privacy policy covers every
provider, so the history the next model sees is the same.

## 5. Cost estimate: development mode only

Users never see an AI dollar figure: the estimate is MetaList's price table applied to token
counts, can be wrong, and would need upkeep for three providers. The cost routes and the
chat panel's `$` exist only when `METALIST_ENVIRONMENT=development`
(`is_development_environment()`, `data-shows-cost-estimate`); in production the routes
answer 404. Token usage stays recorded per provider for the evals and debug views.

## 6. One outbound boundary

Every adapter sends through `PrivacyGuardedInference`: the whitelist/blacklist and
`@password`/`@username` exclusion before serialization, and the canary test that excluded
text never appears in an outbound request. Each adapter builds its own HTTP client: pinned
base URL from the catalog, no redirects, `trust_env=False`, no SDK retries. The agent's
tool-permission rules apply identically whichever provider asked.

## 7. No local models

Ollama stays removed. A hosted vault process can't reach a model on the user's computer.

## Invariants

1. The code contains no AI key belonging to MetaList, and no path where one is configured
   for users.
2. AI keys are per vault, per provider, encrypted with the namespace DEK (session memory
   only in plaintext namespaces), and never leave the vault's own process except to their
   provider.
3. Every AI request goes through the one outbound boundary with the exclusion filter and
   canary, whatever the provider.
4. No AI cost figure is shown in production.
5. Provider hosts, base URLs and model lists come only from the catalog.

## Verified live

- Claude Haiku 5.5 answers in the chat, including after a failed summary step was fixed
  (2026-10-24).
- Gemini 3.5 Flash-Lite answers and streams in the chat; 3.8 Flash answered a probe after
  75 s while Google was overloaded; `AQ.` keys work on the OpenAI-compatible endpoint
  (2026-10-24).
- Not yet checked live: Sonnet 5.5, Opus 5.5, Gemini 4 Argon, Sol and Terra; the
  30/60/120 s silence limits for Anthropic and Google.
