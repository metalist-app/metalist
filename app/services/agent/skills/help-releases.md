# MetaList release notes

What changed in each MetaList version, newest first, from its changelog
(CHANGELOG.md). Changes made after the newest listed version are not described here.
Compare with installed_version from the help lookup to tell the user whether
they already have a release. Version info offers updates (see the data topic).

## 0.28.3

- The vault list on the login page comes up at once on Windows: it no longer checks every vault's ports, each check a PowerShell start, which took about 3 seconds.

## 0.28.2

- Fixed: 0.28.1 showed a red error on every load, "ResizeObserver loop completed with undelivered notifications." That is the browser noting a layout it finished on the next frame, not an error; it no longer shows.

## 0.28.1

- **The login page is quicker,** most of all on another computer over Wi-Fi: it loads only its own few files, and the rest of MetaList downloads while you pick a vault and type your password. Once a browser trusts MetaList's certificate it also keeps MetaList's files between visits, until an update changes them.
- A red error on the login page offers Export Report… too; that report is kept nowhere.
- A problem report's reading of how busy the computer was no longer shows 0% CPU on a Mac.
- The AI chat knows what changed in every release, the oldest included.
- After too many wrong passwords, the login page on Windows no longer says to wait 301 seconds instead of 300.

## 0.28.0

- **Report a Problem.** In the command palette, Report a Problem… saves a report of the last 10 minutes, with a sentence or two of your own, so you can send it to whoever helps you. The red error offers Export Report… too, and Export Problem Reports… saves the last 20. A report holds what you clicked and typed and how busy the computer was, never your words: note text becomes `xxxx`, each tag a made-up name, and MetaList refuses to save a report with anything else in it.
- **The AI conversation is kept.** A restart, an update, logging out or locking keeps it; only Clear Chat ends it. In a vault with a password it is encrypted like the notes.
- **Add or Remove Tag (Current View)…** in the command palette and the view's right-click menu adds a tag to the notes the search finds, or removes one from every note shown, as one undo step.
- **Insert ▸ Password** types a new password into a note, drawn as dots with an eye and click to copy; exports, prints and the AI never see it.
- **Fathom,** a new look under Theme: a code editor's deep blue-grey, in your system's monospace font.
- **⌥⌘Enter** (Ctrl+Alt+Enter on Windows and Linux) adds a note one level out, below the current note's whole branch.
- Changes made while another is still saving wait their turn instead of failing. Deleting a folder's notes, or a view's, shows the trim reminder at once.
- Imports no longer take the search's tags, and a folder import's kinds open again to list their files. A red error now shows above any open dialog.
- MetaList renews its own HTTPS certificate before it expires, so phones and other computers keep connecting.
- Logs hold no note text, tags or searches, and stay small; the old encrypted log files are deleted. Backups made before an update include attachments.
- A vault saved by a newer MetaList is refused before anything is written to it.
- Vaults are upgraded (database version 19) when first unlocked, or at startup without a password, after a backup: an older MetaList cannot open them afterwards.

## 0.27.0

