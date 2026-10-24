# AI providers: what is left

**Status:** Agreed with the maintainer 2026-10-23, not scheduled. The rest of the AI
providers design is built and documented in `docs/design/ai-providers.md`; this note holds
the parts that were not built when `feature/ai-providers` merged (2026-10-24).

## 1. Eval runs for every shipped model

**Done when:** each provider has run the `evals/` agent cases and the summary/tagging cases,
with per-provider pass rates recorded (for example in `evals/RESULTS-*.md`). All three are
required for the hosted launch. Claude and Gemini are offered already (the maintainer
dropped the "evals first" rule on 2026-10-23), so these runs measure, they do not gate.

- Agent eval cases are fixed to `gpt-5.6-luna` in code (`evals/agent_models.py`,
  `model: Literal["gpt-5.6-luna"]`); widen the schema to the chosen Claude and Gemini models.
- Live evals so far ran on Luna at Low thinking only (the maintainer's standing rule: Luna
  Low only, runs kept quick). Runs on other models need the maintainer's keys and explicit
  go-ahead, since they cost money.
- Sol and Terra are listed in the catalog but have not been through the evals either.
- **Gemini adapter choice:** Google's OpenAI-compatible Chat Completions (built) or the
  native `google-genai` SDK. Switch only if the evals show strict structured output or
  streamed tool calls falling short through the compatible endpoint, and record why.
- Not yet checked live: Sonnet 5.5, Opus 5.5, Gemini 4 Argon; the 30/60/120 s silence
  limits for Anthropic and Google (`UNMEASURED_SILENCE_LIMIT_SECONDS`).

## 2. Demo vault

The anonymous demo vault has **AI off by default** and says so in the AI panel: the demo is a
tour of MetaList's interface and features, with the AI not turned on. A visitor may paste
their own key for any of the three providers. That key is held only in that demo process's
memory (the plaintext-namespace session path), never written to the demo template or
anywhere else, and is gone when the demo is discarded. The key field says this and suggests
a separate, spending-limited key the visitor can revoke afterwards.

Check that the chat panel's hover preview of which notes the AI may see works with no key
set, so demo visitors without a key still see the exclusion rules at work.

**Open:** the demo vault does not exist yet; nothing in `app/` or `docs/` describes it. This
belongs with the hosted plan, `docs/future-plans/hosted-own-copy.md`.

## 3. Hosted launch questions (ask the maintainer)

The hosted deployment restricts each vault process's outbound network to an allowlist built
from the provider catalog (`app/services/ai_catalog.py`).

- **The web tool and the allowlist.** `open_web_pages` (`app/services/agent/agent_tools.py`)
  fetches arbitrary pages from the vault process, which conflicts with an allowlist of known
  hosts. Options: a separate fetcher with no keys or notes, plus limits on the URLs it
  accepts; the web tool off in hosted mode; or direct fetching with only private and
  metadata addresses blocked.
- **Allowed host, someone else's key.** An allowlist by host doesn't stop code inside the
  process from calling an allowed provider with a different API key. Decide whether the
  boundary should check that outbound AI requests carry the vault's own key.
