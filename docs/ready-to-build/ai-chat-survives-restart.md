# AI conversations survive a restart

**Status:** Agreed with the maintainer 2026-11-08. Ready to build. The maintainer: customers would be furious to lose a conversation unexpectedly because of an upgrade.

`docs/ready-to-build/ai-chat-size-line.md` depends on this: its count is saved with the conversation.

---

## 0. Today (from the code)

- A conversation lives only in server memory: `AiChatSessionStore` (`app/services/ai_chat.py`), keyed by the login session's key (`token_service.get_session_key`). A reload keeps it.
- These end it: Clear Chat, logout, locking (`app/services/runtime_lock.py`), a server restart, setting or removing a password, and a restore (`ai_chat_store.reset()` in `app/api/routes/auth.py`).
- Two stores sit beside it in memory, cleared with it: `web_evidence_store` (pages opened for follow-up questions) and `summary_batch_store`.

## 1. The change

- **A restart or an upgrade keeps the conversation:** its messages, its summaries, and what the model still sees of them.
- **Saved in the vault,** encrypted like the notes while the vault has a password. It therefore goes into backups and comes back with a restore.
- **Only Clear Chat ends it,** on disk too (decided 2026-11-08). Logging out or the vault locking leaves it, encrypted on disk.

## 2. For whoever builds it

- The key cannot be the login session: a restart ends every session, so the conversation belongs to the vault (and, with `docs/ready-to-build/multi-view-editing.md`, to a view).
- This changes the persistent schema: AGENTS.md's "Database Schema Changes Require a Version Bump" applies, including the encryption audit and `docs/security/README.md`.
- A question still running when the server stops comes back as interrupted, not as running forever.
- The privacy boundary still applies after a restart: `synchronize_disclosure_boundary` holds back turns that a note's change of privacy makes unsendable, and that must hold for a saved conversation too.
- Setting or removing a password rewrites the conversation like the notes, rather than ending it, and a restore brings back the conversation in the backup.
- `docs/ui/ai-chat.md` and the AI help say a restart, logout and locking clear the chat; change both.

## 3. Decided 2026-11-08

The text of web pages opened for follow-up questions (`web_evidence_store`) is not saved: after a restart the AI opens a page again if it needs it, as the Web access setting allows, and the conversation keeps what it said about the page.

## 4. Invariants

1. Only Clear Chat ends a conversation.
2. In a vault with a password, no part of a conversation is on disk unencrypted.

## 5. Done when

1. A conversation is the same after a restart and after a real upgrade, including its summaries and history meter.
2. Clear Chat removes it from disk.
3. Tests cover both, logging out and locking keeping the conversation, a question interrupted by a restart, a note made private while the server was down, and the encryption audit before and after the schema step.
