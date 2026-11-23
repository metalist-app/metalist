import assert from 'node:assert/strict';

import {runThenCleanUp} from './suite-outcome.mjs';
import {installRequestMonitor, waitForAppQuiet} from './browser-app-idle.mjs';
import {clickAndSelectAll} from './browser-select-field.mjs';

// Changes made in another view show here without a reload, and what the user is looking at stays
// still (multi-view editing step 3; docs/design/multi-view-editing.md, "Step 3's cases";
// docs/ui/interaction-principles.md, principles 1, 2 and 5). Two browser tabs on one vault: "here"
// (the suite's page, in front) and "there" (a second tab, its own view), which makes the changes.

// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
// A change shows within the 2-second status check, plus its refresh.
const SHOWS_WITHIN_MS = 6000;
// Long enough for a change made in the page to have been sent to the server.
const ACT_SENT_MS = 400;
// Long enough for a waiting change to have shown, had it not waited.
const WAITS_AT_LEAST_MS = 5000;
const SETTLE_MS = 800;
// Positions are compared to the pixel; 1px covers sub-pixel rounding only.
const EXACT_PX = 1;
const ROOT_COUNT = 16;
const TAG = 'livechangesfixture';
// Upward: the editing case leaves the page near its bottom, where a step down would not scroll.
const SCROLL_STEP_PX = -2;
const SCROLL_STEP_MS = 100;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function paragraphs(label, count) {
  return Array.from({length: count}, (_, index) =>
    `<p>${label} paragraph ${index + 1}: ordinary sentence text giving the line a realistic width.</p>`).join('');
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// "Root 1" … "Root 16" top to bottom, three lines each; the first three tagged.
async function createFixture(page) {
  return page.evaluate(async ({count, tag, bodies}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {};
    // createNote(null, '') inserts at the top, so create bottom-up.
    for (let index = count; index >= 1; index -= 1) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, bodies[index - 1], index <= 3 ? tag : '');
      ids[`Root ${index}`] = note.id;
    }
    return ids;
  }, {count: ROOT_COUNT, tag: TAG, bodies: Array.from({length: ROOT_COUNT}, (_, index) => paragraphs(`Root ${index + 1}`, 3))});
}

// The notes left: the window-top case deletes "Root 8" itself.
async function deleteFixture(page, ids) {
  await page.evaluate(async ids => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of ids) await NotesAPI.deleteNote(id);
  }, Object.entries(ids).filter(([label]) => label !== 'Root 8').map(([, id]) => id));
}

function noteTop(page, label) {
  return page.evaluate(label => {
    const paragraph = [...document.querySelectorAll('#notes-container p')].find(p => p.textContent.trim().startsWith(`${label} paragraph 1:`));
    return paragraph ? paragraph.closest('.note').getBoundingClientRect().top : null;
  }, label);
}

function inset(page) {
  return page.evaluate(async () => {
    const {getViewportTopInset} = await import('/static/js/modules/mode-manager/services/viewport-reference.js');
    return getViewportTopInset();
  });
}

async function scrollNoteTopTo(page, label, viewportY) {
  const top = await noteTop(page, label);
  assert.notEqual(top, null, `"${label}" should be loaded`);
  await page.evaluate(delta => window.scrollBy(0, delta), top - viewportY);
  await pause(SETTLE_MS);
}

function assertAt(label, what, actual, expected) {
  assert.notEqual(actual, null, `${label}: ${what} should be shown`);
  assert.ok(Math.abs(actual - expected) <= EXACT_PX, `${label}: ${what} should be at y=${Math.round(expected)}, got y=${Math.round(actual)}`);
}

function saveThere(there, id, html, tags) {
  return there.evaluate(async ({id, html, tags}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(id, html, tags);
  }, {id, html, tags});
}

function textOf(page, id) {
  return page.evaluate(id => document.querySelector(`[data-note-id="${id}"] > .note-content`).textContent, id);
}

async function waitForText(page, id, expected) {
  await page.waitForFunction((id, expected) => {
    const content = document.querySelector(`[data-note-id="${id}"] > .note-content`);
    return content !== null && content.textContent.includes(expected);
  }, {timeout: SHOWS_WITHIN_MS}, id, expected);
  await idle(page);
  await pause(SETTLE_MS);
}

