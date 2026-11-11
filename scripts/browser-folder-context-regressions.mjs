import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// The folders tab only shows or hides the tree (docs/ready-to-build/folders-tab-and-multiple-folders.md
// §1, agreed with the maintainer 2026-11-11): the search context shown, its search, its notes and
// its scroll stay as they are; switching contexts leaves the tree as it is, so the column never moves
// on a switch; a reload keeps it. A folder clicked is the search of the context shown, from the top
// (docs/ui/interaction-principles.md, principle 2); ⌘-click adds or takes out one folder, keeping the
// rest of the search; every folder the search names is marked (§2, §5). Positions exact.
// Server-only: older saved states with folder contexts (tests/unit/test_folders_tab.py).

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
const EMPTY_LABEL = '(empty)';
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

// ⌘-click (the tree takes Ctrl-click too, off the Mac).
async function cmdClickFolder(page, folder) {
  await page.keyboard.down('Meta');
  try {
    await clickFolder(page, folder);
  } finally {
    await page.keyboard.up('Meta');
  }
}

async function state(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/notes/tab-state', {headers: buildSessionHeaders(false), cache: 'no-store'});
    if (!response.ok) throw new Error(`tab-state read failed with status ${response.status}`);
    const server = await response.json();
    const labels = {};
    const folderIcons = [];
    for (const item of document.querySelectorAll('#search-contexts-list .tab-context-item')) {
      labels[item.dataset.tabId] = item.querySelector('.tab-context-query').textContent;
      if (item.querySelector('.tab-context-folder-icon') !== null) folderIcons.push(item.dataset.tabId);
    }
    return {
      treeShown: document.getElementById('virtual-folders-button').getAttribute('aria-pressed') === 'true'
        && document.body.classList.contains('virtual-folders-on') && !document.getElementById('virtual-folders').hidden,
      chosen: [...document.querySelectorAll('#virtual-folders .virtual-folder.is-filtered > .virtual-folder-row')]
        .map(row => ('virtualFolderRoot' in row.dataset ? '/' : row.dataset.virtualFolder)).sort(),
      columnLeft: Math.round(document.getElementById('notes-container').getBoundingClientRect().left),
      treeRight: Math.round(document.getElementById('virtual-folders').getBoundingClientRect().right),
      rootIds: [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId),
      scrollY: Math.round(window.scrollY),
      isEditing: mode.isEditing,
      activeTabId: mode.activeTabId,
      tabOrder: [...mode.tabOrder],
      searchInput: document.getElementById('search-input').value,
      labels,
      serverTreeShown: server.treeShown,
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

// Every frame while an action runs: whether the tree shows, the search box, and where the column is.
async function watchFrames(page) {
  await page.evaluate(() => {
    window.__folderFrames = [];
    const sample = () => {
      if (window.__folderFrames === null) return;
      window.__folderFrames.push({
        tree: document.body.classList.contains('virtual-folders-on'),
        search: document.getElementById('search-input').value,
        columnLeft: Math.round(document.getElementById('notes-container').getBoundingClientRect().left),
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



async function deleteFromList(page, tabId) {
  await clickInList(page, `#search-contexts-list .delete-context[data-delete-tab-id="${tabId}"]`);
}

// The folders tab, open or closed.
async function clickFoldersTab(page) {
  await page.click('#virtual-folders-button');
  await idle(page);
  await pause(SETTLE_MS);
}

// §1: the folders tab shows the tree and changes nothing else; again, it hides it.
async function checkTheTabOnlyShowsTheTree(page, ids, todoTab) {
  const before = await state(page);
  assert.deepEqual([before.treeShown, before.serverTreeShown], [false, false], 'the tree hidden at first');
  await watchFrames(page);
  await clickFoldersTab(page);
  let frames = await watchedFrames(page);
  let after = await state(page);
  assert.deepEqual([after.treeShown, after.serverTreeShown], [true, true], 'tab 1: the tree shown');
  assert.deepEqual([after.activeTabId, after.tabOrder, after.searchInput, after.rootIds, after.scrollY],
    [todoTab, before.tabOrder, SEARCH, before.rootIds, before.scrollY], 'tab 1: same context, search, notes and scroll');
  assert.ok(after.columnLeft >= after.treeRight, 'tab 1: the column clear of the tree');
  assert.deepEqual(frames.filter(frame => frame.search !== SEARCH), [], 'tab 1: the search never changes');
  await watchFrames(page);
  await clickFoldersTab(page);
  frames = await watchedFrames(page);
  after = await state(page);
  assert.deepEqual([after.treeShown, after.serverTreeShown, after.activeTabId, after.searchInput, after.rootIds, after.scrollY, after.columnLeft],
    [false, false, todoTab, SEARCH, before.rootIds, before.scrollY, before.columnLeft], 'tab 2: hidden again, nothing else changed');
  assert.deepEqual(frames.filter(frame => frame.search !== SEARCH), [], 'tab 2: the search never changes');
  await clickFoldersTab(page);
}

// §1: switching search contexts leaves the tree shown, the column where it is in every frame.
async function checkSwitchingKeepsTheTree(page, ids, todoTab) {
  const shownLeft = (await state(page)).columnLeft;
  await watchFrames(page);
  const otherTab = await newContextSearching(page, FOLDER_B);
  let after = await state(page);
  assert.deepEqual([after.treeShown, after.chosen, shown(after, ids)], [true, [FOLDER_B], inB(ids)], 'tab 3: a new context, the tree still shown');
  await clickTab(page, todoTab);
  const frames = await watchedFrames(page);
  after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown, after.chosen, after.columnLeft], [todoTab, true, ['/'], shownLeft], 'tab 3: back, the tree shown');
  assert.deepEqual(frames.filter(frame => !frame.tree || frame.columnLeft !== shownLeft), [], 'tab 3: the tree and the column still in every frame');
  assert.deepEqual([after.folderIcons, after.labels[otherTab]], [[otherTab], FOLDER_B], 'a context searching a folder has the folder icon');
  return otherTab;
}

// §2: a click makes the folder the search, from the top; the only chosen folder again, or `/`, empties it.
async function checkClickingFolders(page, ids, todoTab) {
  await scrollTo(page, SCROLLED_Y);
  await clickFolder(page, FOLDER_A);
  let after = await state(page);
  assert.deepEqual([after.activeTabId, after.searchInput, after.chosen, shown(after, ids), after.scrollY],
    [todoTab, FOLDER_A, [FOLDER_A], inA(ids), 0], 'click 1: the folder is the search, from the top');
  assert.equal(after.labels[todoTab], FOLDER_A, 'click 1: named by its search');
  await searchFor(page, `${FOLDER_A} ${TODO}`);
  after = await state(page);
  assert.deepEqual([shown(after, ids), after.chosen], [inA(todos(ids)), [FOLDER_A]], 'typing narrows the folder');
  await clickFolder(page, FOLDER_A);
  after = await state(page);
  assert.deepEqual([after.searchInput, after.chosen, shown(after, ids), after.labels[todoTab]], ['', ['/'], ids, EMPTY_LABEL], 'click 2: the only chosen folder again empties the search');
  await clickFolder(page, FOLDER_B);
  await clickFolder(page, '');
  after = await state(page);
  assert.deepEqual([after.searchInput, after.chosen], ['', ['/']], 'click 2: / empties the search');
}

// §2, §3, §5: ⌘-click adds a folder or takes it out, keeping the rest; several folders add results;
// ⌘-click on `/` takes every folder out; an OR search marks every folder it names.
async function checkCmdClickingFolders(page, ids) {
  await searchFor(page, `${FOLDER_A} ${TODO}`);
  await scrollTo(page, SCROLLED_Y);
  await cmdClickFolder(page, FOLDER_B);
  let after = await state(page);
  const inEither = ids.filter(id => inA(ids).includes(id) || inB(ids).includes(id));
  assert.deepEqual([after.searchInput, after.chosen, shown(after, ids), after.scrollY],
    [`${FOLDER_A} ${FOLDER_B} ${TODO}`, [FOLDER_A, FOLDER_B], inEither.filter(id => todos(ids).includes(id)), 0], 'click 3: ⌘-click adds a folder');
  await cmdClickFolder(page, FOLDER_B);
  after = await state(page);
  assert.deepEqual([after.searchInput, after.chosen], [`${FOLDER_A} ${TODO}`, [FOLDER_A]], 'click 4: ⌘-click again takes it out');
  await cmdClickFolder(page, '');
  after = await state(page);
  assert.deepEqual([after.searchInput, after.chosen, shown(after, ids)], [TODO, ['/'], todos(ids)], 'click 5: ⌘-click on / keeps the rest');
  await searchFor(page, `${FOLDER_A} OR ${FOLDER_B} ${TODO}`);
  after = await state(page);
  assert.deepEqual([after.chosen, shown(after, ids)], [[FOLDER_A, FOLDER_B], ids.filter(id => inA(ids).includes(id) || (inB(ids).includes(id) && todos(ids).includes(id)))], 'click 6: OR marks both');
  await searchFor(page, SEARCH);
}

// A reference view keeps the tree in every frame; a folder clicked there goes back to the context
// it was opened from, its search that folder.
async function checkAReferenceViewKeepsTheTree(page, ids, todoTab) {
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
  assert.notEqual(referenceTab, todoTab, 'a reference view shows');
  assert.equal(after.treeShown, true, 'with the tree');
  assert.deepEqual(frames.filter(frame => !frame.tree), [], 'the tree in every frame');
  await clickFolder(page, FOLDER_A);
  after = await state(page);
  assert.ok(!after.tabOrder.includes(referenceTab), 'the reference view closed');
  assert.deepEqual([after.activeTabId, after.searchInput, shown(after, ids)], [todoTab, FOLDER_A, inA(ids)], 'back in its context, the folder its search');
}

// §1: a reload keeps the tree shown or hidden; a renamed folder renames the searches naming it.
async function checkReloadAndRename(page, todoTab) {
  await reload(page);
  let after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown, after.chosen], [todoTab, true, [FOLDER_A]], 'tab 4: a reload keeps the tree shown');
  await clickFoldersTab(page);
  await reload(page);
  after = await state(page);
  assert.deepEqual([after.activeTabId, after.treeShown], [todoTab, false], 'tab 4: a reload keeps it hidden');
  await clickFoldersTab(page);
  // Rename Folder… in the tree's menu, its new name typed.
  await page.click(`#virtual-folders [data-virtual-folder="${FOLDER_A}"]`, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible', {visible: true});
  const item = await page.evaluateHandle(() => [...document.querySelectorAll('#context-menu.is-visible .context-menu-item')]
    .find(node => node.querySelector('.context-menu-item-label').textContent.trim() === 'Rename Folder…'));
  await item.click();
  await page.waitForSelector('#folder-name-input', {visible: true});
  await clickAndSelectAll(page, '#folder-name-input');
  await page.keyboard.type(RENAMED_B.slice(0, -1));
  await page.keyboard.press('Enter');
  await idle(page);
  await pause(SETTLE_MS);
  after = await state(page);
  assert.deepEqual([after.searchInput, after.labels[todoTab], after.chosen], [RENAMED_B, RENAMED_B, [RENAMED_B]], 'the search follows the folder');
}

export async function checkFolderContext(page) {
  const ids = await createNotes(page);
  await page.setViewport(WINDOW);
  await reload(page);
  const todoTab = (await state(page)).activeTabId;
  await runThenCleanUp('folders tab', async () => {
    await searchFor(page, SEARCH);
    await scrollTo(page, SCROLLED_Y);
    await checkTheTabOnlyShowsTheTree(page, ids, todoTab);
    await checkSwitchingKeepsTheTree(page, ids, todoTab);
    await checkClickingFolders(page, ids, todoTab);
    await checkCmdClickingFolders(page, ids);
    await checkAReferenceViewKeepsTheTree(page, ids, todoTab);
    await checkReloadAndRename(page, todoTab);
    console.log('PASS folders tab: it only shows or hides the tree; folders clicked and ⌘-clicked are the search');
  }, async () => {
    // Leave one search context and the tree hidden, as the suite found the vault; contexts go with
    // their −, as a person deletes them (deleted behind the page's back, its next save is refused).
    for (const tabId of (await state(page)).tabOrder) {
      if (tabId !== todoTab) await deleteFromList(page, tabId);
    }
    if ((await state(page)).treeShown) await clickFoldersTab(page);
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
