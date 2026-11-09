import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Folder contexts (docs/ready-to-build/virtual-folders.md, "Folder contexts", cases 1-8 agreed with the maintainer
// 2026-11-07): a search context is a folder context, with the tree and its own folder, or a plain
// search, with no tree. Open folders tab goes to the folder context used last (a new one on `/`
// when there is none); close folders tab goes to the plain search used last (a new blank one when
// there is none); nothing is deleted but by -. A new view shows from the top
// (docs/ui/interaction-principles.md, principle 2); a context gone back to is as it was left.
// Positions exact. Server-only: the limit of search contexts, older saved states, a deleted folder
// (tests/unit/test_folder_context.py). Not here: an import opens a plain search (afterImport).

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
// Every note of the suite carries it, so its search shows only them.
const SEARCH = 'fctxtest';
// A tag some of them carry too, as @todo would: typed in the folder context it narrows the folder.
const TODO = 'fctxtodo';
const FOLDER_A = 'Fctxa/';
const FOLDER_B = 'Fctxb/';
const RENAMED_B = 'Fctxrenamed/';
const NOTE_COUNT = 24;
// Every third note in A, the next in B; every other note is a to-do.
const FOLDER_EVERY = 3;
const IN_B = 1;
const TODO_EVERY = 2;
// Far enough down the column that a jump to the top would show.
const SCROLLED_Y = 600;
const TOP_LABEL = '/';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function createNotes(page) {
  return page.evaluate(async ({search, todo, folderA, folderB, count, every, inB, todoEvery}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // createNote(null, '') inserts at the top, so create bottom-up.
    for (let index = count - 1; index >= 0; index -= 1) {
      const note = await NotesAPI.createNote(null, '');
      const lines = Array.from({length: 4}, (_, line) => `<p>Folder context note ${index} line ${line}</p>`).join('');
      const tags = [search];
      if (index % every === 0) tags.push(folderA);
      if (index % every === inB) tags.push(folderB);
      if (index % todoEvery === 0) tags.push(todo);
      await NotesAPI.saveNote(note.id, lines, tags.join(' '));
      ids.unshift(note.id);
    }
    return ids;
  }, {search: SEARCH, todo: TODO, folderA: FOLDER_A, folderB: FOLDER_B, count: NOTE_COUNT,
    every: FOLDER_EVERY, inB: IN_B, todoEvery: TODO_EVERY});
}

const inA = ids => ids.filter((_, index) => index % FOLDER_EVERY === 0);
const inB = ids => ids.filter((_, index) => index % FOLDER_EVERY === IN_B);
const todos = ids => ids.filter((_, index) => index % TODO_EVERY === 0);

async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  if (query === '') await page.keyboard.press('Backspace');
  else await page.keyboard.type(query);
  await page.keyboard.press('Escape');
  await idle(page);
  await pause(SETTLE_MS);
}

async function clickFolder(page, folder) {
  let row = `#virtual-folders [data-virtual-folder="${folder}"] .virtual-folder-name`;
  if (folder === '') row = '#virtual-folders [data-virtual-folder-root] .virtual-folder-name';
  await page.waitForSelector(row, {visible: true});
  await page.click(row);
  await idle(page);
  await pause(SETTLE_MS);
}

async function state(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/notes/tab-state', {headers: buildSessionHeaders(false), cache: 'no-store'});
    if (!response.ok) throw new Error(`tab-state read failed with status ${response.status}`);
    const server = await response.json();
    const indicator = document.getElementById('virtual-folder-indicator');
    const labels = {};
    const folderIcons = [];
    for (const item of document.querySelectorAll('#search-contexts-list .tab-context-item')) {
      labels[item.dataset.tabId] = item.querySelector('.tab-context-query').textContent;
      if (item.querySelector('.tab-context-folder-icon') !== null) folderIcons.push(item.dataset.tabId);
    }
    return {
      treeShown: document.getElementById('virtual-folders-button').getAttribute('aria-pressed') === 'true'
        && document.body.classList.contains('virtual-folders-on') && !document.getElementById('virtual-folders').hidden,
      chipShown: indicator.classList.contains('is-shown'),
      chip: document.getElementById('virtual-folder-indicator-label').textContent,
      rootIds: [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId),
      scrollY: Math.round(window.scrollY),
      isEditing: mode.isEditing,
      activeTabId: mode.activeTabId,
      tabOrder: [...mode.tabOrder],
      searchInput: document.getElementById('search-input').value,
      labels,
      folderContexts: server.folderContexts,
      recentTabs: server.recentTabs,
      folderIcons: folderIcons.sort(),
      serverSearches: Object.fromEntries(Object.entries(server.tabs).map(([tabId, tab]) => [tabId, tab.searchQuery])),
    };
  });
}

