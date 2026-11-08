import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import {clickAndSelectAll} from './browser-select-field.mjs';

// Switching tabs: after each switch, the notes shown, the search box and the
// server's active tab all belong to the tab that was picked.

const SETTLE_MS = 400;
// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
// Each tab is switched to and from this many times.
const ROUND_TRIPS = 4;
const TAB_QUERIES = ['scratchpad', 'todo'];
// A quoted text search that looks like markup, short enough to show in full in the tab list.
const MARKUP_QUERY = '"<b>x</b>"';
// A folder (a tag ending in /) one of the notes is filed in.
const FOLDER = 'Tabswitchfolder/';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function createNotes(page) {
  return page.evaluate(async (queries, folder) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (const tag of queries) {
      for (const index of [1, 2]) {
        const note = await NotesAPI.createNote(null, '');
        await NotesAPI.saveNote(note.id, `<p>Tab switch ${tag} note ${index}</p>`, tag);
        ids.push(note.id);
      }
    }
    const filed = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(filed.id, '<p>Tab switch filed note</p>', folder);
    ids.push(filed.id);
    // Untagged, so the Untagged view shows a note.
    const untagged = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(untagged.id, '<p>Tab switch untagged note</p>', '');
    ids.push(untagged.id);
    return ids;
  }, TAB_QUERIES, FOLDER);
}

async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  await page.keyboard.type(query);
  await page.keyboard.press('Enter');
  await idle(page);
  await pause(SETTLE_MS);
}

async function viewState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/notes/tab-state', {headers: buildSessionHeaders(false), cache: 'no-store'});
    if (!response.ok) throw new Error(`tab-state read failed with status ${response.status}`);
    const server = await response.json();
    const shown = [...document.querySelectorAll('#notes-container .note > .note-content')]
      .filter(node => node.getClientRects().length > 0)
      .map(node => node.textContent.trim())
      .filter(text => text.startsWith('Tab switch ') && text !== 'Tab switch filed note');
    return {
      activeTabId: mode.activeTabId,
      serverActiveTabId: server.activeTabId,
      sortMode: mode.activeTabSortMode,
      serverSortMode: server.tabs[mode.activeTabId].sortMode,
      hasDateRange: (await import('/static/js/modules/mode-manager/services/date-range-filter-service.js')).getActiveDateFilter() !== null,
      serverHasDateRange: Object.hasOwn(server.dateFilters, mode.activeTabId),
      fileFilter: (await import('/static/js/modules/mode-manager/services/file-filter-service.js')).getActiveFileFilterKind(),
      isUntagged: mode.isUntaggedView,
      serverIsUntagged: server.untaggedViews.includes(mode.activeTabId),
      untaggedChipShown: document.getElementById('untagged-view-indicator').classList.contains('is-shown'),
      searchQuery: mode.searchQuery,
      searchInput: document.getElementById('search-input').value,
      shown,
    };
  });
}

async function showTabList(page) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
}

async function setUntagged(page, isUntagged) {
  await page.evaluate(async isUntagged => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setIsUntaggedView(isUntagged);
  }, isUntagged);
  await idle(page);
}

