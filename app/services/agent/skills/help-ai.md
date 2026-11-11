# MetaList AI and tagging

Explain MetaList from this reference, without pretending to inspect the user's
saved settings or notes. Defaults below do not establish their current values.

MetaList's AI runs on the user's own key from OpenAI, Anthropic (Claude models) or
Google (Gemini models); Ollama/local model support has been removed. AI agent settings (also found
by searching AI, LLM, or OpenAI in the menu) has four tabs, Keys, Privacy, Reading and Tagging,
and one Save. Keys has a switch per provider holding its
API key and a link to the provider's usage and billing page; the Google tab warns that on Gemini's free tier what is
sent may be used to improve Google's products and read by people, so a key with
billing turned on is the one to use. Below it are
**Web access** (Off, Links in your notes, Any public page), the privacy rules **Never
send notes with (blacklist)** and **Only send notes with (whitelist)**, and **Model window
used**: the one context limit, a percentage (1–100) of the chat model's own context window,
for answers and tagging batches alike. Use these exact labels when directing the user.
The defaults are gpt-5.6-luna and 50%. Because it is a percentage, one setting fits every
model and a token count has to be converted: OpenAI's models have a 1,050,000-token window,
so "250k context" there means Model window used = 24%.
The model and thinking level are picked only beside chat Send, and the last choice
sticks; picking a model also picks its provider. The picker lists the models of every
provider with a saved key, under the provider's name: the ones MetaList ships
(OpenAI: gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna; Anthropic: claude-opus-5-5,
claude-sonnet-5-5, claude-haiku-5-5; Google: gemini-4-argon, gemini-3.8-flash,
gemini-3.5-flash-lite). These are the only models MetaList offers: each is tested with
MetaList's prompts first, so a user cannot add another model by name. A newer model
arrives with a MetaList update once it has passed those tests.

Web access has three modes and defaults to **No web access**. In that mode the
agent cannot open pages. **Open links from permitted context** lets it
batch-open public HTTP(S) URLs already present in user-authored chat, disclosed
note evidence, or retained web evidence. It cannot follow new links
found inside opened pages. URLs that occur only in privacy-blocked, password,
redacted, or omitted notes are not disclosed and cannot be opened. **Open any
public web page** lets the agent propose direct public HTTP(S) page URLs even when
they are absent from context. It can open a Google results URL and then open useful
result pages; both use MetaList's page opener rather than an LLM-provider search
service. MetaList has no separate search-engine action. Before opening an address
that contains words from the user's notes that the user did not type (for example
one a web page tricked the AI into building to send note text elsewhere), the chat
shows the address in a Yes/No box; nothing opens without Yes. Google Search and
Google Finance addresses never ask, since they only reach Google; redirects get
the same check. Page text is untrusted
evidence, supports HTML, plain text, and PDF, and must be cited. Web
evidence is retained only in the current chat session and Clear Chat removes it.
Changing the Web access selection applies on the next message.