- **Files of any size.** Uploads stream into storage and the 100 MB limit is gone. Each file is its own file on disk, in a `files` folder beside the notes; in a vault with a password each one is encrypted with its own key and padded so its size doesn't reveal it.
- **Galleries.** `@gallery` shows the pictures in a note and every note under it as a grid, PDFs by their first page and drawings that open their editor. It switches between grid and outline, folds to one row and steps through its pictures full screen. With a search on, it shows the pictures of the notes the search finds; its own meta tags don't count, so `test @gallery` shows what `test` finds under it.
- **Search links.** `[[search:…]]` opens a search; `![[search:…]]` shows its results in the note, folded to its first line. Rename Tag renames them too.
- **Folders in the search.** `Projects/` finds that folder and every folder below it, and several folders add results: `Projects/ Archive/ @todo` finds to-dos in either. A folder implies the folders above it, rules included. The folders tab only shows or hides the tree, and a reload keeps it. Clicking a folder makes it the search; ⌘-click (Ctrl-click on Windows and Linux) adds or removes one.
- **`/*help*/` in the search** finds the notes whose tag-bar comments contain "help".
- **Two new looks under Theme:** Illuminated, a painted manuscript, and Ye Olde Scrypte, notes in old English on parchment.
- **Tags as you type:** every field that asks for a tag offers the tags in use, tags starting with what you typed first. The tag bar offers a note's own words as new tags once nothing matches.
- A folded note that starts with a Mermaid diagram shows a thumbnail of it. File size order shows each file's size. Notes with Files lists every file type in use. A dropped folder's import ends on what it brought in.
- **Safety backups no longer pile up.** Each vault keeps its newest 3, removed only after a new backup checks out and the upgrade or update has succeeded.
- **AI summaries are faster:** batches go out as fast as your provider's limits allow, the limits are remembered, and one progress bar follows each model's timing. AI Agent Settings has four tabs: Keys, Privacy, Reading and Tagging.
- Imports add their notes at the bottom, and files not aimed at a note get a note each. Unlocking a vault is faster. The import from the old MetaList is gone.
- Vaults are upgraded (database version 18) when first unlocked, or at startup without a password, after a backup: an older MetaList cannot open them afterwards.

## 0.26.1

- **Large vaults no longer freeze.** An AI question with an empty search box took minutes on a vault of tens of thousands of notes, holding the server so the search box and Stop got no answer and a "command stuck" error appeared; the step that names each note for the AI is now linear, and reading the notes runs beside the server's other work. An import of more than a few hundred files showed the same error at 15 seconds while it was still running fine; an import now takes as long as its files take, with its progress bar.
- An AI search that matched no note ended the chat with "stream ended before completion"; it now answers.

## 0.26.0

- **Notes from the old MetaList.** A newly installed MetaList that finds the old MetaList's notes in its data folder offers them as soon as it opens. Protected notes ask for the old password, which then protects this MetaList too (a new one when it is too weak). The old file is only read, never changed. At a terminal, `convert-from-legacy.py` now reads protected exports and the old file itself.
- **Import** from the command palette and when creating a vault: an Obsidian vault, a Markdown folder, any folder of files (with a file checklist, a prefix folder and images compressed to a size you choose), or browser bookmarks. Files dropped on the page come into the search context they were dropped in.
- **Files open in a viewer**, with previews for code, web pages, CSV, JSON and email (.eml). Text in PDFs is searchable, with snippets under the matched cards; Find looks inside files and diagrams. Rename File… on file cards, pictures and diagrams.
- **Markdown follows standard Markdown:** line breaks, nested lists and quotes, plus callouts and `<details>` folds (saved in the note), footnotes, `==highlights==`, clickable tasks, web images, and links and embeds.
- **Passwords show as eight dots**, whatever their length, with an eye that shows one until your next click or key. Clicking a password, username or `@copyable` value copies it.
- **Previews while editing** for LaTeX, CSV, Mermaid and JSON; Insert LaTeX, CSV or Mermaid Diagram.
- **AI chat:** long chats keep going, with summaries of earlier turns and a meter showing how full the chat is.
- Search: tags and searches in any script, quoted tag values, property searches on any tag, OR between rule groups, and quoted searches update as you type. Search contexts keep their sort, date range and Untagged view.
- `@datetime` dates a note. Notes save themselves 10 seconds after you stop typing. A Referenced by badge shows on notes others link to. An embed no longer gives its tags to the note it is in; only parents do.
- An experiment, off unless turned on: virtual folders, a folder tree beside the notes.
- Fixed: restoring the open vault no longer sends the page to Session locked; keys typed while a clicked note opens are no longer lost; adding a note to the AI chat no longer resets its history.
- Vaults are upgraded (database version 14) when first unlocked: an older MetaList cannot open them afterwards.

