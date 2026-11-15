import assert from 'node:assert/strict';

import {runThenCleanUp} from './suite-outcome.mjs';
import {installRequestMonitor, waitForAppQuiet} from './browser-app-idle.mjs';

// Changes made in another view show here without a reload, and what the user is looking at stays
// still (multi-view editing step 3; docs/design/multi-view-editing.md, "Step 3's cases";
// docs/ui/interaction-principles.md, principles 1, 2 and 5). Two browser tabs on one vault: "here"
// (the suite's page, in front) and "there" (a second tab, its own view), which makes the changes.

// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
// A change shows within the 2-second status check, plus its refresh.
const SHOWS_WITHIN_MS = 6000;
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

async function waitForText(page, id, expected, label) {
  await page.waitForFunction((id, expected) => {
    const content = document.querySelector(`[data-note-id="${id}"] > .note-content`);
    return content !== null && content.textContent.includes(expected);
  }, {timeout: SHOWS_WITHIN_MS}, id, expected).catch(error => {
    throw new Error(`${label}: "${expected}" should show here within ${SHOWS_WITHIN_MS}ms (${error.message})`);
  });
  await idle(page);
  await pause(SETTLE_MS);
}

// Case 2: a note above the window grows there; the note at the window's top stays put.
async function changeAboveCase(here, there, ids) {
  await scrollNoteTopTo(here, 'Root 5', 200);
  const before = await noteTop(here, 'Root 5');
  await saveThere(there, ids['Root 2'], paragraphs('Root 2', 3) + paragraphs('Grown', 4), TAG);
  await waitForText(here, ids['Root 2'], 'Grown paragraph 4', 'change above');
  assertAt('change above', '"Root 5"', await noteTop(here, 'Root 5'), before);
}

// Case 3: a note in view changes there; its top stays, the notes below shift by its change.
async function changeInViewCase(here, there, ids) {
  const before = await noteTop(here, 'Root 6');
  const nextBefore = await noteTop(here, 'Root 7');
  await saveThere(there, ids['Root 6'], paragraphs('Root 6', 1), '');
  await waitForText(here, ids['Root 6'], 'Root 6 paragraph 1', 'change in view');
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
  await waitForText(here, ids['Root 9'], 'Grown while editing paragraph 3', 'editing');
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
  await waitForText(here, ids['Root 12'], 'Changed behind a dialog', 'dialog closed');
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
  await waitForText(here, ids['Root 13'], 'Changed while scrolling', 'scrolling stopped');
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
  await here.waitForFunction(tag => document.getElementById('search-input').value === tag, {timeout: SHOWS_WITHIN_MS}, TAG)
    .catch(error => { throw new Error(`search changed there: the search box here should read "${TAG}" (${error.message})`); });
  await idle(here);
  await pause(SETTLE_MS);
  assert.equal(await here.evaluate(() => window.scrollY), 0, 'search changed there: the list should show from the top');
  const labelOf = Object.fromEntries(Object.entries(ids).map(([label, id]) => [id, label]));
  assert.deepEqual((await shownRootIds(here)).map(id => labelOf[id]), ['Root 1', 'Root 2', 'Root 3'], 'search changed there: the tagged notes should show');

  await saveThere(there, ids['Root 2'], paragraphs('Root 2', 1), '');
  await here.waitForFunction(id => document.querySelector(`[data-note-id="${id}"]`) === null, {timeout: SHOWS_WITHIN_MS}, ids['Root 2'])
    .catch(error => { throw new Error(`stops matching: "Root 2" should leave the list here (${error.message})`); });
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
  }, {timeout: SHOWS_WITHIN_MS}, added).catch(error => { throw new Error(`context added there: it should be listed here (${error.message})`); });
  await idle(here);
  assert.equal((await contextIds(here)).active, before.active, 'context added there: this view should stay on its own context');

  await there.evaluate(async deleted => {
    const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
    await deleteTabOnServer(deleted);
  }, before.active);
  await here.waitForFunction(added => document.getElementById('search-input').value === 'livechangesnothing', {timeout: SHOWS_WITHIN_MS}, added)
    .catch(error => { throw new Error(`context deleted there: this view should move to the context left (${error.message})`); });
  await idle(here);
  await pause(SETTLE_MS);
  assert.deepEqual(await shownRootIds(here), [], 'context deleted there: the context left should run its own search here');
  assert.equal((await contextIds(here)).active, added);
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
    await waitsForDialogCase(here, there, ids);
    await waitsForScrollingCase(here, there, ids);
    await searchChangedCase(here, there, ids);
    await contextsCase(here, there);
    assert.deepEqual(errors, [], 'the other tab should raise no errors');
  }, async () => {
    await there.close();
    await deleteFixture(here, ids);
  });
}
