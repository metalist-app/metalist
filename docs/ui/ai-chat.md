# AI Chat, Product Help and Scoped Investigation

**Agreed, not built (2026-11-08):** the AI will read the whole view in batches rather than part of it (`docs/ready-to-build/ai-reads-whole-view.md`), a line will show how much text a conversation has sent (`docs/ready-to-build/ai-chat-size-line.md`), and conversations will survive a restart (`docs/ready-to-build/ai-chat-survives-restart.md`).

## Scope

- MetaList chats with one user-selected model (OpenAI, Anthropic or Google) through an
  authenticated, application-owned agent runtime.
- Every Send freezes the currently displayed MetaList result scope. The agent can
  investigate only matching notes inside that boundary; it cannot run a new
  namespace-wide search or escape to hidden notes.
- Investigation is read-only. Explicit requests can generate, accept, or remove
  tag proposals through the separate bulk proposal workflow. The agent cannot
  create, edit, move, trash, or delete note bodies.
- Product questions load selected MetaList help skills. Requests can open an
  existing settings/help dialog or highlight a menu command. Highlighting does
  not execute that command; forms are not submitted and settings are not changed.
- The agent answers by calling tools (help lookup, menus, reading notes in the
  view, opening web pages, tag operations, summaries) and then streams its answer
  directly from the selected provider. Instructor remains for the structured
  summary and tagging batches. OpenAI requests disable provider-side storage.
- While a provider generates, the active eye-mode panel shows an approximate output-token
  count that updates in place with a subtle pulse; completed panels retain the final
  count separately from their input estimate.
- Answers have no output limit of MetaList's own (decided 2026-10-24): OpenAI and
  Gemini are sent none, and Claude, whose API requires one, its models' maximum
  (128,000 tokens). Only a runaway reply reaches a model's maximum; then the chat keeps
  what was written and says under it: "<model> reached the longest answer it can write
  before finishing (its thinking counts toward that), so the answer stopped there.
  Anything it wrote is kept above. Ask it to continue, or ask for a shorter answer."
  (`OutputLimitReached`). Structured steps (summaries, tag work) keep their own budgets,
  at least 8,192 tokens, since thinking counts against them; a cut-off there is retried
  and explained (below).
- When a structured step's reply is rejected on every attempt (cut off at the output
  limit, not matching the required format, empty, or refused), the chat explains the
  failure in the error itself: which step failed, what went wrong on each attempt in plain words (including the
  rule broken and what the model chose), the setup (model, thinking level, web
  access), and what to try. The explanation is saved with the turn, so a screenshot is
  enough to diagnose it; Agent Debug remains for the raw requests and responses
  (`app/services/agent/failure_explanations.py`).
