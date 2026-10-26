import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// An action's refresh while another view request is in flight waits its turn, then runs
// (docs/ui/state-handling.md, "Refreshes in flight"; 2026-10-26). It used to be dropped:
// switching notes then crashed ("Redundant state change: currentContent is already null"),
// moving a note left the edited note without content, and a deleted note stayed on screen.
// Each case holds the answer to a background view request in the page (as the link-title and
// icon refreshes leave one in flight), does the action, then lets the held answer through.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
// Long enough for an action that does not wait to reach its refresh and give up.
const ACTION_REACHES_REFRESH_MS = 600;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function seedNotes(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {};
    for (const name of ['first', 'second', 'third', 'fourth']) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<div>Refresh in flight ${name}</div>`, '');
      ids[name] = note.id;
    }
    return ids;
  });
}

// Starts a background view request and holds its answer until releaseHeldView().
async function holdBackgroundView(page) {
  await page.evaluate(async () => {
    const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    const pageFetch = window.fetch;
    let isHeld = false;
    let release = null;
    const held = new Promise(resolve => { release = resolve; });
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.endsWith('/notes/view') && !isHeld) {
        isHeld = true;
        const answer = await pageFetch(input, init);
        await held;
        return answer;
      }
      return pageFetch(input, init);
    };
    window.__releaseHeldView = () => {
      window.fetch = pageFetch;
      release();
    };
    window.__backgroundView = actionRefreshAndMaybeSelect({context: 'background view in flight', animateNoteChanges: false});
    while (!isHeld) await new Promise(resolve => setTimeout(resolve, 10));
  });
}

async function releaseHeldView(page) {
  await pause(ACTION_REACHES_REFRESH_MS);
  await page.evaluate(async () => {
    window.__releaseHeldView();
    await window.__backgroundView;
  });
  await pause(SETTLE_MS);
  await idle(page);
}

function appState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {
      fatal: document.getElementById('fatal-error-overlay') !== null,
      editing: mode.isEditing,
      noteId: mode.currentNoteId,
      hasContent: mode.currentContent !== null,
      order: [...document.querySelectorAll('#notes-container .note[data-note-id]')]
        .map(note => note.dataset.noteId),
    };
  });
}

async function editNote(page, noteId) {
  await page.click(`.note[data-note-id="${noteId}"] > .note-content`);
  await page.waitForSelector(`.note.editing[data-note-id="${noteId}"]`);
  await pause(SETTLE_MS);
  await idle(page);
}

async function leaveEditing(page) {
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
}

// The reported crash: clicking another note while editing.
async function switchCase(page, ids) {
  await editNote(page, ids.first);
  await holdBackgroundView(page);
  await page.click(`.note[data-note-id="${ids.second}"] > .note-content`);
  await releaseHeldView(page);
  const state = await appState(page);
  assert.equal(state.fatal, false, 'switching notes during a background refresh does not crash');
  assert.deepEqual([state.editing, state.noteId, state.hasContent], [true, ids.second, true],
    'the clicked note is edited, with its content');
  await leaveEditing(page);
}

// Moving the edited note: its refreshed content comes back.
async function moveCase(page, ids) {
  await editNote(page, ids.third);
  const before = (await appState(page)).order;
  await holdBackgroundView(page);
  await page.evaluate(async id => {
    const {moveNoteUp} = await import('/static/js/modules/mode-manager/actions/note-actions.js');
    window.__moving = moveNoteUp(id);
  }, ids.third);
  await releaseHeldView(page);
  await page.evaluate(async () => { await window.__moving; });
  await idle(page);
  const state = await appState(page);
  assert.equal(state.fatal, false, 'moving a note during a background refresh does not crash');
  assert.deepEqual([state.editing, state.noteId, state.hasContent], [true, ids.third, true],
    'the moved note is still edited, with its content');
  assert(state.order.indexOf(ids.third) < before.indexOf(ids.third), 'the list shows the note moved up');
  await leaveEditing(page);
}

// A note deleted outside edit mode leaves the list, though a view was in flight.
async function deleteCase(page, ids) {
  await holdBackgroundView(page);
  await page.evaluate(async id => {
    const {deleteNoteOutsideEdit} = await import('/static/js/modules/mode-manager/actions/note-actions.js');
    window.__deleting = deleteNoteOutsideEdit(id);
  }, ids.fourth);
  await releaseHeldView(page);
  await page.evaluate(async () => { await window.__deleting; });
  await idle(page);
  const state = await appState(page);
  assert.equal(state.fatal, false, 'deleting a note during a background refresh does not crash');
  assert.equal(state.order.includes(ids.fourth), false, 'the deleted note leaves the list');
}

export async function checkRefreshInFlight(page) {
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('refresh in flight', async () => {
    const failures = [];
    for (const [label, run] of [['switch notes', switchCase], ['move up', moveCase], ['delete', deleteCase]]) {
      try {
        await run(page, ids);
      } catch (error) {
        if (!(error instanceof assert.AssertionError)) throw error;
        failures.push(`${label}: ${error.message}`);
      }
      if ((await appState(page)).fatal) break;
    }
    assert.deepEqual(failures, []);
  }, async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      // The delete case removes the fourth note itself, unless it failed.
      for (const id of Object.values(ids)) {
        if (document.querySelector(`.note[data-note-id="${id}"]`) !== null) await NotesAPI.deleteNote(id);
      }
    }, ids);
  });
}
