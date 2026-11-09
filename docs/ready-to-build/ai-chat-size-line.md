# How much text a conversation has sent

**Status:** Agreed with the maintainer 2026-11-08. Ready to build. A companion to `ai-reads-whole-view`, whose warning uses the same unit.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- Users never see an AI dollar figure (`docs/design/ai-providers.md` §5). The estimated-spend tracker is development only, directly below the chat header (`docs/ui/ai-chat.md`), and its totals live in server memory.
- The AI settings link to each provider's usage and billing page.

## 1. Why

People want some sense of how much they've used. Tokens mean little to them, dollars would be an estimate, and an ordinary API key can't read the remaining budget. So: exact amounts of text, and a link to the provider for the money. No dollar figure; that rule stands.

## 2. Per conversation, not per month

A monthly total would imply a record of past months and a way to view it. MetaList keeps no list of past conversations, and each view has its own, so the number belongs to the conversation, however long it lasts.

## 3. The line

> This chat: 42 MB of text sent, 3 MB received · See what you've spent

- **Directly below the chat header,** where the development tracker sits. Quiet; shown only once something has been sent. In every deployment.
- **"See what you've spent"** opens the provider's usage and billing page.
- **Saved with the conversation,** encrypted with it, so it survives reloads and restarts.
- **Compaction doesn't reset it.** Clear Chat ends it, with the conversation.
- **Each piece of text counts once** (proposed): what's read for a question is added once, even though it goes along with that question's later steps; earlier turns sent back with a new message aren't added again. A warning that says 18 MB adds 18 MB here.
- Includes batches. A cancelled warning adds nothing.
- No total across conversations.
- The development tracker is unchanged.

## 4. Invariants

1. MetaList shows no AI dollar figure to users.
2. The number lives and ends with its conversation; there's no history of it.

## 5. Done when

1. The line appears after the first send and adds up as described, including batches.
2. It survives a reload and a restart, isn't reset by compaction, and goes away with Clear Chat.
3. The link opens the current provider's page.
4. `docs/ui/ai-chat.md` and the AI help describe it; tests cover a multi-step question counted once, a later message, batches, compaction, Clear Chat and a restart.

## 6. Checked 2026-11-08 (filed from the inbox)

- Filed as ready to build, as its status asks. Nothing built.
- **Confirmed:** no dollar figure for users (`docs/design/ai-providers.md` §5); the development-only tracker directly below the chat header, with nothing persisted (`docs/ui/ai-chat.md`); each provider's `billing_url` (`app/services/ai_catalog.py`), already linked from the AI settings.
- **"Each view has its own" (§2)** is not true yet: several views are `docs/ready-to-build/multi-view-editing.md`. Today the rule is simply one number per conversation.

**Decided 2026-11-08:** the number survives a restart, and so does the conversation: losing a conversation to an upgrade is not acceptable. That is its own work, `docs/ready-to-build/ai-chat-survives-restart.md`, and it comes first: this line is saved with the conversation.
