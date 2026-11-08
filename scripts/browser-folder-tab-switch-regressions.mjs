import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// The folder tab switches folder browsing on and off (docs/ready-to-build/virtual-folders.md, the folder tree switch;
// cases agreed with the maintainer 2026-11-07). Closing the tree turns every search context's
// folder off, opening it turns each back on; the view changes only for a context with a folder,
// as choosing a folder changes it (from the top, editing ended first); with none, nothing moves
// (docs/ui/interaction-principles.md, principles 2 and 4). Positions exact.
// Cases G and H (renames, deletes, duplicates while closed), K (two browsers) and L (new notes,
// find) are covered by tests/unit/test_tab_state.py and tests/unit/test_folder_tree_switch.py;
// I (an import showing the tree) reopens it through the same setVirtualFoldersShown as C.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
const SHOWN_KEY = 'metalist.virtual_folders.shown';
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
// Every note of the suite carries it, so its search shows only them.
const SEARCH = 'ftabswitchtest';
const FOLDER = 'Ftabswitch/';
const NOTE_COUNT = 24;
// Every third note is in the folder.
const FOLDER_EVERY = 3;
// Far enough down the column that a jump to the top would show.
const SCROLLED_Y = 600;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function createNotes(page) {
  return page.evaluate(async ({search, folder, count, every}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // createNote(null, '') inserts at the top, so create bottom-up.
    for (let index = count - 1; index >= 0; index -= 1) {
      const note = await NotesAPI.createNote(null, '');
      const lines = Array.from({length: 4}, (_, line) => `<p>Switch note ${index} line ${line}</p>`).join('');
      let tags = search;
      if (index % every === 0) tags = `${search} ${folder}`;
      await NotesAPI.saveNote(note.id, lines, tags);
      ids.unshift(note.id);
    }
    return ids;
  }, {search: SEARCH, folder: FOLDER, count: NOTE_COUNT, every: FOLDER_EVERY});
}

async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  await page.keyboard.type(query);
  await page.keyboard.press('Escape');
  await idle(page);
  await pause(SETTLE_MS);
}

async function chooseFolder(page, folder) {
  await page.evaluate(async chosen => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setVirtualFolder(chosen);
  }, folder);
  await idle(page);
  await pause(SETTLE_MS);
}

async function toggleTree(page) {
  await page.click('#virtual-folders-button');
  await idle(page);
  await pause(SETTLE_MS);
}

async function state(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const indicator = document.getElementById('virtual-folder-indicator');
    const roots = [...document.querySelectorAll('#notes-container > .note')];
    const activeLabel = document.querySelector('#search-contexts-list .tab-context-item.is-active .tab-context-query');
    return {
      treeShown: document.getElementById('virtual-folders-button').getAttribute('aria-pressed') === 'true',
      chipShown: indicator !== null && getComputedStyle(indicator).display !== 'none',
      chip: document.getElementById('virtual-folder-indicator-label').textContent,
      rootIds: roots.map(note => note.dataset.noteId),
      scrollY: Math.round(window.scrollY),
      label: activeLabel === null ? null : activeLabel.textContent,
      isEditing: mode.isEditing,
    };
  });
}

async function noteTop(page, noteId) {
  return page.$eval(`#notes-container > .note[data-note-id="${noteId}"]`, note => Math.round(note.getBoundingClientRect().top));
}

async function scrollTo(page, y) {
  await page.evaluate(top => window.scrollTo(0, top), y);
  await pause(SETTLE_MS);
}

function inFolder(ids) {
  return ids.filter((_, index) => index % FOLDER_EVERY === 0);
}

// A: closing the tree on a context with a folder shows its search alone, from the top, the
// chip gone, editing ended; the list names it by its search.
async function checkClosingAContextWithAFolder(page, ids) {
  await searchFor(page, SEARCH);
  await chooseFolder(page, FOLDER);
  const before = await state(page);
  assert.deepEqual([before.treeShown, before.chipShown, before.chip], [true, true, FOLDER], 'A: open, the folder narrows');
  assert.deepEqual(before.rootIds, inFolder(ids), 'A: open, only the folder\'s notes');
  await scrollTo(page, SCROLLED_Y);
  await page.click(`#notes-container > .note[data-note-id="${inFolder(ids)[1]}"] .note-content`);
  await pause(SETTLE_MS);
  assert.equal((await state(page)).isEditing, true, 'A: a note is being edited');
  await toggleTree(page);
  const after = await state(page);
  assert.deepEqual([after.treeShown, after.chipShown], [false, false], 'A: closed, no chip');
  assert.deepEqual(after.rootIds, ids, 'A: closed, the search alone');
  assert.equal(after.scrollY, 0, 'A: shown from the top');
  assert.equal(after.isEditing, false, 'A: editing ended first');
  assert.equal(after.label, SEARCH, 'A: the list names it by its search');
}

// B: closing the tree on a context with no folder moves nothing and keeps editing.
async function checkClosingAContextWithNoFolder(page, ids) {
  // A left the tree closed: open it on a context with no folder.
  await toggleTree(page);
  await chooseFolder(page, '');
  assert.equal((await state(page)).treeShown, true);
  await scrollTo(page, SCROLLED_Y);
  const anchor = ids[4];
  await page.click(`#notes-container > .note[data-note-id="${anchor}"] .note-content`);
  await pause(SETTLE_MS);
  const before = {...(await state(page)), top: await noteTop(page, anchor)};
  assert.equal(before.isEditing, true, 'B: a note is being edited');
  await toggleTree(page);
  const after = {...(await state(page)), top: await noteTop(page, anchor)};
  assert.equal(after.treeShown, false);
  assert.equal(after.scrollY, before.scrollY, 'B: the page does not scroll');
  assert.equal(after.top, before.top, 'B: the note stays where it was, to the pixel');
  assert.equal(after.isEditing, true, 'B: editing goes on');
  await page.keyboard.press('Escape');
  await idle(page);
}

