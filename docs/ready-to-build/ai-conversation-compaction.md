# AI chat: compaction with a summary the user can read

**Status:** Agreed with the maintainer 2026-10-24. Ready to build, not started. Filed here from `docs/inbox/` on 2026-10-24 (see "Found when filed").
**Scope:** What happens when an AI chat outgrows the model's context. The oldest turns are replaced by a summary that the user can open and read, instead of being dropped silently.

Written without running the code. Code references were read on 2026-10-24; check each before relying on it, and build only what's missing.

---

## 1. What happens today

- `app/services/ai_chat.py`: `_MAX_MESSAGES_PER_SESSION = 100` (50 turns) and `_MAX_MESSAGE_CHARACTERS = 32_000`. When a new turn would pass 100 messages, the oldest turn is deleted (around line 179), along with its activities and action log. The user isn't told.
- `app/services/agent/context.py`: each request sends the full canonical conversation, plus `EARLIER_ACTIONS`.
- No check was found that keeps the whole conversation within the active model's context. 100 messages of up to 32,000 characters can exceed most context windows. Confirm whether one exists.

Two problems for the user:
- Something important can disappear from the AI's view, and the AI then seems to forget for no visible reason.
- A long conversation with large answers may overflow.

## 2. The behavior to build

**Compaction is automatic and never secret.**

1. **Budget by tokens, not messages.** Give the conversation a token budget, measured against the active model's context (the runtime already inspects context windows: `inspect_context_window` in `app/services/agent/runtime.py`). It replaces the 100-message drop as the mechanism that keeps the conversation in bounds.
2. **Before the conversation would exceed its budget,** summarize the oldest turns that no longer fit. **Nothing leaves the AI's view without a summary taking its place.**
3. **The AI then works from the summary plus the turns after it.** Summarized originals are **never sent again**, even if the user asks about them. What the user can read in the summary is exactly what the AI knows about that part of the conversation.
4. **Repeated compaction:** when the conversation outgrows its budget again, summarize the existing summary together with the next oldest turns into one new summary. There is only ever one summary in the AI's view.
5. **"Summarize now":** the same compaction, on request. Add it to the chat panel's menu and the command palette.

## 3. What the user sees

- **A summary entry, collapsed by default,** inserted into the conversation where the summary begins. Collapsed: one line, for example "Earlier conversation summarized — what the AI kept." Expanded: the full summary text. It's part of the conversation, not a modal, banner or toast. Nothing about compaction pops up or shifts the layout (see `docs/ui/modals.md` ("Errors and status")).
- **Summarized turns stay on screen,** above the summary entry, so the user can scroll back and read them. Render them **greyed and in italics,** with a divider marking where the AI stopped seeing them directly. That must look different from any turn that's held back from the AI for privacy reasons, so the two states can't be confused.
- **Correcting the summary is just conversation.** If the user notices something missing, they say so in their next message. There's no summary editor.
- **Copy Response** works on the summary like on any answer, which gives users a ready way to save a long conversation as a note.

The point of the design: unlike most chat apps, the user can see exactly what the AI chose to remember.

## 4. Making the summary

- **Same provider and model as the conversation,** through the normal request path. It must not send anything the conversation hasn't already sent to that provider.
- **Instructions:** keep decisions, facts, open questions and anything the user asked the AI to remember; **keep note citations** for anything that came from notes, so the AI can still say which note something came from; drop pleasantries and repetition.
- **Size:** cap the summary at a fixed fraction of the conversation budget, so it never crowds out the current turns. Choose the fraction; record it with the other AI limits.

## 5. Privacy

- **The summary inherits every privacy rule that applies to the turns it replaces.** Whatever today drops or resets earlier turns when what the AI may see changes (excluded notes or phrases, `@password`/`@username`, the disclosure-boundary reset noted in `ai_chat.py`) must drop or reset the summary too. A summary that draws on a now-hidden note must not keep being sent.
- **Provider change:** the summary follows the same rule as the earlier turns. (`ai_chat.py` has a 2026-10-24 comment saying switching provider now keeps the conversation; whatever is current applies to the summary.)
- **Where it lives:** with the conversation. If and when conversations are persisted, the summary is persisted with them, encrypted the same way, and Clear Chat removes it.

## 6. Tests

- A long conversation never overflows the context, and no turn leaves the AI's view without a summary covering it.
- After compaction, the summarized originals are absent from the request sent to the provider; the summary is present.
- Repeated compaction leaves exactly one summary in the request.
- The summary entry renders collapsed, expands to the full text, and doesn't shift the layout.
- Summarized turns render greyed and italic; held-back turns render differently.
- When a note that a summarized answer read becomes excluded, the summary is no longer sent.
- "Summarize now" works from the chat menu and the command palette.

## Found when filed (2026-10-24)

- **The references hold.** `ai_chat.py:14` and `:17` hold the two limits; `ai_chat.py:179-188` drops the oldest turn, its activities and its action log, with nothing shown to the user. `context.py` sends the conversation plus `EARLIER_ACTIONS` (`:202`).
- **No check keeps the conversation within the model's context** (confirmed). `runtime.py:1070-1079` only checks that the model's window meets MetaList's minimum (`required_tokens`); the agent loop estimates input tokens for display (`agent_loop.py:309`) but never limits them. Tag generation alone refuses an over-long request (`tagging_run.py:155`).
- **Held-back turns have no look of their own today.** When what the AI may see changes, `synchronize_disclosure_boundary` (`ai_chat.py:338-346`) moves `history_start` past every earlier turn, but the chat still shows those turns exactly like the ones the AI sees. §3 asks summarized turns to look different from held-back ones, so held-back turns need a look first.
- **Conversations are not persisted:** the transcript lives in server session memory (`AiChatSessionStore`), so §5's "where it lives" applies only once they are.

Questions for the maintainer:
1. The summary's share of the conversation budget (§4): proposed 10%.
2. How held-back turns look (needed before summarized turns can look different from them): proposed a plain divider "Earlier messages are not sent to the AI (privacy settings changed)", with the turns above it unchanged.
3. "Summarize now" while a summary already covers everything but the last turn: proposed it summarizes all but the last turn again, or does nothing with a floating "Nothing to summarize yet."

## Invariants

1. Nothing leaves the AI's view without a summary taking its place.
2. The summary is always readable by the user and is exactly what the AI knows about the summarized part.
3. Summarized originals are never sent again.
4. Note citations survive summarization.
5. The summary is subject to every privacy rule that applies to the turns it replaced.
6. Compaction never pops up or rearranges the layout.
