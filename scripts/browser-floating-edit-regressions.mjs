import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Editing a note in a floating window (agreed with the maintainer 2026-11-21, cases 1 to 7;
// docs/ui/state-handling.md, "Floating note windows"). The window holds "Trip plan" with
// "Tickets" (and "Train" under it) and "Packing".
// 1. A click on a note in the window edits it there, the caret where clicked, with its tag
//    bar; a note edited in the list is saved and left first.
// 2. The editor works as in the list: the `[[` list and the tag suggestions show whole.
// 3. Escape saves and leaves edit mode, the window staying (and keeping the focus); a second
//    Escape closes it. A click outside the window leaves edit mode too.
// 4. The list's copy of the note shows the pencil; a click in it moves the editing to the list.
// 5. The caret stays in the window's own scrolling area, above the tag bar; the page stays still.
// 6. The window does not take others' text changes while a note in it is edited; it shows
//    them once editing leaves it.
// 7. A new note made from the window is edited there; a note moved out from under the
//    window's note is edited in the list. No new note goes beside the window's own note
//    (⌘Enter on it, ⌘⌥Enter under it): it would be outside the window; nor is the window's own
//    note deleted or cut out from inside the window (⌘⌫, ⌘X, the menu), 2026-11-22.
// And, agreed 2026-11-22, a window draws its notes as the list does:
// 9. A gallery shows its grid only, with its switch; the switch is the list's choice too.
// 10. Notes are folded as saved, with their arrows; an arrow folds or unfolds the note
//     everywhere, also while a note in the window is edited.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
const LONG_LINES = 40;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const MODIFIER = process.platform === 'darwin' ? 'Meta' : 'Control';

// The caret to the end of the edited text. Not a key: End scrolls the page in Firefox on a
// Mac, and ⌘→ indents the note in MetaList.
async function goToLineEnd(page) {
  await page.evaluate(() => {
    const selection = getSelection();
    selection.selectAllChildren(document.activeElement);
    selection.collapseToEnd();
  });
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function makeNotes(page) {
  return page.evaluate(async (longLines) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const lines = Array.from({length: longLines}, (_, index) => `<div>Packing line ${index + 1}</div>`).join('');
    const trip = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(trip.id, '<div>Trip plan</div>', '');
    const tickets = await NotesAPI.createChild(trip.id, '');
    await NotesAPI.saveNote(tickets.id, '<div>Tickets to Lisbon</div>', '');
    const train = await NotesAPI.createChild(tickets.id, '');
    await NotesAPI.saveNote(train.id, '<div>Train at 9:40</div>', '');
    const packing = await NotesAPI.createSibling(tickets.id, '');
    await NotesAPI.saveNote(packing.id, `<div>Packing</div>${lines}`, '');
    const groceries = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(groceries.id, '<div>Groceries for the week</div>', '');
    // A gallery of two Markdown files, as the maintainer's "Centuries of Steel".
    const gallery = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(gallery.id, '<div>Centuries of Steel</div>', '@gallery=markdown');
    for (const name of ['Addendum.md', 'Design notes.md']) {
      const uploaded = await FilesAPI.uploadFile(new File([`# ${name}\n\nThe game should support asynchronous play.\n`], name, {type: 'text/markdown'}));
      const child = await NotesAPI.createChild(gallery.id, '');
      await NotesAPI.saveNote(child.id, `<p>${uploaded.reference_token}</p>`, '');
    }
    return {trip: trip.id, tickets: tickets.id, train: train.id, packing: packing.id, groceries: groceries.id, gallery: gallery.id};
  }, LONG_LINES);
}

async function openWindow(page, noteId) {
  await page.evaluate(async id => {
    const {openFloatingNote} = await import('/static/js/modules/mode-manager/services/floating-note-service.js');
    await openFloatingNote(id);
  }, noteId);
  await idle(page);
}

async function closeWindows(page) {
  await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {actionDeselectNote} = await import('/static/js/modules/mode-manager/actions/selection-actions.js');
    const {closeAllFloatingNotes} = await import('/static/js/modules/mode-manager/services/floating-note-service.js');
    if (mode.isEditing) await actionDeselectNote();
    closeAllFloatingNotes();
  });
  await idle(page);
}

