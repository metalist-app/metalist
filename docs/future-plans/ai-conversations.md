# Several kept AI conversations

**Status:** A future option, noted by the maintainer 2026-11-14. Not designed, not scheduled.

Today, and with several views (`docs/design/multi-view-editing.md` §5, decided
2026-11-14), the vault has one AI conversation: saved with the vault, shown in every browser tab
and on the phone, ended only by Clear Chat (`docs/ui/ai-chat.md`, "Saved with the vault").

**The option:** several kept conversations to choose from, as the web versions of chatbots have:
a list of them, a new one started without losing the others, an earlier one picked up again.

**What it must keep:** nothing is lost when a browser tab or the browser closes. A conversation is
the vault's, never a tab's: a tab lives too briefly to own one (the reason one per view was
dropped, multi-view note §10). Each Send uses the scope of the view that sent it.

**Each view chooses its own conversation, as it chooses its own search context** (the maintainer,
2026-11-14). The list of conversations is shared by every view, like the list of search contexts;
which one a view shows is that view's place, like which search context it shows. A new view opens
on the conversation used most recently. Two views on the same conversation see it live and take
turns, one answer at a time (multi-view note §5); two views on different conversations can each
have an answer being written at once.

**To decide when it is designed:** what a new conversation is called and how one is renamed or deleted; whether
Clear Chat becomes deleting a conversation; how saved conversations are encrypted and kept in
backups (one `ai_chat` row today, database version 19); and the bound on how many are kept
(`docs/ready-to-build/unbounded-growth-audit.md`).
