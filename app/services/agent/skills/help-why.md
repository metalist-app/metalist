# Why MetaList works this way

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/interaction-principles.md, docs/ui/modals.md, docs/ui/floating-messages.md, docs/ui/controls.md, docs/ui/state-handling.md, docs/ui/search-semantics.md, docs/ui/tag-bar.md, docs/ui/references.md, docs/ui/content-formatting.md, docs/ui/find.md, docs/ui/command-palette.md, docs/ui/ai-chat.md, docs/design/multi-view-editing.md, docs/design/tag-suggestion-learnings.md, docs/design/search-suggestion-learnings.md, docs/design/similar-notes-learnings.md, docs/security/README.md, docs/security/cloud-privacy-boundary.md, docs/ready-to-build/import-export-launch.md, docs/ready-to-build/reference-cards.md

# Why MetaList works this way

The reasons behind MetaList's design, for questions such as "why does it do that?" or "why
doesn't it do this?". Each entry says what MetaList does and why. How to use a feature is in
the other help topics.

When a question is about a decision not listed here, say that the reason is not recorded here.
Never make up a reason, and never present a guess as MetaList's reason. You may add that a
behaviour follows from one of the six principles below when it plainly does, and say that this
is your reading.

## The six principles

Most of what MetaList does on screen after an action follows from these.

1. **What you are looking at stays put.** After any action, the thing your eyes are on (the
   click point, the caret, the drop line) stays at the same place on screen. Why: attention is
   anchored to a point, so MetaList redraws around it, never under it.
2. **Nothing moves unless you did it.** MetaList adds no scrolling, flashing, expanding or
   animation of its own. Why: anything you did not cause is noise that costs attention.