// A point in a note's text as the window draws it now: read-only (in its shadow root) or
// being edited (in the page), `characterIndex` into its first line.
function pointInWindowNote(page, noteId, characterIndex) {
  return page.evaluate((id, index) => {
    const host = document.querySelector('.floating-note-window');
    let content = host.querySelector(`.floating-note-editing-tree .note[data-note-id="${id}"] > .note-content`);
    if (content === null) content = host.shadowRoot.querySelector(`.note[data-note-id="${id}"] > .note-content`);
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    const text = walker.nextNode();
    const range = document.createRange();
    range.setStart(text, index);
    range.setEnd(text, index + 1);
    const box = range.getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2};
  }, noteId, characterIndex);
}

function editingState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const surface = await import('/static/js/modules/editing-surface.js');
    const host = document.querySelector('.floating-note-window');
    let windowEditable = [];
    let windowShowsNotes = false;
    if (host !== null) {
      windowEditable = [...host.querySelectorAll('.floating-note-editing-tree .note-content[contenteditable="true"]')]
        .map(content => content.closest('.note').dataset.noteId);
      windowShowsNotes = host.querySelector('.floating-note-editing-tree') === null
        && !host.shadowRoot.querySelector('.floating-note-tree').hidden;
    }
    return {
      isEditing: mode.isEditing, noteId: mode.currentNoteId, isInWindow: surface.isEditingInWindow(),
      windowEditable, windowShowsNotes, windows: document.querySelectorAll('.floating-note-window').length,
      focusOnWindow: host !== null && document.activeElement === host,
    };
  });
}

function listCopy(page, noteId) {
  return page.evaluate(id => {
    const note = document.querySelector(`#notes-container .note[data-note-id="${id}"]`);
    if (note === null) return null;
    const content = note.querySelector(':scope > .note-content');
    return {text: content.textContent, isEditable: content.isContentEditable,
      hasPencil: note.querySelector(':scope > .note-edited-in-window') !== null};
  }, noteId);
}

function savedText(page, noteId) {
  return page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const answer = await NotesAPI.getFloatingNote(id, '');
    const holder = document.createElement('div');
    holder.innerHTML = answer.notes[id].content;
    // Firefox types a space at a line's end as a non-breaking one.
    return holder.textContent.replaceAll('\u00a0', ' ');
  }, noteId);
}

// The caret's offset in its text node and that text, for "the caret is where clicked".
function caretAt(page) {
  return page.evaluate(() => {
    const selection = getSelection();
    return {offset: selection.focusOffset, text: selection.focusNode.textContent};
  });
}

async function clickEditsInTheWindowAndLeavesTheList(page, ids) {
  // A note edited in the list first: typed in, then a click in the window.
  await page.click(`#notes-container .note[data-note-id="${ids.groceries}"] > .note-content`);
  await idle(page);
  await goToLineEnd(page);
  await page.keyboard.type(' and fruit');
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.tickets, 3);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  const state = await editingState(page);
  assert.equal(state.noteId, ids.tickets, 'the note clicked in the window is edited');
  assert.equal(state.isInWindow, true, 'it is edited in the window');
  assert.deepEqual(state.windowEditable, [ids.tickets], 'only it is editable in the window');
  // The caret where clicked: the character under the pointer is the 4th, "k" of "Tickets".
  const caret = await caretAt(page);
  assert.equal(caret.text, 'Tickets to Lisbon');
  assert.ok(caret.offset === 3 || caret.offset === 4, `the caret is at the clicked letter, at ${caret.offset}`);
  assert.equal(await page.$eval(`.floating-note-editing-tree .note[data-note-id="${ids.tickets}"] .note-tag-bar-input`, input => input.isConnected), true,
    'the note edited in the window has its tag bar');
  const groceries = await listCopy(page, ids.groceries);
  assert.equal(groceries.isEditable, false, 'the note edited in the list was left');
  assert.equal(await savedText(page, ids.groceries), 'Groceries for the week and fruit', 'and saved first');
}

