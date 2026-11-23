import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Dragging notes inside a floating window (agreed with the maintainer 2026-11-22, cases 1 to 6;
// docs/ui/state-handling.md, "Dragging in a floating window"). The window is on "Trip plan",
// with "Tickets" ("Train" under it), "Packing" and a run of "Item" notes under it.
// 1. Reorder: "Packing" dragged above "Tickets" lands there, in the window and the list, with
//    the list's ghost and landing line; the page behind does not move.
// 2. Indent and outdent: dragged right, "Tickets" goes under "Packing"; dragged left, "Train"
//    comes out beside "Tickets".
// 3. Never out of the window: "Trip plan" (the window's own note) does not drag; a note right
//    under it does not drag left.
// 4. A press and release without moving still edits the note.
// 5. A drag near the window's bottom edge scrolls the window, not the page.
// 6. (Not included: dragging between the list and a window.)

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
const ITEMS = 25;
// How far a sideways drag goes, in pixels: past the 20 the drag needs to count.
const SIDEWAYS_PX = 70;
const DRAG_STEPS = 8;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function makeNotes(page) {
  return page.evaluate(async (items) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async (parentId, text) => {
      const note = await NotesAPI.createChild(parentId, '');
      await NotesAPI.saveNote(note.id, `<div>${text}</div>`, '');
      return note.id;
    };
    const trip = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(trip.id, '<div>Trip plan</div>', '');
    // createChild puts a note first under its parent: made last to first.
    const itemIds = [];
    for (let index = items; index >= 1; index--) itemIds.unshift(await make(trip.id, `Item ${index}`));
    const packing = await make(trip.id, 'Packing');
    const tickets = await make(trip.id, 'Tickets');
    const train = await make(tickets, 'Train');
    return {trip: trip.id, tickets, train, packing, firstItem: itemIds[0]};
  }, ITEMS);
}

async function openWindow(page, noteId) {
  await page.evaluate(async id => {
    const {openFloatingNote} = await import('/static/js/modules/mode-manager/services/floating-note-service.js');
    await openFloatingNote(id);
  }, noteId);
  await idle(page);
}

// The window's notes as "text<parent text", in order: its shape.
function windowShape(page) {
  return page.evaluate(() => {
    const root = document.querySelector('.floating-note-window').shadowRoot;
    const text = note => note.querySelector(':scope > .note-content').textContent;
    return [...root.querySelectorAll('.floating-note-tree .note[data-note-id]')].map((note) => {
      const parent = note.parentElement.closest('.note');
      if (parent === null) return text(note);
      return `${text(note)}<${text(parent)}`;
    });
  });
}

function listShape(page, tripId) {
  return page.evaluate((id) => {
    const text = note => note.querySelector(':scope > .note-content').textContent;
    const trip = document.querySelector(`#notes-container .note[data-note-id="${id}"]`);
    return [...trip.querySelectorAll('.note[data-note-id]')].map(note => `${text(note)}<${text(note.parentElement.closest('.note'))}`);
  }, tripId);
}

// The middle of a note's own line in the window's drawing.
function noteLine(page, noteId) {
  return page.evaluate((id) => {
    const root = document.querySelector('.floating-note-window').shadowRoot;
    const box = root.querySelector(`.note[data-note-id="${id}"] > .note-content`).getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2, top: box.top, bottom: box.bottom};
  }, noteId);
}

async function waitForShape(page, expected) {
  await page.waitForFunction((wanted) => {
    const root = document.querySelector('.floating-note-window').shadowRoot;
    const text = note => note.querySelector(':scope > .note-content').textContent;
    const shape = [...root.querySelectorAll('.floating-note-tree .note[data-note-id]')].map((note) => {
      const parent = note.parentElement.closest('.note');
      if (parent === null) return text(note);
      return `${text(note)}<${text(parent)}`;
    });
    return JSON.stringify(shape.slice(0, wanted.length)) === JSON.stringify(wanted);
  }, {}, expected);
}

// Press on a note's line, move by (dx, dy), and say what shows while the button is down.
async function dragNote(page, noteId, dx, dy) {
  const from = await noteLine(page, noteId);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + dx, from.y + dy, {steps: DRAG_STEPS});
  const during = await page.evaluate(() => {
    const shown = selector => [...document.querySelectorAll(selector)].some(element => getComputedStyle(element).display !== 'none' && element.getBoundingClientRect().width > 0);
    let ghostTop = null;
    const ghost = document.querySelector('.note-drag-ghost');
    if (ghost !== null && shown('.note-drag-ghost')) ghostTop = Math.round(ghost.getBoundingClientRect().top);
    return {ghost: shown('.note-drag-ghost'), line: shown('.note-drop-line'), dragging: document.body.classList.contains('note-drag-active'), ghostTop};
  });
  await page.mouse.up();
  await idle(page);
  return during;
}

async function isEditing(page) {
  return page.evaluate(async () => (await import('/static/js/modules/mode-manager/mode-context.js')).ModeContextInstance.isEditing);
}

// The window's own notes before the "Item" run.
const START = ['Trip plan', 'Tickets<Trip plan', 'Train<Tickets', 'Packing<Trip plan'];