// Case 2: a note above the window grows there; the note at the window's top stays put.
async function changeAboveCase(here, there, ids) {
  await scrollNoteTopTo(here, 'Root 5', 200);
  const before = await noteTop(here, 'Root 5');
  await saveThere(there, ids['Root 2'], paragraphs('Root 2', 3) + paragraphs('Grown', 4), TAG);
  await waitForText(here, ids['Root 2'], 'Grown paragraph 4');
  assertAt('change above', '"Root 5"', await noteTop(here, 'Root 5'), before);
}

// Case 3: a note in view changes there; its top stays, the notes below shift by its change.
async function changeInViewCase(here, there, ids) {
  const before = await noteTop(here, 'Root 6');
  const nextBefore = await noteTop(here, 'Root 7');
  await saveThere(there, ids['Root 6'], paragraphs('Root 6', 1), '');
  await waitForText(here, ids['Root 6'], 'Root 6 paragraph 1');
  await here.waitForFunction(id => !document.querySelector(`[data-note-id="${id}"]`).textContent.includes('paragraph 2'), {timeout: SHOWS_WITHIN_MS}, ids['Root 6']);
  assertAt('change in view', '"Root 6"', await noteTop(here, 'Root 6'), before);
  const nextAfter = await noteTop(here, 'Root 7');
  assert.ok(nextAfter < nextBefore - EXACT_PX, `change in view: "Root 7" should move up as "Root 6" shrank (was y=${Math.round(nextBefore)}, now y=${Math.round(nextAfter)})`);
}

// Case 5: the note at the window's top is deleted there; the one below it takes its place.
async function windowTopDeletedCase(here, there, ids) {
  await scrollNoteTopTo(here, 'Root 8', 150);
  const before = await noteTop(here, 'Root 8');
  await there.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNote(id);
  }, ids['Root 8']);
  await here.waitForFunction(id => document.querySelector(`[data-note-id="${id}"]`) === null, {timeout: SHOWS_WITHIN_MS}, ids['Root 8']);
  await idle(here);
  await pause(SETTLE_MS);
  assertAt('window top deleted', '"Root 9"', await noteTop(here, 'Root 9'), Math.max(before, await inset(here)));
}

// Case 6: editing here while a note above changes there: the edited note, its caret and the typing
// stay where they are.
async function editingCase(here, there, ids) {
  await scrollNoteTopTo(here, 'Root 11', 300);
  const point = await here.evaluate(() => {
    const paragraph = [...document.querySelectorAll('#notes-container p')].find(p => p.textContent.trim().startsWith('Root 11 paragraph 1:'));
    const rect = paragraph.getBoundingClientRect();
    return {x: rect.left + 40, y: rect.top + rect.height / 2};
  });
  await here.mouse.click(point.x, point.y);
  await here.waitForSelector(`.note.editing[data-note-id="${ids['Root 11']}"]`);
  await idle(here);
  await here.keyboard.type('TYPED');
  const before = await here.evaluate(id => {
    const selection = window.getSelection();
    return {
      top: document.querySelector(`[data-note-id="${id}"]`).getBoundingClientRect().top,
      caretText: selection.focusNode.textContent, caretOffset: selection.focusOffset,
    };
  }, ids['Root 11']);
  await saveThere(there, ids['Root 9'], paragraphs('Root 9', 3) + paragraphs('Grown while editing', 3), '');
  await waitForText(here, ids['Root 9'], 'Grown while editing paragraph 3');
  const after = await here.evaluate(id => {
    const selection = window.getSelection();
    const note = document.querySelector(`[data-note-id="${id}"]`);
    return {
      isEditing: note.classList.contains('editing'), top: note.getBoundingClientRect().top,
      caretText: selection.focusNode.textContent, caretOffset: selection.focusOffset,
    };
  }, ids['Root 11']);
  assert.ok(after.isEditing, 'editing: the note should still be in edit mode');
  assertAt('editing', 'the edited "Root 11"', after.top, before.top);
  assert.equal(after.caretText, before.caretText, 'editing: the typing should be untouched');
  assert.equal(after.caretOffset, before.caretOffset, 'editing: the caret should stay put');
  assert.ok(after.caretText.includes('TYPED'), 'editing: the typed text should still be there');
  await here.keyboard.press('Escape');
  await idle(here);
}

