# The AI reads the whole view, files included, in batches when it must

**Status:** Agreed with the maintainer 2026-11-08. Ready to build.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- The AI's tools (`app/services/agent/agent_tools.py`): `view_overview`, `read_view_notes` (whole trees, as many as fit; reports what's left unread), `search_view_notes` (words only), `summarize_view` (in batches; ends the turn; MetaList writes the summary). At most 8 steps per question.
- Its instructions (`app/services/agent/prompts/agent.md`) use `summarize_view` only for summaries. For "compare them, list them, which ones…" they say to use `read_view_notes`, and a precise question is answered from what was searched or read. So those can answer from part of a view that doesn't fit.
- The reading limit is a percentage of each model's window, default 50% (`retrieval_settings.py`). `211dff4e` removed the question a summary asked about scope, because choosing part of a window confused people.
- A later message carries the conversation and a short record of each tool call, not the notes read. Within one question, what was read stays for its remaining steps (`agent_loop.py`).
- File text is kept for search, up to 5 MiB per file (`app/services/file_text_search.py`, `MAX_FILE_TEXT_CHARACTERS`, `is_cut`). The AI's tools don't read it.
- `NoteTextGuard` (`app/services/agent/web_actions.py`): an address the AI wants to open needs the user's Yes if it contains a word from the notes shown to the model that the user didn't type.
- Privacy filter: `app/services/agent/cloud_privacy.py`.
- Check: exactly what the AI is shown about a file on a note today.

## 1. The AI never answers from part of the view because there's too much

- **The view is what the person asked about.** The AI reads all of it.
- **If it doesn't all fit, it answers in batches:** each batch answers the question for its part, and the results are combined. A summary becomes one kind of question this path handles.
- **No word search first to decide what's relevant.** It gives a false sense of having found everything: a landlord's number can be in several notes, for different times or buildings, and some may never say "landlord". The AI doesn't stop at the first hit either.
- **The person narrows, not the AI:** the view (a search or a folder), or a question about the selected note or one they name. Someone who doesn't narrow goes through everything, after the warning in §4.
- **The app enforces this,** rather than relying on the model choosing the right tool: a question over a view that doesn't fit goes down the batch path. Update the instructions to match.
- **It never reports what it skipped for lack of room,** because it doesn't skip.
- Word search remains only for a question literally about which notes contain a word.
- **A long answer must survive combining:** if 300 notes match, the final answer keeps all 300. Test exactly that.
- Tag proposals are unchanged.

## 2. File text travels with its note

- **A note's file text counts as part of the note:** read with it, batched with it, as the kept text for search.
- **Off by default,** a separate switch on the AI Privacy tab. People keep documents like tax returns as files and think of them differently from notes, and text sent to a provider can't be taken back.
- **Turning it on says:** "The text of files in the notes the AI can see will be sent to the AI provider you chose."
- **While off:** the AI gets no file text; if a question needs it, it says so in a sentence and points to the switch.
- **The privacy rules cover it:** a note the AI can't see keeps its files from it too. A file whose text holds a never-send phrase isn't sent (proposed).
- **A file over the kept text's limit, or with no text** (a scanned PDF, a photo): the answer says which files it couldn't read in full. That's a limit of the file, not of room.

## 3. File text is outside content

A downloaded PDF can hold instructions aimed at the AI.
- The model is told that file text is material to read, never instructions to follow.
- **File text counts as note text for `NoteTextGuard`,** so a word from a file can't leave in a web address without the user's Yes.

## 4. The warning

- **Default threshold: 1 MB of text in one question,** notes and files together, the same for every model (proposed).
- **Adjustable in AI Agent Settings:** "Warn before sending more than [1] MB of text", which can be raised or turned off. The warning has a small link to it (proposed).
- **Before anything is sent.** The AI reads the whole view, so the total is known at the start.
- **Wording:**

> **This is a very large request.** It will send about 18 MB of text to OpenAI, on your own account. To send less, narrow the view with a search or a folder.
> **[Go ahead] [Cancel]**

- The provider's name follows the one in use.
- **Megabytes of text,** never pages or tokens. Always "of text": a 40 MB PDF may hold 1 MB.
- **No amounts to choose** on the warning, and no dollar figure.
- **No second warning** for later messages: what was read isn't sent again.

## 5. Invariants

1. The AI never answers from part of the view because of its size.
2. No file text reaches a provider unless the person turned it on, and only for notes the AI may see.
3. File text is never treated as instructions, and can't leave in a web address without a Yes.
4. Nothing above the person's threshold is sent before they say Go ahead, unless they turned the warning off.

## 6. Done when

1. A question that needs a view too large for one read is answered in batches, covering every note; no answer reports notes skipped for room.
2. The AI uses no word search to decide what to read.
3. With the switch on, file text is read and batched with its note; with it off, none reaches a provider.
4. The warning appears at the threshold, before any send, and the setting raises or turns it off.
5. `docs/design/agent-harness.md`, `docs/ui/ai-chat.md` and the AI help describe this. Tests cover: a view that needs batches with a "which ones" question, several matches for a lookup, a 300-match answer through combining, file text on and off, a hidden note's file, a never-send phrase in a file, a word from a file in a web address, a cut-off file, the threshold and the setting.
