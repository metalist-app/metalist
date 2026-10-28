import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Sorted tabs: which new root notes may be added, the order staying frozen
// while a note is edited, and the surrounding notes staying on screen when the
// edited note moves to its sorted place on leaving edit mode.
//
// The fixture has more roots than the band of loaded roots (75 each side of
// the viewport), so a note that sorts to the far end is outside the band.

const ROOT_COUNT = 200;
const SETTLE_MS = 1500;
const TOLERANCE_PX = 2;
// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
const BLOCKED_MESSAGE = 'sort order';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function createFixture(page) {
  return page.evaluate(async count => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // Distinct sizes (content volume), names (alphabetical) and creation times.
    for (let index = 0; index < count; index += 1) {
      const note = await NotesAPI.createNote(null, '');
      const label = String(index).padStart(3, '0');
      await NotesAPI.saveNote(note.id, `<p>Sorted root ${label}: ${'x'.repeat(600 - index)}</p>`, '');
      ids.push(note.id);
    }
    return ids;
  }, ROOT_COUNT);
}

async function deleteNotes(page, ids) {
  await page.evaluate(async ids => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of ids) await NotesAPI.deleteNote(id);
  }, ids);
}

async function reload(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function runPaletteCommand(page, query) {
  await page.keyboard.down('Meta');
  await page.keyboard.press('/');
  await page.keyboard.up('Meta');
  await pause(400);
  await page.keyboard.type(query);
  await pause(300);
  await page.keyboard.press('Enter');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(300);
}

function modeState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {isEditing: mode.isEditing, currentNoteId: mode.currentNoteId, isLoading: mode.isLoading,
      rootCountTotal: mode.rootCountTotal};
  });
}

async function waitIdle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function waitForEditing(page, noteId) {
  await page.waitForFunction(async noteId => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.isEditing && mode.currentNoteId === noteId && !mode.isLoading;
  }, {}, noteId);
  await pause(400);
}

function rootOrder(page) {
  return page.evaluate(() => [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId));
}

function bannerText(page) {
  return page.evaluate(() => {
    const message = document.querySelector('#floating-messages .floating-message:last-child .floating-message-text');
    return message ? message.textContent : '';
  });
}

function fatalText(page) {
  return page.evaluate(() => {
    const overlay = document.getElementById('fatal-error-overlay');
    return overlay ? overlay.textContent : '';
  });
}

function noteTop(page, noteId) {
  return page.evaluate(noteId => document.querySelector(`[data-note-id="${noteId}"]`).getBoundingClientRect().top, noteId);
}

// Hover the root at about a third down the screen (Enter outside edit mode acts there).
async function hoverRoot(page, noteId) {
  await page.evaluate(noteId => document.querySelector(`[data-note-id="${noteId}"]`).scrollIntoView({block: 'center'}), noteId);
  await pause(250);
  const point = await page.evaluate(noteId => {
    const rect = document.querySelector(`[data-note-id="${noteId}"] .note-content`).getBoundingClientRect();
    return {x: rect.left + 30, y: rect.top + Math.min(10, rect.height / 2)};
  }, noteId);
  await page.mouse.move(point.x, point.y);
  return point;
}

async function editRoot(page, noteId) {
  const point = await hoverRoot(page, noteId);
  await page.mouse.click(point.x, point.y);
  await waitForEditing(page, noteId);
}

// After a blocked action: nothing was created, a banner explains why, and
// scrolling afterwards still loads more roots without a fatal error.
async function assertBlocked(page, label, rootCountBefore) {
  await waitIdle(page);
  const banner = await bannerText(page);
  assert.ok(banner.toLowerCase().includes(BLOCKED_MESSAGE), `${label}: a banner should explain the block, got "${banner}"`);
  const {rootCountTotal} = await modeState(page);
  assert.equal(rootCountTotal, rootCountBefore, `${label}: no root note should be created`);
}