// Text in the edited note that MetaList has not recorded yet (it ignores input while a command
// runs: typing right after Insert LaTeX, dictation) is the user's: a refresh that brings the
// note's newer server copy keeps it. Found 2026-11-15 (Firefox, Linux): a status check right
// after Insert LaTeX redrew the note and the typed \frac{1}{2} was gone.
async function unrecordedTypingCase(here, ids) {
  await scrollNoteTopTo(here, 'Root 12', 300);
  const point = await here.evaluate(() => {
    const paragraph = [...document.querySelectorAll('#notes-container p')].find(p => p.textContent.trim().startsWith('Root 12 paragraph 1:'));
    const rect = paragraph.getBoundingClientRect();
    return {x: rect.left + 40, y: rect.top + rect.height / 2};
  });
  await here.mouse.click(point.x, point.y);
  await here.waitForSelector(`.note.editing[data-note-id="${ids['Root 12']}"]`);
  await idle(here);
  const kept = await here.evaluate(async ({id, html}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    // The note's server copy changes (as Insert LaTeX saves the note and its tag)...
    await NotesAPI.saveNote(id, html, '');
    // ...and text reaches the editor with no input recorded.
    document.querySelector(`[data-note-id="${id}"] > .note-content p`).append(' UNRECORDED');
    await CommandGate.runWhenFree('test.refresh', () => actionRefreshAndMaybeSelect({context: 'test-unrecorded-typing'}));
    return document.querySelector(`[data-note-id="${id}"] > .note-content`).textContent;
  }, {id: ids['Root 12'], html: paragraphs('Root 12', 3) + paragraphs('Saved meanwhile', 1)});
  assert.ok(kept.includes('UNRECORDED'), `unrecorded typing: the text in the editor should stay, got "${kept.slice(0, 120)}"`);
  await here.keyboard.press('Escape');
  await idle(here);
}

// A scroll made while a change from another view is being fetched stays: the refresh keeps still
// what is at the window's top when it lands, not what was there when it asked (found 2026-11-15:
// the page jumped back, and the scale suite's scroll to the bottom was undone).
async function scrolledWhileFetchingCase(here, there, ids) {
  await scrollNoteTopTo(here, 'Root 4', 200);
  await here.evaluate(() => {
    const pageFetch = window.fetch;
    window.__heldView = {asked: false, release: null};
    const released = new Promise(resolve => { window.__heldView.release = resolve; });
    window.fetch = async (resource, options) => {
      const url = String(resource instanceof Request ? resource.url : resource);
      if (url.endsWith('/api2/notes/view') && window.__heldView !== null) {
        window.__heldView.asked = true;
        await released;
      }
      return pageFetch(resource, options);
    };
    window.__restoreFetch = () => { window.fetch = pageFetch; window.__heldView = null; };
  });
  await saveThere(there, ids['Root 14'], paragraphs('Root 14', 3) + paragraphs('Changed below', 1), '');
  await here.waitForFunction(() => window.__heldView.asked, {timeout: SHOWS_WITHIN_MS});
  await here.evaluate(() => window.scrollBy(0, 300));
  const scrolledTo = await here.evaluate(() => window.scrollY);
  await here.evaluate(() => window.__heldView.release());
  await waitForText(here, ids['Root 14'], 'Changed below paragraph 1');
  await here.evaluate(() => window.__restoreFetch());
  assert.ok(Math.abs(await here.evaluate(() => window.scrollY) - scrolledTo) <= EXACT_PX,
    `scrolled while fetching: the page should stay at y=${scrolledTo}, got y=${await here.evaluate(() => window.scrollY)}`);
}