- OpenAI models sometimes wrap a citation in ChatGPT's own markup (U+E200 `cite` U+E202 … U+E201), which would show as boxes and a stray "cite". `ChatTurnStream` removes it as the answer streams (`strip_provider_citation_markup`, holding back markup that has not closed yet), keeping MetaList's own `[[…]]` citations inside it, so the chat, the saved answer and copied text never contain it.
- A whole-view summary that fails or is stopped keeps its finished batches for the chat (the explanation says how many); asking again ("try that again") continues it: only the remaining batches run, with the original question, and the progress says "Reusing your earlier attempt". A different question starts fresh.
- Until OpenAI sends its first signal for a request, the heading reads "Waiting for OpenAI…" with the elapsed seconds instead of "Thinking…", so a network stall does not look like thinking.
- A request OpenAI never answers fails after a silence limit instead of the library's 10 minutes: 15 s at Off and Low thinking (measured on Luna: first signal in 0.7–2 s and streaming gaps under 0.4 s, also with a 180,000-token input), 60 s at Medium and 120 s at High (generous, not measured, since a model may think silently before its first word). The explanation says "OpenAI did not respond for 15 seconds. Check your internet connection and ask again." The same holds when OpenAI goes silent partway through an answer; a connection that drops partway says "The connection to OpenAI broke off. Check your internet connection and ask again." Google and Anthropic do the same with their own silence message and name ("The connection to Google broke off…").
- Google's overloaded models hang without sending anything (3.8 Flash, 2026-10-24: no answer in two minutes while 3.5 Flash-Lite answered in 3 s), so when Google stays silent the message says "Google did not respond for 30 seconds. gemini-3.8-flash may be busy at Google: ask again later or pick another model." When Google answers that the model is busy (HTTP 503), it says "Google says gemini-3.8-flash is busy right now. Ask again later or pick another model." A failed structured step names its provider on each attempt ("Google did not respond…", "Google said … is busy right now") and suggests asking again later or picking another model, then checking the connection if no model answers.
- Every failure explanation ends with where the run stopped: the step it was in (and for how long) or had just finished, the step before, and an operation's latest progress, for example `Where it stopped: during "Thinking" (15.2 s into that step), step 3 of the run; before that: "Scope ready · …".`
- The first activity line says how long preparing the view took ("Scope ready · All notes · 45,479 notes in … result trees · prepared in 0.2 s"). Preparing records which notes are in view and their content as of Send, but extracts a note's text only when a tool first reads it, so a question that reads no notes does not pay for the whole view. Cloud privacy rules that match phrases still read every note's text at Send to decide what is private.
- A step that extracted note text says how much on its line, for example "Search complete · … · text extracted for 45,480 notes in 3.8 s" (the first search in an answer reads every note in view; later steps reuse the text). A stored note's text starts from the visible text the vault already keeps for search, with the link addresses and cached titles added without Python's HTML parser: about 15 µs a note instead of 52 (100,000 generated notes, a fifth with links, 2026-11-07); only an unsaved draft is parsed. A whole-view summary reports it on its "Planned N evidence batches" line.
- Stop no longer ends in a fatal error: the "Cancelling request" activity carries the fields every activity needs.
- The AI remembers a failed request and the explanation you saw, so you can follow up
  with "try that again" or ask why it failed (`docs/design/agent-harness.md`).
- A Send that MetaList refuses before the AI starts (the AI is not set up, the active search context changed, a message it rejects) stays in the chat with the reason, so the message is not lost and the reason says what to fix. The server keeps no record of such a turn, so the page keeps it (`ai-chat-refused-turns.js`) and puts it back after the server message it followed each time the chat reloads: later Sends leave it in place, in order. Clear chat clears it, a refused turn goes with the earlier message it followed when the server trims old history, and reloading the page forgets it. The AI never sees refused turns. A connection lost mid-answer is not a refusal: the server has that turn.

## Web access

**AI Agent Settings** (its Reading tab) has three enforced browsing modes:

- **No web access** is the default. The agent cannot open pages and
  explains that limitation when a request needs the web.
- **Open links from permitted context** can open only exact URLs supplied by the
  user or present in note/evidence content that passed the same disclosure
  boundary as the rest of the prompt. Links found inside an opened page do not
  become available.
- **Open any public web page** lets the agent propose direct public HTTP(S) page
  URLs even when they are not in the current note or conversation. Ordinary
  lookups open a Google results page and then useful result pages through the same
  MetaList page opener. No LLM provider supplies search or retrieval, and MetaList
  has no separate search-engine action.

The web-browsing skill tells the agent to batch up to eight URLs,
reuse duplicate pages, treat page text as untrusted evidence, and explain what
the active mode permits. Page opens support HTML, plain text, and PDF. Individual
pages can fail or be truncated without discarding successful siblings.

Successful pages remain in bounded server-memory chat evidence for follow-up
questions. Clear Chat, logout, a disclosure-boundary change, server restart, or
runtime reset removes that evidence. Web claims use their own external reference
links; responses can cite disclosed notes and web pages together. A direct article
summary references the opened article. For an aggregator, directory, index, or
search-results summary, named items reference the visible destination links from
that page instead of only the containing site. Those destination references do not
mean MetaList opened or read the linked pages, and they do not make the links
available to contextual browsing.

## Product help and menus