async function scrollThroughBand(page) {
  for (let step = 0; step < 6; step += 1) {
    await page.evaluate(() => window.scrollBy(0, window.innerHeight));
    await pause(700);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await pause(1500);
  await waitIdle(page);
  assert.equal(await fatalText(page), '', 'scrolling the sorted tab must not hit a fatal error');
}

async function newNoteAtTopBlockedCase(page, ids, sortCommand, label) {
  await runPaletteCommand(page, sortCommand);
  const {rootCountTotal} = await modeState(page);
  await hoverRoot(page, (await rootOrder(page))[2]);
  await page.keyboard.press('Enter');
  await waitIdle(page);
  const banner = await bannerText(page);
  const state = await modeState(page);
  if (state.isEditing) {
    // Not blocked: scroll while editing the new note (how the crash was hit).
    await page.evaluate(() => window.scrollTo(0, 0));
    await pause(3000);
    assert.equal(await fatalText(page), '', `${label}: a new note sorted outside the loaded band must not hit a fatal error`);
  }
  await scrollThroughBand(page);
  assert.ok(banner.toLowerCase().includes(BLOCKED_MESSAGE), `${label}: a banner should explain the block, got "${banner}"`);
  assert.equal(state.rootCountTotal, rootCountTotal, `${label}: no root note should be created`);
}

async function newNoteBelowBlockedCase(page, ids, sortCommand, label) {
  await runPaletteCommand(page, sortCommand);
  const {rootCountTotal} = await modeState(page);
  const target = (await rootOrder(page))[2];
  await editRoot(page, target);
  await page.keyboard.down('Meta');
  await page.keyboard.press('Enter');
  await page.keyboard.up('Meta');
  await assertBlocked(page, `${label}, new note below a root`, rootCountTotal);
  const state = await modeState(page);
  assert.ok(state.isEditing && state.currentNoteId === target, `${label}: still editing the same note after the block`);
  await page.keyboard.press('Escape');
  await waitIdle(page);
}

async function newNoteAtTopAllowedCase(page, sortCommand, label, created) {
  await runPaletteCommand(page, sortCommand);
  const {rootCountTotal} = await modeState(page);
  await hoverRoot(page, (await rootOrder(page))[2]);
  await page.keyboard.press('Enter');
  await waitIdle(page);
  const state = await modeState(page);
  assert.equal(state.rootCountTotal, rootCountTotal + 1, `${label}: Enter adds a note`);
  assert.ok(state.isEditing, `${label}: the new note is being edited`);
  assert.equal((await rootOrder(page))[0], state.currentNoteId, `${label}: the new note is at the top`);
  created.push(state.currentNoteId);
  await page.keyboard.press('Escape');
  await waitIdle(page);
  assert.equal(await fatalText(page), '', `${label}: no fatal error`);
}

// A view request already on its way when the user picks a sort order (the
// infinite-scroll poll moving the band, a link-title refresh) is answered in the
// old order. The new order's own refresh must still run after it: dropping it
// left the list and the sort chip in the old order although the tab was sorted.
// The page holds the sort-mode POST before it is sent and the stray view's
// answer after the server sent it, so the requests land in that order every time.
async function sortWhileViewInFlightCase(page, ids) {
  await waitIdle(page);
  assert.equal((await rootOrder(page))[0], ids[ids.length - 1], 'normal order: the newest root is first');
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    const pageFetch = window.fetch;
    const release = {};
    const held = {};
    const gate = name => {
      held[name] = new Promise(resolve => { release[name] = resolve; });
      return held[name];
    };
    const sortRequestHeld = gate('sortRequest');
    const viewAnswerHeld = gate('viewAnswer');
    let sortRequestSeen = false;
    let viewAnswerSeen = false;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.endsWith('/tab-state/sort-mode') && !sortRequestSeen) {
        sortRequestSeen = true;
        await sortRequestHeld;
        return pageFetch(input, init);
      }
      if (url.endsWith('/notes/view') && sortRequestSeen && !viewAnswerSeen) {
        viewAnswerSeen = true;
        const answer = await pageFetch(input, init);
        await viewAnswerHeld;
        return answer;
      }
      return pageFetch(input, init);
    };
    const until = async isDone => {
      while (!isDone()) await new Promise(resolve => setTimeout(resolve, 10));
    };
    try {
      const sorting = CommandPalette.setSortMode('alphabetical');
      await until(() => sortRequestSeen);
      const strayView = actionRefreshAndMaybeSelect({context: 'stray view request', animateNoteChanges: false});
      await until(() => viewAnswerSeen);
      release.sortRequest();
      // hydrateTabState and the sort's refresh call run in one task, so once the
      // mode is hydrated the refresh has been dropped or is waiting its turn.
      await until(() => mode.activeTabSortMode === 'alphabetical');
      // While it waits, the infinite-scroll poll records the roots on screen, still in
      // the old order (infinite-scroll-service.js, handlePoll). Under load it ticked here
      // and the sorted list opened at those roots, partway down (2026-10-27): record
      // them as it would.
      const onScreen = [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId);
      mode.setVisibleRootRange(onScreen[0], onScreen[Math.min(onScreen.length - 1, 5)]);
      release.viewAnswer();
      await Promise.all([sorting, strayView]);
    } finally {
      window.fetch = pageFetch;
    }
  });
  await waitIdle(page);
  const chip = await page.evaluate(() => ({
    shown: document.getElementById('root-sort-indicator').classList.contains('is-shown'),
    label: document.getElementById('root-sort-indicator-label').textContent,
  }));
  assert.deepEqual(chip, {shown: true, label: 'A–Z'}, 'the sort chip shows the new order');
  assert.equal((await rootOrder(page))[0], ids[0], 'the list is in the new order: Sorted root 000 first');
}

