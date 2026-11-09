# A decision model for tags and for choosing notes (future plan)

**Status:** Being designed, nothing built. Written 2026-11-07 at the maintainer's request, before any code, then measured the same day with a live benchmark on throwaway data (§7, $0.75). **Decided 2026-11-07:** the AI's word search (`search_view_notes`, notes containing every query word) is replaced by decision-model ranking of the notes in view, and that comes first (§4, §8 question 5). The other open questions are in §8. Numbers marked *estimate* remain worked out, with their assumptions beside them; *measured* numbers come from §7.

Vocabulary as in `docs/AI-SUMMARY.md`: users see **vault**; code says **namespace**.

---

## 1. What a decision model is

A decision model does not write. It reads a context, answers typed questions about it, and returns values code can act on, each with probabilities. Two exist (checked 2026-11-07):

- **OpenAI's Decisions API** (`POST /v1/decisions`, model `gpt-6-luna`, generally available; [guide](https://developers.openai.com/api/docs/guides/decisions), [reference](https://developers.openai.com/api/reference/resources/decisions/methods/create)):
  - One request has a shared `input` (text, messages or JSON) and 1–400 independent `questions`.
  - Question types: **predicate** (returns a probability), **choice** (one of 2–255 values, with a probability for each and a confidence), **score** (2–10 levels, a probability-weighted score). There is no pick-several type: several tags means one predicate per tag.
  - Price: $0.10 per million uncached input tokens ($0.20 above 272,000), cached input at the cheaper rate, **output free** ([pricing](https://developers.openai.com/api/docs/pricing)). For comparison, `gpt-5.6-luna` is $0.20 in and $1.20 out per million (long context $0.40 / $1.80).
  - Speed: OpenAI says "about 10x faster than the Responses API", with no method, baseline or absolute latency. Rate limits and the context window are not on OpenAI's pages (Vercel lists 1,050,000 tokens).
  - Probabilities are not claimed to be calibrated: OpenAI says to set thresholds from labelled examples.
  - Shared `input` can be prompt-cached (prefix ≥ 1,024 tokens); text inside `questions` is never cached.
  - US and EU processing; Zero Data Retention for eligible accounts.
- **Jev** (TypeSafe AI, September 2026): the same idea from another company. Not researched further.

## 2. What is measured today

**MetaList's own work** (100,000 generated notes, scripted AI that answers instantly, 2026-11-07, after `aa74790e`): a whole-vault question takes about 5 s before any AI: 2 s preparing the view, 2.2–2.4 s for the AI's word search, the rest small.

**Luna's own time**, from the maintainer's exported AI histories (`logs/metalist-llm-history-*.json`, 12 calls, `gpt-5.6-luna` through the Responses API, whole-second resolution):

| Input tokens (cached) | Output tokens | Seconds |
|---|---|---|
| 5,000–6,000 (0–4,800) | 13–140 | 1–3 |
| 38,775 (16,054) | 619 | 7 |
| 153,652 (38,772) | 1,019 | 10 |
| 274,989 (23,047) | 238 | 4 |
| 300,933 (276,985) | 1,389 | 13 |

Read roughly: about **1 s to start**, about **100 output tokens a second**, and input is cheap in time (a quarter of a million new tokens costs a second or two). *Writing is what is slow, not reading.* Twelve calls are a thin sample; §7 measures properly.

## 3. Purpose 1: choosing tags for notes

### Today

`docs/design/agent-harness.md`, "Tag Proposal Operations"; code in `app/services/agent/tagging_run.py`, `tagging.py`, `note_tag_suggestions.py`.

- **Suggest Tags with AI** (one note, or a note and its children): one structured-output call to the chat's model. It sends the note, its ancestors, a ranked vocabulary (up to 60 tags from the tag bar's own ranking, `suggest_tags_for_note`, then the 150 most used) and writes back up to 12 tags per note, at most 2 of them new (`MAX_NEW_TAGS`).
- **Bulk tagging from chat** (`propose_tag_generation`): the view's trees in batches of up to Model window used (by default half the model's window, about 500,000 tokens), the first batch alone, then 4 at a time. Each batch writes JSON proposals; the output is capped at 8,192 tokens (`TAG_BATCH_MAX_OUTPUT_TOKENS`). New tags are allowed unless the focus is "existing".
- The tag bar's own suggestions use no AI (about 200 ms a note; `docs/design/tag-suggestion-learnings.md` measured 4–5 ms for an experimental ranking with better Hit@5).

### With a decision model