Questions about MetaList itself are answered only from help: the agent looks up
the relevant topics (notes, search, tags, formatting, references, menus,
reminders, AI, privacy, data, or release notes) and answers from those skills.
Help text is not retained in later conversation turns; the export records exactly
what the model saw. "Where do I…" and "how do I change…" questions look up help and then open the menu
that holds the setting.
A request only to open a menu opens it directly, and no menu opens for a feature
MetaList does not have.

Examples: “How does tag inheritance work?” explains from the tags skill.
“Open AI settings” opens that dialog. “How do I change context to 250k?” opens
AI settings and identifies Model window used = 24% (on OpenAI's 1,050,000-token window), leaving
the user to save. “Open Create backup in the menu” highlights its command without
creating a backup.

Before opening, the browser checks the originating scope, cancellation and other
open dialogs. It acknowledges actual visibility, and the agent is told whether the
menu opened. Missing acknowledgment times out after 30 seconds and is reported as
unavailable. Exported LLM history includes the requested destination and browser
result, rather than treating model prose as proof of execution.

## Scope at Send

The browser captures one required view descriptor from the active search context:

- normal search, All notes, Untagged notes, or temporary Reference source;
- executed search text;
- sort mode;
- reference UUIDs where applicable;
- a human-readable scope label.

The server verifies that the descriptor targets the active search context and matches its
canonical search/sort state, then resolves actual note membership itself.
The browser never submits a trusted corpus-sized UUID list. Later typing, search-context
switches, or reference navigation do not change the running request.

The assistant turn does not repeat this scope above its response. When developer
diagnostics are visible, the scope-freezing activity panel shows the label and
note/tree counts.

With developer diagnostics hidden, an in-progress turn uses one stable
`Working…` row whose dots animate without replacing the label or resizing the
panel. If the evidence limit omits trailing roots, a calm informational notice
appears before the answer as `Only using X of Y root notes for answer`; detailed retention
counts remain in Agent Debug.

The same note/tree counts are supplied to the agent before note content is loaded.
Note content reaches the model only through the note tools; their activity panels
report what was read and its approximate token count.

Every Send captures a fresh authoritative MetaList scope. Conversation history is
used to resolve follow-ups, but earlier assistant claims about unavailable notes do
not override the newly captured scope. Retrying an unresolved note-dependent task
after changing the search or context re-investigates that current scope.

Only true matching nodes become evidence. Ancestors needed to make the result tree
readable appear only as contentless structural objects. Gray/redacted content is
excluded. A protected `@password` or `@username` note hides itself and its complete
descendant subtree from every model.

Before a cloud scope is frozen, MetaList also applies the namespace's shared cloud
privacy policy. Tag whitelists and blacklists use inherited and ontology-expanded
effective tags; text lists use case-insensitive literal substrings. Entries in a
whitelist are OR, entries in a blacklist are OR, and blacklists win. If any ancestor
is hidden, every descendant is hidden as well. The resulting filtered set—not the
original search set—drives counts, evidence, references, and debug payloads.

## Investigation Behavior

The agent decides from the conversation which tools it needs; there is no keyword
classifier. General conversation needs no tools. When the selected note's tree
already holds the answer, it answers from that. Otherwise it reads the frozen
result view with:

- `view_overview`: counts, the selected note's tree and a preview of each tree;
- `search_view_notes`: notes containing every query word, with their trees;
- `read_view_notes`: whole trees for given notes, or the view in order.

Reads take complete trees in visible order until the evidence limit; a result says
which trees were left unread (readable in a later call) or are too large on their
own. The model sees short note ids (`n1`, `n2`…) instead of UUIDs and cites them as
`[[n12]]`; MetaList turns these into ordinary note references as the answer streams. A
summary's batches, condensing stages and final answer use the same short ids (2026-11-08,
after a summary failed on a miscopied UUID): about 20 tokens less per note, 11% of a generated
45,000-note vault's evidence.

`summarize_view` is for summarizing, comparing or synthesizing the complete view.
In an empty view the agent says there is nothing to summarize.

