import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { runThenCleanUp } from './suite-outcome.mjs';

// The Illuminated skin (docs/ui/skins.md), chosen under Theme: it takes over the page and goes
// without a trace. Run in Chrome and Firefox: Firefox draws ::first-letter differently.

const REQUESTS_QUIET_MS = 300;
const NOTE_TEXTS = ['Apple', 'Birch', 'Cedar', 'Dahlia', 'Elm', 'Fern', 'Gorse', 'Holly', 'Ivy'];
const NOTES_PER_ORNAMENT = 4;
const INITIAL_SIZE_PX = 104;
const INITIAL_GAP_PX = 3;
const PIXEL_ROUNDING = 0.5;
const ORNAMENT_WIDTH_PX = 250;
const ORNAMENT_HEIGHT_PX = 78;
const ORNAMENT_GAP_PX = 10;
const ORNAMENTS_BY_NOTE = new Map([[3, 'ornament-01'], [7, 'ornament-05']]);
const SECOND_LETTER = 1;
const AFTER_THE_LETTER = 2;

async function applyPreference(page, key, value) {
  await page.evaluate(async ({key, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(key, value);
  }, {key, value});
}

async function createNotes(page) {
  return page.evaluate(async texts => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // A new top-level note goes first, so the last text is made first.
    for (const text of [...texts].reverse()) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<div>${text}</div>`, '');
      ids.push(note.id);
    }
    return ids;
  }, NOTE_TEXTS);
}

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// What the page shows for the skin; a note's letter offset is where its second letter starts.
function readPage(page) {
  return page.evaluate(({secondLetter, afterTheLetter}) => {
    const root = document.documentElement;
    const notes = [...document.querySelectorAll('#notes-container > .note')];
    const letterOffset = note => {
      const content = note.querySelector(':scope > .note-content');
      const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
      const range = document.createRange();
      range.setStart(text, secondLetter);
      range.setEnd(text, afterTheLetter);
      return range.getBoundingClientRect().left - content.getBoundingClientRect().left - parseFloat(getComputedStyle(content).paddingLeft);
    };
    return {
      skin: root.getAttribute('data-skin'),
      theme: root.getAttribute('data-theme'),
      pageCursor: getComputedStyle(root).cursor,
      buttonCursor: getComputedStyle(document.querySelector('button')).cursor,
      initials: notes.map(note => note.dataset.initial || null),
      texts: notes.map(note => note.querySelector(':scope > .note-content').textContent.trim()),
      letterOffsets: notes.map(letterOffset),
      ornaments: notes.map(note => {
        const after = getComputedStyle(note, '::after');
        return {
          image: after.backgroundImage,
          width: parseFloat(after.width),
          height: parseFloat(after.height),
          marginBottom: parseFloat(getComputedStyle(note).marginBottom),
        };
      }),
      hasErrorOverlay: document.getElementById('fatal-error-overlay') !== null,
    };
  }, {secondLetter: SECOND_LETTER, afterTheLetter: AFTER_THE_LETTER});
}

function assertNear(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) <= PIXEL_ROUNDING, `${label}: ${actual} is not ${expected}`);
}

function assertSkinned(shown) {
  assert.equal(shown.skin, 'illuminated');
  assert.equal(shown.theme, 'light');
  assert.equal(shown.hasErrorOverlay, false);
  assert.match(shown.pageCursor, /cursor-quill/);
  assert.match(shown.buttonCursor, /cursor-hand/);
  shown.texts.forEach((text, index) => {
    const isOpening = index % NOTES_PER_ORNAMENT === 0;
    assert.equal(shown.initials[index], isOpening ? text[0] : null, `the letter of ${text}`);
    if (isOpening) assertNear(shown.letterOffsets[index], INITIAL_SIZE_PX + INITIAL_GAP_PX, `after the big ${text[0]}`);
    else assert.ok(shown.letterOffsets[index] < INITIAL_SIZE_PX / NOTES_PER_ORNAMENT, `${text} has no big letter`);
  });
  shown.ornaments.forEach((ornament, index) => {
    const name = ORNAMENTS_BY_NOTE.get(index);
    if (name === undefined) {
      assert.equal(ornament.image, 'none', `no ornament after note ${index}`);
      return;
    }
    assert.match(ornament.image, new RegExp(`${name}\\.webp`));
    assert.equal(ornament.width, ORNAMENT_WIDTH_PX);
    assert.equal(ornament.height, ORNAMENT_HEIGHT_PX);
    assert.equal(ornament.marginBottom, ORNAMENT_HEIGHT_PX + ORNAMENT_GAP_PX + ORNAMENT_GAP_PX);
  });
}

function assertPlain(shown) {
  assert.equal(shown.skin, null);
  assert.equal(shown.theme, null);
  assert.equal(shown.hasErrorOverlay, false);
  assert.doesNotMatch(shown.pageCursor, /cursor-quill/);
  assert.doesNotMatch(shown.buttonCursor, /cursor-hand/);
  assert.deepEqual(shown.initials, shown.texts.map(() => null));
  assert.deepEqual(shown.ornaments.map(ornament => ornament.image), shown.texts.map(() => 'none'));
}

async function skinCases(page) {
  await reloadApp(page);
  const before = await readPage(page);
  assert.deepEqual(before.texts, NOTE_TEXTS);
  assertPlain(before);

  await applyPreference(page, 'pref.theme', 'illuminated');
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
  assertSkinned(await readPage(page));

  await reloadApp(page);
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
  assertSkinned(await readPage(page));

  await applyPreference(page, 'pref.theme', 'system');
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') === null);
  assertPlain(await readPage(page));
}

export async function checkSkin(page) {
  await applyPreference(page, 'pref.animated_transitions', false);
  const ids = await createNotes(page);
  await runThenCleanUp('skin', () => skinCases(page), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
    if (await page.evaluate(() => document.documentElement.getAttribute('data-skin') !== null)) await applyPreference(page, 'pref.theme', 'system');
    await applyPreference(page, 'pref.animated_transitions', true);
  });
}