- **Candidates come from MetaList**: the tag bar's ranking (or the faster experimental one) gives each note's 20–60 likeliest existing tags.
- **One request per note**: the note (and its ancestors) as shared `input`; one predicate per candidate tag ("Does this tag fit this note?"). Tags above a threshold become proposals, exactly as today (`proposed_tags`, accepted with +).
- **New tags**: a decision model only chooses among the candidates it is given; it cannot invent a tag. New tags stay with the chat model (see §8, question 1).

### How much faster (*estimates*)

| Operation | Today | With a decision model | Why |
|---|---|---|---|
| Suggest Tags with AI, one note | *Measured:* median 2.71 s, slowest tenth 4.21 s (Luna Low, the production request) | *Measured:* median 0.31 s, slowest tenth 0.88 s (53 tags as predicates) | Nothing is written: the answer is probabilities, and output is free. **8.7 times faster** at the median |
| Bulk tagging, 10,000 notes | *Estimate:* about 12 min: about 30 output tokens a note (note id plus three tags in JSON), 100 tokens a second per call, 4 calls at a time | *Measured rates, projected:* about 16 s. 200,000 questions (20 candidate tags a note) in 500 requests of 400, many notes in each request's input; a 400-question request takes about 0.8 s, 25 at a time | One request answers up to 400 questions in parallel (§7). About **45 times faster**, not measured end to end |

- **Cost is higher, not lower** (*measured*): every predicate question costs about 133 input tokens of OpenAI's own overhead beyond its own words, whatever the input (§7); the shared input is billed once a request. One note with 53 candidate tags took 9,400 input tokens, about $0.0009; Luna's one-note request took a median 1,400 in and 118 out, about $0.0004. For 10,000 notes with 20 candidates each: about $3.60 against Luna's estimated $0.70–1.30 (the higher figure when batches pass 272,000 tokens and long-context rates apply).
- **Quality** (*measured*, 50 hand-written notes with known tags, 103 tags in all): at a threshold of 0.6 the decision model found 92 of the 103 tags and added 19 wrong ones (F1 0.86); thresholds from 0.5 to 0.8 scored the same within 0.003. Luna, with today's one-note request, found 1: it proposed two new, more specific tags for every note instead (`sourdough`, `rome`, `kyoto` where `recipe`, `travel` and `japan` were in the vocabulary; §9).
- **What it needs from MetaList**: the candidate ranking must be fast. At today's 200 ms a note, ranking 10,000 notes alone takes 33 minutes; at the experimental 4–5 ms, under a minute.

## 4. Purpose 2: choosing which notes the main AI reads

### Today

`app/services/agent/agent_tools.py` (`_search_view_notes`), `investigation.py` (`read_root_trees`, `plan_complete_root_batches`).

- The AI's search keeps notes containing **every** query word (substrings, case-insensitive), then takes their whole trees **in list order** until Model window used (about 500,000 tokens) is full. The rest are "unread". There is no ranking by relevance.
- On 100,000 notes, the search for "harbor" matched 11,602 trees and sent the first 2,819 notes, about 512,000 tokens, to the AI.
- A whole-view summary splits the entire view into 500,000-token batches, each read and summarized by the chat model.
- The system prompt already admits the gap: a word search "cannot find notes by a category or meaning you would have to judge" (`prompts/agent.md`).

### With a decision model (decided 2026-11-07: replaces the word search, first)

- **Ranking**: each candidate tree gets a predicate, "Does this note help answer: <the user's question>?" (or a score of 2–5 levels). The candidates are **always the whole view**; no word search first (§10).
- **What Luna reads**: every tree above the threshold, with no budget. If they don't all fit, it answers in batches, as `docs/ready-to-build/ai-reads-whole-view.md` describes (§10).
- **Summaries**: a summary of a whole view reads every tree. The filter may narrow only a summary of notes fitting a description (§10).

### How much faster (*estimates*)

| Operation | Today | With a decision model | Why |
|---|---|---|---|
| A question answered from a broad search (the harbor case) | MetaList 5 s, then *measured* Luna 9.8 s reading 362,481 tokens and writing 642 | MetaList 5 s, then *measured*: ranking 11,602 trees (their first 400 characters) in 2.5 s, 30 requests at a time, and Luna 7.7 s reading 46,077 tokens and writing 557 | **Even**: 10.3 s against 9.8 s. Luna's time follows what it writes; reading 316,000 fewer tokens saved 2 s, and the ranking took 2.5 |
| A summary of a large view (for example 18 million tokens, 36 batches) | 36 Luna calls, each writing a summary: at about 1,000 output tokens each, 10 s a call, 4 at a time (assumed, as tagging; not checked in `staged_summary.py`): about 1.5 min plus the final combining call | Ranking the view's trees: 18 million tokens through the decision model, about 3–6 s at 20–50 requests at a time (same assumed 150,000 tokens a second); then 1–3 Luna batches: about 20–30 s | Writing fewer batch summaries is where the time goes |