A summary starts without a question, however large the view (2026-11-08; before, one that
needed several batches asked first): one ordinary model call when the whole scope fits in one
evidence payload, otherwise batches. Tag proposals ask one card first: the scope's size as a
multiple of the evidence budget, the tag-focus selector (existing, new, or both), then
"Tag all N", "Use first K only" when the scope exceeds the evidence budget, and
Cancel (last and tinted red). Complete processing keeps every root tree intact,
has no cap on the total number of batches, and sends as many model requests at once
as the provider's rate limits allow (2026-11-07; before, at most four): every batch starts
at once (2026-11-08; before, the first ran alone to seed provider caching, a whole batch's wait
for a small share of each batch), four until a first answer reports the account's limits, and
the findings are restored to original scope order before synthesis. Each model's limits are saved
in the vault, encrypted like the AI settings, when an answer reports new ones (2026-11-08, database
version 15, `app/services/agent/saved_rate_limits.py`), so after a restart the batches go out as
the account allows from the first one; that first answer still corrects them. When several batches fail,
the lowest-numbered failure is the one reported. A request
the provider refuses as too many (429) or answers as overloaded waits the time the
provider names and goes again, so a busy moment no longer fails the summary
(`app/services/agent/provider_limits.py`).
The progress widget sits in the conversation immediately above the answer it is
producing: earlier messages and the current request stay above it, and the final
answer streams in below it. It is one bar, with a status line such as "Summarizing · 42%" on the left
of the row under it and the processing time on the right (`1m 23s` past a minute, still counting every
second; "Processing time" is its tooltip). Before 2026-11-08 it was a scrolling card per batch with
batch counts in the text. The widget closes when every batch has finished and the final answer is
requested.

No provider says how far along a model is, and a batch spends most of its time reading before it
writes anything, so the bar is an estimate from the clock (agreed 2026-11-08). Each model's timing, a
startup cost and a time per million tokens, is saved in the vault after a summary finishes, encrypted
like the AI settings (database version 16). Two batches of different sizes separate the two, so a model
with no saved timing starts with two small real batches, a tenth and a fifth of a normal one; a view
that fits one batch has none. The estimate weighs each batch by its size, moves it by the clock up to
90%, counts it at least half done once its response starts arriving, and is corrected by this run's
own batches once two have finished. The bar does not show the estimate directly, since an estimate can
jump, stand still or fall behind: it starts at 5%, glides toward the estimate and always creeps toward
95%, so it never stalls or goes backward, and only every batch finishing fills it.

If the verified batch findings are themselves too large for one synthesis call,
MetaList condenses them through additional ordered stages until they fit. Exact
root coverage and disclosed original-note citations are validated at each stage. After one
correction, a citation to a note the batch was never sent (a garbled ID) is dropped and listed in
the diagnostics rather than stopping the summary (2026-11-08); other invalid citations still stop it.
The final answer appears only after every batch succeeds. Failure or cancellation
stops outstanding work and never presents a partial result as complete.

Every retained note carries its full disclosure-safe content. The agent is told
exactly which trees it has not read and must not claim exhaustive coverage of them.

The agent cannot expand beyond the frozen scope or cite an undisclosed note ID. Those boundaries are enforced programmatically.

## Ordering and Evidence Limit

- Evidence uses MetaList's canonical top-level result-tree order and visible node
  order. SearchIndex membership never becomes ordering.
- Results near the top are generally newer or more highly user-ranked, which is a
  prioritization hint rather than relevance proof.
- Each note read packs complete result trees up to the limit, a percentage of the
  model's context window (default 50%, configurable from 1–100%).
- A root tree is never divided. If the first root alone exceeds the limit, the run
  fails visibly; otherwise the first root that would overflow and all following
  roots are omitted.
- Matching notes are not character-truncated. The evidence limit applies only to
  the complete serialized payload.
- The estimate covers compact serialized JSON, including content, UUIDs, tags,
  timestamps, hierarchy, object keys, and punctuation. The same deterministic
  estimator drives the debug-panel token estimates.
- The payload is a `trees` array of root note objects with recursively nested
  `children`, not a flat note list. Content-bearing nodes expose note IDs, content,
  created/updated timestamps, and directly assigned raw tags in tag-bar order.
  Untagged notes omit `tags`; leaf notes omit `children`; parent/root IDs are not
  repeated because nesting already communicates the hierarchy.
  Contentless `is_evidence: false` ancestors preserve paths to nested matches
  without disclosing gray/redacted note information.