// Case 10: a change waits while a dialog (here the command palette) is open, and shows once it closes.
async function waitsForDialogCase(here, there, ids) {
  await here.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.open();
  });
  await saveThere(there, ids['Root 12'], paragraphs('Root 12', 1) + '<p>Changed behind a dialog</p>', '');
  await pause(WAITS_AT_LEAST_MS);
  assert.ok(!(await textOf(here, ids['Root 12'])).includes('Changed behind a dialog'), 'dialog: the change should wait while the dialog is open');
  await here.keyboard.press('Escape');
  await waitForText(here, ids['Root 12'], 'Changed behind a dialog');
}

// Case 9: a change waits while the page is scrolling, and shows once it stops.
async function waitsForScrollingCase(here, there, ids) {
  await here.evaluate(({step, every}) => {
    window.__liveScrolling = window.setInterval(() => window.scrollBy(0, step), every);
  }, {step: SCROLL_STEP_PX, every: SCROLL_STEP_MS});
  // The page is scrolling before the change is made.
  await pause(SETTLE_MS);
  const scrolledFrom = await here.evaluate(() => window.scrollY);
  await saveThere(there, ids['Root 13'], paragraphs('Root 13', 1) + '<p>Changed while scrolling</p>', '');
  await pause(WAITS_AT_LEAST_MS);
  assert.ok(await here.evaluate(from => window.scrollY < from, scrolledFrom), 'scrolling: the page should have been scrolling');
  const textWhileScrolling = await textOf(here, ids['Root 13']);
  await here.evaluate(() => window.clearInterval(window.__liveScrolling));
  assert.ok(!textWhileScrolling.includes('Changed while scrolling'), 'scrolling: the change should wait while the page scrolls');
  await waitForText(here, ids['Root 13'], 'Changed while scrolling');
}

function searchBox(page) {
  return page.evaluate(() => document.getElementById('search-input').value);
}

// Typed in the other tab, which stays behind (a background tab's timers are slowed, so its
// requests are waited for by time): the search runs once typing pauses, then is saved.
const SEARCH_RUN_AND_SAVE_MS = 3000;

async function typeSearchThere(there, search) {
  await there.evaluate(search => {
    const input = document.getElementById('search-input');
    input.focus();
    input.value = search;
    input.dispatchEvent(new Event('input', {bubbles: true}));
  }, search);
  await pause(SEARCH_RUN_AND_SAVE_MS);
  await there.evaluate(() => document.getElementById('search-input').blur());
}

function shownRootIds(page) {
  return page.evaluate(() => [...document.querySelectorAll('#notes-container > .note[data-note-id]')].map(note => note.dataset.noteId));
}

// Case 13, then 7: the search of the context shown here changed there shows here, from the top; a
// note that stops matching it leaves.
async function searchChangedCase(here, there, ids) {
  await here.evaluate(() => window.scrollTo(0, 300));
  await pause(SETTLE_MS);
  await typeSearchThere(there, TAG);
  await here.waitForFunction(tag => document.getElementById('search-input').value === tag, {timeout: SHOWS_WITHIN_MS}, TAG);
  await idle(here);
  await pause(SETTLE_MS);
  assert.equal(await here.evaluate(() => window.scrollY), 0, 'search changed there: the list should show from the top');
  const labelOf = Object.fromEntries(Object.entries(ids).map(([label, id]) => [id, label]));
  assert.deepEqual((await shownRootIds(here)).map(id => labelOf[id]), ['Root 1', 'Root 2', 'Root 3'], 'search changed there: the tagged notes should show');

  await saveThere(there, ids['Root 2'], paragraphs('Root 2', 1), '');
  await here.waitForFunction(id => document.querySelector(`[data-note-id="${id}"]`) === null, {timeout: SHOWS_WITHIN_MS}, ids['Root 2']);
}

// The box, the search this view holds as typed, and the search its list was run for.
function searchState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {box: document.getElementById('search-input').value, typed: mode.searchQuery, run: mode.getExecutedSearchQuery()};
  });
}

