import assert from 'node:assert/strict';

import {runThenCleanUp} from './suite-outcome.mjs';
import {installRequestMonitor, waitForAppQuiet} from './browser-app-idle.mjs';

// One editor per root note (multi-view editing step 4; docs/design/multi-view-editing.md,
// "Step 4's cases"). Two browser tabs on one vault: "here" (the suite's page, in front) and "there"
// (a second tab of the same browser, so a root it edits is "in another tab").

const REQUESTS_QUIET_MS = 300;
// A lock shows within the 2-second status check, plus its refresh.
const SHOWS_WITHIN_MS = 6000;
// A click in a root edited there waits for the other tab to save and leave, at most the handover time.
const TAKES_OVER_WITHIN_MS = 10000;
// Long enough for a moved note to have moved, had it not been kept in place.
const WAITS_AT_LEAST_MS = 4000;
const SETTLE_MS = 800;
// The other tab is in the background, where animation frames (waitForFunction's default) never come.
const BACKGROUND_POLL_MS = 100;
// A typed search's lock (edit_locks.py SEARCH_LOCK_SECONDS, 5 s) plus a status check and its refresh.
const SEARCH_LOCK_ENDS_WITHIN_MS = 10000;
const EXACT_PX = 1;
const ROOT_COUNT = 12;
const IN_ANOTHER_TAB = 'in another tab';
const TYPED_THERE = ' typed in the other tab';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function paragraphs(label, count) {
  return Array.from({length: count}, (_, index) =>
    `<p>${label} paragraph ${index + 1}: ordinary sentence text giving the line a realistic width.</p>`).join('');
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// "Root 1" … "Root 12" top to bottom, three lines each; "Root 3" has a child.
async function createFixture(page) {
  return page.evaluate(async ({count, bodies}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {};
    for (let index = count; index >= 1; index -= 1) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, bodies[index - 1], '');
      ids[`Root ${index}`] = note.id;
    }
    const child = await NotesAPI.createChild(ids['Root 3'], '');
    await NotesAPI.saveNote(child.id, '<p>Child of Root 3: a line of text.</p>', '');
    ids['Child of Root 3'] = child.id;
    return ids;
  }, {count: ROOT_COUNT, bodies: Array.from({length: ROOT_COUNT}, (_, index) => paragraphs(`Root ${index + 1}`, 3))});
}

async function deleteFixture(page, ids) {
  await page.evaluate(async ids => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of ids) await NotesAPI.deleteNote(id);
  }, Object.entries(ids).filter(([label]) => label.startsWith('Root ')).map(([, id]) => id));
}

function noteTop(page, id) {
  return page.evaluate(id => document.querySelector(`[data-note-id="${id}"]`).getBoundingClientRect().top, id);
}

async function scrollNoteTopTo(page, id, viewportY) {
  await page.evaluate((id, y) => window.scrollBy(0, document.querySelector(`[data-note-id="${id}"]`).getBoundingClientRect().top - y), id, viewportY);
  await pause(SETTLE_MS);
}

function assertAt(label, what, actual, expected) {
  assert.ok(Math.abs(actual - expected) <= EXACT_PX, `${label}: ${what} should be at y=${Math.round(expected)}, got y=${Math.round(actual)}`);
}

// Edits the note there; a root this tab still shows as edited here is taken over first.
async function editThere(there, noteId) {
  await there.evaluate(async noteId => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {actionEditTakenOverNote} = await import('/static/js/modules/mode-manager/actions/selection-actions.js');
    await CommandGate.runWhenFree('test.edit-there', () => actionEditTakenOverNote(noteId, {initialCaretVisibility: 'visible'}));
  }, noteId);
  await there.waitForFunction(async noteId => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.isEditing && ModeContextInstance.currentNoteId === noteId;
  }, {timeout: TAKES_OVER_WITHIN_MS, polling: BACKGROUND_POLL_MS}, noteId);
  return isEditing(there, noteId);
}