async function reload(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// The Untagged view belongs to its search context, as its sort order and date range do
// (the maintainer, 2026-11-02, docs/ui/state-handling.md): one check per agreed case.
async function checkUntaggedViewStaysWithItsTab(page, firstTabId, secondTabId, untaggedNoteId) {
  const untagged = state => [state.isUntagged, state.serverIsUntagged, state.untaggedChipShown];
  const ON = [true, true, true];
  const OFF = [false, false, false];
  await clickTab(page, firstTabId);
  await setUntagged(page, true);
  let state = await viewState(page);
  assert.deepEqual(untagged(state), ON, 'the first tab shows its untagged notes');
  assert.deepEqual(state.shown, ['Tab switch untagged note'], 'the Untagged view shows the untagged note');

  await clickTab(page, secondTabId);
  assert.deepEqual(untagged(await viewState(page)), OFF, 'the second tab shows its own search');
  await clickTab(page, firstTabId);
  state = await viewState(page);
  assert.deepEqual(untagged(state), ON, 'case 1: back on the first tab, its Untagged view is kept');
  assert.deepEqual(state.shown, ['Tab switch untagged note'], 'case 1: and shows the untagged note');

  await clickTab(page, firstTabId);
  assert.deepEqual(untagged(await viewState(page)), ON, 'case 4: clicking the tab already shown keeps it');

  await reload(page);
  state = await viewState(page);
  assert.deepEqual([state.activeTabId, ...untagged(state)], [firstTabId, ...ON], 'case 3: a reload keeps it');
  assert.deepEqual(state.shown, ['Tab switch untagged note'], 'case 3: and shows the untagged note');

  // Case 6: following a reference opens a new view, which starts with nothing; coming back
  // finds the tab as it was.
  await page.evaluate(async noteId => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {openReferenceInNewTab} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await CommandGate.run('test.reference', () => openReferenceInNewTab(noteId));
  }, untaggedNoteId);
  await idle(page);
  await pause(SETTLE_MS);
  state = await viewState(page);
  assert.notEqual(state.activeTabId, firstTabId, 'case 6: the reference opens in its own view');
  assert.deepEqual(untagged(state), OFF, 'case 6: the reference view starts without the Untagged view');
  await page.click('#reference-source-indicator-clear');
  await idle(page);
  await pause(SETTLE_MS);
  state = await viewState(page);
  assert.deepEqual([state.activeTabId, ...untagged(state)], [firstTabId, ...ON], 'case 6: coming back keeps it');

  // Case 7: Reset Current View Filters ends it.
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.resetViewFilters();
  });
  await idle(page);
  assert.deepEqual(untagged(await viewState(page)), OFF, 'case 7: Reset Current View Filters ends it');
  await searchFor(page, TAB_QUERIES[0]);

  // Case 2: View → All Notes and the chip's × end it.
  await setUntagged(page, true);
  await setUntagged(page, false);
  assert.deepEqual(untagged(await viewState(page)), OFF, 'case 2: All Notes ends it');
  await setUntagged(page, true);
  await page.click('#untagged-view-indicator-clear');
  await idle(page);
  assert.deepEqual(untagged(await viewState(page)), OFF, 'case 2: its × ends it');
}

// Case 5: + duplicates everything the tab shows; a new tab starts with nothing.
async function checkDuplicateCopiesEverything(page, firstTabId) {
  await clickTab(page, firstTabId);
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setSortMode('created');
    await CommandPalette.setDateRangePreset('last-30-days');
    await CommandPalette.setFileFilter('any');
    // Only a folder context has a folder (docs/ready-to-build/virtual-folders.md, "Folder contexts"): its
    // duplicate is checked in browser-folder-context-regressions.mjs.
    await CommandPalette.setIsUntaggedView(true);
  });
  await idle(page);
  const everything = async () => {
    const state = await viewState(page);
    const folder = await page.evaluate(async () => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      return (await NotesAPI.listVirtualFolders()).folder;
    });
    return {
      search: state.searchQuery, sort: [state.sortMode, state.serverSortMode],
      dateRange: [state.hasDateRange, state.serverHasDateRange], fileFilter: state.fileFilter, folder,
      untagged: [state.isUntagged, state.serverIsUntagged],
    };
  };
  const narrowed = {
    search: TAB_QUERIES[0], sort: ['created', 'created'], dateRange: [true, true], fileFilter: 'any', folder: '',
    untagged: [true, true],
  };
  assert.deepEqual(await everything(), narrowed, 'the first tab is narrowed every way');

  await showTabList(page);
  const plus = `#search-contexts-list .tab-context-item[data-tab-id="${firstTabId}"] .duplicate-context`;
  await page.waitForSelector(plus, {visible: true});
  await pause(SETTLE_MS);
  await page.click(plus);
  await idle(page);
  await pause(SETTLE_MS);
  const duplicateTabId = (await viewState(page)).activeTabId;
  assert.notEqual(duplicateTabId, firstTabId, 'the duplicate is shown');
  assert.deepEqual(await everything(), narrowed, 'the duplicate copies everything');

  await page.evaluate(async () => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {createBlankSearchContextFromHover} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await CommandGate.run('test.new_tab', () => createBlankSearchContextFromHover());
  });
  await idle(page);
  const blankTabId = (await viewState(page)).activeTabId;
  assert.deepEqual(await everything(), {
    search: '', sort: ['normal', 'normal'], dateRange: [false, false], fileFilter: 'none', folder: '', untagged: [false, false],
  }, 'a new tab starts with nothing');

  for (const tabId of [blankTabId, duplicateTabId]) {
    await page.evaluate(async tabId => {
      const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
      await deleteTabOnServer(tabId);
    }, tabId);
  }
  await reload(page);
  await clickTab(page, firstTabId);
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    await CommandPalette.setIsUntaggedView(false);
    await NotesAPI.setVirtualFolderFilter(mode.activeTabId, '');
    await CommandPalette.setFileFilter('none');
    await CommandPalette.setDateRangePreset('none');
    await CommandPalette.setSortMode('normal');
  });
  await idle(page);
}

