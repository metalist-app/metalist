import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A tag dialog's suggestion list never moves the dialog (docs/ui/interaction-principles.md: keep
// the user's point of attention still; the maintainer, 2026-11-11: "it slightly horizontally
// shifts the entire modal by a few pixels"). A list reaching past the window's bottom gave the
// dialog layer a scrollbar, and the dialog, centred in what was left, moved half its width. The
// list now ends inside the window and scrolls within itself, and dialogs keep a scrollbar's room
// on both sides. Cases agreed 2026-11-11; positions exact.

const FRAMES_TO_SETTLE = 3;
const REQUESTS_QUIET_MS = 300;
const TAG_PREFIX = 'listcheck';
// More tags than a list shows (MAX_TAG_SUGGESTIONS, 20): the longest list there is.
const TAG_COUNT = 24;
const TAG_DIGITS = 2;
// The dialog fits; a full list of suggestions does not.
const WINDOW = {width: 1280, height: 600};
// Shorter than the dialog itself: the dialog layer scrolls before any list opens.
const SHORT_WINDOW = {width: 1280, height: 160};
const PHONE_WINDOW = {width: 375, height: 700};
const DESKTOP_WINDOW = {width: 1280, height: 900};
// Typed after the prefix, it narrows the full list to the tags 20 to 23.
const NARROWING = '2';
const NARROWED_ROWS = 4;
const ESCAPES_AFTER_A_FAILURE = 3;

const DIALOGS = [
  {label: 'Add or Remove Tag', method: 'tagNotesInView', modal: '#tag-in-view-modal',
    input: '#tag-in-view-input', list: '#tag-in-view-suggestions'},
  {label: 'Prioritize Tag', method: 'prioritizeTagToFront', modal: '#prioritize-modal',
    input: '#prioritize-tag-input', list: '#prioritize-modal-suggestions'},
];

const tagNames = () => Array.from({length: TAG_COUNT}, (_, index) => `${TAG_PREFIX}${String(index).padStart(TAG_DIGITS, '0')}`);