async function suggestionListsShowWhole(page, ids) {
  await goToLineEnd(page);
  await page.keyboard.type(' [[Groceries');
  await page.waitForSelector('.reference-suggestions:not([hidden])', {visible: true});
  const references = await page.evaluate(() => {
    const list = document.querySelector('.reference-suggestions');
    const box = list.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    let hitName = "nothing";
    if (hit !== null) hitName = `${hit.tagName}.${hit.className}`;
    const content = document.querySelector('.floating-note-editing-tree .note-content[contenteditable="true"]');
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    let trigger = null;
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      const at = text.data.indexOf('[[');
      if (at >= 0) {
        const range = document.createRange();
        range.setStart(text, at);
        range.setEnd(text, at + 2);
        const rect = range.getBoundingClientRect();
        trigger = [rect.left, rect.top, rect.width, rect.height, text.data];
      }
    }
    return {isOnTop: list.contains(hit), hit: hitName, box: [box.left, box.top, box.width, box.height], trigger};
  });
  assert.equal(references.isOnTop, true, `the [[ list shows above the window: ${JSON.stringify(references)}`);
  await page.keyboard.press('Escape');
  await idle(page);
  // The tag bar: its suggestions open upward, inside the window's scrolling area.
  await page.keyboard.press('Tab');
  await page.keyboard.type('@mark');
  await page.waitForSelector(`.floating-note-editing-tree .note[data-note-id="${ids.tickets}"] .note-tag-suggestions:not([hidden])`);
  await idle(page);
  const tags = await page.evaluate(id => {
    const list = document.querySelector(`.floating-note-editing-tree .note[data-note-id="${id}"] .note-tag-suggestions`);
    const area = document.querySelector('.floating-note-window').shadowRoot.querySelector('.floating-note-scroll').getBoundingClientRect();
    const box = list.getBoundingClientRect();
    return {top: box.top, bottom: box.bottom, areaTop: area.top, areaBottom: area.bottom, text: list.textContent};
  }, ids.tickets);
  assert.match(tags.text, /@markdown/);
  assert.ok(tags.top >= tags.areaTop && tags.bottom <= tags.areaBottom, `the tag suggestions are inside the window: ${JSON.stringify(tags)}`);
  // Clear the typed tag start, then back to the text.
  for (let index = 0; index < '@mark'.length; index++) await page.keyboard.press('Backspace');
  await page.keyboard.press('Tab');
  await idle(page);
}

async function escapeLeavesThenCloses(page, ids) {
  await page.keyboard.press('Escape');
  await idle(page);
  let state = await editingState(page);
  assert.equal(state.isEditing, false, 'Escape leaves edit mode');
  assert.equal(state.windows, 1, 'the window stays');
  assert.equal(state.windowShowsNotes, true, 'the window shows its notes again');
  assert.equal(state.focusOnWindow, true, 'the window keeps the focus');
  assert.match(await savedText(page, ids.tickets), /^Tickets to Lisbon/, 'the note was saved');
  await page.keyboard.press('Escape');
  await idle(page);
  state = await editingState(page);
  assert.equal(state.windows, 0, 'a second Escape closes the window');
  // A click outside the window (on another note in the list) leaves the window too.
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.train, 2);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  await page.click(`#notes-container .note[data-note-id="${ids.groceries}"] > .note-content`);
  await idle(page);
  state = await editingState(page);
  assert.equal(state.noteId, ids.groceries, 'the note clicked in the list is edited');
  assert.equal(state.isInWindow, false);
  assert.equal(state.windowShowsNotes, true, 'the window shows its notes again');
  await closeWindows(page);
}