// Enter with the pointer over the open list of search contexts makes a new, blank one and shows
// it (4aeb5e26; the maintainer, 2026-11-08: "that used to be the case"), the list staying open.
async function checkEnterOverTheListMakesANewContext(page, rowSelector) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
  await page.waitForSelector(rowSelector, {visible: true});
  await pause(SETTLE_MS);
  const row = await (await page.$(rowSelector)).boundingBox();
  await page.mouse.move(row.x + row.width / 2, row.y + row.height / 2);
  await pause(SETTLE_MS);
  const before = await viewState(page);
  const orderBefore = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return [...mode.tabOrder];
  });
  await page.keyboard.press('Enter');
  await idle(page);
  await pause(SETTLE_MS);
  const after = await viewState(page);
  const orderAfter = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return [...mode.tabOrder];
  });
  assert.equal(orderAfter.length, orderBefore.length + 1, 'Enter over the list makes a new search context');
  assert.notEqual(after.activeTabId, before.activeTabId, 'and shows it');
  assert.equal(after.activeTabId, orderAfter.at(-1), 'the new one, at the end of the list');
  assert.deepEqual([after.searchQuery, after.searchInput], ['', ''], 'blank');
  const isListShown = await page.$eval('#search-contexts-list', list => getComputedStyle(list).display !== 'none');
  assert.equal(isListShown, true, 'the list stays open');
  await page.evaluate(async tabId => {
    const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    await deleteTabOnServer(tabId);
  }, after.activeTabId);
  await reload(page);
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

function expectTab(state, tabId, query, label) {
  assert.equal(state.activeTabId, tabId, `${label}: the picked tab is active`);
  assert.equal(state.serverActiveTabId, tabId, `${label}: the server has the picked tab active`);
  assert.equal(state.searchQuery, query, `${label}: the tab's search is active`);
  assert.equal(state.searchInput, query, `${label}: the search box shows the tab's search`);
  assert.deepEqual(state.shown.toSorted(), [`Tab switch ${query} note 1`, `Tab switch ${query} note 2`],
    `${label}: only the tab's notes are shown`);
}