async function reorderLandsInTheWindowAndTheList(page, ids) {
  assert.deepEqual((await windowShape(page)).slice(0, START.length), START);
  const pageTop = await page.evaluate(() => window.scrollY);
  const tickets = await noteLine(page, ids.tickets);
  const packing = await noteLine(page, ids.packing);
  // The ghost goes no further than the note can land: at the top of "Tickets", the first note under "Trip plan".
  const ticketsNoteTop = await page.evaluate(id => Math.round(document.querySelector('.floating-note-window').shadowRoot
    .querySelector(`.note[data-note-id="${id}"]`).getBoundingClientRect().top), ids.tickets);
  const during = await dragNote(page, ids.packing, 0, tickets.top - packing.y);
  assert.deepEqual(during, {ghost: true, line: true, dragging: true, ghostTop: ticketsNoteTop}, 'the ghost and the landing line show while dragging');
  const moved = ['Trip plan', 'Packing<Trip plan', 'Tickets<Trip plan', 'Train<Tickets'];
  await waitForShape(page, moved);
  assert.deepEqual((await listShape(page, ids.trip)).slice(0, moved.length - 1), moved.slice(1), 'the list shows the same order');
  assert.equal(await isEditing(page), false, 'the release edits nothing');
  assert.equal(await page.evaluate(() => window.scrollY), pageTop, 'the page behind does not move');
}

async function sidewaysDragsIndentAndOutdent(page, ids) {
  await dragNote(page, ids.tickets, SIDEWAYS_PX, 0);
  await waitForShape(page, ['Trip plan', 'Packing<Trip plan', 'Tickets<Packing', 'Train<Tickets']);
  await dragNote(page, ids.train, -SIDEWAYS_PX, 0);
  const out = ['Trip plan', 'Packing<Trip plan', 'Tickets<Packing', 'Train<Packing'];
  await waitForShape(page, out);
  assert.deepEqual((await listShape(page, ids.trip)).slice(0, out.length - 1), out.slice(1), 'the list shows the same');
}

async function nothingIsDraggedOutOfTheWindow(page, ids) {
  const before = await windowShape(page);
  // The window's own note: no drag starts.
  const own = await dragNote(page, ids.trip, 0, SIDEWAYS_PX);
  assert.deepEqual(own, {ghost: false, line: false, dragging: false, ghostTop: null}, 'the window\'s own note does not drag');
  // A note right under it, dragged left: a drag, with nowhere to land.
  const left = await dragNote(page, ids.packing, -SIDEWAYS_PX, 0);
  assert.equal(left.line, false, 'no landing line out of the window');
  assert.deepEqual(await windowShape(page), before, 'nothing moved');
  assert.equal(await isEditing(page), false);
}

async function aDragNearTheBottomEdgeScrollsTheWindow(page, ids) {
  const read = () => page.evaluate(() => {
    const area = document.querySelector('.floating-note-window').shadowRoot.querySelector('.floating-note-scroll');
    const box = area.getBoundingClientRect();
    return {scrolled: area.scrollTop, bottom: box.bottom, top: box.top, pageTop: window.scrollY};
  });
  const before = await read();
  assert.equal(before.scrolled, 0);
  const from = await noteLine(page, ids.firstItem);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  // To just inside the bottom edge, then on the spot: each move of the pointer scrolls a step.
  const nearBottom = before.bottom - 6;
  await page.mouse.move(from.x, nearBottom, {steps: DRAG_STEPS});
  for (let nudge = 0; nudge < DRAG_STEPS; nudge++) {
    await page.mouse.move(from.x + (nudge % 2), nearBottom);
  }
  const during = await read();
  await page.mouse.move(from.x, from.y);
  await page.mouse.up();
  await idle(page);
  assert.ok(during.scrolled > 0, `the window scrolled: ${JSON.stringify(during)}`);
  assert.equal(during.pageTop, before.pageTop, 'the page behind does not move');
  // Back to the window's top, where the next case's notes are.
  await page.evaluate(() => {
    document.querySelector('.floating-note-window').shadowRoot.querySelector('.floating-note-scroll').scrollTop = 0;
  });
  await idle(page);
}

async function aPressWithoutMovingEditsTheNote(page, ids) {
  const line = await noteLine(page, ids.packing);
  await page.mouse.click(line.x, line.y);
  await idle(page);
  const state = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const surface = await import('/static/js/modules/editing-surface.js');
    return {noteId: mode.currentNoteId, isInWindow: surface.isEditingInWindow()};
  });
  assert.deepEqual(state, {noteId: ids.packing, isInWindow: true}, 'a click still edits the note in the window');
  await page.keyboard.press('Escape');
  await idle(page);
}

export async function checkFloatingDrag(page) {
  await page.setViewport(WINDOW);
  const ids = await makeNotes(page);
  await runThenCleanUp('floating drag', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await openWindow(page, ids.trip);
    await reorderLandsInTheWindowAndTheList(page, ids);
    await sidewaysDragsIndentAndOutdent(page, ids);
    await nothingIsDraggedOutOfTheWindow(page, ids);
    await aDragNearTheBottomEdgeScrollsTheWindow(page, ids);
    await aPressWithoutMovingEditsTheNote(page, ids);
  }, async () => {
    await page.evaluate(async (tripId) => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      const {actionDeselectNote} = await import('/static/js/modules/mode-manager/actions/selection-actions.js');
      const {closeAllFloatingNotes} = await import('/static/js/modules/mode-manager/services/floating-note-service.js');
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      if (mode.isEditing) await actionDeselectNote();
      closeAllFloatingNotes();
      await NotesAPI.deleteNote(tripId);
    }, ids.trip);
    await idle(page);
  });
}