function stopEditingThere(there) {
  return there.evaluate(async () => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const {actionDeselectNote} = await import('/static/js/modules/mode-manager/actions/selection-actions.js');
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    if (ModeContextInstance.isEditing) await CommandGate.runWhenFree('test.stop-there', () => actionDeselectNote());
  });
}

function isEditing(page, noteId) {
  return page.evaluate(async noteId => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.isEditing && ModeContextInstance.currentNoteId === noteId;
  }, noteId);
}

async function waitForMarker(here, rootId) {
  await here.waitForFunction(rootId => document.querySelector(`#notes-container > .note[data-note-id="${rootId}"] > .note-edit-lock`) !== null,
    {timeout: SHOWS_WITHIN_MS}, rootId);
  await idle(here);
}

async function waitForNoMarker(here, rootId) {
  await here.waitForFunction(rootId => document.querySelector(`#notes-container > .note[data-note-id="${rootId}"] > .note-edit-lock`) === null,
    {timeout: SHOWS_WITHIN_MS}, rootId);
  await idle(here);
}

async function clickText(page, noteId) {
  const point = await page.evaluate(noteId => {
    const content = document.querySelector(`[data-note-id="${noteId}"] > .note-content`);
    const rect = content.querySelector('p').getBoundingClientRect();
    return {x: rect.left + 40, y: rect.top + rect.height / 2};
  }, noteId);
  await page.mouse.click(point.x, point.y);
}

// Cases 1 and 3: editing a child there locks its whole root here; the marker's tooltip says where.
async function markerCase(here, there, ids) {
  assert.ok(await editThere(there, ids['Child of Root 3']), 'the other tab should edit the child');
  await waitForMarker(here, ids['Root 3']);
  const tooltip = await here.evaluate(rootId => document.querySelector(`[data-note-id="${rootId}"] > .note-edit-lock`).title, ids['Root 3']);
  assert.equal(tooltip, `Being edited ${IN_ANOTHER_TAB}`);
}

// The floating message there saying why its editing ended.
function waitForMessageThere(there, text) {
  return there.waitForFunction(text => [...document.querySelectorAll('.floating-message-text')].some(shown => shown.textContent === text),
    {timeout: TAKES_OVER_WITHIN_MS, polling: BACKGROUND_POLL_MS}, text);
}

function isRootCollapsed(page, rootId) {
  return page.evaluate(rootId => document.querySelector(`#notes-container > .note[data-note-id="${rootId}"]`).classList.contains('collapsed'), rootId);
}

// Cases 4 and 5: a click in the text of a root edited there takes it over at once: the other tab
// saves its typing and leaves, and the root is edited here, staying where it was. No card, no
// second click (decided 2026-11-15).
async function clickTakesOverCase(here, there, ids) {
  await there.keyboard.type(TYPED_THERE);
  await scrollNoteTopTo(here, ids['Root 3'], 200);
  const before = await noteTop(here, ids['Root 3']);
  await clickText(here, ids['Root 3']);
  await here.waitForFunction(async rootId => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.isEditing && ModeContextInstance.currentNoteId === rootId;
  }, {timeout: TAKES_OVER_WITHIN_MS}, ids['Root 3']);
  await idle(here);
  assert.equal(await here.evaluate(() => document.querySelector('.note-edit-lock-card')), null, 'click: no card should open');
  assertAt('click', '"Root 3"', await noteTop(here, ids['Root 3']), before);
  assert.equal(await isEditing(there, ids['Child of Root 3']), false, 'click: the other tab should have left the note');
  await waitForMessageThere(there, 'Editing moved to another tab');
  const childText = await here.evaluate(childId => document.querySelector(`[data-note-id="${childId}"] > .note-content`).textContent, ids['Child of Root 3']);
  assert.ok(childText.includes(TYPED_THERE.trim()), `click: the other tab's typing should be saved, got "${childText}"`);
  assert.equal(await here.evaluate(rootId => document.querySelector(`[data-note-id="${rootId}"] > .note-edit-lock`), ids['Root 3']), null);
  await here.keyboard.press('Escape');
  await idle(here);
}