async function theListCopyShowsThePencilAndTakesTheEditing(page, ids) {
  // "Trip plan" is in the list: its copy shows the pencil while the window edits it.
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.trip, 1);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  let copy = await listCopy(page, ids.trip);
  assert.deepEqual({hasPencil: copy.hasPencil, isEditable: copy.isEditable}, {hasPencil: true, isEditable: false},
    'the list copy shows the pencil and is not edited');
  // A click in the list copy, right of the window, moves the editing there.
  const point = await page.evaluate(id => {
    const content = document.querySelector(`#notes-container .note[data-note-id="${id}"] > .note-content`);
    const box = content.getBoundingClientRect();
    return {x: box.right - 20, y: box.top + box.height / 2};
  }, ids.trip);
  await page.mouse.click(point.x, point.y);
  await idle(page);
  const state = await editingState(page);
  copy = await listCopy(page, ids.trip);
  assert.equal(state.noteId, ids.trip);
  assert.equal(state.isInWindow, false, 'the editing moved to the list');
  assert.deepEqual({hasPencil: copy.hasPencil, isEditable: copy.isEditable}, {hasPencil: false, isEditable: true});
  assert.equal(state.windowShowsNotes, true);
  await closeWindows(page);
}

async function theCaretStaysInTheWindow(page, ids) {
  // From the page's top: the note's copy in the list grows as it saves, and with the page scrolled
  // the list keeps the note at its top still by scrolling (the list's own rule, not the window's).
  await page.evaluate(() => window.scrollTo(0, 0));
  await idle(page);
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.packing, 2);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  const pageTop = await page.evaluate(() => window.scrollY);
  for (let line = 0; line < LONG_LINES; line++) await page.keyboard.press('ArrowDown');
  await page.keyboard.type('x');
  await page.keyboard.press('Enter');
  await idle(page);
  const where = await page.evaluate(id => {
    const range = getSelection().getRangeAt(0);
    let caret = range.getBoundingClientRect();
    if (caret.height === 0) caret = range.startContainer.getBoundingClientRect();
    const bar = document.querySelector(`.floating-note-editing-tree .note[data-note-id="${id}"] .note-tag-bar`).getBoundingClientRect();
    const area = document.querySelector('.floating-note-window').shadowRoot.querySelector('.floating-note-scroll');
    return {caretTop: caret.top, caretBottom: caret.bottom, barTop: bar.top, areaTop: area.getBoundingClientRect().top,
      areaScrolled: area.scrollTop, pageTop: window.scrollY};
  }, ids.packing);
  assert.equal(where.pageTop, pageTop, 'the page behind the window stays still');
  assert.ok(where.areaScrolled > 0, 'the window scrolled');
  assert.ok(where.caretTop >= where.areaTop && where.caretBottom <= where.barTop,
    `the caret is in the window, above the tag bar: ${JSON.stringify(where)}`);
  await closeWindows(page);
}

async function othersChangesWaitUntilEditingLeaves(page, ids) {
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.tickets, 2);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  // Another view changes "Train" meanwhile.
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(id, '<div>Train at 10:15</div>', '');
  }, ids.train);
  await pause(1500);
  await idle(page);
  const shown = await page.$eval(`.floating-note-editing-tree .note[data-note-id="${ids.train}"] > .note-content`, content => content.textContent);
  assert.equal(shown, 'Train at 9:40', 'the window keeps what it showed while a note in it is edited');
  await page.keyboard.press('Escape');
  await idle(page);
  const after = await page.evaluate(id => document.querySelector('.floating-note-window').shadowRoot
    .querySelector(`.note[data-note-id="${id}"] > .note-content`).textContent, ids.train);
  assert.equal(after, 'Train at 10:15', 'the window shows the change once editing leaves it');
  await closeWindows(page);
}