// C: reopening on a context with a remembered folder brings it back, from the top.
// D: reopening on a context with no folder moves nothing.
async function checkReopening(page, ids) {
  // D first: this context has no folder now (B cleared it), the tree is closed.
  await scrollTo(page, SCROLLED_Y);
  const anchor = ids[5];
  const beforeD = {...(await state(page)), top: await noteTop(page, anchor)};
  await toggleTree(page);
  const afterD = {...(await state(page)), top: await noteTop(page, anchor)};
  assert.equal(afterD.treeShown, true);
  assert.equal(afterD.scrollY, beforeD.scrollY, 'D: the page does not scroll');
  assert.equal(afterD.top, beforeD.top, 'D: the note stays where it was, to the pixel');
  // C: with a folder chosen, close, scroll, reopen.
  await chooseFolder(page, FOLDER);
  await toggleTree(page);
  await scrollTo(page, SCROLLED_Y);
  await toggleTree(page);
  const afterC = await state(page);
  assert.deepEqual([afterC.treeShown, afterC.chipShown, afterC.chip], [true, true, FOLDER], 'C: the chip is back');
  assert.deepEqual(afterC.rootIds, inFolder(ids), 'C: the folder narrows again');
  assert.equal(afterC.scrollY, 0, 'C: shown from the top');
  assert.equal(afterC.label, `${SEARCH} ${FOLDER}`, 'C: the list names the folder again');
}

// F: a search typed while closed is the search alone; reopening narrows it to the folder.
async function checkASearchTypedWhileClosed(page, ids) {
  await searchFor(page, 'ftabswitchnothing');
  await toggleTree(page);
  await searchFor(page, SEARCH);
  const closed = await state(page);
  assert.deepEqual(closed.rootIds, ids, 'F: closed, the new search alone');
  assert.equal(closed.chipShown, false);
  await toggleTree(page);
  const open = await state(page);
  assert.deepEqual(open.rootIds, inFolder(ids), 'F: reopened, the new search in the folder');
  assert.equal(open.chip, FOLDER);
}

// E: another context while closed shows its search alone; each gets its own folder back.
async function checkAnotherContext(page, ids) {
  const firstTabId = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.activeTabId;
  });
  await page.evaluate(async () => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {createBlankSearchContextFromHover} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await CommandGate.run('test.new_tab', () => createBlankSearchContextFromHover());
  });
  await idle(page);
  await searchFor(page, SEARCH);
  const otherTabId = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.activeTabId;
  });
  assert.notEqual(otherTabId, firstTabId, 'E: a second context is shown');
  await toggleTree(page);
  await clickTab(page, firstTabId);
  const closed = await state(page);
  assert.deepEqual([closed.chipShown, closed.rootIds], [false, ids], 'E: closed, the first context shows its search alone');
  await toggleTree(page);
  const open = await state(page);
  assert.deepEqual([open.chip, open.rootIds], [FOLDER, inFolder(ids)], 'E: reopened, it gets its own folder back');
  await clickTab(page, otherTabId);
  const other = await state(page);
  assert.deepEqual([other.chipShown, other.rootIds], [false, ids], 'E: the other context has no folder');
  await page.evaluate(async tabId => {
    const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    await deleteTabOnServer(tabId);
  }, otherTabId);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await clickTab(page, firstTabId);
}

async function clickTab(page, tabId) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
  await page.waitForSelector(`#search-contexts-list .tab-context-item[data-tab-id="${tabId}"]`, {visible: true});
  await pause(SETTLE_MS);
  await page.click(`#search-contexts-list .tab-context-item[data-tab-id="${tabId}"] .tab-context-query`);
  await idle(page);
  await pause(SETTLE_MS);
}

// M: a reload with the tree closed keeps it closed, folders off; reopening restores them.
// J: the chip's x shows only with the tree open, and clears the folder for good.
async function checkReloadAndTheChip(page, ids) {
  await toggleTree(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await pause(SETTLE_MS);
  const reloaded = await state(page);
  assert.deepEqual([reloaded.treeShown, reloaded.chipShown, reloaded.rootIds], [false, false, ids], 'M: closed after a reload');
  await toggleTree(page);
  const reopened = await state(page);
  assert.deepEqual([reopened.chip, reopened.rootIds], [FOLDER, inFolder(ids)], 'M: reopening restores the folder');
  await page.click('#virtual-folder-indicator-clear');
  await idle(page);
  await pause(SETTLE_MS);
  await toggleTree(page);
  await toggleTree(page);
  const cleared = await state(page);
  assert.deepEqual([cleared.chipShown, cleared.rootIds], [false, ids], 'J: a folder cleared with x does not come back');
}

export async function checkFolderTabSwitch(page) {
  const ids = await createNotes(page);
  await page.setViewport(WINDOW);
  await page.evaluate(key => window.localStorage.setItem(key, 'true'), SHOWN_KEY);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('the folder tab switch', async () => {
    await checkClosingAContextWithAFolder(page, ids);
    await checkClosingAContextWithNoFolder(page, ids);
    await checkReopening(page, ids);
    await checkASearchTypedWhileClosed(page, ids);
    await checkAnotherContext(page, ids);
    await checkReloadAndTheChip(page, ids);
    console.log('PASS folder tab switch: closing turns folders off, reopening turns each back on; nothing moves without a folder');
  }, async () => {
    await page.evaluate(async ({noteIds, key}) => {
      window.localStorage.setItem(key, 'false');
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, {noteIds: ids, key: SHOWN_KEY});
  });
}
