# MetaList release notes

What changed in each MetaList version, newest first, from its changelog
(CHANGELOG.md). Changes made after the newest listed version are not described here.
Compare with installed_version from the help lookup to tell the user whether
they already have a release. Version info offers updates (see the data topic).

## 0.33.0

- **A link can lead to words inside a note.** Type `[[`, a note's name and `#` (`[[Trip plan#`): the list shows that note's lines, headings first, and letters after the `#` narrow them. Choosing a line writes a link to those words. Clicking the link opens the note with the words brought into view and marked; the mark goes at your next click, scroll or key. Any text in the note or in a note under it can be pointed at, not only a heading. If the words are later reworded, the link still opens the note.
- A link to a place reads the note's first line, ` > ` and the words, each shortened to its first sentence or the part before its first comma: `galleries are confusing > only some pdfs displayed?`. `|title` still gives a link text of its own.
- **A click on a gallery tile opens what it shows.** A PDF, a Markdown, text, code or data file, and any file shown by its badge open in the viewer; a picture opens full screen, as before. Some tiles did nothing when clicked.
- **Importing a folder again:** a link from a note that comes in to a note the import leaves alone (unchanged, or left out by Changed since) now leads to that note in your vault.
- Fixed: in 0.32.0, importing an Obsidian or Markdown folder again with Replace could leave a link to a heading in an unchanged file leading nowhere.

## 0.32.0

- **Importing a folder again can replace what came in before.** When some of a folder's files were imported earlier (the same folder into the same place), the Summary says when, how many changed since and how many of those you edited in MetaList, and asks: **Keep both** (chosen at first) or **Replace the old notes**. Replace puts a changed file's notes where the old ones were, so links to them keep working, leaves unchanged files alone, and keeps notes you edited unless you tick their box. Folders imported with an earlier MetaList are not recognized: importing them again only adds, as before. Bookmarks still only add.
- **Changed since.** The import's Folder screen has a date, empty at first: only the files changed on that day or later come in.
- **1 to 9 switch search contexts.** With nothing being typed, a number key goes to the search context the list shows under that number.
- **Galleries:** a `@gallery` note inside an embed shows its grid, its switch and, folded, its row of pictures. A file with no picture of its own is one tile, and a Markdown, text, code or data file shows the top of the file as a small page. The switch sits right under the fold arrow.
- **Restore From Backup** lists a row per backup (vault, date, size, place), grouped by vault with the open one first, and Choose File… picks a backup from anywhere on the computer MetaList runs on.
- **Dropping files:** while a note is being edited, every dropped file goes into that note, wherever it is let go. A dropped `.md` file asks Note or File; Note makes a note with the file's text, tagged `@markdown`. A file dropped on the page keeps the date it was last changed (it took the time of the drop).
- **Tag suggestions:** as you type, the matching tags come in the order of those the note's text names, those that already apply, then the rest, each by how often you use it. With nothing typed, the tag bar no longer offers a tag the list's search excludes, nor both a word and its plural. A pointer resting over the list no longer highlights a suggestion.
- **The AI can say why MetaList works the way it does:** ask it why something behaves as it does, and it answers from the reasons recorded for each design decision, or says none is recorded.
- The phone layout needs a touch screen as well as a narrow window. Password Audit's summary names `@password` and says what to do when it finds none.
- This release upgrades each vault when it is first opened (database version 21). An older MetaList cannot open an upgraded vault.
- Fixed: Export as HTML failed for a view with a gallery holding a PDF; a problem report now and then could not be made, and its code locations were always empty.

## 0.31.0