// Case 6: a click on the fold arrow of a root edited there takes it over and folds it; the other
// tab leaves editing, and neither tab holds the root afterwards: no pencil in either.
async function arrowTakesOverCase(here, there, ids) {
  assert.ok(await editThere(there, ids['Child of Root 3']), 'the other tab should edit the child again');
  await waitForMarker(here, ids['Root 3']);
  assert.equal(await isRootCollapsed(here, ids['Root 3']), false);
  await here.click(`#notes-container > .note[data-note-id="${ids['Root 3']}"] > .note-collapse-toggle`);
  await here.waitForFunction(rootId => document.querySelector(`#notes-container > .note[data-note-id="${rootId}"]`).classList.contains('collapsed'),
    {timeout: TAKES_OVER_WITHIN_MS}, ids['Root 3']);
  await idle(here);
  assert.equal(await here.evaluate(() => document.querySelector('.note-edit-lock-card')), null, 'arrow: no card should open');
  await there.waitForFunction(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return !ModeContextInstance.isEditing;
  }, {timeout: TAKES_OVER_WITHIN_MS, polling: BACKGROUND_POLL_MS});
  // Editing did not move here: the fold ended it (found 2026-11-15: it said "Editing moved").
  await waitForMessageThere(there, 'Editing ended: changed in another tab');
  await waitForNoMarker(here, ids['Root 3']);
  // A tab in the background shows what changed once it is shown again.
  await there.bringToFront();
  await waitForNoMarker(there, ids['Root 3']);
  await here.bringToFront();
  assert.equal(await isEditing(here, ids['Root 3']), false, 'arrow: the root should not be edited here');
  await here.click(`#notes-container > .note[data-note-id="${ids['Root 3']}"] > .note-collapse-toggle`);
  await here.waitForFunction(rootId => !document.querySelector(`#notes-container > .note[data-note-id="${rootId}"]`).classList.contains('collapsed'),
    {timeout: SHOWS_WITHIN_MS}, ids['Root 3']);
  await idle(here);
}

// Case 7, a neighbour: the other tab moves the note below the root edited here to just above it.
// Only the neighbour moved, so it shows above at once; the edited root stays at its height (found
// 2026-11-15: the list kept the old order until editing ended).
async function neighbourMovedAboveEditedCase(here, there, ids) {
  await scrollNoteTopTo(here, ids['Root 9'], 250);
  await clickText(here, ids['Root 9']);
  await here.waitForSelector(`.note.editing[data-note-id="${ids['Root 9']}"]`);
  await idle(here);
  const editedTop = await noteTop(here, ids['Root 9']);
  await there.evaluate(async ({moved, before}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.moveNote(moved, before, 'before', null);
  }, {moved: ids['Root 10'], before: ids['Root 9']});
  await here.waitForFunction(({moved, edited}) => {
    const roots = [...document.querySelectorAll('#notes-container > .note[data-note-id]')].map(note => note.dataset.noteId);
    return roots.indexOf(moved) === roots.indexOf(edited) - 1;
  }, {timeout: SHOWS_WITHIN_MS}, {moved: ids['Root 10'], edited: ids['Root 9']});
  await idle(here);
  await pause(SETTLE_MS);
  assertAt('neighbour moved', 'the edited "Root 9"', await noteTop(here, ids['Root 9']), editedTop);
  assert.ok(await isEditing(here, ids['Root 9']), 'neighbour moved: "Root 9" should still be edited');
  await here.keyboard.press('Escape');
  await idle(here);
}

