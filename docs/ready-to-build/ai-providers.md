# AI Providers: OpenAI, Claude and Gemini, Bring Your Own Key

Status: agreed design, ready to build, not started. Decided 2026-10-23. Code references below checked against the repo on 2026-10-23, when it was filed here from `docs/inbox/`.

Vocabulary as in `docs/AI-SUMMARY.md`: users see **vault**; code and APIs say **namespace**.

## Progress

Built on `feature/ai-providers` (2026-10-23), with OpenAI behaving as before:

- **Cost estimate in development only** (Design §4): `is_development_environment()` in `app/startup_environment.py`; the cost routes answer 404 in production, and the chat panel shows the `$` only where the page says the estimate is offered (`data-shows-cost-estimate`).
- **One encrypted key slot per provider, per vault** (Design §3): `app/services/ai_credentials.py` (replaces `openai_credentials.py`); `app_settings` columns `anthropic_api_key_*` and `gemini_api_key_*` beside `openai_api_key_*`; database version 11 (`add_ai_provider_credential_columns`), the encryption audit and `docs/security/README.md` updated. Erasing a vault's encryption clears every provider's key.
- **Per-provider credential routes** (Design §3): `/api2/ai/{provider}/credential`, for registered providers only. OpenAI's URL is unchanged.
- **Route models take the registered provider type** (`AiProvider`) instead of a fixed `"openai"` (Design §2).
- **Provider configuration** (Design §2), decided with the maintainer 2026-10-23: no configuration file. The shipped providers and models are part of MetaList's code (`app/services/ai_catalog.py`: label, API address, billing page, models, default model, context size; OpenAI's three models moved there from `openai_models.py`). API addresses are never editable, so a key goes only to its provider and a hosted allowlist can be built from the catalog. A request's model must be one MetaList ships (`ai_catalog.require_shipped_model`); saved preferences only need a well-formed name, so a release that drops a model never breaks loading a vault.
- **No typed-in models** (2026-10-23, the maintainer): a vault could briefly add models by name ("Your models"). Removed the same day. A model is offered only once it has been tested with MetaList's prompts in the regression evals: a new model may behave differently, may need model-specific prompts (as a provider may need provider-specific ones), or may be too weak to give reliable results whatever the prompts. Typing an exact ID was also error-prone. New models arrive with MetaList updates; the saved `pref.ai.<provider>.added_models` preferences are dropped when a vault loads.

- **One place to pick the model** (2026-10-23, agreed with the maintainer): AI Agent Settings no longer picks a model or provider. Its folder tabs only show each provider's key and billing link. The chat's model picker lists the models of every provider with a key, each under its provider's name, and picking a model picks its provider (`POST /api2/ai/model-choices`). The last model and thinking level picked are the next default. The reading limit is one number (**Max token window**); the separate tagging batch window is gone.