- **Cost** for the harbor question (*measured*): today $0.15 for Luna's first read at the long-context rate, cheaper on later cached turns. With ranking: $0.25 to rank (about 215 input tokens a tree: 100 of text, the rest per-question overhead) plus $0.01 for Luna. **More expensive on the first turn**, cheaper only when the evidence would stay in a long conversation. Ranking the whole 100,000-note view would cost about $0.65 a question even on short candidates (37,203 trees at about 175 tokens each), so whole-view ranking needs the word search first.
- **The bigger gain here is not speed**: the AI finds notes by meaning, and when more matches than fit, it reads the relevant ones instead of the first ones in the list.

## 5. Where it fits in the code (*proposed*)

- A **decision role** beside the chat model in `ai_setup` (`docs/design/ai-providers.md`): asked "is a decision model set up", never "is there an OpenAI key", so the features stay provider-neutral. OpenAI's native API first; other providers could imitate it through structured output (slower, uncalibrated probabilities), or the features stay with today's paths.
- **Privacy**: the decision model sees exactly what the chat model may see. The cloud privacy boundary (`cloud_privacy.py`) and `@password` redaction apply before any note reaches it.
- **Off the request loop**, as the AI's note tools already are (`read_notes_off_request_loop`), with Stop ending the requests still running.
- **Thresholds from the vault itself**: tags the user accepted or rejected (`proposed_tags` history) are labelled examples for tag thresholds; nothing invented.
- **Fallback**: when the decision model fails, the whole view is read in batches, never a word search or a cut-off, and the chat shows which one answered (§10).

## 6. Invariants

1. A decision model never sees a note the chat model may not see.
2. The chat model still writes every answer and every new tag; the decision model only chooses.
3. A proposal from a decision model is a proposal like any other: nothing is tagged until the user accepts it.
4. When the decision model is off or unavailable, everything still works, without a partial read (§10).

## 7. Measured 2026-11-07