// Holds this view's next reading of the search contexts (the tab state it takes again when another
// view changed them) until released, so a case can act while it is being fetched.
async function holdContextsReading(page) {
  await page.evaluate(() => {
    const pageFetch = window.fetch;
    window.__heldReading = {asked: false, release: null};
    const released = new Promise(resolve => { window.__heldReading.release = resolve; });
    window.fetch = async (resource, options) => {
      const url = String(resource instanceof Request ? resource.url : resource);
      const isReading = url.endsWith('/api2/notes/tab-state') && options !== undefined && options.method === 'GET';
      if (isReading && window.__heldReading !== null && !window.__heldReading.asked) {
        window.__heldReading.asked = true;
        await released;
      }
      return pageFetch(resource, options);
    };
    window.__restoreFetch = () => { window.fetch = pageFetch; window.__heldReading = null; };
  });
}

async function releaseContextsReading(page) {
  await page.evaluate(() => window.__heldReading.release());
  await idle(page);
  await pause(SETTLE_MS);
  await idle(page);
  await page.evaluate(() => window.__restoreFetch());
}

function labelsShown(page, ids) {
  const labelOf = Object.fromEntries(Object.entries(ids).map(([label, id]) => [id, label]));
  return shownRootIds(page).then(shown => shown.map(id => labelOf[id]));
}

// A search typed while a change to the contexts from another view is being fetched stands: the
// box, the search and the list follow the typing (principle 2: only the user's action changes
// the screen). Found 2026-11-15, in one view: after an AI answer the view took its contexts
// again, the search box was cleared meanwhile, and the answer put the old search back under an
// empty box (the scale suite, Linux and Windows). Here the box is cleared while it fetches: the
// list shows everything. Returns the context added there, for the next case and the clean-up.
async function clearedWhileFetchingCase(here, there, ids) {
  const tagged = await labelsShown(here, ids);
  assert.deepEqual(await searchState(here), {box: TAG, typed: TAG, run: TAG}, 'cleared while fetching: this view starts on the tag search');
  // The other view typed this context's search and left its box: once this view has heard so,
  // its own box can be typed in again (the search lock, case 13).
  await here.waitForFunction(() => !document.getElementById('search-input').readOnly, {timeout: SHOWS_WITHIN_MS});
  await idle(here);
  await holdContextsReading(here);
  await there.evaluate(async () => {
    const keyboardEvents = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await keyboardEvents.openSearchInNewSearchContext('livechangesother', 'live-changes-suite');
  });
  const added = (await contextIds(there)).active;
  await here.waitForFunction(() => window.__heldReading.asked, {timeout: SHOWS_WITHIN_MS});
  await clickAndSelectAll(here, '#search-input');
  await here.keyboard.press('Backspace');
  assert.equal(await searchBox(here), '', 'cleared while fetching: the box is cleared while the contexts are still being fetched');
  assert.equal(await here.evaluate(() => window.__heldReading.asked && window.__heldReading !== null), true);
  await releaseContextsReading(here);
  assert.deepEqual(await searchState(here), {box: '', typed: '', run: ''}, 'cleared while fetching: the cleared search should stand');
  const shown = await labelsShown(here, ids);
  assert.ok(shown.length > tagged.length, `cleared while fetching: the list should show every note, got ${shown.join(', ')}`);
  return {added, tagged};
}

// The same with a search typed into the box while it fetches: its notes show.
async function typedWhileFetchingCase(here, there, ids, tagged) {
  await holdContextsReading(here);
  // Typed there in its own context: the contexts change, the one shown here does not.
  await typeSearchThere(there, 'livechangesotherchanged');
  await here.waitForFunction(() => window.__heldReading.asked, {timeout: SHOWS_WITHIN_MS});
  await clickAndSelectAll(here, '#search-input');
  await here.keyboard.type(TAG);
  assert.equal(await searchBox(here), TAG, 'typed while fetching: the box holds the typed search while the contexts are still being fetched');
  await releaseContextsReading(here);
  assert.deepEqual(await searchState(here), {box: TAG, typed: TAG, run: TAG}, 'typed while fetching: the typed search should stand');
  assert.deepEqual(await labelsShown(here, ids), tagged, 'typed while fetching: the typed search\'s notes should show');
}