async function newNotesStayAndMovedNotesLeave(page, ids) {
  await openWindow(page, ids.trip);
  const clicked = await pointInWindowNote(page, ids.train, 2);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  await page.keyboard.down(MODIFIER);
  await page.keyboard.press('Enter');
  await page.keyboard.up(MODIFIER);
  await idle(page);
  await page.keyboard.type('Bus at noon');
  await idle(page);
  let state = await editingState(page);
  assert.equal(state.isInWindow, true, 'the new note is edited in the window');
  assert.notEqual(state.noteId, ids.train);
  const newId = state.noteId;
  assert.equal(await page.$eval(`.floating-note-editing-tree .note[data-note-id="${newId}"]`, note => note.dataset.parentId), ids.tickets,
    'it is drawn below "Train", under "Tickets"');
  // ⌘← twice: under "Trip plan", then beside it, out of the window.
  await page.keyboard.down(MODIFIER);
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.up(MODIFIER);
  await idle(page);
  state = await editingState(page);
  assert.equal(state.isInWindow, true, 'still under the window\'s note');
  // The window draws its notes again once the move's command is over (followEditedNote).
  await page.waitForFunction((id, parentId) => {
    const note = document.querySelector(`.floating-note-editing-tree .note[data-note-id="${id}"]`);
    return note !== null && note.dataset.parentId === parentId;
  }, {}, newId, ids.trip);
  assert.equal(await page.$eval(`.floating-note-editing-tree .note[data-note-id="${newId}"]`, note => note.dataset.parentId), ids.trip);
  await page.keyboard.down(MODIFIER);
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.up(MODIFIER);
  await idle(page);
  state = await editingState(page);
  assert.equal(state.noteId, newId);
  assert.equal(state.isInWindow, false, 'moved out of the window, it is edited in the list');
  assert.equal((await listCopy(page, newId)).isEditable, true);
  assert.equal(state.windowShowsNotes, true);
  await closeWindows(page);
  return newId;
}

// The notes of the vault, for "no note was made".
function noteCount(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return (await NotesAPI.fetchView(mode.currentNoteId, null, mode.activeTabId, {topRootId: null, bottomRootId: null}, false)).snapshot.rootCountTotal;
  });
}

async function pressWith(page, keys, key) {
  for (const held of keys) await page.keyboard.down(held);
  await page.keyboard.press(key);
  for (const held of [...keys].reverse()) await page.keyboard.up(held);
  await idle(page);
}

// The note menu of a note in the window being edited: its items, and those of its Add submenu.
async function windowNoteMenu(page, noteId) {
  const point = await pointInWindowNote(page, noteId, 1);
  await page.mouse.click(point.x, point.y, {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible');
  await pause(SETTLE_MS);
  const items = await page.$$eval('.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item-label',
    found => found.map(label => label.textContent));
  const entries = await page.$$('.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item');
  for (const entry of entries) {
    if (await entry.$eval('.context-menu-item-label', label => label.textContent) === 'Add') {
      await entry.click();
      await pause(SETTLE_MS);
      break;
    }
  }
  const add = await page.$$eval('.context-menu-submenu.is-visible .context-menu-item-label', found => found.map(label => label.textContent));
  await page.keyboard.press('Escape');
  await idle(page);
  return {items, add};
}

async function noteIsThere(page, noteId) {
  return page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    return (await NotesAPI.getFloatingNote(id, '')).status === 'ready';
  }, noteId);
}