A live benchmark, approved by the maintainer as an exception to Luna-Low-only live evals, on throwaway data only: 50 hand-written notes with known tags from a 53-tag vocabulary, and the 100,000-note generated vault of §2. `gpt-6-luna` through `POST /v1/decisions` (the installed `openai` 2.54.0 has no Decisions client, so the script called the endpoint directly); `gpt-5.6-luna` at Low thinking through the Responses API, with the production one-note tag request (`note_tag_suggestions.request_messages`'s messages). The script and its results stayed in the session's scratch folder. Spent: $0.75 ($0.06 tags, $0.28 concurrency, $0.41 selection).

| Test | Luna today | Decision model |
|---|---|---|
| One note's tags (50 notes, one at a time) | Median 2.71 s, slowest tenth 4.21 s; 1,400 tokens in, 118 out | Median 0.31 s, slowest tenth 0.88 s; 9,400 tokens in, nothing out |
| Tag quality (103 known tags) | 1 found; 99 new, more specific tags proposed instead | 92 found, 19 wrong (threshold 0.6, F1 0.86) |
| Requests at a time, 100 each | | 10: 20 a second (median 0.32 s). 25: **45 a second** (median 0.38 s). 50: 6.6 a second (median 0.83 s, slowest tenth 2.6 s). No 429 at any level: past about 25, OpenAI slows rather than refuses |
| The harbor question | 9.8 s reading 362,481 tokens | Ranking 11,602 trees: 2.5 s (30 requests of up to 400 questions, 30 at a time); then Luna 7.7 s reading 46,077 tokens |

- **What OpenAI's "about 10x faster" means here**: 8.7 times at the median for one note's tags, where Luna had to write about 120 tokens. It is not 10 times faster at reading: the time saved is the writing.
- **Massively parallel**: one request with 40 notes as input answered 1, 10, 100 and 400 questions in 0.47, 0.22, 0.48 and 0.80 s (OpenAI's own processing 168, 96, 334 and 626 ms). 400 questions take about as long as one. So many notes go in one request's input and the questions name them ("Is note 12 about travel?"); 1,000 answers are three 400-question requests sent together, back in under a second. The one-note tag test above asked only 53 questions a request, the wrong shape for bulk.
- **Billing**: the shared input is billed once a request (40 notes, about 1,900 tokens, were not billed again per question). Each question adds about 133 tokens of overhead whatever its length: 400 questions on a near-empty input billed 53,312 tokens. Questions are never cached. That overhead, not the note text, sets the cost: about $0.006 for 400 answers.
- **Jev** (TypeSafe, `docs.typesafe.ai`): the same shape with no cap on questions (64,000 tokens a request, 32,000 for the input plus any one question), input billed once at $0.042 per million tokens, no per-question overhead stated, 70–500 ms a request. Not measured: it needs its own key.
- **Not measured**: a real vault's notes and tags, a bulk run end to end, rate limits on other accounts, and probabilities' calibration beyond these 50 notes.

Ranking in this benchmark used each tree's first 400 characters and a reading budget. §10 replaces both, so these figures and the §4 estimates understate what ranking costs.

## 8. Open, for the maintainer

1. **New tags**: a decision model chooses only among existing tags. Keep new-tag suggestions on the chat model (both run, results merged), or make decision-model tagging existing-only?
2. **Provider-neutral**: only OpenAI offers this natively. Is an OpenAI-only feature acceptable, with other providers keeping today's path?
3. ~~**Benchmark**~~ **Done 2026-11-07** (§7). **New:** the decision model costs more per tag than Luna (per-question overhead). Is about $3.60 per 10,000 notes acceptable for 3 times faster bulk tagging and much faster one-note suggestions?
4. ~~**Note selection**~~ **Decided 2026-11-08:** full text, with the note's file text too when that switch is on. A landlord's number on a long note's last line has to count (§10).
5. ~~**Order of work**~~ **Decided 2026-11-07:** replacing the AI's word search with decision-model ranking comes first. The maintainer: matching literal words is worse than retrieval by meaning, and it should not be how the AI finds notes. Tags come after.

## 9. Found while writing this

- **Built 2026-11-07**: summaries and tagging no longer send at most 4 batches at a time; as many go at once as the provider's rate limits allow, and a refused or overloaded request waits and goes again (`app/services/agent/provider_limits.py`; `docs/design/agent-harness.md`). The chat model's "4 requests at a time" figures above describe the old behavior.

- *To verify on a real vault*: today's one-note request (Suggest Tags with AI) sends `tagging_mode: "new"` with focus "both". On the 50 benchmark notes (no tags yet, every right tag in the vocabulary), Luna proposed two new tags per note and found only 1 of 103 existing ones. In a real vault the vocabulary is ranked by the tag bar first, so it may do better; if it doesn't, existing tags are not being suggested.

- *To verify*: a bulk tagging batch may hold up to 500,000 tokens of notes (about 2,700 notes), but its output is capped at 8,192 tokens, about 270 notes' proposals at 30 tokens each. A batch that needs to tag more notes than that may be cut off. Not tested; worth a test whatever this plan decides.

## 10. A relevance filter never caps what the AI reads (agreed 2026-11-08)

**The AI must never miss the needle in the haystack.** The maintainer: "if they need to see more, we'll just batch it." Showing only the top N notes, or the top so many tokens, is never acceptable, in any feature that chooses what the AI reads. This goes with `docs/ready-to-build/ai-reads-whole-view.md`.

What the filter may do:

- **Drop what isn't relevant, never what doesn't fit.** Size is never a reason to leave a note out.
- **When it isn't sure, the note goes in.** The threshold is low, tuned from labelled examples so that missing a relevant note is rare; extra notes only cost a little more.
- **The answer says it was filtered,** with **Go through everything**, which reads the whole view in batches, after the size warning if it's large.
- **The size warning counts the filter's pass** and names where the text goes: everything sent to the filter and everything then sent to the main AI.

Which model is not decided. The maintainer expects OpenAI's Decisions API not to be cheap enough at full text, and Jev to be the cost-effective choice, so measure Jev first (it needs its own key), on full text and on real-sized views. If it's Jev, it is a separate provider receiving the notes: its own key, its own line in the AI settings and the privacy wording, and only what the chat model may see. Check its data retention and training terms first; nobody has yet.

Invariants:

1. No feature limits what the AI reads to a top N or a size budget.
2. Only relevance removes a note, never size, and uncertainty keeps it.
3. A filter failure never falls back to a partial read.

Checked when filed: the design and UI docs still describe today's partial read in `docs/ui/ai-chat.md` ("trees were left unread") and the evidence budget in `docs/design/agent-harness.md`; those change when `ai-reads-whole-view` is built. Bulk tagging's **Use first K only** is no exception: it goes when that note is built (§7 there).