// The suite's notes in the view, in order (other notes of the test vault left out).
function shown(state, ids) {
  return state.rootIds.filter(id => ids.includes(id));
}

async function scrollTo(page, y) {
  await page.evaluate(top => window.scrollTo(0, top), y);
  await pause(SETTLE_MS);
}

// Every frame while an action runs: what the search box and the folder chip show together, so a
// context's search is never seen beside another context's folder (the chip waited for the
// tree's next refresh until 2026-11-07).
async function watchFrames(page) {
  await page.evaluate(() => {
    window.__folderFrames = [];
    const sample = () => {
      if (window.__folderFrames === null) return;
      window.__folderFrames.push({
        tree: document.body.classList.contains('virtual-folders-on'),
        search: document.getElementById('search-input').value,
        chip: document.getElementById('virtual-folder-indicator').classList.contains('is-shown')
          ? document.getElementById('virtual-folder-indicator-label').textContent : '',
      });
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
}

async function watchedFrames(page) {
  return page.evaluate(() => {
    const frames = window.__folderFrames;
    window.__folderFrames = null;
    return frames;
  });
}

async function showTabList(page) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
}

async function clickInList(page, selector) {
  await showTabList(page);
  await page.waitForSelector(selector, {visible: true});
  await pause(SETTLE_MS);
  await page.click(selector);
  await idle(page);
  await pause(SETTLE_MS);
}

async function clickTab(page, tabId) {
  await clickInList(page, `#search-contexts-list .tab-context-item[data-tab-id="${tabId}"] .tab-context-query`);
}

async function newContextSearching(page, query) {
  await page.evaluate(async () => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {createBlankSearchContextFromHover} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await CommandGate.run('test.new_tab', () => createBlankSearchContextFromHover());
  });
  await idle(page);
  await searchFor(page, query);
  return (await state(page)).activeTabId;
}

async function reload(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await pause(SETTLE_MS);
}



// The folders tab, open or closed.
async function clickFoldersTab(page) {
  await page.click('#virtual-folders-button');
  await idle(page);
  await pause(SETTLE_MS);
}

async function deleteFromList(page, tabId) {
  await clickInList(page, `#search-contexts-list .delete-context[data-delete-tab-id="${tabId}"]`);
}

// 1: open folders tab with no folder context: a new one at the end on `/`, with the tree and its icon.
async function checkOpeningMakesTheFirst(page, ids, todoTab) {
  await scrollTo(page, SCROLLED_Y);
  assert.equal((await state(page)).treeShown, false, '7: no tree in a plain search');
  await clickFoldersTab(page);
  const after = await state(page);
  const folderTab = after.activeTabId;
  assert.notEqual(folderTab, todoTab, '1: a folder context is shown');
  assert.deepEqual(after.folderContexts, [folderTab], '1: one folder context');
  assert.equal(after.tabOrder.at(-1), folderTab, '1: at the end of the list');
  assert.deepEqual([after.treeShown, after.searchInput, after.chipShown], [true, '', false], '1: the tree, every note');
  assert.deepEqual(shown(after, ids), ids, '1: every note');
  assert.equal(after.scrollY, 0, '1: from the top');
  assert.deepEqual([after.labels[folderTab], after.folderIcons], [TOP_LABEL, [folderTab]], '1: named /, with the folder icon');
  assert.equal(after.serverSearches[todoTab], SEARCH, '1: the plain search unchanged');
  return folderTab;
}

// 6: a folder clicked narrows the folder context, its search emptied, from the top; typing
// narrows the folder; the chosen folder again or `/` show every note; x keeps what is typed.
async function checkChoosingFolders(page, ids, folderTab) {
  await clickFolder(page, FOLDER_A);
  let after = await state(page);
  assert.deepEqual([after.activeTabId, after.chip, shown(after, ids), after.scrollY], [folderTab, FOLDER_A, inA(ids), 0], '6: the folder');
  assert.equal(after.labels[folderTab], FOLDER_A, '6: named by its folder');
  await searchFor(page, TODO);
  after = await state(page);
  assert.deepEqual([shown(after, ids), after.labels[folderTab]], [inA(todos(ids)), `${FOLDER_A} ${TODO}`], '6: typing narrows the folder');
  await scrollTo(page, SCROLLED_Y);
  await clickFolder(page, FOLDER_B);
  after = await state(page);
  assert.deepEqual([after.searchInput, after.chip, shown(after, ids), after.scrollY], ['', FOLDER_B, inB(ids), 0], '6: another folder, its search emptied');
  await clickFolder(page, FOLDER_B);
  after = await state(page);
  assert.deepEqual([after.chipShown, shown(after, ids), after.labels[folderTab]], [false, ids, TOP_LABEL], '6: chosen again: every note');
  await clickFolder(page, FOLDER_A);
  await clickFolder(page, '');
  assert.deepEqual(shown(await state(page), ids), ids, '6: / shows every note');
  await clickFolder(page, FOLDER_A);
  await searchFor(page, TODO);
  await page.click('#virtual-folder-indicator-clear');
  await idle(page);
  await pause(SETTLE_MS);
  after = await state(page);
  assert.deepEqual([after.chipShown, after.searchInput], [false, TODO], '6: x clears the folder, not the search');
  await clickFolder(page, FOLDER_A);
  await searchFor(page, TODO);
  await scrollTo(page, SCROLLED_Y);
}

// 2: close folders tab: the plain search used last, as left, with no tree; nothing deleted.
async function checkClosingGoesToThePlainSearch(page, ids, folderTab, todoTab, todoScrollY) {
  const folderScrollY = (await state(page)).scrollY;
  await watchFrames(page);
  await clickFoldersTab(page);
  const frames = await watchedFrames(page);
  const after = await state(page);
  assert.equal(after.activeTabId, todoTab, '2: the plain search used last');
  assert.deepEqual([after.treeShown, after.chipShown, after.searchInput], [false, false, SEARCH], '2: as left, with no tree');
  assert.equal(after.scrollY, todoScrollY, '2: its scroll as left');
  assert.ok(after.tabOrder.includes(folderTab), '2: the folder context stays in the list');
  assert.deepEqual(frames.filter(frame => frame.search === SEARCH && (frame.chip !== '' || frame.tree)), [], '2: the search never beside the tree or a chip');
  return folderScrollY;
}

// 1: open folders tab with a folder context: the one used last, as left; no new one.
async function checkOpeningGoesBack(page, ids, folderTab, folderScrollY) {
  const before = await state(page);
  await clickFoldersTab(page);
  const after = await state(page);
  assert.equal(after.activeTabId, folderTab, '1: the folder context used last');
  assert.deepEqual(after.tabOrder, before.tabOrder, '1: no new context');
  assert.deepEqual([after.treeShown, after.chip, after.searchInput, shown(after, ids)], [true, FOLDER_A, TODO, inA(todos(ids))], '1: as left');
  assert.equal(after.scrollY, folderScrollY, '1: its scroll as left');
}

// 4: + on a folder context makes another, same folder and search, with the tree and the icon.
// 7: each folder context keeps its own folder; a plain search has no tree.
async function checkCopiesAndTheirOwnFolders(page, ids, folderTab, todoTab) {
  await clickInList(page, `#search-contexts-list .duplicate-context[data-source-tab-id="${folderTab}"]`);
  let after = await state(page);
  const copyTab = after.activeTabId;
  assert.notEqual(copyTab, folderTab, '4: the copy shows');
  assert.deepEqual(after.folderContexts, [folderTab, copyTab].sort(), '4: another folder context');
  assert.deepEqual([after.treeShown, after.chip, after.searchInput, shown(after, ids)], [true, FOLDER_A, TODO, inA(todos(ids))], '4: same folder and search');
  assert.deepEqual(after.folderIcons, [folderTab, copyTab].sort(), '4: both with the folder icon');
  await clickFolder(page, FOLDER_B);
  await clickTab(page, folderTab);
  after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown, after.chip], [folderTab, true, FOLDER_A], '7: its own folder');
  await clickTab(page, copyTab);
  after = await state(page);
  assert.deepEqual([after.treeShown, after.chip, shown(after, ids)], [true, FOLDER_B, inB(ids)], '7: the copy\'s own folder');
  await watchFrames(page);
  await clickTab(page, todoTab);
  const frames = await watchedFrames(page);
  after = await state(page);
  assert.deepEqual([after.treeShown, after.chipShown], [false, false], '7: no tree in a plain search');
  assert.deepEqual(frames.filter(frame => frame.search === SEARCH && (frame.chip !== '' || frame.tree)), [], '7: the search never beside the tree or a chip');
  return copyTab;
}

