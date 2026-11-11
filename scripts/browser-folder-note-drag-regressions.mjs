import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Dragging a note from the column onto a virtual folder (docs/ready-to-build/
// virtual-folders.md §4): over the tree the drag becomes a drop into the folder under
// the pointer, the note ends up in exactly that folder, and what changed stays visible. One
// check per agreed case (the maintainer, 2026-11-02), positions exact.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
// Every note of the suite carries it, so its search shows only them.
const SEARCH = 'fdragtest';
const FOLDER_A = 'Dragalpha/';
const FOLDER_B = 'Dragbeta/';
// Where the pointer takes hold of a note's text, from its top left.
const GRAB_OFFSET_PX = 12;
// Pointer steps for a drag, so every move is seen.
const DRAG_STEPS = 16;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const UNDO_MODIFIER = process.platform === 'darwin' ? 'Meta' : 'Control';

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function createNotes(page) {
  return page.evaluate(async ({search, folderA, folderB}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    // createNote(null, '') inserts at the top, so create bottom-up.
    const make = async (name, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>Folder drag ${name}</p>`, tags);
      return note.id;
    };
    const two = await make('two', `${search} ${folderA} ${folderB}`);
    const plain = await make('plain', search);
    const below = await make('below', `${search} ${folderA}`);
    const mover = await make('mover', `${search} ${folderA}`);
    const above = await make('above', `${search} ${folderA}`);
    const child = await NotesAPI.createChild(above, '');
    await NotesAPI.saveNote(child.id, '<p>Folder drag child</p>', search);
    return {above, mover, below, plain, two, child: child.id};
  }, {search: SEARCH, folderA: FOLDER_A, folderB: FOLDER_B});
}

const rowSelector = folder => folder === ''
  ? '#virtual-folders [data-virtual-folder-root]'
  : `#virtual-folders [data-virtual-folder="${folder}"]`;

async function center(page, selector) {
  const box = await (await page.$(selector)).boundingBox();
  return {x: box.x + box.width / 2, y: box.y + box.height / 2};
}

async function grabPoint(page, noteId) {
  const box = await (await page.$(`.note[data-note-id="${noteId}"] > .note-content`)).boundingBox();
  return {x: box.x + GRAB_OFFSET_PX, y: box.y + GRAB_OFFSET_PX};
}

// What the drag shows now: the highlighted folder rows and whether the column's ghost and
// drop line show.
async function dragState(page) {
  return page.evaluate(() => {
    const isShown = selector => {
      const element = document.querySelector(selector);
      return element !== null && !element.hidden;
    };
    // The top's row (`/`) has no folder path of its own.
    const folderOfRow = row => {
      if (row.hasAttribute('data-virtual-folder-root')) return '/';
      return row.dataset.virtualFolder;
    };
    return {
      highlighted: [...document.querySelectorAll('#virtual-folders .is-drop-target')].map(folderOfRow),
      ghost: isShown('.note-drag-ghost'),
      line: isShown('.note-drop-line'),
    };
  });
}

async function startDrag(page, noteId) {
  const start = await grabPoint(page, noteId);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  return start;
}

async function moveTo(page, point) {
  await page.mouse.move(point.x, point.y, {steps: DRAG_STEPS});
  await pause(SETTLE_MS);
}

async function release(page) {
  await page.mouse.up();
  await idle(page);
  await pause(SETTLE_MS);
}

async function noteTop(page, noteId) {
  return page.$eval(`.note[data-note-id="${noteId}"]`, node => node.getBoundingClientRect().top);
}

async function shownIds(page) {
  return page.$$eval('#notes-container > .note', nodes => nodes.map(node => node.dataset.noteId));
}

// The folder tags of a note the column shows.
async function folderTags(page, noteId) {
  return page.$eval(`.note[data-note-id="${noteId}"]`,
    note => note.dataset.noteTags.split(/\s+/).filter(tag => tag.endsWith('/')).sort());
}

async function count(page, folder) {
  const text = await page.$eval(`${rowSelector(folder)} .virtual-folder-count`, node => node.textContent);
  return Number.parseInt(text.replace('(', ''), 10);
}

async function messages(page) {
  return page.$$eval('#floating-messages .floating-message:not([data-leaving="true"])', cards => cards.map(card => {
    const actionButton = card.querySelector('.floating-message-action');
    return {
      text: card.querySelector('.floating-message-text').textContent,
      // null: the card offers no action.
      action: actionButton === null ? null : actionButton.textContent,
    };
  }));
}

async function chooseFolder(page, folder) {
  await page.click(`${rowSelector(folder)} .virtual-folder-name`);
  await idle(page);
  await pause(SETTLE_MS);
}

async function showEveryFolder(page) {
  await page.evaluate(async () => {
    // `/`: the search emptied, every note (folder-tags-in-search.md §2).
    const {chooseFolder} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    const {updateVirtualFolders} = await import('/static/js/modules/mode-manager/services/virtual-folders-service.js');
    await chooseFolder('', false);
    await updateVirtualFolders();
  });
  await idle(page);
}

// Two notes down, at the middle of the plain note: an ordinary reorder.
async function overTheColumn(page, ids) {
  return center(page, `.note[data-note-id="${ids.plain}"] > .note-content`);
}

// Cases 2, 3 and 6: the drag over a folder, over the note's own folder, and back over the column.
async function checkDraggingOverTheTree(page, ids) {
  const start = await startDrag(page, ids.mover);
  await moveTo(page, await overTheColumn(page, ids));
  assert.deepEqual(await dragState(page), {highlighted: [], ghost: true, line: true}, 'over the column: an ordinary note drag');
  await moveTo(page, await center(page, rowSelector(FOLDER_B)));
  assert.deepEqual(await dragState(page), {highlighted: [FOLDER_B], ghost: false, line: false},
    'case 2: over a folder, the folder highlights and the column shows no drop');
  await moveTo(page, await center(page, rowSelector(FOLDER_A)));
  assert.deepEqual(await dragState(page), {highlighted: [], ghost: false, line: false},
    'case 3: over the folder it is already in, nothing highlights');
  await moveTo(page, await overTheColumn(page, ids));
  assert.deepEqual(await dragState(page), {highlighted: [], ghost: true, line: true}, 'case 6: back over the column, a note drag again');
  // Back where it started: nothing moves.
  await moveTo(page, start);
  await release(page);
  assert.deepEqual(await folderTags(page, ids.mover), [FOLDER_A], 'a drag let go where it started changes nothing');
}

// Cases 7, 8, 10 and 11 (Undo in the message), every folder shown.
async function checkDropWithEveryFolderShown(page, ids) {
  const top = await noteTop(page, ids.mover);
  const countBefore = await count(page, FOLDER_B);
  await startDrag(page, ids.mover);
  await moveTo(page, await center(page, rowSelector(FOLDER_B)));
  await release(page);
  assert.deepEqual(await folderTags(page, ids.mover), [FOLDER_B], 'case 7: its folder tags are replaced by the target');
  assert.equal(await count(page, FOLDER_B), countBefore + 1, 'case 7: the target counts it at once');
  assert.equal(await noteTop(page, ids.mover), top, 'case 8: it stays exactly where it was');
  assert.deepEqual(await messages(page), [{text: `Moved to ${FOLDER_B}`, action: 'Undo'}], 'case 10: the message says where, with Undo');
  await page.click('#floating-messages .floating-message-action');
  await idle(page);
  await pause(SETTLE_MS);
  assert.deepEqual(await folderTags(page, ids.mover), [FOLDER_A], 'case 11: Undo in the message puts it back');
  assert.equal(await noteTop(page, ids.mover), top, 'case 11: still in its place');
  assert.deepEqual(await messages(page), [], 'case 11: the message leaves with its Undo');

  // A note in no folder goes into one.
  await startDrag(page, ids.plain);
  await moveTo(page, await center(page, rowSelector(FOLDER_A)));
  await release(page);
  assert.deepEqual(await folderTags(page, ids.plain), [FOLDER_A], 'a note in no folder goes into the target');
}

// Case 9, and case 11 with ⌘Z: with a folder chosen the moved note leaves the column.
async function checkDropLeavingTheFolderView(page, ids) {
  await chooseFolder(page, FOLDER_A);
  const tops = {above: await noteTop(page, ids.above), mover: await noteTop(page, ids.mover), below: await noteTop(page, ids.below)};
  await startDrag(page, ids.mover);
  await moveTo(page, await center(page, rowSelector(FOLDER_B)));
  await release(page);
  assert.equal((await shownIds(page)).includes(ids.mover), false, 'case 9: the note leaves the folder\'s view');
  assert.equal(await noteTop(page, ids.above), tops.above, 'case 9: the note above does not move');
  assert.equal(await noteTop(page, ids.below), tops.mover, 'case 9: the note below closes the gap');
  assert.deepEqual(await messages(page), [{text: `Moved to ${FOLDER_B}`, action: 'Undo'}], 'case 10: the message shows');
  // Doing anything else closes the message, so its Undo never undoes something else.
  await page.keyboard.press('Shift');
  await pause(SETTLE_MS);
  assert.deepEqual(await messages(page), [], 'the message closes on the next thing done');
  await page.keyboard.down(UNDO_MODIFIER);
  await page.keyboard.press('z');
  await page.keyboard.up(UNDO_MODIFIER);
  await idle(page);
  await pause(SETTLE_MS);
  assert.deepEqual(await folderTags(page, ids.mover), [FOLDER_A], 'case 11: ⌘Z puts it back');
  assert.deepEqual({above: await noteTop(page, ids.above), mover: await noteTop(page, ids.mover), below: await noteTop(page, ids.below)},
    tops, 'case 11: back in its old place, the others where they were');
  await showEveryFolder(page);
}

// Case 4: the top of the tree means no folder; case 5: a child is refused.
async function checkTopAndChild(page, ids) {
  await startDrag(page, ids.plain);
  await moveTo(page, await center(page, rowSelector(FOLDER_A)));
  assert.deepEqual((await dragState(page)).highlighted, [], 'case 3: its own folder does not highlight');
  await moveTo(page, await center(page, rowSelector('')));
  assert.deepEqual((await dragState(page)).highlighted, ['/'], 'case 4: the top highlights');
  await moveTo(page, await grabPoint(page, ids.plain));
  await release(page);

  await startDrag(page, ids.two);
  await moveTo(page, await center(page, rowSelector('')));
  await release(page);
  assert.deepEqual(await folderTags(page, ids.two), [], 'case 4: dropped on the top, a note in two folders is in none');
  assert.deepEqual(await messages(page), [{text: 'Moved out of every folder', action: 'Undo'}], 'case 10: the top\'s message');
  await page.keyboard.press('Shift');

  await startDrag(page, ids.two);
  await moveTo(page, await center(page, rowSelector('')));
  assert.deepEqual((await dragState(page)).highlighted, [], 'case 3: a note in no folder: the top does not highlight');
  await moveTo(page, await grabPoint(page, ids.two));
  await release(page);

  // No note is in Dragbeta/ any more, so it has left the tree.
  assert.equal(await page.$(rowSelector(FOLDER_B)), null, 'a folder no note is in leaves the tree');
  await startDrag(page, ids.child);
  await moveTo(page, await center(page, rowSelector(FOLDER_A)));
  assert.deepEqual(await dragState(page), {highlighted: [], ghost: false, line: false}, 'case 5: a child highlights no folder');
  await release(page);
  assert.deepEqual(await folderTags(page, ids.child), [], 'case 5: the child is unchanged');
  assert.deepEqual(await messages(page), [{text: 'Only top-level notes can go in a folder.', action: null}], 'case 5: it says why');
}

async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  await page.keyboard.type(query);
  // No Enter: it would open the first match for editing, and a note being edited can't be dragged.
  await idle(page);
  await page.evaluate(() => document.getElementById('search-input').blur());
  await pause(SETTLE_MS);
}

export async function checkFolderNoteDrag(page) {
  const ids = await createNotes(page);
  await page.setViewport(WINDOW);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  // The folders tab shows the tree (docs/ready-to-build/folders-tab-and-multiple-folders.md §1).
  await page.click('#virtual-folders-button');
  await idle(page);
  await runThenCleanUp('dragging notes into folders', async () => {
    await searchFor(page, SEARCH);
    await page.waitForSelector(rowSelector(FOLDER_B), {visible: true});
    await checkDraggingOverTheTree(page, ids);
    await checkDropWithEveryFolderShown(page, ids);
    await checkDropLeavingTheFolderView(page, ids);
    await checkTopAndChild(page, ids);
  }, async () => {
    await page.evaluate(async ({ids}) => {
      // Hides the tree again.
      if (document.body.classList.contains('virtual-folders-on')) document.getElementById('virtual-folders-button').click();
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.above, ids.mover, ids.below, ids.plain, ids.two]) await NotesAPI.deleteNote(id);
    }, {ids});
  });
}