## 0.25.0

- **Claude and Gemini beside OpenAI.** AI Agent Settings has a key for each provider, on your own account; you pick the model in the chat, and a conversation carries on when you switch provider.
- **Stats of a note's subtree.** `@stats` shows, under a note's own text, the Total, Min, Max and Count of each number property in it and the notes under it; `@sum=calories` (and `@avg`, `@min`, `@max`, `@count`) shows one figure, and a plain `@sum` covers every property. With nothing logged yet, a sum or count reads 0. **Stats Style** in the command palette: Strip, Tiles or Ledger. Search the figures with `@sum:calories>2000`: the days over 2000, each with the notes under it.
- **Four built-in tags renamed:** `@highlighter` is now `@highlight`, `@llm` `@ai`, `@list-bulleted` `@bullets` and `@list-numbered` `@numbered`. Each vault converts its notes and saved searches once, the first time it is unlocked after the update; the old names stop working. `@gray` works as well as `@grey`.
- **Light and Dark everywhere:** dialogs, menus, the command palette, reminder cards and the tag rules editor follow the theme, and changing the theme cross-fades the page. After logging in, the login screen fades out over your notes.
- References: typing `[[` suggests notes to link or embed; `[[note|text]]` shows your own link text; a link to a password or username note shows its copyable row. A folded note reads as one line.
- The tag bar suggests a super tag with last time's values (`jogging:miles=12`), and property names for a tag that has none yet (`calories=` for a new `salad:`).
- Markdown tables: `<br>` breaks a line in a cell, rows with too few or too many cells and escaped `\|` work, and a wide table scrolls instead of squeezing its columns.
- Web links show their site's icon, their title and their domain.
- Under 640 px wide (a phone), MetaList shows a read-only layout with a box to capture new notes.
- Dialogs are consistent: the main action on the right, Cancel beside it, and Enter never confirms a deletion. Messages float instead of moving the page. The command palette keeps its order while it is open, and its box says "Type keywords".
- A new mark and favicon.
- Fixed: changing the sort order while the list was still loading could open it partway down; a refresh asked for during another could be dropped, leaving deleted notes or old search results on screen; a dropped file could land out of sight; tag suggestions failed on a note whose only tags were `@` tags.
- Vaults are upgraded (database version 12) when first unlocked: an older MetaList cannot open them afterwards.
- Security: msgpack 1.2.4 (CVE-2026-114613) in the tools that build and test MetaList; MetaList itself does not use msgpack.

## 0.24.2

- ⇧⌘V pastes a copied note as a child again. Since 0.21.0, in Chrome, it put the copied note's text into the selected note instead.

## 0.24.1