The only retrieval control in `AI Agent Settings…` is **Model window used** (its `?`
explains it in a tooltip): how much of the model's context window what one read returns may
fill, as a percentage, so one setting fits every model (agreed 2026-11-08; before, a number of
tokens. One saved earlier reads as its share of OpenAI's 1,050,000-token window, so 500,000 is
48%). Room for the prompt and a batch's answer is always left. Claude and Gemini report their
windows through their APIs, asked once per model while MetaList runs (`docs/design/ai-providers.md`).
Tagging batches use the same limit; there is no separate tagging window.

## Providers and Configuration

- Three providers on the user's own keys, named by company: OpenAI, Anthropic (Claude
  models) and Google (Gemini models), registered in `app/services/ai_setup.py` with their models in
  `app/services/ai_catalog.py` (design and what is verified live:
  `docs/design/ai-providers.md`; what is left: `docs/future-plans/ai-providers-remaining.md`). The chat's model picker lists the models of
  each provider with a key, under the provider's name; picking a model picks its
  provider.

- Defaults: `gpt-5.6-luna` and 50% of the model's context window read at once. Saved model
  and limit overrides are retained; the retired tagging batch preference
  (`pref.ai.openai.tagging.batch_tokens`) is dropped from the vault.

- Open `AI Agent Settings…` from the command palette or chat gear. Four folder tabs and
  one Save (agreed 2026-11-07; before, one long page and a separate AI Tagging Vocabulary
  dialog):
  - **Keys**: a switch per provider (OpenAI, Anthropic, Google); it starts on the provider
    the chat uses. The switch only shows that provider's settings and picks nothing. It
    holds the API key (saved, changed or removed at once, apart from Save: "Key saved,
    encrypted in this vault" or "Key saved for this session") and a **Usage and billing**
    link to the provider's own page.
  - **Privacy**: the privacy rules (below).
  - **Reading**: **Web access**, three segments, Off / Links in your notes / Any public
    page, each explained in its tooltip; and **Model window used**, a percentage, with a `?`
    whose tooltip explains it.
  - **Tagging**: **Tags the AI may propose**, Existing tags only / Existing and new tags
    (`pref.ai.tagging.vocabulary`; neither until chosen here or when a tagging run asks).
  - `AI Agent Settings…` opens on Keys, `Cloud AI Privacy…` on Privacy with the cursor in
    its first rule field, and `AI Tagging Vocabulary…` on Tagging.
  - Every tab's panel is drawn, stacked in one place, and only the open one is shown: the
    dialog keeps the size of the largest whichever tab is open, and switching tabs redraws
    nothing, so what is typed but not yet saved stays. One Save saves every tab; a value
    that did not change is not written again.
- The dialog has no model or thinking picker: both are chosen beside chat Send.
- The Google tab says under the key, with Google's terms in its tooltip: "Use a key
  with billing turned on: on the free tier, Google may use what you send to improve its
  products, and people may read it." (Not in the EEA, Switzerland or the UK.)
- **Model picker** (chat composer): the models of every provider with a saved key,
  plus the provider of the model picked last even without one
  (`GET /api2/ai/model-choices`, a read that never blocks a note change), each provider's under its name, even when there is
  only one. Picking a model picks its provider too (an option's
  value is `provider model`, `ai-model-names.js`). Saving or removing a key reloads
  the picker. Each provider lists only the models MetaList ships
  (`app/services/ai_catalog.py`). A user never types a model in: a model is offered
  once it has been tested with MetaList's prompts (the regression evals), because a
  model can be too weak to give reliable results, or need model-specific prompts
  (decided 2026-10-23; a typed-in "Your models" list existed for a day and its saved
  preferences, `pref.ai.<provider>.added_models`, are dropped when a vault loads). A
  saved model a later release no longer offers leaves the picker blank; the picker has
  no "Select model" prompt. A request naming any other model is refused politely
  (`ai_catalog.require_shipped_model`); a provider's API address is never editable.
- The same settings modal has one privacy section shared by all cloud providers:
  **Never send notes with (blacklist)** and, behind its checkbox, **Only send notes
  with (whitelist)**. Each is a row of chips with one input: Enter adds the entry, a
  tag as typed or "a phrase" in quotes; a pasted list becomes one chip per line; a
  chip's × removes it. The whitelist stays open while it has entries. They are
  stored as four lists (whitelisted tags and phrases, blacklisted tags and
  phrases). The automatic `@password` and `@username` boundaries also apply, as the
  section's one line says. The policy is namespace-scoped and is encrypted with client preferences
  when the namespace is password-protected.
- Hovering the AI chat column asks the server to preview that boundary over the
  current note view. Notes the selected provider cannot receive have a gray
  background and blurred content until the pointer leaves chat. Excluded
  descendants are blurred too.
- The compact composer controls choose model and thinking (High, Medium, Low, Off,
  listed most thinking first).
  Selection persists immediately: the last choice is the one used next time.
- A compact estimated-spend tracker, a developer tool: it exists only when
  `METALIST_ENVIRONMENT=development` (the panel's `data-shows-cost-estimate`; in
  production the **$** button never shows and the cost routes answer 404). Users see
  what they spent on their provider's own billing page. It appears directly below the
  chat header when the header's **$** button is on (off by default, remembered per
  namespace as `pref.ai.show_spend`; it keeps counting while hidden). Its four token totals are New input, Cached input, Cache writes, and
  Output. Values come from OpenAI's response usage rather than MetaList's prompt
  estimator and update after each completed intermediate or final request. Reset
  returns the process-local aggregate to `$0.00`; clearing chat does not. Nothing
  from this tracker is persisted, and an interrupted request that never returns
  final usage may be absent from the estimate.