// The other order a slow network gives (2026-10-27): the view request already in flight
// reaches the server after the sort is saved. It is answered in the new order but around
// the old order's roots on screen, and the page caches that view; the sort's refresh,
// waiting its turn, then asked from that cache and the sorted list opened partway down.
async function sortWhileViewReachesServerLateCase(page, ids) {
  await setSortModeAndWait(page, 'normal');
  assert.equal((await rootOrder(page))[0], ids[ids.length - 1], 'normal order: the newest root is first');
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    const pageFetch = window.fetch;
    let releaseStray = null;
    const strayHeld = new Promise(resolve => { releaseStray = resolve; });
    let straySeen = false;
    let sortSaved = false;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.endsWith('/tab-state/sort-mode')) {
        const answer = await pageFetch(input, init);
        sortSaved = true;
        return answer;
      }
      if (url.endsWith('/notes/view') && !straySeen) {
        straySeen = true;
        await strayHeld;
      }
      return pageFetch(input, init);
    };
    const until = async isDone => {
      while (!isDone()) await new Promise(resolve => setTimeout(resolve, 10));
    };
    try {
      const strayView = actionRefreshAndMaybeSelect({context: 'stray view request', animateNoteChanges: false});
      await until(() => straySeen);
      const sorting = CommandPalette.setSortMode('alphabetical');
      await until(() => sortSaved);
      releaseStray();
      await Promise.all([sorting, strayView]);
    } finally {
      window.fetch = pageFetch;
    }
  });
  await waitIdle(page);
  assert.equal((await rootOrder(page))[0], ids[0], 'the sorted list opens at its top: Sorted root 000 first');
}

// The tab-state snapshot (the scroll poll's save, the save after a search) is read
// before the user picks a sort order and reaches the server after it. It carries
// the old order, which must not replace the new one: the tab reverted, also after
// a reload, while the menu still ticked the new order. The page holds the snapshot
// before it is sent until the sort order is saved.
async function staleSnapshotAfterSortCase(page, ids) {
  await setSortModeAndWait(page, 'normal');
  assert.equal((await rootOrder(page))[0], ids[ids.length - 1], 'normal order: the newest root is first');
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {persistTabStateSnapshot} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    const pageFetch = window.fetch;
    let releaseSnapshot = null;
    const snapshotHeld = new Promise(resolve => { releaseSnapshot = resolve; });
    let snapshotSeen = false;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.endsWith('/notes/tab-state') && init.method === 'POST' && !snapshotSeen) {
        snapshotSeen = true;
        await snapshotHeld;
      }
      return pageFetch(input, init);
    };
    try {
      // A scroll the poll saves: the snapshot differs from the saved one, so it is sent.
      mode.updateActiveTabScroll(1);
      const staleSave = persistTabStateSnapshot();
      while (!snapshotSeen) await new Promise(resolve => setTimeout(resolve, 10));
      await CommandPalette.setSortMode('alphabetical');
      releaseSnapshot();
      await staleSave;
    } finally {
      window.fetch = pageFetch;
    }
  });
  await reload(page);
  const state = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {sortMode: mode.activeTabSortMode, chip: document.getElementById('root-sort-indicator-label').textContent};
  });
  assert.deepEqual(state, {sortMode: 'alphabetical', chip: 'A–Z'}, 'after a reload the tab keeps the new order');
  assert.equal((await rootOrder(page))[0], ids[0], 'the list is in the new order: Sorted root 000 first');
}