- **Deleting a folder with its notes deletes their files too.** Delete Folder… says what goes ("Also delete its 1289 notes and their 212 files (1.8 GB)") and deletes the notes and those files in one step; the box now starts ticked. Delete Notes (Current View)… does the same. Before, the files stayed in the vault, and in every backup, until Trim Unused Files… was run. A file a note that stays also uses is kept. Deleting a single note still keeps its files, so ⌘Z can bring it back.
- **Back Up Now… offers to trim first.** When the vault holds files no note uses, the dialog shows "Trim N unused files (size) first"; ticked, they are deleted before the backup is made.
- **No red error after restoring the vault you have open.** Looking at another browser tab before closing "Backup restored" showed a red error, and Export Report… on it failed with a second one.
- **Export Report… works after your session has ended,** with a report of the error and what led to it, and nothing from the vault. If no report can be made, MetaList says so and the error stays on screen.
- The red error has a Copy button, and messages now appear below it instead of underneath it.
- Search contexts keep up more reliably when MetaList is open in several tabs or on your phone: each change (a search, an order, a context made or deleted) is sent on its own, so one tab can no longer put back what another changed.
- MetaList's startup lists the network address of each vault shared on the network.
- Fixed: a red error when a redraw shortened the text under the caret; typing straight after a click in the tag bar was lost; Back Up Now… could not be left while it loaded; an error about a search context another tab had just deleted; in Firefox, a picture that now and then stayed empty.

## 0.30.1

- **MetaList on Windows is fast again when it is doing two things at once.** In 0.30.0, on Windows, MetaList slowed to a crawl whenever work overlapped: an AI question while the list searched, or anything just after unlocking or importing into a large vault. An AI answer over a large vault that took minutes takes seconds.
- **A search you type is no longer thrown away.** Typing or clearing the search just after an AI answer, or while another tab or your phone changed the search contexts, could leave the list on the old search.
- MetaList no longer refreshes its search contexts a second after you click into or out of the search box. A click made at that moment could land on the wrong thing.
- The AI chat no longer loads itself a second time just after it opens.
- Work MetaList does in the background now also waits while the AI is reading your notes for an answer.
- Fixed: a red error while scrolling in Firefox; menus and dialogs refused for a moment while a change from another tab arrived.

## 0.30.0

- **Password Audit.** In the command palette, Password Audit… checks every password in the vault and lists the leaked (if you turn that check on), reused, weak and old ones, each a click from its note. It keeps up while open as you change passwords, and a reminder offers it now and then in a vault with passwords.
- **Following a link turns to a page,** no longer opening a search context. The page shows the linked note alone, as if it were a root, with the notes under it; ◀ goes back, ⏮ straight back to your search, ▶ forward again. Each search context keeps the page it is on (its row reads `miscellaneous > Source note`), and deleting the note a page shows closes the page.
- **Backlinks** (once "Referenced by"): a note other notes reference shows the link icon mirrored instead of a number; its page lists the notes most recently edited first.
- **Each vault says whether it is shared on the network,** in Manage Vault Ports. A shared vault accepts this computer's own names and addresses as they are now, so a new address from the router needs no change. Vaults shared before stay shared. `METALIST_HOST` is no longer read: MetaList refuses to start while it is set.
- **No pause after logging in:** work MetaList does in the background waits while you are using it.
- **Typing a search no longer stalls MetaList on a slow computer:** suggestions are asked for one at a time and never hold up your notes. Before, a page could wait minutes for them.
- AI answers keep the web pages they cite, and the AI cites the note that makes sense on its own.
- Fixed: a red error after saving an Excalidraw drawing; a red error when an AI answer sent an empty piece; the Password Audit, a preview or full screen failing when a note was deleted at the same moment.
- Search contexts and reference views saved by 0.29.0 open as reference pages.
- Vaults are upgraded (database version 20) when first unlocked, or at startup without a password, after a backup: an older MetaList cannot open them afterwards.

## 0.29.0

- **Two new looks under Theme:** Phosphor, a green terminal screen in your system's monospace font where nothing ever animates, and Vellum, warm cream paper with notes in a book serif (Source Serif 4) for long reading.
- Problem report files are named by your own date and time, one way for all of them: `metalist-problem-report-2026-11-12 18-52-09.json`, and `metalist-problem-reports-…` for several exported together.

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

Older versions are in the releases-2 help topic.