async function settle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function createTaggedNotes(page) {
  return page.evaluate(async tags => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (const tag of tags) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>List check ${tag}</p>`, tag);
      ids.push(note.id);
    }
    return ids;
  }, tagNames());
}

// The dialog's box, its list's box, whether the dialog layer scrolls, and the highlighted row's box.
async function measure(page, dialog) {
  return page.evaluate(({modal, list}) => {
    const layer = document.querySelector(modal);
    const content = layer.querySelector('.modal-content').getBoundingClientRect();
    const listElement = document.querySelector(list);
    const listBox = listElement.getBoundingClientRect();
    const selected = listElement.querySelector('.is-selected');
    let selectedBox = null;
    if (selected !== null) {
      const box = selected.getBoundingClientRect();
      selectedBox = {top: box.top, bottom: box.bottom};
    }
    return {
      left: content.left, top: content.top, width: content.width,
      rows: listElement.querySelectorAll('button').length,
      isListShown: !listElement.hidden && listBox.height > 0,
      listTop: listBox.top, listBottom: listBox.bottom,
      windowHeight: window.innerHeight,
      layerScrolls: layer.scrollHeight > layer.clientHeight,
      gutter: getComputedStyle(layer).scrollbarGutter,
      selectedBox,
    };
  }, dialog);
}

async function open(page, dialog, size) {
  await page.setViewport(size);
  await settle(page);
  await page.evaluate(async method => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    void CommandPalette[method]();
  }, dialog.method);
  await page.waitForSelector(dialog.input, {visible: true});
  await settle(page);
  // Opened, the field has focus: the list shows once there is something to suggest.
  await page.evaluate(selector => document.querySelector(selector).blur(), dialog.input);
  await settle(page);
  return measure(page, dialog);
}

async function type(page, dialog, text) {
  await page.focus(dialog.input);
  await page.keyboard.type(text);
  await settle(page);
  return measure(page, dialog);
}

async function close(page) {
  await page.keyboard.press('Escape');
  await settle(page);
}

// Where scrollbars take room (a Mac with a mouse, Windows, Linux), a dialog layer that starts or
// stops scrolling would move the dialog; the test browser's scrollbars take none. So the dialog
// layer keeps their room on both sides whatever it holds, which this checks as well as the position.
function assertStill(before, after, label) {
  assert.equal(after.gutter, 'stable both-edges', `${label}: the dialog layer keeps a scrollbar's room on both sides`);
  assert.deepEqual({left: after.left, top: after.top, width: after.width}, {left: before.left, top: before.top, width: before.width},
    `${label}: the dialog must not move`);
}

function assertListInWindow(state, label) {
  assert.ok(state.isListShown, `${label}: the list shows`);
  assert.ok(state.listBottom <= state.windowHeight, `${label}: the list ends inside the window (${state.listBottom} > ${state.windowHeight})`);
}

async function checkShortList(page, dialog) {
  const label = `${dialog.label}, a short list`;
  const before = await open(page, dialog, WINDOW);
  const after = await type(page, dialog, `${TAG_PREFIX}${NARROWING}`);
  assert.equal(after.rows, NARROWED_ROWS, `${label}: a few suggestions`);
  assertStill(before, after, label);
  assertListInWindow(after, label);
  await close(page);
}

async function checkLongList(page, dialog, size, label) {
  const before = await open(page, dialog, size);
  assert.equal(before.layerScrolls, false, `${label}: the dialog fits the window`);
  const after = await type(page, dialog, TAG_PREFIX);
  assert.ok(after.rows > 1, `${label}: many suggestions`);
  assertStill(before, after, label);
  assertListInWindow(after, label);
  assert.equal(after.layerScrolls, false, `${label}: the list does not make the dialog layer scroll`);
  return before;
}

async function checkNarrowingTheList(page, dialog) {
  const label = `${dialog.label}, typing shortens a long list`;
  const before = await checkLongList(page, dialog, WINDOW, label);
  const after = await type(page, dialog, NARROWING);
  assert.equal(after.rows, NARROWED_ROWS, `${label}: a few suggestions left`);
  assertStill(before, after, label);
  await close(page);
}

async function checkShortWindow(page, dialog) {
  const label = `${dialog.label}, a window shorter than the dialog`;
  const before = await open(page, dialog, SHORT_WINDOW);
  assert.equal(before.layerScrolls, true, `${label}: the dialog layer scrolls already`);
  const after = await type(page, dialog, TAG_PREFIX);
  assertStill(before, after, label);
  await close(page);
}

async function checkArrowingDown(page, dialog) {
  const label = `${dialog.label}, arrowing past the last row in view`;
  const before = await checkLongList(page, dialog, WINDOW, label);
  let state = await measure(page, dialog);
  for (let row = 1; row < state.rows; row += 1) {
    await page.keyboard.press('ArrowDown');
  }
  await settle(page);
  state = await measure(page, dialog);
  assert.notEqual(state.selectedBox, null, `${label}: a row is highlighted`);
  assert.ok(state.selectedBox.top >= state.listTop && state.selectedBox.bottom <= state.listBottom,
    `${label}: the highlighted row is in view (${JSON.stringify(state.selectedBox)} in ${state.listTop}-${state.listBottom})`);
  assertStill(before, state, label);
  await close(page);
}

async function checkPhone(page, dialog) {
  const label = `${dialog.label}, at phone width`;
  await checkLongList(page, dialog, PHONE_WINDOW, label);
  await close(page);
}

export async function checkTagDialogLists(page) {
  const ids = await createTaggedNotes(page);
  await runThenCleanUp('tag dialog lists', async () => {
    for (const dialog of DIALOGS) {
      await checkShortList(page, dialog);
      const longLabel = `${dialog.label}, a long list`;
      await checkLongList(page, dialog, WINDOW, longLabel);
      await close(page);
      await checkNarrowingTheList(page, dialog);
      await checkShortWindow(page, dialog);
      await checkArrowingDown(page, dialog);
      await checkPhone(page, dialog);
    }
    console.log('PASS tag dialog lists: the suggestions never move the dialog and stay inside the window');
  }, async () => {
    for (let press = 0; press < ESCAPES_AFTER_A_FAILURE; press += 1) await page.keyboard.press('Escape');
    await page.setViewport(DESKTOP_WINDOW);
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