async function setSortModeAndWait(page, sortMode) {
  await page.evaluate(async sortMode => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setSortMode(sortMode);
  }, sortMode);
  await waitIdle(page);
}

// Grow (content volume) or touch (updated) a root in the middle of the screen:
// while editing it keeps its neighbours; after Escape it moves to the top and
// the note that was below it stays where it was on screen.
async function frozenWhileEditingCase(page, sortCommand, label) {
  await runPaletteCommand(page, sortCommand);
  const order = await rootOrder(page);
  const target = order[20];
  const before = order[19];
  const after = order[21];
  await editRoot(page, target);
  await page.evaluate(noteId => {
    const content = document.querySelector(`[data-note-id="${noteId}"] .note-content`);
    const range = document.createRange();
    range.selectNodeContents(content);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand('insertText', false, ` ${'y'.repeat(2000)}`);
  }, target);
  // Save, then refresh the view while still editing, as a poll or band move
  // would: the server now sorts the grown/touched note elsewhere.
  await page.evaluate(async noteId => {
    const {actionSaveNote} = await import('/static/js/modules/mode-manager/actions/content-actions.js');
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    await actionSaveNote(noteId);
    await actionRefreshAndMaybeSelect({startedAt: performance.now(), context: 'sorted-tab-test'});
  }, target);
  await waitIdle(page);
  await pause(800);
  const editingOrder = await rootOrder(page);
  const index = editingOrder.indexOf(target);
  assert.ok(index > 0, `${label}: the edited note is still loaded`);
  assert.equal(editingOrder[index - 1], before, `${label}: while editing, the note keeps the note above it`);
  assert.equal(editingOrder[index + 1], after, `${label}: while editing, the note keeps the note below it`);

  const afterTop = await noteTop(page, after);
  await page.keyboard.press('Escape');
  await waitIdle(page);
  await pause(SETTLE_MS);
  const exitedOrder = await rootOrder(page);
  assert.equal(exitedOrder[0], target, `${label}: after leaving edit mode the note moves to its sorted place (the top)`);
  const afterTopNow = await noteTop(page, after);
  assert.ok(Math.abs(afterTopNow - afterTop) <= TOLERANCE_PX,
    `${label}: the surrounding notes stay on screen: y=${Math.round(afterTop)} -> ${Math.round(afterTopNow)}`);
  assert.equal(await fatalText(page), '', `${label}: no fatal error`);
}

export async function checkSortedTabs(page) {
  const ids = await createFixture(page);
  const created = [];
  const failures = [];
  const check = async (name, body) => {
    try {
      await body();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${name}: ${error.message}`);
      if ((await modeState(page)).isEditing) {
        await page.keyboard.press('Escape');
        await pause(500);
      }
    }
  };
  try {
    await reload(page);
    await check('sort while a view request is in flight', () => sortWhileViewInFlightCase(page, ids));
    await check('sort while a view request reaches the server late', () => sortWhileViewReachesServerLateCase(page, ids));
    await check('stale tab-state snapshot after a sort', () => staleSnapshotAfterSortCase(page, ids));
    // The reported crash: Enter in a content-volume tab added an empty note
    // that sorted to the far end, outside the band on screen.
    await check('content volume, Enter', () => newNoteAtTopBlockedCase(page, ids, 'Sort order: Content volume', 'content volume'));
    await check('alphabetical, Enter', () => newNoteAtTopBlockedCase(page, ids, 'Sort order: Alphabetical', 'alphabetical'));
    await check('content volume, new below', () => newNoteBelowBlockedCase(page, ids, 'Sort order: Content volume', 'content volume'));
    await check('created, new below', () => newNoteBelowBlockedCase(page, ids, 'Sort order: Datetime created', 'created'));
    await check('created, Enter', () => newNoteAtTopAllowedCase(page, 'Sort order: Datetime created', 'created', created));
    await check('updated, Enter', () => newNoteAtTopAllowedCase(page, 'Sort order: Datetime last updated', 'updated', created));
    await check('content volume, frozen', () => frozenWhileEditingCase(page, 'Sort order: Content volume', 'content volume'));
    await check('updated, frozen', () => frozenWhileEditingCase(page, 'Sort order: Datetime last updated', 'updated'));
    assert.deepEqual(failures, [], `sorted tab failures:\n${failures.join('\n')}`);
  } finally {
    await runPaletteCommand(page, 'Sort order: Normal');
    await deleteNotes(page, [...ids, ...created]);
    await reload(page);
  }
}