export async function checkTabSwitching(page) {
  const ids = await createNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('tab switching', async () => {
    const firstTabId = (await viewState(page)).activeTabId;
    await searchFor(page, TAB_QUERIES[0]);
    expectTab(await viewState(page), firstTabId, TAB_QUERIES[0], 'first tab searched');
    await page.evaluate(async () => {
      const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
      const {createBlankSearchContextFromHover} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
      await CommandGate.run('test.new_tab', () => createBlankSearchContextFromHover());
    });
    await idle(page);
    const secondTabId = (await viewState(page)).activeTabId;
    assert.notEqual(secondTabId, firstTabId, 'a new tab is active');
    await searchFor(page, TAB_QUERIES[1]);
    expectTab(await viewState(page), secondTabId, TAB_QUERIES[1], 'second tab searched');
    for (let round = 1; round <= ROUND_TRIPS; round += 1) {
      await clickTab(page, firstTabId);
      expectTab(await viewState(page), firstTabId, TAB_QUERIES[0], `round ${round}, back to the first tab`);
      await clickTab(page, secondTabId);
      expectTab(await viewState(page), secondTabId, TAB_QUERIES[1], `round ${round}, back to the second tab`);
    }
    // What a tab shows and its order stay the tab's until each is ended with its × (the
    // maintainer, 2026-11-02, docs/ui/state-handling.md: sorted by Created, a journal tab came
    // back in its normal order after another tab was visited; a new search ended them too).
    await clickTab(page, firstTabId);
    await page.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.setSortMode('created');
      await CommandPalette.setDateRangePreset('last-30-days');
    });
    await idle(page);
    const kept = state => [state.sortMode, state.serverSortMode, state.hasDateRange, state.serverHasDateRange];
    const KEPT = ['created', 'created', true, true];
    assert.deepEqual(kept(await viewState(page)), KEPT, 'the first tab is sorted by Created over the last 30 days');
    await clickTab(page, secondTabId);
    assert.deepEqual(kept(await viewState(page)), ['normal', 'normal', false, false], 'the second tab keeps its own');
    await clickTab(page, firstTabId);
    assert.deepEqual(kept(await viewState(page)), KEPT, 'back on the first tab, its sort and date range are kept');
    await searchFor(page, `${TAB_QUERIES[0]} note`);
    assert.deepEqual(kept(await viewState(page)), KEPT, 'a new search in the tab keeps them');
    await searchFor(page, TAB_QUERIES[0]);
    await page.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.setSortMode('normal');
      await CommandPalette.setDateRangePreset('none');
    });
    await idle(page);
    await clickTab(page, secondTabId);
    await checkUntaggedViewStaysWithItsTab(page, firstTabId, secondTabId, ids.at(-1));
    await checkDuplicateCopiesEverything(page, firstTabId);
    await clickTab(page, secondTabId);
    // A search's text is shown in the tab list as text, never as markup.
    await searchFor(page, MARKUP_QUERY);
    const zone = await (await page.$('#tab-hover-zone')).boundingBox();
    await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
    const label = `#search-contexts-list .tab-context-item[data-tab-id="${secondTabId}"] .tab-context-query`;
    await page.waitForSelector(label, {visible: true});
    assert.deepEqual(await page.$eval(label, node => ({text: node.textContent, elements: node.childElementCount})),
      {text: MARKUP_QUERY, elements: 0}, 'the tab list shows the search text as text');
    await checkEnterOverTheListMakesANewContext(page, label);
    // The same with the cursor in the search box,
    await page.click('#search-input');
    await pause(SETTLE_MS);
    await checkEnterOverTheListMakesANewContext(page, label);
    // with search suggestions open under it (the maintainer's case, 2026-11-08: Enter did nothing),
    await clickAndSelectAll(page, '#search-input');
    await page.keyboard.type(TAB_QUERIES[0].slice(0, 3));
    await idle(page);
    await pause(SETTLE_MS);
    assert.equal(await page.$eval('#search-suggestions', list => !list.hidden), true, 'search suggestions are open');
    await checkEnterOverTheListMakesANewContext(page, label);
    // in a folder context,
    await page.setViewport({width: 1440, height: 900});
    await page.click('#virtual-folders-button');
    await idle(page);
    await pause(SETTLE_MS);
    await checkEnterOverTheListMakesANewContext(page, label);
    // and just after a folder was clicked in its tree.
    await page.setViewport({width: 1440, height: 900});
    if (!(await page.evaluate(() => document.body.classList.contains('virtual-folders-on')))) {
      await page.click('#virtual-folders-button');
      await idle(page);
    }
    await page.click(`#virtual-folders [data-virtual-folder="${FOLDER}"] .virtual-folder-name`);
    await idle(page);
    await pause(SETTLE_MS);
    const folderTabRow = await page.evaluate(async () => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      return mode.activeTabId;
    });
    await checkEnterOverTheListMakesANewContext(page, `#search-contexts-list .tab-context-item[data-tab-id="${folderTabRow}"] .tab-context-query`);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