3. **It moves things only to keep them in sight.** If what you just acted on would end up out of
   sight (behind the search bar, past the window's edge), it moves by the least needed. Why: you
   should never lose sight of what you just acted on; this is the only reason MetaList moves
   anything itself.
4. **Your choices stay, and your work stays visible.** A note you folded stays folded until you
   unfold it; looking around changes nothing. Why: a deliberate choice should last, and you
   should be able to see that your work took.
5. **Your own results are never highlighted.** Only errors, and changes made by something else,
   may be highlighted. Why: you already know where your own changes are.
6. **A dialog saves and closes the note first.** Opening any dialog, confirmation, full screen
   or the app menu while editing saves the note and leaves edit mode. Why: one rule for every
   dialog is easy to keep in mind; the cost is at most one click to go on editing.

## Scrolling and what stays still

- **Move to Bottom does not scroll after the note.** Why: sending a note to the bottom is a
  choice to stop looking at it.
- **A change from another tab or device does not make the screen jump**, and is not highlighted;
  it waits while you scroll, drag or have a menu open. Why: principles 1, 2 and 5.
- **In a sorted list, the note you are editing stays where it was** and goes to its sorted place
  only when you leave it, the screen staying on the notes around it. Why: nothing you are
  looking at should jump while you work on it.
- **The command palette keeps its order while it is open** (rows are ranked by use as of
  opening). Why: using a command, such as cycling Theme, must not move the row under you.
- **Backlinks list the most recently edited note first, in the order taken when the page
  opened.** Why: editing a note there does not move it.
- **A fold arrow sits on its note's first line, like a bullet.** Why: it stays level with that
  line at any text size, and folding moves neither the arrow nor the line.

## Dialogs, errors and messages

- **Errors and status messages float; they are never written into the page or a dialog.** Why:
  an inserted message pushes things around under your attention, and one below the visible part
  is missed.
- **A refused action gets its own error dialog over the dialog you were in**, which stays open
  with what you typed. Why: nothing in your dialog moves, and nothing you typed is lost.
- **A destructive button sits in the usual rightmost place, and Enter never presses it.** Why:
  moving it "to be safe" would break the habit that works everywhere else.
- **Work in the background (reading document text, updating previews) shows a progress card in
  the lower left**; work shorter than a second shows nothing. Why: you should know when MetaList
  is busy; at the top right the card covered the search bar, and very short work would only
  flicker.
- **Reading document text waits for an import to finish**, then runs at low priority. Why: what
  shows on the page comes first.
- **Floating cards fade in rather than slide.** Why: a card appears where it stays.
- **A reminder card waits behind an open dialog.** Why: the dialog is what you are working in,
  and a card must not cover its buttons.

## Notes and editing

- **Edit mode shows the raw text, with small previews beside formulas, tables, JSON and
  diagrams.** Why: raw text is precise, lasts as plain text and hides no formatting; the
  previews help without hiding or moving the text.
- **Code has no preview.** Why: coloured code already looks as typed.
- **Standard Markdown always renders as the standard says** (CommonMark with GitHub's
  extensions); where another app differs, the standard wins. Why: text written to the standard
  should look the same everywhere.
- **Long text wraps at the note's edge**, code included; only a table wider than the note
  scrolls sideways. Why: text should never run out of its note.
- **The diagram editor opens where you left it** (pan and zoom are kept). Why: principle 4.
- **The diagram editor loads only when first used**, so the first opening takes about a second.
  Why: pages without diagrams should not pay for it.
- **Dictation uses the phrase "start tags"**, not a word said twice. Why: dictation tools drop a
  repeated word.
- **The number keys 1 to 9 switch search contexts only while nothing is being typed.** Why: in a
  note, the tag bar or the search box, a digit has to be a digit.

## Undo

- **A change from another device empties your undo history.** Why: undo puts back what was
  there before your change, and would silently overwrite what the other device did. Editing on
  two devices at once is rare, so losing undo then is the smaller harm.
- **Undo history ends when you switch search context or change the search.** Why: undo belongs
  to the list you were working in.

## Search and search contexts

- **A search context keeps everything about which notes you see and in what order**: the
  search, the sort, the date range, the files filter, the Untagged view and the folders. The
  layout (tree shown, chat width, theme) is the same in all of them. Why: switching contexts
  should change what the list shows, never the shape of the screen around it.
- **A sort order and a date range stay through a new search**, each until its chip's × is
  clicked. Why: they are part of how you chose to look at that context (principle 4).
- **A new search ends the Untagged view.** Why: that view shows notes no tag search would find,
  so the two cannot combine.
- **Search contexts always show.** Why: they proved too useful to hide.
- **Every tab and device shows the same list of search contexts.** Why: a new browser tab has
  no identity of its own, so with separate lists MetaList could not tell which one to show
  without losing or wrongly merging contexts.
- **Typing in a context's search locks that search in other tabs and devices.** Why: two people
  typing in one search box has no sensible result.
- **A note that embeds or links another does not take its tags.** A search for the linked
  note's tags finds that note, not the ones that show it. Why: an embed is a window onto
  another note, not a statement that the host is about the same things.
- **No new note is made at the top of a search a new note could not match** (such as
  `miles>3`); a message says so. Why: the note would vanish from the search it was made in.
- **The search bar suggests tags only, never words from notes.** Why: suggesting words would be
  text search, and tags are easier to remember than words.
- **⌘F / Ctrl+F is MetaList's own find, not the browser's.** Why: the browser holds only the
  part of the list near the window, so its find cannot see the rest or folded notes.
- **A folder in a search (`Projects/`) means the same with the folder tree shown or hidden.**
  Why: the setting only shows or hides the tree; a search must not change its meaning with it.
- **Several folders in one search add their notes together.** Why: it matches selecting several
  folders in a file manager.
- **Deleting a folder leaves searches that name it as typed**; they then find nothing. Why: it
  behaves as deleting a tag does, and undoing the deletion needs no repair.
- **Only a top-level note can be dropped on a folder.** Why: a note inside another takes its
  parent's folder, so a drop would put it in two folders instead of moving it.

## Tags and tag suggestions

- **Typing in the tag bar only narrows the suggestions; it never reorders them.** Why: each
  letter should only remove tags that stop matching. Measured on real use, keeping the order
  made the wanted tag show among the first five far more often.
- **An empty tag bar does not offer a tag the current search excludes.** Why: accepting it
  would take the note out of the list you are in.
- **"Why suggested" shows the ranking's own reasons.** Why: an explanation worked out
  separately could disagree with the list.
- **A tag's values are suggested from the last note with that tag**, not from defaults you set
  up. Why: no setup, and logging something regular takes a couple of keys.
- **Tags may hold any letters of any language.** Why: folder and tag names from an import, such
  as Café, come in exactly.

## Links, embeds and files

- **A link can lead to any words in a note (`[[note#words]]`), not only to a heading.** Why: it is more useful, and a link whose words were reworded simply opens the note, so nothing breaks. The words are marked on arrival, until your next click, scroll or key, because you cannot otherwise know where in a long note the link meant.
- **Link to… and Embed… type `[[` or `![[` for you.** Why: they teach the syntax by showing it.
- **A reference page (a followed link, backlinks) has back and forward arrows instead of a
  search.** Why: showing something that is not a search in the search bar misleads however it
  is done.
- **The browser's Back button leaves reference pages alone.** Why: Back goes to another web
  page, and MetaList is one page.
- **On a reference page, notes can be added only inside the linked note.** Why: a note added
  beside it would not be there the next time the link is followed.
- **A file is shown as a card with Open and Download, not copied into the note as text**; its
  text is kept for search only. Why: an editable copy drifts from its file, and previews for
  only some kinds of file looked arbitrary.
- **A file's badge shows its real extension** (.CSS, .RTF). Why: labels such as TXT or FILE
  said too little.
- **A picture is never drawn larger than its own size.** Why: a small icon should not be blown
  up.

## Import and export

- **Anything imported goes after the last note in the list.** Why: at the top, imported notes
  looked as if they had replaced everything to someone working without a search.
- **An import ends by showing what came in.** Why: that is what you want to look at next.
- **Imports are best effort; MetaList adds no feature only to match another app.** Why: a
  feature is built when MetaList wants it for itself.
- **Importing a folder that came in before asks Keep both or Replace, with Keep both chosen
  first.** Why: nothing should be lost without a click. Replace leaves notes you edited in
  MetaList alone unless you tick their box, for the same reason.
- **A replaced file's notes take the old notes' place.** Why: links to the note keep working,
  and it stays where you put it.
- **Importing bookmarks again only adds.** Why: a rule anyone can predict; every way of
  matching bookmarks would surprise someone.
- **Export is one ordered document shaped like the outline, not a file per note.** Why: files
  sort by name, so a file per note loses your order and scatters the outline.

## Backups, passwords and privacy

- **An existing backup is never changed, renamed or converted.** Why: a backup is what you fall
  back on, so it must stay exactly as it was made, with the password it was made with.
- **Only the newest three safety backups of a vault are kept.** Why: nothing else ever removed
  them, and they grew without limit.
- **Backing up to the cloud means choosing a folder a sync app uploads** (Dropbox, iCloud
  Drive), not signing MetaList in to a cloud service. Why: MetaList then holds no cloud
  credentials. A vault without a password asks first, because its backup would be readable
  there.
- **A new vault is ticked for backup from the start.** Why: otherwise it would never be backed
  up and nothing would warn you.
- **A new password must be very strong.** Why: the password alone protects a backup, and a
  stolen backup can be guessed at without any limit on tries.
- **A vault without a password stores its files unencrypted.** Why: with no password behind the
  key, encrypting would only pretend to protect them.
- **Sharing on the network is chosen per vault**, and another computer sees only the shared
  vaults. Why: one setting for all vaults silently overrode each vault's own choice. Restoring
  a backup keeps the vault's sharing choice, because sharing belongs to this computer, not to
  the backup.
- **A password in a note is not in the page's text until its eye is clicked.** Why: blurring
  hid it from a glance but left it to selection, copying and screen readers.

## AI

- **You bring your own key.** Why: requests go straight from your vault to the provider under
  your account; MetaList never relays or pays for them.
- **Only models MetaList was tested with are offered.** Why: a model can be too weak, or need
  instructions of its own.
- **"Waiting for…" names the provider while no answer has come.** Why: a stalled connection
  should not look like thinking.
- **A question that could not be sent stays in the chat with the reason.** Why: your text is not
  lost, and the reason says what to fix.
- **The conversation is saved with the vault, one per vault.** Why: a conversation should
  survive an upgrade or a restart, and a browser tab lives too briefly to own one.
- **A search term that matches only private notes is withheld from the AI.** Why: otherwise the
  AI could tell "no notes" from "only private notes".
- **Text the AI quoted earlier is not scrubbed from the chat when a note becomes private; Clear
  Chat does that.** Why: automatic scrubbing would miss rewordings and give false confidence.

## Tried and removed

- **Show Similar Notes** was built and taken out. Why: most notes do not stand on their own, so
  "similar" meant little, and it was slow.
- **Dragging a note to another level of the outline** was tried and dropped. Why: it needs a
  different way of dragging than moving among siblings. Indent and outdent do it instead.