- **Security updates.** pypdf 6.21.2 fixes three ways a crafted PDF could keep MetaList busy for a long time; MetaList reads PDFs only when the AI opens one on the web (web access is off unless you turn it on). Mako 1.4.2 fixes a Windows template-path issue MetaList does not reach. Tooling used only to build and test MetaList is updated too (filelock, setuptools, zod).
- **Notes with files** (right-click menu, search box menu and command palette): show only the notes with an attached file, or with images, PDFs or Markdown files, each under the notes above it. Images also finds pictures pasted into a note. It works with a search (pick Images, then search, to find those notes with a picture); a chip in the search box names it and its `×` shows every note again. It stays with its tab.
- Pasting text that carries formatting (an answer copied from Copilot or another AI chat, a web page) is now checked too: Markdown left in it (`##` headings, `**`), CSV, code or LaTeX is offered on the small card, and Apply puts in the plain text with the tag. Headings over paragraphs and plain ``` code blocks are offered as Markdown.
- A collapsed embed of a note that only holds a link to another note now shows that note's first line in its own formatting, instead of a blank line and plain text. A link on a source's first line no longer breaks the embed.
- A note that holds only a reference stays an embed even with an invisible character beside the reference (left by ⌘B with nothing selected, or pasted).
- In a password-protected vault, PDFs and images attached before the last unlock are recognized again, for Notes with files, picture resizing and the image tag.

## 0.24.0

- **Super tags.** A tag can carry values: `jogging:miles=3:duration=30`, `drug:dosage=10mg`, `run:start=10:30pm`. Search by them with `jogging:miles>2`, `jogging:miles?` (notes missing it), `date>=2024-01`, or `jogging:miles=MAX` / `=MIN` for the largest or smallest among the notes found. Values compare as numbers (a unit is a label: `dosage>5mg` compares only mg, `dosage>5` every unit), dates, times (`10:30pm` = `22:30`) or text. A search reads values through tag rules too: with `jogging => exercise`, `exercise:miles>2` finds your runs. The tag bar and the search box suggest the property names and units you already use, and `MAX`/`MIN` after `=`. A plain `jogging` search still finds `jogging:miles=3`; children inherit the tag, never its values.
- Tag rules can test values: `jogging:miles>10 => long-run`, `task:due? => needs-date`. The tag a rule gives passes to the note's children; Edit Tag Relationships shows such a rule in the left column of the tag it gives, suggests names and units while you type one, and warns about a property no note has (a typo). Saving one re-tags only the notes it can concern.
- The AI can propose super tags with values a note states (`jogging:miles=3` for "ran 3 miles"), reusing your property names and units; accepting one adds its values to the note's tag.
- **Date range** (right-click menu, search box menu and command palette): show only notes created, or last updated, today, in the last 7 or 30 days, this year, or in a custom range. A chip in the search box names it; its `×`, a new search or leaving the tab ends it.
- File names are searchable: a quoted search (`"congratulation"`) and find (Cmd/Ctrl+F) match the names of files a note holds, and the AI sees them.
- ⌘+ / ⌘− with the pointer on a picture or diagram makes it bigger or smaller, viewing or editing.
- Right-clicking the search box past what you typed offers View, Sort by and Date range.

## 0.23.0

- **Reference views.** Following a reference (a link, an embed's reference icon, Go to Source Note) or an AI answer's references slides the list to the left, and a gray chip takes the search box's place: **Source note** (its first line is the tooltip), **Reference** or **All references**. `←` or Escape goes back one level, `×` straight back to your search, each to the exact place you left; the list slides back to the right. With Reduce Motion it is a quick fade. The magnifier beside the chip starts a new search. Reference tabs keep their label and chip after a reload and in every window: no tab is named by a note ID any more.
- One reference icon, a page with an arrow coming into it, on embeds, links, the chip, the tab list and the right-click menu's **Go to Source Note**; All references has two pages. A collapsed embed shows its source's first line in its own formatting (a green heading stays a green heading), and embeds are a shade darker grey, deeper again for an embed inside an embed.
- Sort orders and Untagged show as chips inside the search box (`Created`, `Updated`, `A–Z`, `Size`, `Untagged`; the full name is the tooltip). New **Reverse Order** in Sort by works with any order: Z to A, oldest or smallest first, or your own order bottom to top. Typing a new search or leaving a tab ends its sort; a new tab starts unsorted; a reference view and back keeps it.
- Right-clicking the list offers **Paste Note as Reference at Top** (⌘R) beside Paste Note at Top.
- Backlinks (`↖`) are hidden for now, until they have a sign of their own.
- Coming back to a tab, or from a reference view, lands exactly where you were; a note just below the top could put you up to 80px further down.
- **Find in the list** (Cmd/Ctrl+F) finds text far below the loaded notes and inside folded ones; a folded match opens just for the find.
- Namespaces are called **vaults** on screen; `--vault` works like `--namespace`.
- Edit tag relationships: suggestions list tags linked to the focus tag first, a condition shows one part per line, and with no focus tag the `+` buttons are dimmed instead of stopping MetaList.
- A file link downloads only from its badge and name; a click beside it edits the note.
- Make Bigger, Make Smaller and Reset Size keep the caret on its side of the image.
- Logging out while a log entry was being written could close the log under it; the logout now waits.

## 0.22.0

- Tag suggestions only narrow as you type, however many letters: `q`, `qu`, `que` keep their order, and a tag that already applies (a parent's, or implied by a rule) stays right after the tags with evidence instead of dropping to the bottom. Each letter after the first answers in a few milliseconds. Measured on a 107,000-note namespace, the wanted tag is in the top five more often after two and three letters (90% and 96%, up from 88% and 93%).
- With nothing typed, the tag bar and Suggest Tags with AI no longer offer another spelling of a tag the note has: no `eggs` beside `egg`, no `easter-eggs` beside `easter-egg`. Typing still offers every spelling that matches.
- Synonyms of the tags in the bar are never suggested (no `avocados` once `avocado` is there), and a tag a parent already has is not suggested until you type it, whatever else goes with it.
- The Tag Suggestions setting "Allow suggesting tags that already apply" is removed; a saved choice is dropped.

## 0.21.0

- **Memory usage** (command palette): the server's memory now and at its peak (on a Mac as Activity Monitor counts it), the notes it holds decrypted, how long the last unlock took and where, and *Measure what holds it*, a breakdown of each part; Copy puts it all on the clipboard.
- Much lighter and faster for large namespaces (measured on about 107,500 notes): memory down from about 1.5 GB to about 640 MB, starting the servers from 4.6 to about 2 s (the launch ends with "Ready in"), unlocking from about 9 to about 6 s. Suggestions after typing a tag and a space now come in a few hundredths of a second instead of most of a second, and searches of tags alone are faster.
- Search highlights the quoted phrases it found. `@code` finds every `@code=<language>` note, suggestions offer the family and its members, and `@code=python` can be typed directly.
- **Backup reminder** (command palette): Off, Daily, Weekly (the default), Every 2 weeks or Monthly. When this namespace's newest backup is older than that, a card floats at the bottom right.
- References have one syntax, and embedded notes are drawn like the main tree. ⌘V pastes what is on the clipboard rather than the last copied note, a pasted note keeps each copied note's collapsed or expanded state, and a click on a short Markdown list item edits that item.
- Pasted web addresses lose their tracking parameters.
- AI privacy: the text actually sent is checked against the privacy settings, private search terms are never sent, proposed tags never count toward a whitelist, and changing the privacy settings stops a request already under way.
- Exported HTML is cleaned like the note view and carries its own security policy; code lines stay whole in full screen and in exports.
- Fixed: right-clicking selected images (just pasted, for example) failed instead of opening the image menu; a refused chat Send now stays on screen with its reason; Enter and the arrow keys act only on a suggestion list made for what was typed; the banner and zoom work while editing; clicking a diagram edits it and pictures can be dragged; a move that changes nothing does nothing; a save made while a password is being set (or a backup restored) waits for it to finish instead of failing, and the "Processing" page returns to MetaList on its own; reminder fixes.
- **MetaList now needs Python 3.11 or newer.** Python 3.10 reaches its end of life this month, and Pillow's fixes below no longer support it. An install on Python 3.10 needs a newer Python before it can update.
- Security: Pillow 13.0.0 (eight advisories in decoding crafted TIFF, GIF, PPM, EPS and PDF files, which MetaList meets in remote images and attachments), pypdf 6.21.1 (crafted PDFs that loop, use too much memory, or reach arbitrary image parsers), aiohttp 3.14.4 (GHSA-2g87-pp6c-29x5), certifi 2026.10.19 and uv 0.13.4. The source repository moved to metalist-app/metalist.

## 0.20.0

- **Suggest Tags with AI** for the note being edited: right-click the note, or its tag bar past the tags, and choose 🤖 Suggest Tags with AI (for a note with children: This Note, or This Note and Its Children). The proposals appear under the tag bar for `+`/`−`, tags not yet in use marked **new** and grouped on the right; adding them can be undone. It shows only when an AI is set up and may see the note.
- The robot count (🤖 N) next to a note: click it to open every collapsed note on the way to its proposals and edit the highest one that has some; right-click it to Accept All or Reject All, one undo step.
- **Print**: the note menu's Print ▸ Note / View, the background menu's Print View, or the palette's Print view, through the browser's print dialog (Save as PDF included). Always light, fully expanded, without arrows, using the page's full width with its own margins, so the browser prints no header or footer.
- Export as HTML and Print open one dialog: a title with a smart default (the note's first line, or MetaList with the view's search), which heads the page unless the first note already says it and names an exported file; 🤖 Suggest with AI for the title, asked only when you press it, which never sees private notes, usernames, passwords or the search; and, when some would show, an Include Unredacted Passwords / Usernames checkbox (unchecked: each shows `••••••••`, whatever its length).
- Exported HTML files show the view as it is shown (its search, sort order, Untagged view; notes a search leaves out are absent), start fully expanded with MetaList's collapse arrows working in the file, and copy usernames, included passwords and `@copyable` values on click. Collapsing no longer shifts the page sideways.
- `@username` notes are private like `@password`: never sent to the AI. Username, password and email rows show just their icon, named on hover, and the value.
- Text never runs out of its note: a word too long for the line (a token, a hash, a long URL) breaks at the note's edge, and code, `@json`, `@diff`, CSV and Markdown code blocks wrap. Images shrink to fit their note or embedded note, and `@size` scales them only up to that width.
- The light theme's header bar is black again, with white icons and count, and the AI chat header now lines up with the search bar.

## 0.19.0

- Paste formats: pasting a fenced code block that names its language tags the note `@markdown`, and `@markdown` now colours that code like `@code=<language>` (with its label). Code copied from VS Code is tagged `@code=<its language>`, and cells copied from Excel, Google Sheets or Numbers become CSV text tagged `@csv`.
- Text that only looks like a format is offered, not applied: after pasting CSV-like, Markdown-like or code-like text, a small card says "Apply as CSV" / "Apply as Markdown" / "Apply as Python" (up to three close languages for code) with "Skip". The card moves nothing and never takes the keyboard; typing on, Escape or a click elsewhere closes it. It also appears when the paste makes a new note.
- Right-click a tag already in the tag bar or the search box for **About this tag**: whether the note names it, the notes it shares with your other tags, whether a parent or a rule already gives it, its synonyms and implications, how many notes have it ("Only on this note" hints at a typo); in the search box, what it finds and what leaving it out removes. Edit Tag Relationships now comes first in the tag menu, at a fixed place under the pointer.
- Tag suggestions: a web address in a note counts only by its site's name, so a YouTube link no longer suggests `HTTPS` or `V-neuron`; one letter alone no longer names a tag with longer words. A suggestion without evidence now says only what is true (what you typed matches, which part of its name the note has) instead of "Nothing in this note points to it".
- Fixed: accepting a Grammarly suggestion while editing could undo itself and end editing, when Grammarly drew its card in an element MetaList did not recognise.
- Removed the "Make pseudo-suggestions" test item from the note menu.

## 0.18.0

- Right-click a tag suggestion, in the tag bar or the search bar, to see why it is suggested. The menu starts with **Why suggested**: the words of the note that name the tag (or a synonym), the tags it goes with and on how many notes, notes sharing this note's tags, whether it already applies through a parent or a rule, or that nothing in the note points to it; then how often the tag is used. Search suggestions also say how often you worked with a tag lately (when that put it first), what your search so far finds, or what leaving it out removes. The reasons are MetaList's own ranking, not the AI's, and appear instantly.
- Fixed: right-clicking a suggestion closed the list and opened the menu of the note underneath (or the browser's own menu). The list, your typed letters and the cursor now stay as they were, and `Escape` on an open right-click menu closes only the menu instead of also leaving edit mode.

## 0.17.0

- A whole-view summary that fails or is stopped keeps the batches it finished; saying "try that again" continues it, running only the remaining batches with the original question.
- The AI remembers a failed request and the explanation you saw, so you can say "try that again" or ask why it failed. Every failure explanation now ends with where the run stopped: the step, how long it had been there, and the step before.
- Until OpenAI responds, the chat says "Waiting for OpenAI…" instead of "Thinking…". A request OpenAI never answers fails after 15 seconds at Off or Low thinking (60 s Medium, 120 s High) with a message to check the internet connection, instead of waiting up to 10 minutes.
- Questions that do not read your notes answer faster in large views: the view is no longer processed note by note up front. With diagnostic activity on, the first line shows how long preparing the view took, and each step shows how much note text it read.
- Summaries no longer fail because the AI left out its list of supporting notes (OpenAI now enforces the answer format), and a retry tells the model what was wrong.
- Fixed: pressing Stop ended in a fatal error; stray boxes and "cite" appeared around some citations; a step OpenAI never answered was described as "the reply was empty".

## 0.16.0

- Right-clicking outside any note opens a fuller menu: Add/Paste Note at Top, Undo, Redo, Go to Top, Go to Bottom, Fully Expand/Collapse All, View (All or Untagged notes), Sort by, Show (Chat, Tabs, Tags in List), Theme (System, Light, Dark), New Tab, Open/Switch Namespace, Reminders, Export View as HTML and Log Out. The current choices are ticked.
- The note menu is grouped: Copy Note, Paste, Add, Move, Outline, Focus, Export, the editing actions, and Delete Note last. Keyboard shortcuts show on the right of both menus, and actions that cannot happen from that note are hidden.
- Move to Bottom (in Move, or ⇧⌘↓) puts a note after its last sibling, or after the view's last note (the last match in a search). The view stays put: the notes above keep their place and the ones below close the gap.
- A down arrow under the up arrow goes to the bottom of the list, even when the end is not loaded yet; each arrow is dimmed when you are already at its end. Both arrows, and Focus ▸ Full Screen (now also offered while editing), save the note and leave edit mode first.
- The right-click menu closes when the pointer moves well away from it, and keys pressed in full-screen view no longer reach the list behind it.

## 0.15.0

- Pasting JSON, a chess position (FEN), a diff, a Mermaid diagram or a LaTeX block tags the note for it as you paste: the plain tag into an empty note, `((…))` around the paste in a note that already has text. ⌘Z right after the paste removes the tag with it; ⇧⌘V pastes without detection.
- New formats: `@code=python` (or any language) highlights code, `@diff` colours diffs, `@mermaid` draws a diagram without a Markdown fence, and `@chess` draws a FEN position as a board. JSON, code and diff blocks are more compact.
- Switching namespace stays in one tab: on the login screen the panel clears as you pick and the other namespace's login screen fades in under the same logo, with no white flash. In the app, Open/Switch namespace offers Open in This Tab or Open in New Tab.
- Tag suggestions: tags used elsewhere in the tree, or named in nearby notes, no longer get a boost; only the note's own text does. A new Tag Suggestions setting can also suggest tags that a parent or the rules already apply.
- Change password with no password opens Add password, and Open/Switch namespace with only one namespace opens Create namespace. The AI tag-proposal menu items now say they are about AI-proposed tags.
- Fixed: Add reminder did nothing (a missing title now says so); a password change could end on Session locked; right-clicking math or a Mermaid diagram showed the browser's menu; the Untagged notes × needed two clicks while editing a note; indented JSON and pie charts pasted into a note showed as invalid; a tiny scrollbar beside tall math; a white stripe and logo shift on the login screen with always-visible scrollbars.

Older versions are in the releases-2 help topic.