async function nothingGoesBesideTheWindowsNote(page, ids) {
  await openWindow(page, ids.trip);
  const roots = await noteCount(page);
  const onTrip = await pointInWindowNote(page, ids.trip, 1);
  await page.mouse.click(onTrip.x, onTrip.y);
  await idle(page);
  await pressWith(page, [MODIFIER], 'Enter');
  let state = await editingState(page);
  assert.deepEqual({noteId: state.noteId, isInWindow: state.isInWindow}, {noteId: ids.trip, isInWindow: true},
    '⌘Enter on the window\'s own note does nothing');
  assert.equal(await noteCount(page), roots, 'no note was made beside it');
  const onTickets = await pointInWindowNote(page, ids.tickets, 2);
  await page.mouse.click(onTickets.x, onTickets.y);
  await idle(page);
  await pressWith(page, [MODIFIER, 'Alt'], 'Enter');
  state = await editingState(page);
  assert.deepEqual({noteId: state.noteId, isInWindow: state.isInWindow}, {noteId: ids.tickets, isInWindow: true},
    '⌘⌥Enter under the window\'s own note does nothing');
  assert.equal(await noteCount(page), roots, 'no note was made beside the window\'s note');
  // A note right under the window's note: no "one level out" in its menu.
  assert.equal((await windowNoteMenu(page, ids.tickets)).add.includes('Add Note One Level Out'), false,
    'no Add Note One Level Out under the window\'s note');
  // The window's own note: its menu offers no sibling and no delete; ⌘⌫ and ⌘X leave it.
  await page.mouse.click(onTrip.x, onTrip.y);
  await idle(page);
  const menu = await windowNoteMenu(page, ids.trip);
  assert.equal(menu.items.includes('Delete Note'), false, 'no Delete Note for the window\'s note');
  // With one Add entry left, the menu shows it on its own (pushGroup).
  const offered = [...menu.items, ...menu.add];
  assert.equal(offered.includes('Add Sibling Note'), false, 'no Add Sibling Note for it');
  assert.equal(offered.includes('Add Child Note'), true, 'Add Child Note stays');
  await page.mouse.click(onTrip.x, onTrip.y);
  await idle(page);
  await pressWith(page, [MODIFIER], 'Backspace');
  await pressWith(page, [MODIFIER], 'x');
  state = await editingState(page);
  assert.deepEqual({noteId: state.noteId, isInWindow: state.isInWindow}, {noteId: ids.trip, isInWindow: true},
    'the delete and cut keys do nothing to the window\'s own note');
  assert.equal(await noteIsThere(page, ids.trip), true, 'it is still there');
  await closeWindows(page);
}

// The read-only window's notes: text, folded or not, and whether its arrow shows.
function windowNotes(page) {
  return page.evaluate(() => {
    const root = document.querySelector('.floating-note-window').shadowRoot;
    return [...root.querySelectorAll('.note[data-note-id]')].map(note => {
      const arrow = note.querySelector(':scope > .note-collapse-toggle');
      return {id: note.dataset.noteId, isFolded: note.classList.contains('collapsed'),
        hasArrow: arrow !== null && getComputedStyle(arrow).display !== 'none' && arrow.getBoundingClientRect().width > 0};
    });
  });
}

// The middle of an element in the window: in its read-only drawing, or its notes being edited.
function windowPoint(page, selector) {
  return page.evaluate(found => {
    const host = document.querySelector('.floating-note-window');
    let element = host.querySelector(`.floating-note-editing-tree ${found}`);
    if (element === null) element = host.shadowRoot.querySelector(found);
    const box = element.getBoundingClientRect();
    const area = host.shadowRoot.querySelector('.floating-note-scroll').getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2, isInside: box.left >= area.left && box.right <= area.right};
  }, selector);
}

async function aGalleryShowsItsGridOnly(page, ids) {
  await openWindow(page, ids.gallery);
  const read = () => page.evaluate(id => {
    const note = document.querySelector('.floating-note-window').shadowRoot.querySelector(`.note[data-note-id="${id}"]`);
    const children = note.querySelector(':scope > .note-children');
    const listed = document.querySelector(`#notes-container .note[data-note-id="${id}"]`);
    return {tiles: note.querySelectorAll('.meta-gallery-tile').length, areChildrenShown: getComputedStyle(children).display !== 'none',
      isOutline: note.classList.contains('is-gallery-outline'), isListOutline: listed.classList.contains('is-gallery-outline')};
  }, ids.gallery);
  assert.deepEqual(await read(), {tiles: 2, areChildrenShown: false, isOutline: false, isListOutline: false},
    'the window shows the grid, not the notes under it');
  const toggle = await windowPoint(page, `.note[data-note-id="${ids.gallery}"] .meta-gallery-switch`);
  assert.equal(toggle.isInside, true, 'the switch shows inside the window');
  await page.mouse.click(toggle.x, toggle.y);
  await idle(page);
  assert.deepEqual(await read(), {tiles: 2, areChildrenShown: true, isOutline: true, isListOutline: true},
    'the switch shows the notes, in the window and the list');
  await page.mouse.click(toggle.x, toggle.y);
  await idle(page);
  assert.deepEqual(await read(), {tiles: 2, areChildrenShown: false, isOutline: false, isListOutline: false});
  await closeWindows(page);
}