Before the release: run the evals on each shipped model, not only Luna. Sol and Terra are listed but have not been through them (needs the maintainer's go-ahead, since live evals normally run on Luna Low only).

- **Claude and Gemini adapters** (Design §1, 2026-10-23), offered everywhere at once: the maintainer dropped Invariant 4 for them (no waiting for eval pass rates). Chosen with the maintainer:
  - Claude: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, default Sonnet 5.5. `app/services/agent/anthropic_inference.py` on the native `anthropic` SDK, pinned to 1.12.1 (the newest release at least two weeks old) with its HTTP stack held to older releases by `[tool.uv] constraint-dependencies` in `pyproject.toml`. Streaming Messages, strict tools with `tool_choice: auto`, adaptive thinking with effort from the thinking level (Off and Low both "low": Opus 5.5 cannot turn thinking off), thinking blocks handed back as `provider_state`, top-level prompt caching, structured replies through `output_config.format` with MetaList's own retry (the shared `structured_retry_messages` wording). System messages before the first reply become `system`; later ones stay as mid-conversation system messages; an empty assistant reply is left out.
  - Gemini: `gemini-4-argon`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`, default 3.8 Flash. `app/services/agent/openai_compatible_inference.py` (`GEMINI` row) on Google's OpenAI-compatible Chat Completions endpoint, no new dependency. Extra fields on a streamed tool call (Gemini's thought signatures) are kept in `provider_state` and sent back with that call. Structured replies through Instructor with strict schemas, as OpenAI's.
  - Registered in `ai_setup.py` (`AI_PROVIDERS`), `ai_catalog.py` (models, billing pages, 1M-token contexts) and the browser's copy `ai-providers.js` (a test checks they match). The chat's model picker lists every provider with a key under its name; picking a model picks its provider. Each provider's tab in AI Agent Settings holds its key and billing link; the Google tab warns about Gemini's free tier under the key. Providers are named by company everywhere (OpenAI, Anthropic, Google); models keep their own names. The max token window stays one setting for all providers.
  - **Not verified against the live APIs yet** (no keys): mocked tests drive both adapters through the real SDKs with recorded wire formats. To check with a key: that Gemini's endpoint accepts `max_completion_tokens`, `additionalProperties: false` in tool parameters and strict `response_format`, and returns thought signatures where expected; that Claude's adaptive thinking and effort behave as mapped on each model; the silence limits (`UNMEASURED_SILENCE_LIMIT_SECONDS`, 30/60/120 s), not measured for either.

Not built yet: eval runs for Claude and Gemini (the eval schema is fixed to `gpt-5.6-luna`; needs the maintainer's keys and go-ahead), provider logos in the chat (below), and the demo vault parts.

## Background

MetaList's AI works only with OpenAI today, on the user's own API key. Users want Claude (Anthropic) and Gemini (Google) too. AI stays optional; MetaList is complete without it.

The planned hosted MetaList runs each user's vault in its own server process. AI there works exactly as in self-hosting: **the user brings their own key**, and calls go from that vault's own process straight to the provider the user chose, under the user's account with that provider. MetaList never supplies, pays for, relays or proxies AI for anyone, including the anonymous demo. So no AI key belonging to MetaList exists anywhere in the code or the deployment.

## What exists today

- **Provider-neutral features, one provider.** Features ask `app/services/ai_setup.py` whether an AI is set up (`describe_ai_setup`) and for a connection (`connect_to_ai`), never for a key. The registry is `AI_PROVIDERS = ("openai",)` (`ai_setup.py:24`); `connect_to_ai` builds an `OpenAIInferenceAdapter` wrapped in `PrivacyGuardedInference` (`ai_setup.py:67–86`).
- **The adapter interface already exists:** `InferenceAdapter` (`app/services/agent/inference.py:105`) with `provider_label`, `inspect_context_window`, `infer_structured`, `stream_text` and `stream_tool_turn`. Tool calling is provider-neutral in `tool_calling.py`.
- **OpenAI specifics:** the Responses API (`openai_inference.py:528`), `store: false` (`openai_inference.py:328`), its own `httpx` client pinned to `OPENAI_API_BASE_URL` with no redirects and `trust_env=False` (`openai_inference.py:98–108`), structured output through Instructor with strict schemas (`strict_structured_outputs.py`).
- **Route models accept only OpenAI:** `provider: Literal["openai"]` and `assert self.provider == "openai"` in `app/api/routes/ai.py` (for example `:123`, `:230`, `:267`). Credential routes are `/openai/credential` (`ai.py:375`, `:392`, `:422`).
- **Key storage:** `app/services/openai_credentials.py`. In an encrypted namespace the key is encrypted with the namespace DEK into `app_settings.openai_api_key_ciphertext` / `_nonce` / `_tag` (`openai_credentials.py:62–66`; migration 5, `app/db/migrations.py:230–232`). In a plaintext namespace it is held only in server session memory (`openai_credentials.py:81`). It is never returned to the browser or included in traces.
- **Cost estimate:** `openai_cost_tracking.py` multiplies API-reported token usage by a price table in code. Served at `GET /api2/ai/openai/cost` and reset at `POST /api2/ai/openai/cost/reset` (`ai.py:646`, `:656`); the chat panel reads it (`app/static/js/modules/ai-chat/ai-chat-api.js:378`).
- **Environment setting:** `METALIST_ENVIRONMENT` is `development` or `production` (`app/startup_environment.py:9–11`).
- **Ollama was removed** (commit `fd09d7fd`); only OpenAI is accepted.

## Design

### 1. Three providers, three adapters

| Provider | Adapter | Notes |
|---|---|---|
| OpenAI | the existing `OpenAIInferenceAdapter` | Move only what's needed behind the registry; zero behavior change. |
| Claude | new `AnthropicInferenceAdapter` on the **native** `anthropic` SDK | Messages API with streaming, tool use with strict input schemas, and prompt caching for the repeated evidence prefix. Not Anthropic's OpenAI-compatibility endpoint: it ignores `strict` on tools, doesn't support prompt caching, and doesn't return thinking. Some Claude models reject forced tool choice; use `auto`. |
| Gemini | new `OpenAICompatibleInferenceAdapter` (Chat Completions), with Gemini as its first configuration row | Gemini's OpenAI-compatible endpoint (`/v1beta/openai/`) supports **Chat Completions only, not the Responses API** used here (Google's compatibility docs; checked 2026-10-23). Later OpenAI-dialect providers reuse this adapter as configuration. If strict structured output or streamed tool calls fall short through that endpoint, use the native `google-genai` SDK instead and record why. |

No LiteLLM or other multi-provider wrapper: three adapters are small, and this is the most privacy-sensitive outbound path in the app.

Normalization the adapters own, proven by the agent eval suite rather than assumed: tool-call formatting, parallel tool calls, how tool results are returned, structured output and its retries (Instructor supports Anthropic; check the strictness guarantees match), length/stop reasons (a length stop must still fail visibly), silence limits and `provider_started`, and usage reporting.

Grok (xAI) is **not planned**; don't add it. Possible later additions, as configuration rows on the OpenAI-compatible adapter: Mistral, OpenRouter.

**Done when:** each of the three providers has run the `evals/` agent cases and the summary/tagging cases, with per-provider pass rates recorded (for example in `evals/RESULTS-*.md`). A provider without recorded pass rates is not offered in the UI. All three are required for the hosted launch.

### 2. Registry, routes and settings

- Extend `AiProvider` and `AI_PROVIDERS` to `openai`, `anthropic`, `gemini`. Each provider registers its label, how to tell it is set up, its base URL, and its adapter factory.
- Route models take any registered provider instead of `Literal["openai"]`; model validation is per provider.
- Provider list, base URLs and model lists are **configuration**, not code (a config file the user can override), because model lists change monthly.
- Provider and model are chosen **per vault**, using the existing chat-panel pickers.
- Provider prompts stay provider-neutral. A per-provider prompt overlay is allowed only where an eval case requires it, with the reason recorded next to it.

### 3. Keys: one encrypted slot per provider, per vault

- Generalize OpenAI's credential store so each provider has its own key slot in the vault, encrypted with the namespace DEK exactly as today. Switching provider never asks for a key again. The storage shape (columns or a small table) is your call; add a migration.
- Same rules for every provider: write-only from the browser, never returned, never in traces, debug or history, and never in any control-plane or account-service request.
- Plaintext namespaces keep today's session-memory-only behavior for every provider.
- Credential routes become per provider (for example `/api2/ai/{provider}/credential`).
- Next to each key field, link to **that provider's own usage and billing page**. That's where users see what they spent.
- **Gemini key field warning:** under Google's terms, free-tier Gemini API traffic may be used to improve Google's products and seen by human reviewers; paid-tier traffic is not (check Google's current terms when writing the text). The field says so and asks for a key from a Google Cloud project with billing enabled. It's a warning, not a check, unless the API exposes the tier.

### 4. Cost estimate: development mode only

- Users never see an AI dollar figure. The estimate is MetaList's price table applied to token counts, can be wrong (for example on interrupted requests), and would need upkeep for three providers.
- Keep it as a developer tool: the cost routes and the chat panel's `$` exist only when `METALIST_ENVIRONMENT=development`. In production the routes return 404 and the UI doesn't render the control. Where shown, it is labeled "estimated".
- Token usage stays recorded uniformly per provider, for the evals and the debug views.

### 5. One outbound boundary

- Every adapter sends through the same boundary as today: `PrivacyGuardedInference`, the whitelist/blacklist and `@password`/`@username` exclusion before serialization, and the canary test that excluded text never appears in an outbound request. No adapter opens its own path to the network outside it.
- Each adapter builds its own HTTP client the way the OpenAI one does: pinned base URL from configuration, no redirects, `trust_env=False`, no SDK retries.
- The agent's tool-permission rules apply identically whichever provider asked.
- The hosted deployment restricts each vault process's outbound network to an allowlist. Provider API hosts come only from the provider configuration, so the allowlist can be generated from it.

### 6. Demo vault

The anonymous demo vault has **AI off by default** and says so in the AI panel: the demo is a tour of MetaList's interface and features, with the AI not turned on. A visitor may paste their own key for any of the three providers. That key is held only in that demo process's memory (the plaintext-namespace session path), never written to the demo template or anywhere else, and is gone when the demo is discarded. The key field says this and suggests a separate, spending-limited key the visitor can revoke afterwards.

Check that the chat panel's hover preview of which notes the AI may see works with no key set, so demo visitors without a key still see the exclusion rules at work.

### 7. No local models

Ollama stays removed. A hosted vault process can't reach a model on the user's own computer, and nothing here brings local models back.

## Invariants

1. The code contains no AI key belonging to MetaList, and no path where one is configured for users.
2. AI keys are per vault, per provider, encrypted with the namespace DEK (session memory only in plaintext namespaces), and never leave the vault's own process except to their provider.
3. Every AI request goes through the one outbound boundary with the exclusion filter and canary, whatever the provider.
4. ~~A provider appears in the UI only after its eval pass rates are recorded.~~ Dropped by the maintainer 2026-10-23: Claude and Gemini are offered before their evals run.
5. No AI cost figure is shown in production.
6. Provider hosts, base URLs and model lists are configuration.

## Open questions (ask the maintainer)

Found when the note was filed (2026-10-23):

- **The demo vault does not exist yet.** Nothing in `app/` or `docs/` describes an anonymous demo, so Design §6 waits until there is one (it belongs with the hosted plan, `docs/future-plans/hosted-own-copy.md`).
- **Which model each provider is evaluated on.** Agent eval cases are fixed to `gpt-5.6-luna` in code (`evals/agent_models.py:125`, `model: Literal["gpt-5.6-luna"]`), and live evals have so far run on Luna at Low thinking only. Per-provider pass rates (Design §1) need one chosen Claude model and one Gemini model, the eval schema widened to them, and the maintainer's keys for those providers (live runs cost money).
- **Provider logos in the chat** (asked 2026-10-23): show the OpenAI, Claude and Gemini logos where the chat names the provider. Each company's rules, read 2026-10-23 (not legal advice):
  - **OpenAI** (openai.com/brand, "API Developers"): an API developer "may truthfully identify the OpenAI technology" used, but the app's name, logo, description and screenshots "should be free of OpenAI's brands (including … logos)". Its logo rules otherwise allow use "only when it directly relates to OpenAI services", exactly as provided, never more prominent than the app's own brand, never implying endorsement. Logo permission requests: partnercomms@openai.com.
  - **Anthropic** (anthropic.com/legal/trademark-guidelines): its trademarks, logos included, may be used "only as specifically permitted by us and only in materials we approve beforehand", with images Anthropic supplies and no alterations. Its Agent SDK docs allow the name "Claude" in a dropdown menu. Requests: marketing@anthropic.com (existing business relationship) or Anthropic sales.
  - **Google** (developers.google.com/terms §6; about.google/brand-resource-center): the API terms license Google's brand features "for the purpose of promoting or advertising that you use the APIs", under the Brand Features Use Guidelines; naming Google products in plain text needs no request; product icons (the Gemini mark) are "Ask first" unless the icon usage guidelines cover the use.
  - So: the provider's name in text is fine for all three. A logo needs Anthropic's approval, OpenAI's guidance points away from it in an app built on its API, and Google's icon needs checking or asking. Ship names in text; ask the three companies before adding any logo, and use only the files each supplies.
  - **Decided 2026-10-23: names in text, no logos.** Where the chat or settings name the provider, they write it. Providers are named by company, models by their own names (2026-10-23, the maintainer: tabs read OpenAI, Anthropic and Google; the chat's picker lists claude-… models under "Anthropic" and gemini-… models under "Google"). Logos are not planned; revisit only with each company's written permission and its own files.
- **Gemini key warning** (Design §3), checked 2026-10-23 against ai.google.dev/gemini-api/terms ("Unpaid Services"): on unpaid quota Google uses prompts and responses to improve its products, and human reviewers may read them; not in the EEA, Switzerland or the UK, where the paid-service terms apply to all use. The warning can say exactly that.
- **New dependency:** the native `anthropic` SDK (and `google-genai` if the evals pick it); the supply-chain check covers locked dependencies.
- **Database version:** per-provider key slots change the persistent schema, so they bump `CURRENT_DATABASE_VERSION` (currently 10) with a migration and encryption-audit update, as `AGENTS.md` requires.

From the design:

- **The web tool and the outbound allowlist.** `open_web_pages` (`app/services/agent/agent_tools.py:178`) fetches arbitrary pages from the vault process, which conflicts with a hosted allowlist that admits only known hosts. Options: a separate fetcher with no keys or notes, plus limits on the URLs it accepts; the web tool off in hosted mode; or direct fetching with only private and metadata addresses blocked. Not needed to ship the three providers, but needed before hosted launch.
- **Allowed host, someone else's key.** An allowlist by host doesn't stop code inside the process from calling an allowed provider with a different API key. Worth deciding whether the boundary should check that outbound AI requests carry the vault's own key.
- **Gemini adapter:** OpenAI-compatible Chat Completions or the native SDK (Design §1), decided by the evals.
- **Default model per provider.**