// Holds the answer to this view's next reading of the search contexts until released: the server
// has answered it, as the tabs were then, and the page takes it only after what the case does next.
async function holdContextsAnswer(page) {
  await page.evaluate(() => {
    const pageFetch = window.fetch;
    window.__heldAnswer = {fetched: false, release: null};
    const released = new Promise(resolve => { window.__heldAnswer.release = resolve; });
    let isHeld = false;
    window.fetch = async (resource, options) => {
      const url = String(resource instanceof Request ? resource.url : resource);
      const isReading = url.endsWith('/api2/notes/tab-state') && options !== undefined && options.method === 'GET';
      if (!isReading || isHeld) return pageFetch(resource, options);
      isHeld = true;
      const response = await pageFetch(resource, options);
      window.__heldAnswer.fetched = true;
      await released;
      return response;
    };
    window.__restoreFetch = () => { window.fetch = pageFetch; window.__heldAnswer = null; };
  });
}

async function releaseContextsAnswer(page) {
  await page.evaluate(() => window.__heldAnswer.release());
  await idle(page);
  await pause(SETTLE_MS);
  await idle(page);
  await page.evaluate(() => window.__restoreFetch());
}

// What this view holds of its contexts, and what the server holds for it.
function contextsState(page, otherContext) {
  return page.evaluate(async otherContext => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/notes/tab-state', {headers: buildSessionHeaders(false), cache: 'no-store'});
    if (!response.ok) throw new Error(`tab-state read failed with status ${response.status}`);
    const server = await response.json();
    return {
      active: mode.activeTabId,
      order: [...mode.tabOrder],
      serverOrder: server.tabOrder,
      untagged: [mode.isUntaggedView, server.untaggedViews.includes(mode.activeTabId)],
      sort: [mode.activeTabSortMode, server.tabs[mode.activeTabId].sortMode],
      search: mode.searchQuery,
      otherSearch: mode.tabs[otherContext].searchQuery,
    };
  }, otherContext);
}

// The other view changes the contexts (the search of its own context), this view reads them, and
// `act` happens here after the server answered that reading and before the page takes the answer.
async function actWhileAReadingIsAnswered(here, there, otherSearch, act) {
  await idle(here);
  await holdContextsAnswer(here);
  await typeSearchThere(there, otherSearch);
  await here.waitForFunction(() => window.__heldAnswer.fetched, {timeout: SHOWS_WITHIN_MS});
  // The change is sent while the answer is held; what it shows waits its turn behind the reading
  // (turns.js), so it is finished only once the answer is let go.
  const acting = act();
  await pause(ACT_SENT_MS);
  await releaseContextsAnswer(here);
  await acting;
}