Evidence is the permitted result view active when Send is pressed, including
matching notes not yet rendered on screen. Privacy filtering happens before
counts or note data reach the model. The AI uses tools on that view: an overview,
a word search (every word must appear in a note's text or tags), and reading whole
result trees in visible order. Each read returns as many whole trees as fit the
evidence limit; a tree is never divided, trees left unread can be read in a later
step, and a tree too large for the limit on its own is reported instead of read.
The AI keeps a private record of what it did for each answer in the chat (help it looked up, notes it read, searches and pages it opened), so it can say truthfully how an earlier answer was made; the record is cleared with the chat. Notes within returned trees are complete. A whole-view summary packs trees in
visible order and asks before using several batches. The limit estimates
serialized evidence, not the entire conversation/model context. Raising it can
include more evidence and increase cost. A reference-source view
opened by an AI citation retains the originating search as the next Send scope.
The note being edited at Send goes along with its whole tree. If AI privacy
settings hide it, the AI is told only that it is private, never which setting
(blacklist, whitelist or password protection) or rule. With no note selected, it
asks which note "this note" means.

The chat AI decides which tools a request needs, in a default order (MetaList
help, then notes in the view, then the web, then a change), and may use several
for one request, up to 8 steps. General conversation needs no tools. Product
questions look up selected MetaList help topics, including release notes (what
changed in each version and the installed version); help text is transient and is
not automatically added to future turns. Explicit requests to generate/accept/remove
tag proposals hand over to that operation, which asks first; a request to summarize the
whole view starts the summary right away, in as many batches as it takes, with one progress bar, a percentage and the time in the chat. No AI provider reports how far along a model is, so the percentage is an estimate from how long that model took before; a model's first summary starts with two small batches to learn that. Asking about that workflow is not permission to run it. The help action can explain and open dialogs only; it cannot set a
model/token limit or submit a form. If a user supplies a desired value, open the
appropriate settings and explain which field/value to save, honestly stating
that the value has not been changed automatically.

Proposed tags are separate from accepted tags. Tagging works on current-context
whole root trees, includes ancestors, randomizes roots before batching, and
collects results before atomic application. The vocabulary selector offers
existing only, new only, or both. Existing vault vocabulary is shared across
batches; tags proposed in earlier batches are optional reuse vocabulary but
remain unaccepted. Existing pending proposals are not generated again. Above
one evidence budget, generation asks confirmation before proceeding. Tagging
batch size is independently configurable. Bulk accept/remove can target current
context or the vault, optionally an exact tag. Asked in chat, accept/remove
first shows a Yes/No box with exactly what will change (how many proposals, of
which tag, across how many notes, where) and changes nothing without Yes. Successful bulk changes clear
undo/redo and create no bulk undo entry. There is no persistent rejection memory
or automatic background proposal generation. Individual proposal controls differ
from bulk operations; do not promise bulk undo.

Accepting a proposal converts it to an accepted tag. Removing/rejecting proposals
discards only pending, unaccepted proposals; it cannot remove accepted tags or
reverse a completed bulk acceptance. Do not offer proposal removal as a workaround
for missing bulk undo. Removing an accepted tag requires editing that note's tags,
which this chat workflow cannot do. An explanation of these limits does not itself
request opening the proposal-management dialog.

**Suggest Tags with AI** (🤖) is in the right-click menu of the note being
edited, and in the menu of a right-click in its tag bar past the tags. It shows
only when an AI is set up and the privacy settings let it see the note as edited
(a blacklisted tag, or `@password` or `@username` just typed, hides it). It saves the note and asks
for that note's tags: *Asking the AI…* floats above the tag bar while you keep
typing, then the proposals appear under the tag bar for `+`/`−`, tags already in
use first and new ones, marked **new**, on the right (at most two new per answer;
pressing `+` creates the tag). Tags the note has, or already proposes, are left out, also
as their singular or plural (no `eggs` beside `egg`). For a note with children it is a submenu: **This
Note** or **This Note and Its Children** (every note below it the view shows; notes
hidden from the AI are skipped); the floating card shows progress, and children's
suggestions show as their robot counts. It always allows new tags, whatever AI tagging
vocabulary says. Nothing new: a floating note says so until your next key or
click. Adding them can be undone. It does not touch other notes and needs no chat.

**Suggest with AI** in the Export and Print dialog (Export ▸ / Print ▸ in the
note menu, Export View as HTML / Print View, or the palette) asks the AI for the
title (the file's heading and name, or the print's); only pressing it asks, and
the field starts with MetaList's own default. It reads the notes going out that
it may see, text and tags from the top: never notes the privacy settings hide
(with everything under them), `@password` or `@username` notes, or the search. While it asks it
reads Stop, with a spinner; typing in the field, Export/Print or Cancel stop it
too. The answer replaces the title, selected, and Cmd/Ctrl+Z restores the one
before; asking again gives another. If some of the notes are private the dialog
says so; if all are, the button is dimmed. Without an AI set up there is no button.

The robot count (🤖 N) sits in the top-right corner of a note and counts its pending
proposals; on a collapsed note, those of its hidden children too. On a long first line
it covers the line's last letters until its proposals are handled. Clicking it opens every collapsed note on
the way to those proposals, so each shows its own robot, and puts the highest note
with suggestions of its own into edit mode, showing them: that note, or the first
one below it. Clicking the note itself just edits it, as always. Right-clicking it offers **Accept All Suggested Tags** and **Reject All
Suggested Tags** for exactly what it counts; ⌘Z undoes either in one step.

Accept or reject AI-proposed tags opens the bulk acceptance/removal form. AI tagging vocabulary
opens AI agent settings on its Tagging tab: existing tags only, or existing and new tags. The AI's prompts and skills
(including the tagging instructions and these help texts) are built into MetaList
and cannot be edited, so the AI behaves the same for everyone; instructions saved
by older versions are ignored. A model's knowledge of an operation does not make
that operation available as a tool.

Long chats are never cut off silently. The chat's history (a summary, the turns and the
agent's records of what it did) may take a quarter of the model's context, at most
32,000 tokens. When the next Send would pass that, the oldest turns are first replaced by
a summary made by the same AI, at most a third as long as what it replaces; the chat
shows "Summarizing earlier conversation". The summary entry sits after the last turn it
replaced, collapsed to "Earlier conversation summarized"; clicking it shows the
summary, and Copy Response works on it. Summarized turns stay on screen, grey and italic,
but the AI never sees them again: it knows them only through the summary, which names
notes by title instead of citing them. A missing detail is corrected by saying it in
the next message; there is no summary editor. **Summarize Now** (right-click a completed
answer, or the palette's "AI Chat: Summarize Now") summarizes every turn at once; while
it works, Send waits. The AI cannot summarize the chat itself. The **History N%** bar above
the message box shows how full the history is (100% means the next Send summarizes);
hovering it shows the summary, turns, agent's records and free space, and what the last
request sent to the model was made of: instructions, history, and the question with its
notes and pages. When the privacy settings change or a note the AI could see becomes
private, earlier turns and the summary stop being sent together, under the divider "Earlier messages are not sent to the AI (privacy
settings changed)".

The chat is saved in the vault (encrypted when it has a password) and shared by every
login to it: a restart, an upgrade, logging out and locking keep it; only Clear Chat ends
it. An answer MetaList stopped during comes back marked as stopped: ask again. Its debug
traces are session-only: Clear Chat, logout or a restart removes them. Export LLM history (download arrow in the chat header)
exports a list of input/output pairs, including actual provider requests,
attempts/retries/errors and activated skills. It makes no additional model call.
Agent Debug shows the latest run. When an AI step fails, the red message in the
chat explains it on its own: the step that failed, what went wrong on each attempt
(for example the reply was cut off at the output limit after the model spent its
budget thinking, or its answer broke a format rule, with what it chose), the model,
thinking level and web access, and what to try (such as a lower thinking level). If OpenAI sends nothing, the request fails after 15 seconds at Off or Low thinking (60 s Medium, 120 s High) with a message to check the internet connection (Claude and Google: 30 s at Off or Low, 60 s Medium, 120 s High; Google's message says the model may be busy, since its overloaded models go silent, and when Google answers that a model is busy the chat says so: ask again later or pick another model, such as Gemini 3.5 Flash-Lite); until OpenAI's first signal the chat says "Waiting for OpenAI". MetaList sets no length limit of its own on answers; a reply that reaches the longest
the model can write (only a runaway does) stops there, keeps what it wrote, and says so;
the user can ask it to continue or for a shorter answer. Failure messages end with where
the run stopped. The AI remembers the failed request and that explanation, so the user can say "try that again" or ask why it failed. A whole-view summary that fails or is stopped keeps the batches it finished for the chat; saying "try that again" continues it, running only the remaining batches. The separate opt-in regression suite lives in
the source repo, excluded from PyPI; cases default to five trials with up to four
concurrent requests and report percentages and cached-token usage.
Neither export nor ordinary tests automatically sends a test suite to OpenAI.

The estimated spend display is a developer tool: it appears only when MetaList
runs in development (`METALIST_ENVIRONMENT=development`); otherwise there is no $
button, and what the AI cost shows on the provider's own billing page (for OpenAI,
platform.openai.com). In development it is hidden by default; the $ button in the chat
header shows or hides it (remembered per vault) and it keeps counting while
hidden. It uses provider usage, tracks new/cached input, cache writes and output,
and is process-local. Resetting it does not affect billing.
Clear Chat does not reset costs. Interrupted calls with no final usage may be
absent. Stop cancels active work; Clear cancels and awaits it before clearing.
The developer eye reveals diagnostic activities. Model prose is not proof that
an action happened: actual menu acknowledgments and operation results are the
records. Past operation counts do not reveal exactly which tags were changed.
Never reconstruct a past operation from the current notes/proposals.