- Ollama support has been removed. Legacy local-provider preferences are discarded
  on load/save. If Ollama was selected, any saved OpenAI model selection is also
  cleared so the default OpenAI model is used. Existing OpenAI
  configurations retain their model, credential, privacy policy, and limits.
  MetaList no longer launches local model servers or downloads models. Existing
  external installations, downloaded models, runtime files, and backups are untouched.

Prompts and skills are packaged and not editable, so every user gets the behavior
the evals measure. Overrides saved by older versions (`pref.ai.prompt.*`,
`pref.ai.skill.*`) are ignored when preferences load and dropped the next time
preferences are saved (`RETIRED_PROMPT_PREFERENCE_KEYS` and
`RETIRED_SKILL_PREFERENCE_KEYS`).

## Panel and Cancellation

- `Show/Hide AI Chat` is available in the command palette and notes-view context
  menu.
- Chat starts at one third of the viewport and narrows the notes area. Dragging its
  separator persists width while retaining at least 280 px for chat and 480 px for
  notes. Composer height also persists.
- The header contains a default-off developer eye toggle, Agent Debug, Clear,
  settings, and close. Eye visibility is namespace-scoped and survives restart.
- With eye mode hidden, an active request still shows one compact Working indicator
  with phase and elapsed time. With eye mode visible, tinted panels report scope,
  model attempts/retries, selected action and reason, retained/omitted root counts,
  the exact evidence payload, and response writing. Logical start/completion events update one
  panel; retries remain separate. Every panel includes approximate input tokens;
  model-generation panels also show approximate output tokens as chunks arrive.
  Every panel shows its own retained duration; the current panel counts live and
  completed durations remain visible after reopening the chat.
- The composer remains editable during generation. Send becomes red Stop and aborts
  browser/server provider work. Clear Chat cancels and awaits any active request before
  clearing transcript and latest trace. No status/error line is placed below the
  composer.
- A Thinking disclosure appears only if the model emits real reasoning; Thinking
  Off never shows a fake heading.

## Rendering and References

- Right-click anywhere inside a completed response bubble, including its padding
  and links, to choose **Copy Response**. Streaming and failed responses do not
  offer this action.
- Assistant output is rendered as Markdown during streaming. Completed LaTeX and
  fenced Mermaid are supported. Blank lines between ordered-list items produce one
  loose list rather than restarting numbering. Explicit non-one list starts are
  honored, and repeated model-generated section markers are normalized to sequential
  numbering.