// A change made here while this view reads its contexts again stands, and what the other view
// changed still arrives (cases agreed 2026-11-17, docs/future-plans/one-writer-refactoring.md,
// idea 1; principle 2: only the user's action changes the screen). The reading was answered
// before the change, so it holds the tabs as they were: taken, it put the screen back (found
// 2026-11-15, the tab-switching suite: Untagged turned on went off again). `other` is the other
// view's context; this view stays on its own until it opens one.
async function changedWhileAReadingIsAnsweredCase(here, there, other) {
  const palette = (name, value) => here.evaluate(async ({name, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette[name](value);
  }, {name, value});

  // Case 1: Untagged turned on. Case 7: the other view's search is shown once the tabs are read again.
  await actWhileAReadingIsAnswered(here, there, 'livechangesovertakenone', () => palette('setIsUntaggedView', true));
  let state = await contextsState(here, other);
  assert.deepEqual(state.untagged, [true, true], 'Untagged turned on while the contexts were read: it should stay on');
  assert.equal(state.search, TAG, 'and its context should keep its search under the Untagged view');
  assert.equal(state.otherSearch, 'livechangesovertakenone', 'and the other view\'s search should still arrive');
  await palette('setIsUntaggedView', false);
  await idle(here);

  // Case 2: the sort order changed.
  await actWhileAReadingIsAnswered(here, there, 'livechangesovertakentwo', () => palette('setSortMode', 'created'));
  state = await contextsState(here, other);
  assert.deepEqual(state.sort, ['created', 'created'], 'the order chosen while the contexts were read: it should stay');
  assert.equal(state.otherSearch, 'livechangesovertakentwo');
  await palette('setSortMode', 'normal');
  await idle(here);

  // Case 5: a context opened here.
  let opened = null;
  await actWhileAReadingIsAnswered(here, there, 'livechangesovertakenthree', async () => {
    opened = await here.evaluate(async () => {
      const keyboardEvents = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
      return keyboardEvents.openSearchInNewSearchContext('livechangesopenedhere', 'live-changes-suite');
    });
  });
  state = await contextsState(here, other);
  assert.equal(state.active, opened, 'a context opened while the contexts were read: it should stay shown');
  assert.ok(state.order.includes(opened) && state.serverOrder.includes(opened), 'and stay in the row');
  assert.equal(state.otherSearch, 'livechangesovertakenthree');

  // Case 6: a context deleted here (the one just opened) does not come back.
  await actWhileAReadingIsAnswered(here, there, 'livechangesovertakenfour', async () => {
    await here.evaluate(opened => document.querySelector(`.delete-context[data-delete-tab-id="${opened}"]`).click(), opened);
    await here.waitForFunction(async opened => {
      const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
      return !ModeContextInstance.tabOrder.includes(opened);
    }, {timeout: SHOWS_WITHIN_MS}, opened);
  });
  state = await contextsState(here, other);
  assert.ok(!state.order.includes(opened) && !state.serverOrder.includes(opened), 'a context deleted while the contexts were read: it should not come back');
  assert.equal(state.otherSearch, 'livechangesovertakenfour');
}

// The context added for the cases above goes, from the view that made it.
async function removeAddedContext(here, there, original, added) {
  await there.evaluate(async ({original, added}) => {
    const keyboardEvents = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await keyboardEvents.switchToTabContext(original, {});
    const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    await deleteTabOnServer(added);
  }, {original, added});
  await here.waitForFunction(async added => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return !ModeContextInstance.tabOrder.includes(added);
  }, {timeout: SHOWS_WITHIN_MS}, added);
  await idle(here);
}

function contextIds(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {order: [...ModeContextInstance.tabOrder], active: ModeContextInstance.activeTabId};
  });
}

// Cases 11 and 12: a context added there shows here and this view stays on its own; the context shown
// here deleted there moves this view to the one left, running its search.
async function contextsCase(here, there) {
  const before = await contextIds(here);
  await there.evaluate(async () => {
    const keyboardEvents = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await keyboardEvents.openSearchInNewSearchContext('livechangesnothing', 'live-changes-suite');
  });
  const added = (await contextIds(there)).active;
  await here.waitForFunction(async added => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.tabOrder.includes(added);
  }, {timeout: SHOWS_WITHIN_MS}, added);
  await idle(here);
  assert.equal((await contextIds(here)).active, before.active, 'context added there: this view should stay on its own context');

  // Typed here while the deletion is being fetched: the context typed in is gone, so the view
  // moves on as it does without typing, and the typed text goes with its context.
  await holdContextsReading(here);
  await there.evaluate(async deleted => {
    const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    await deleteTabOnServer(deleted);
  }, before.active);
  await here.waitForFunction(() => window.__heldReading.asked, {timeout: SHOWS_WITHIN_MS});
  await here.click('#search-input');
  await here.keyboard.type('typedinagonecontext');
  await releaseContextsReading(here);
  await here.waitForFunction(added => document.getElementById('search-input').value === 'livechangesnothing', {timeout: SHOWS_WITHIN_MS}, added);
  await idle(here);
  await pause(SETTLE_MS);
  assert.deepEqual(await shownRootIds(here), [], 'context deleted there: the context left should run its own search here');
  assert.equal((await contextIds(here)).active, added);
}