// 3: the one used last deleted: the most recently used one of that kind still there.
async function checkTheOneUsedLastDeleted(page, ids, folderTab, copyTab, todoTab) {
  const journalTab = await newContextSearching(page, SEARCH);
  await clickTab(page, folderTab);
  await deleteFromList(page, journalTab);
  await clickFoldersTab(page);
  let after = await state(page);
  assert.equal(after.activeTabId, todoTab, '3: the plain search used last still there');
  await deleteFromList(page, folderTab);
  after = await state(page);
  assert.deepEqual(after.folderContexts, [copyTab], '5: - deletes it');
  await clickFoldersTab(page);
  after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown, after.chip], [copyTab, true, FOLDER_B], '3: the folder context used last still there');
}

// 2: close folders tab with no plain search: a new blank one at the end, with no tree.
async function checkClosingMakesAPlainSearch(page, ids, copyTab, todoTab) {
  await deleteFromList(page, todoTab);
  const before = await state(page);
  assert.deepEqual(before.tabOrder, [copyTab], 'only the folder context left');
  await clickFoldersTab(page);
  const after = await state(page);
  const plainTab = after.activeTabId;
  assert.notEqual(plainTab, copyTab, '2: a new plain search');
  assert.deepEqual(after.tabOrder, [copyTab, plainTab], '2: at the end of the list');
  assert.deepEqual([after.treeShown, after.searchInput, after.chipShown, after.folderContexts], [false, '', false, [copyTab]], '2: blank, with no tree');
  return plainTab;
}