- The final model receives exact evidence-note sources with a ready-to-copy
  `[[UUID]]` token beside each source. Every note-derived paragraph or list item is
  prompted to copy the token from the same evidence object that supports its claim.
  Invented, stale, unobserved, and prior-turn references are stripped; the server
  assigns the visible reference numbers programmatically. Tokens are written
  directly after claims without model-generated `Note ID`/`Source` labels.
  Standalone model-generated source bullets and links are removed programmatically;
  any valid citation token on that line is retained on the preceding claim.
- While a response streams, an incomplete trailing `[[UUID]]` token is withheld
  until both closing brackets arrive. It therefore appears atomically as the final
  numbered citation instead of briefly rendering as a note-title mention.
- Inline markers render as clickable superscript `[1]` links. A separate References
  section contains preview-labeled links deduplicated by top-level result tree;
  `Open all references` is available for multiple roots. References are withheld
  until streaming completes, then appear inside a collapsed disclosure. Completion
  scrolls slightly past the answer so the disclosure heading is visible without
  automatically exposing or scrolling through the reference list.
- Tag-generation result messages keep their clickable inline markers but replace
  the References disclosure with one **Show all new tag proposals** link. It opens
  the same combined exact-note view as `Open all references`.
- Root deduplication is presentational only. Each reference retains the exact cited
  child UUIDs as its hidden navigation query. If multiple cited children share a
  root, the query is `UUID1 OR UUID2`; normal search behavior preserves both paths
  and gray-redacts unrelated siblings.
- Individual/all-reference navigation uses the temporary Reference source context,
  leaves the visible search field empty, labels the temporary search context `Reference source`
  instead of displaying its internal exact-note filter, excludes that filter from
  search history, and provides the dismissible X to return to the prior search context.
- Common UUID dash substitutions are normalized programmatically. UUIDs in fenced
  code/existing links remain literal.
- In a note holding a copied answer, `References` stays open or closed as left while the note redraws (each link title or icon that arrives redraws it, 2026-11-09). A reload, or editing the note and leaving it, draws it closed: the state is not saved in the note.
- Right-click a completed answer and choose `Copy Response` to copy Markdown tagged
  `@markdown @ai` into the MetaList note clipboard and rich/plain content onto the
  system clipboard. After pasting that response as a note, its References disclosure
  remains interactive in view mode: opening or closing it does not enter edit mode
  or begin a note drag.

## Long chats

A chat never drops a turn silently. When it outgrows its budget, its oldest turns are
replaced by a summary that the user can open and read, and the summary is exactly what
the AI knows about them (built 2026-10-30, `app/services/agent/chat_compaction.py`).