// Cases 7 and 9: the other tab moves the root edited here to the top: allowed; here it stays at its
// height while editing, and when editing ends it goes to its new place with the note at the window's
// top staying still.
async function movedWhileEditedCase(here, there, ids) {
  await scrollNoteTopTo(here, ids['Root 5'], 120);
  await clickText(here, ids['Root 7']);
  await here.waitForSelector(`.note.editing[data-note-id="${ids['Root 7']}"]`);
  await idle(here);
  const editedTop = await noteTop(here, ids['Root 7']);
  const windowTop = await noteTop(here, ids['Root 5']);
  await there.evaluate(async rootId => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.moveNoteToTop(rootId, '');
  }, ids['Root 7']);
  await pause(WAITS_AT_LEAST_MS);
  await idle(here);
  assertAt('moved while edited', 'the edited "Root 7"', await noteTop(here, ids['Root 7']), editedTop);
  await here.keyboard.press('Escape');
  await idle(here);
  await pause(SETTLE_MS);
  const firstRoot = await here.evaluate(() => document.querySelector('#notes-container > .note').dataset.noteId);
  assert.equal(firstRoot, ids['Root 7'], 'moved while edited: "Root 7" should be at the top once editing ends');
  assertAt('moved while edited', '"Root 5" at the window\'s top', await noteTop(here, ids['Root 5']), windowTop);
}

// Case 8: deleting every note the view shows, while the other tab edits one of them, is refused as a
// whole with a message saying where.
async function bulkRefusedCase(here, there, ids) {
  assert.ok(await editThere(there, ids['Root 2']), 'the other tab should edit "Root 2"');
  await waitForMarker(here, ids['Root 2']);
  const answer = await here.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {noteCount} = await NotesAPI.countNotesToDeleteInView();
    const [outcome] = await Promise.allSettled([NotesAPI.deleteNotesInView(noteCount)]);
    return outcome.status === 'rejected' ? outcome.reason.message : 'deleted';
  });
  assert.match(answer, /being edited in another tab/, `bulk: the refusal should say where, got "${answer}"`);
  await here.reload();
  await here.waitForSelector('[data-app-ready="true"]');
  await idle(here);
  const shown = await here.evaluate(() => document.querySelectorAll('#notes-container > .note[data-note-id]').length);
  assert.equal(shown, ROOT_COUNT, 'bulk: no note should be deleted');
  await stopEditingThere(there);
  await waitForNoMarker(here, ids['Root 2']);
}

// Case 10: a search typed in the other tab is locked here: the box follows it and cannot be typed
// in; once the other tab leaves its box, it can. The other tab types in the background: bringing
// this one forward would take the focus from its box, which ends the lock.
async function searchLockCase(here, there) {
  await there.evaluate(() => {
    const input = document.getElementById('search-input');
    input.focus();
    input.value = 'Root';
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await here.waitForFunction(() => {
    const input = document.getElementById('search-input');
    return input.readOnly && input.value === 'Root' && input.title === 'Being typed in another tab';
  }, {timeout: SHOWS_WITHIN_MS});
  // Left there, or (Firefox: a background tab's box never had the focus to lose) 5 s after the
  // last keystroke there: the lock ends either way, seen here at its next check.
  await there.evaluate(() => document.getElementById('search-input').blur());
  await here.waitForFunction(() => !document.getElementById('search-input').readOnly, {timeout: SEARCH_LOCK_ENDS_WITHIN_MS});
}

export async function checkEditLocks(here, browser) {
  await here.bringToFront();
  const there = await browser.newPage();
  const errors = [];
  there.on('pageerror', error => errors.push(error.message));
  await installRequestMonitor(there);
  await there.goto(here.url());
  await there.waitForSelector('[data-app-ready="true"]');
  await here.bringToFront();
  const ids = await createFixture(here);
  await runThenCleanUp('edit locks', async () => {
    await here.reload();
    await here.waitForSelector('[data-app-ready="true"]');
    await idle(here);
    await there.reload();
    await there.waitForSelector('[data-app-ready="true"]');
    await here.bringToFront();
    await markerCase(here, there, ids);
    await clickTakesOverCase(here, there, ids);
    await arrowTakesOverCase(here, there, ids);
    await neighbourMovedAboveEditedCase(here, there, ids);
    await movedWhileEditedCase(here, there, ids);
    await bulkRefusedCase(here, there, ids);
    await searchLockCase(here, there);
    assert.deepEqual(errors, [], 'the other tab should raise no errors');
  }, async () => {
    await stopEditingThere(there);
    await there.close();
    await deleteFixture(here, ids);
  });
}