// A reference view opened from a folder context keeps the tree in every frame; a folder clicked
// there goes back to that folder context.
async function checkAReferenceViewKeepsTheTree(page, ids, copyTab) {
  await clickFoldersTab(page);
  assert.equal((await state(page)).activeTabId, copyTab);
  await watchFrames(page);
  await page.evaluate(async noteId => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {openReferenceInNewTab} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await CommandGate.run('test.reference', () => openReferenceInNewTab(noteId));
  }, inB(ids)[1]);
  await idle(page);
  await pause(SETTLE_MS);
  const frames = await watchedFrames(page);
  let after = await state(page);
  const referenceTab = after.activeTabId;
  assert.notEqual(referenceTab, copyTab, 'a reference view shows');
  assert.equal(after.treeShown, true, 'with the tree');
  assert.deepEqual(frames.filter(frame => !frame.tree), [], 'the tree in every frame');
  await clickFolder(page, FOLDER_A);
  after = await state(page);
  assert.ok(!after.tabOrder.includes(referenceTab), 'the reference view closed');
  assert.deepEqual([after.activeTabId, after.chip, shown(after, ids)], [copyTab, FOLDER_A, inA(ids)], 'back in the folder context');
}

// 8: a reload keeps which is which and which was used last; a renamed folder renames its contexts.
async function checkReloadAndRename(page, ids, copyTab, plainTab) {
  await reload(page);
  let after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown, after.chip], [copyTab, true, FOLDER_A], '8: the folder context, with the tree');
  await clickFoldersTab(page);
  await reload(page);
  after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown], [plainTab, false], '8: the plain search, no tree');
  await clickFoldersTab(page);
  after = await state(page);
  assert.equal(after.activeTabId, copyTab, '8: the folder context used last, after a reload');
  await page.evaluate(async ({from, to}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.renameVirtualFolder(from, to);
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    await actionRefreshAndMaybeSelect({startedAt: performance.now(), context: 'test.rename'});
  }, {from: FOLDER_A, to: RENAMED_B});
  await idle(page);
  await pause(SETTLE_MS);
  after = await state(page);
  assert.deepEqual([after.chip, after.labels[copyTab]], [RENAMED_B, RENAMED_B], 'the name follows the folder');
}

export async function checkFolderContext(page) {
  const ids = await createNotes(page);
  await page.setViewport(WINDOW);
  await reload(page);
  const todoTab = (await state(page)).activeTabId;
  await runThenCleanUp('folder contexts', async () => {
    await searchFor(page, SEARCH);
    await scrollTo(page, SCROLLED_Y);
    const todoScrollY = (await state(page)).scrollY;
    const folderTab = await checkOpeningMakesTheFirst(page, ids, todoTab);
    await checkChoosingFolders(page, ids, folderTab);
    const folderScrollY = await checkClosingGoesToThePlainSearch(page, ids, folderTab, todoTab, todoScrollY);
    await checkOpeningGoesBack(page, ids, folderTab, folderScrollY);
    const copyTab = await checkCopiesAndTheirOwnFolders(page, ids, folderTab, todoTab);
    await checkTheOneUsedLastDeleted(page, ids, folderTab, copyTab, todoTab);
    const plainTab = await checkClosingMakesAPlainSearch(page, ids, copyTab, todoTab);
    await checkAReferenceViewKeepsTheTree(page, ids, copyTab);
    await checkReloadAndRename(page, ids, copyTab, plainTab);
    console.log('PASS folder contexts: open and close folders tab go to the context used last of the other kind');
  }, async () => {
    // Leave one plain search, as the suite found the vault.
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
      const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
      const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
      const response = await fetch('/api2/notes/tab-state', {headers: buildSessionHeaders(false), cache: 'no-store'});
      const server = await response.json();
      const keep = server.tabOrder.find(tabId => !server.folderContexts.includes(tabId));
      if (keep === undefined) throw new Error('No plain search left to keep');
      for (const tabId of server.tabOrder) {
        if (tabId !== keep) await deleteTabOnServer(tabId);
      }
    }, ids);
  });
}