- **Budget.** The history (summary, turns and the agent's records) may take a quarter
  of the model's context, at most 32,000 tokens (`history_budget`). There is no message
  count limit any more.
- **Automatic summary at Send.** When the summary, the turns and the new message would
  pass the budget, the oldest turns are summarized first, together with the previous
  summary, until the turns kept fill half the budget, so the next Send does not summarize
  again. The chat shows it as an activity, "Summarizing earlier conversation", then
  "Earlier conversation summarized". There is only ever one summary in what the AI is sent,
  as the first message, and summarized turns are never sent again.
- **Summarize Now** (right-click a completed answer, or the palette's
  "AI Chat: Summarize Now") summarizes every turn the AI still sees directly. A working
  line "Summarizing earlier conversation…" stands at the end of the chat; the entry
  replaces it there, and the chat scrolls the minimum distance to show it. With no turn
  since the last summary, the menu hides the item and the palette says
  "Nothing to summarize yet" in a floating card. Enter meanwhile keeps the message and says
  "Wait for the summary to finish"; the server refuses a Send during a summary (`409`).
  Clear waits for the summary, then clears it with the rest.
- **Length.** A summary is at most a third of the tokens it replaces (never under 60
  tokens) and never over a tenth of the budget (`summary_token_limit`); the prompt asks
  for half that many words. One that comes back empty or too long fails with a red
  message and nothing is summarized. The prompt
  (`app/services/agent/prompts/conversation-summary.md`) keeps decisions, facts, open
  questions, what the user asked to remember and what the agent did, and names notes by
  title as plain text: earlier turns reach the AI without their citations, so a summary
  cannot cite.
- **What the user sees.** The summary entry sits right after the last turn it replaced,
  collapsed to one line, "Earlier conversation summarized"; opening it shows the summary
  and keeps its header line still. Summarized turns stay on screen, grey and italic.
  Copy Response works on the entry. Summarizing never moves what the user is reading: the
  latest turn when the chat is scrolled to its end, otherwise the item at the middle.
- **Privacy.** A summary is a turn like the others: when the privacy settings change or
  a note the AI could see becomes private, the history and the summary are held back
  together. Adding, deleting or unhiding a note keeps them. Held-back turns keep their look,
  with a divider after the last of them: "Earlier messages are not sent to the AI
  (privacy settings changed)". A summary made while privacy changed, or while the chat
  was cleared, is discarded. The summary lives with the conversation in server memory;
  if conversations are ever kept on disk, it is kept with them, encrypted the same way,
  and Clear removes it.
- **History meter.** A thin grey bar above the message box with "History N%", the share
  of the budget the history takes, counted as the automatic summary counts it
  (`GET /api2/ai/history-meter`). It reaches 100% when the next Send would summarize.
  Hovering or focusing it shows the summary, turns, agent's records and free space, the
  budget against the model's context, and the latest answer's last request: the
  provider's own count, split into instructions, history, and question with notes and
  pages (`app/services/agent/request_tokens.py`; only the total is exact, instructions is
  what the estimates of the other two leave). Its line is always kept, so it appearing
  or updating moves nothing.
- Tests: `tests/unit/test_chat_compaction.py`, `tests/unit/ai_chat_history_meter.test.mjs`,
  browser suite `ai-chat-summary`.

## Session and Debug Boundaries

- The agent keeps a private record of what each answer did (tools, searches and pages
  opened, notes read), so questions such as "did you search the web?" are answered
  from what actually happened. Only the model sees it; it is cleared with the chat
  history (`docs/design/agent-harness.md`).

- Transcript/activity state lives only in server memory keyed by authenticated
  session token hash. Refresh rehydrates it; logout, auth reset, runtime lock, or
  restart clears it. With several views (`docs/ready-to-build/multi-view-editing.md` §5,
  decided 2026-10-28), each view will have its own conversation: a new browser tab starts
  blank, a reload keeps it, closing the tab ends it.
- The OpenAI usage/cost aggregate is separate process-wide server memory. Browser
  refresh and chat clearing retain it; its Reset button or server restart clears it.
- Canonical future context includes only user text and completed assistant prose.
  Scope, skills, actions, tool payloads, reasoning, and
  citations are transient.
- The latest debug trace is always captured so Agent Debug can be opened after a
  failure. Starting another run replaces the debug view; session history retains
  earlier runs for export.
- Exact detail is shown by default and may be toggled after a run without changing
  capture. The outline records every exact outbound provider body and response,
  retry/validation state, frozen scope/counts, action reason, retained/omitted
  roots, the bounded evidence payload, timing, and final
  response.
- Every investigation request has an `Evidence payload sent to OpenAI` entry with
  the exact compact note tree for that request. `Copy all` copies the complete
  current/most-recent run—including all events and payloads—as formatted JSON.
- Traces are never stored in SQLite, files, browser storage, or canonical history.

See `docs/design/agent-harness.md` for service and invariant details.


## Export LLM history

The chat header's **⇩ Export LLM history** button downloads the current session's
chronological `[input, output]` pairs as JSON. Inputs include the exact provider
request and original application invocation; outputs include responses or stream
chunks and completed/running/error/cancelled status. Agent turns and tool
results, tagging, retries, and final answers are included. Exporting makes no model call.

Page reloads retain server-session history. Clear Chat, logout, and server restart
clear it. The existing Agent Debug dialog and Copy all still concern the latest
run. See [prompt regression authoring](../../evals/README.md) to turn an exported
failure into an agent case.