async function foldsAreSharedWithTheList(page, ids) {
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.collapseNote(id);
  }, ids.tickets);
  await idle(page);
  await openWindow(page, ids.trip);
  let notes = await windowNotes(page);
  assert.deepEqual(notes.map(note => note.id), [ids.trip, ids.tickets, ids.packing], 'a folded note shows none under it');
  assert.deepEqual(notes.find(note => note.id === ids.tickets), {id: ids.tickets, isFolded: true, hasArrow: true});
  const arrow = await windowPoint(page, `.note[data-note-id="${ids.tickets}"] > .note-collapse-toggle`);
  assert.equal(arrow.isInside, true, 'the arrow shows inside the window');
  await page.mouse.click(arrow.x, arrow.y);
  await idle(page);
  notes = await windowNotes(page);
  assert.deepEqual(notes.map(note => note.id), [ids.trip, ids.tickets, ids.train, ids.packing], 'the arrow unfolds it in the window');
  assert.equal(await page.evaluate(id => document.querySelector(`#notes-container .note[data-note-id="${id}"]`).classList.contains('collapsed'), ids.tickets),
    false, 'and in the list');
  // While "Trip plan" is edited in the window, the arrow of "Tickets" folds it everywhere, and
  // "Trip plan" stays edited.
  const clicked = await pointInWindowNote(page, ids.trip, 1);
  await page.mouse.click(clicked.x, clicked.y);
  await idle(page);
  const editingArrow = await windowPoint(page, `.note[data-note-id="${ids.tickets}"] > .note-collapse-toggle`);
  assert.equal(editingArrow.isInside, true, 'the arrow shows while editing');
  await page.mouse.click(editingArrow.x, editingArrow.y);
  await idle(page);
  const state = await editingState(page);
  assert.equal(state.noteId, ids.trip);
  assert.equal(state.isInWindow, true, 'the note stays edited in the window');
  // The window draws its notes again once the fold's command is over (followEditedNote).
  await page.waitForFunction(trainId => document.querySelector(`.floating-note-editing-tree .note[data-note-id="${trainId}"]`) === null, {}, ids.train);
  const drawn = await page.$$eval('.floating-note-editing-tree .note[data-note-id]', elements => elements.map(note => note.dataset.noteId));
  assert.deepEqual(drawn, [ids.trip, ids.tickets, ids.packing], 'the window folds it');
  assert.equal(await page.evaluate(id => document.querySelector(`#notes-container .note[data-note-id="${id}"]`).classList.contains('collapsed'), ids.tickets),
    true, 'and the list does');
  await closeWindows(page);
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.expandNote(id);
  }, ids.tickets);
  await idle(page);
}