// A request this view sends about a context the other view deleted a moment ago, before this view
// heard: nothing changes and no error shows (agreed 2026-11-18); the view then takes the list.
async function askedOfADeletedContextCase(here, there) {
  const asks = {
    'sort order': () => here.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.setSortMode('created');
    }),
    'Untagged': () => here.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.setIsUntaggedView(true);
    }),
    'duplicate': gone => here.evaluate(gone => document.querySelector(`.duplicate-context[data-source-tab-id="${gone}"]`).click(), gone),
    'delete': gone => here.evaluate(gone => document.querySelector(`.delete-context[data-delete-tab-id="${gone}"]`).click(), gone),
  };
  const errors = [];
  const noteError = error => errors.push(error.message);
  here.on('pageerror', noteError);
  for (const [name, ask] of Object.entries(asks)) {
    const kept = (await contextIds(here)).order;
    const gone = await here.evaluate(async () => {
      const keyboardEvents = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
      return keyboardEvents.openSearchInNewSearchContext('livechangesaskedofgone', 'live-changes-suite');
    });
    await idle(here);
    await holdContextsReading(here);
    await there.evaluate(async gone => {
      const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
      await deleteTabOnServer(gone);
    }, gone);
    await here.waitForFunction(() => window.__heldReading.asked, {timeout: SHOWS_WITHIN_MS});
    assert.equal((await contextIds(here)).active, gone, `${name}: this view should not have heard of the delete yet`);

    // What is asked waits its turn behind the reading (turns.js), so it ends once that is let go.
    const asking = ask(gone);
    await pause(SETTLE_MS);
    const messages = await here.evaluate(() => [...document.querySelectorAll('.floating-message-error')].map(card => card.textContent));
    assert.deepEqual(messages, [], `${name} of a context deleted there: no error should show`);

    await releaseContextsReading(here);
    await asking;
    await here.waitForFunction(async gone => {
      const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
      return !ModeContextInstance.tabOrder.includes(gone);
    }, {timeout: SHOWS_WITHIN_MS}, gone);
    await idle(here);
    await pause(SETTLE_MS);
    assert.deepEqual((await contextIds(here)).order, kept, `${name} of a context deleted there: the list should be as before it was made`);
    // The context shown instead was not the one asked: it keeps its own order and view.
    const shownInstead = await here.evaluate(async () => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      return {sort: mode.activeTabSortMode, untagged: mode.isUntaggedView};
    });
    assert.deepEqual(shownInstead, {sort: 'normal', untagged: false}, `${name} of a context deleted there: the context shown instead is left as it was`);
  }
  here.off('pageerror', noteError);
  assert.deepEqual(errors, [], 'asking of a context deleted there should raise no errors');
}

export async function checkLiveChanges(here, browser) {
  await here.bringToFront();
  const there = await browser.newPage();
  const errors = [];
  there.on('pageerror', error => errors.push(error.message));
  await installRequestMonitor(there);
  await there.goto(here.url());
  await there.waitForSelector('[data-app-ready="true"]');
  await here.bringToFront();
  const ids = await createFixture(here);
  await runThenCleanUp('live changes', async () => {
    await here.reload();
    await here.waitForSelector('[data-app-ready="true"]');
    await idle(here);
    assert.equal(await here.evaluate(() => document.hidden), false, 'the suite\'s own tab should be in front');
    await changeAboveCase(here, there, ids);
    await changeInViewCase(here, there, ids);
    await windowTopDeletedCase(here, there, ids);
    await editingCase(here, there, ids);
    await unrecordedTypingCase(here, ids);
    await scrolledWhileFetchingCase(here, there, ids);
    await waitsForDialogCase(here, there, ids);
    await waitsForScrollingCase(here, there, ids);
    await searchChangedCase(here, there, ids);
    const original = (await contextIds(here)).active;
    const {added, tagged} = await clearedWhileFetchingCase(here, there, ids);
    await typedWhileFetchingCase(here, there, ids, tagged);
    await changedWhileAReadingIsAnsweredCase(here, there, added);
    await removeAddedContext(here, there, original, added);
    await contextsCase(here, there);
    await askedOfADeletedContextCase(here, there);
    assert.deepEqual(errors, [], 'the other tab should raise no errors');
  }, async () => {
    await there.close();
    await deleteFixture(here, ids);
  });
}