// Deleting the note edited in a window, from its menu (the maintainer, 2026-11-22: the window
// kept showing the deleted note as edited, and deleting it again failed with a 404): edit mode
// is over, and the window shows its notes without the deleted one.
async function deletingTheEditedNoteLeavesTheWindowReading(page, ids) {
  await openWindow(page, ids.trip);
  const point = await pointInWindowNote(page, ids.packing, 1);
  await page.mouse.click(point.x, point.y);
  await idle(page);
  await page.mouse.click(point.x, point.y, {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible');
  await pause(SETTLE_MS);
  for (const entry of await page.$$('.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item')) {
    if (await entry.$eval('.context-menu-item-label', label => label.textContent) === 'Delete Note') {
      await entry.click();
      break;
    }
  }
  await idle(page);
  const state = await editingState(page);
  assert.deepEqual({isEditing: state.isEditing, isInWindow: state.isInWindow, windowShowsNotes: state.windowShowsNotes, windows: state.windows},
    {isEditing: false, isInWindow: false, windowShowsNotes: true, windows: 1}, 'the window is back to showing its notes');
  await page.waitForFunction(id => document.querySelector('.floating-note-window').shadowRoot.querySelector(`.note[data-note-id="${id}"]`) === null, {}, ids.packing);
  await closeWindows(page);
}

// A right-click on a note of the window that is not being edited (the maintainer, 2026-11-22):
// the note is edited there and its menu opens, with the items of an edited note.
async function aRightClickOpensTheNoteMenu(page, ids) {
  await openWindow(page, ids.trip);
  const point = await pointInWindowNote(page, ids.train, 2);
  await page.mouse.click(point.x, point.y, {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible');
  await pause(SETTLE_MS);
  const items = await page.$$eval('.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item-label',
    found => found.map(label => label.textContent));
  assert.ok(items.includes('Delete Note') && items.includes('Copy Note'), `the note menu opens: ${JSON.stringify(items)}`);
  const state = await editingState(page);
  assert.deepEqual({noteId: state.noteId, isInWindow: state.isInWindow}, {noteId: ids.train, isInWindow: true},
    'the right-clicked note is edited in the window');
  await page.keyboard.press('Escape');
  await idle(page);
  await closeWindows(page);
}

// A copied note pasted into a blank note edited in a window (the maintainer, 2026-11-22: the
// window kept showing it blank while the list showed its text): the window shows the text too,
// and the note is still the one edited there.
async function aNotePastedIntoABlankNoteShowsInTheWindow(page, ids) {
  await openWindow(page, ids.trip);
  const point = await pointInWindowNote(page, ids.trip, 2);
  await page.mouse.click(point.x, point.y);
  await idle(page);
  // A blank note under "Trip plan", edited in the window.
  await pressWith(page, [MODIFIER, 'Shift'], 'Enter');
  const blankId = (await editingState(page)).noteId;
  assert.notEqual(blankId, ids.trip, 'a new note is edited');
  const wanted = await page.evaluate(id => document.querySelector(`#notes-container .note[data-note-id="${id}"] > .note-content`).textContent, ids.groceries);
  await page.evaluate(async (groceriesId) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {actionPasteNoteSibling} = await import('/static/js/modules/mode-manager/actions/note-actions.js');
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    await NotesAPI.copyNote(groceriesId);
    // What ⌘V does with a copied note (keyboard-events.js).
    await CommandGate.run('test.paste', () => actionPasteNoteSibling());
  }, ids.groceries);
  await idle(page);
  const shown = await page.evaluate((id) => {
    const text = root => root.querySelector(`.note[data-note-id="${id}"] > .note-content`).textContent;
    return {window: text(document.querySelector('.floating-note-window .floating-note-editing-tree')),
      list: text(document.querySelector('#notes-container'))};
  }, blankId);
  assert.deepEqual(shown, {window: wanted, list: wanted});
  const state = await editingState(page);
  assert.deepEqual({noteId: state.noteId, windowEditable: state.windowEditable}, {noteId: blankId, windowEditable: [blankId]},
    'the note is still the one edited in the window');
  await page.keyboard.press('Escape');
  await idle(page);
  await page.evaluate(async (id) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNote(id);
  }, blankId);
  await idle(page);
  await closeWindows(page);
}

export async function checkFloatingEdit(page) {
  await page.setViewport(WINDOW);
  const ids = await makeNotes(page);
  const made = [];
  await runThenCleanUp('floating edit', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await clickEditsInTheWindowAndLeavesTheList(page, ids);
    await suggestionListsShowWhole(page, ids);
    await escapeLeavesThenCloses(page, ids);
    await theListCopyShowsThePencilAndTakesTheEditing(page, ids);
    await theCaretStaysInTheWindow(page, ids);
    await othersChangesWaitUntilEditingLeaves(page, ids);
    made.push(await newNotesStayAndMovedNotesLeave(page, ids));
    await nothingGoesBesideTheWindowsNote(page, ids);
    await aGalleryShowsItsGridOnly(page, ids);
    await foldsAreSharedWithTheList(page, ids);
    await aNotePastedIntoABlankNoteShowsInTheWindow(page, ids);
    await aRightClickOpensTheNoteMenu(page, ids);
    await deletingTheEditedNoteLeavesTheWindowReading(page, ids);
  }, async () => {
    await closeWindows(page);
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, [...made, ids.trip, ids.groceries, ids.gallery]);
    await idle(page);
  });
}
