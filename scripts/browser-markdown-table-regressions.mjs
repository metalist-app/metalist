import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Table columns at least as wide as their longest word (docs/ui/content-formatting.md,
// Tables; agreed 2026-10-27): a user's three-column `@markdown` table broke its short
// "State" header into "Stat" / "e", because cells inherited the note's break-anywhere
// wrapping. "State" stays on one line in a `@markdown` and a `@csv` table; a `<br>` breaks
// a cell's line; a table whose words can't all fit scrolls sideways inside its note, with
// no word broken and neither the note nor the page scrolling sideways.

const WIDE_WINDOW = {width: 1280, height: 800};
const NARROW_WINDOW = {width: 480, height: 800};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const LONG_TEXT = 'The motor is stopped and the controller waits for a start signal from the operator panel';
const MARKDOWN_ROWS = [
  '| State | What the hardware is doing | Entry action |',
  '|---|---|---|',
  `| Idle | ${LONG_TEXT} | ${LONG_TEXT} |`,
  '| Running | Turning | Open the valve<br>then start the motor |',
];
const CSV_ROWS = ['State,What the hardware is doing,Entry action', `Idle,${LONG_TEXT},${LONG_TEXT}`];
// Five long words side by side are wider than the narrow window's note.
const WIDE_ROWS = [
  '| Component | Configuration | Responsibility | Interoperability | Documentation |',
  '|---|---|---|---|---|',
  '| Authentication | Internationalization | Synchronization | Compartmentalization | Characterization |',
];

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await settle(page);
}

async function seedNotes(page) {
  const asLines = rows => rows.map(row => `<div>${row.replaceAll('&', '&amp;').replaceAll('<', '&lt;')}</div>`).join('');
  return page.evaluate(async notes => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {};
    for (const [name, html, tags] of notes) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      ids[name] = note.id;
    }
    return ids;
  }, [
    ['markdown', asLines(MARKDOWN_ROWS), '@markdown'],
    ['csv', asLines(CSV_ROWS), '@csv'],
    ['wide', asLines(WIDE_ROWS), '@markdown'],
  ]);
}

async function showAt(page, viewport) {
  await page.setViewport(viewport);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// How many lines each cell's text takes, by the distinct tops of its text's line boxes.
async function cellLines(page, noteId) {
  return page.evaluate(noteId => [...document.querySelectorAll(`[data-note-id="${noteId}"] > .note-content :is(th, td)`)]
    .map(cell => {
      const range = document.createRange();
      range.selectNodeContents(cell);
      return {text: cell.textContent.trim(), lines: new Set([...range.getClientRects()].map(rect => Math.round(rect.top))).size};
    }), noteId);
}

async function wideWindowCases(page, ids) {
  await showAt(page, WIDE_WINDOW);
  for (const name of ['markdown', 'csv']) {
    const state = (await cellLines(page, ids[name])).find(cell => cell.text === 'State');
    assert.equal(state.lines, 1, `${name}: "State" takes ${state.lines} lines`);
  }
  const running = await page.evaluate(noteId => {
    const cell = [...document.querySelectorAll(`[data-note-id="${noteId}"] td`)].find(td => td.textContent.startsWith('Open the valve'));
    return {breaks: cell.querySelectorAll('br').length, text: cell.innerText};
  }, ids.markdown);
  assert.deepEqual(running, {breaks: 1, text: 'Open the valve\nthen start the motor'});
}

async function narrowWindowCases(page, ids) {
  await showAt(page, NARROW_WINDOW);
  const wideCells = await cellLines(page, ids.wide);
  assert.deepEqual(wideCells.filter(cell => cell.lines !== 1), [], 'a word in the wide table broke');
  const scrolling = await page.evaluate(ids => {
    const scrolls = element => element.scrollWidth > element.clientWidth;
    const wrapOf = noteId => document.querySelector(`[data-note-id="${noteId}"] .meta-markdown-table-wrap`);
    const wideWrap = wrapOf(ids.wide);
    return {
      wideTable: scrolls(wideWrap),
      wideTableVertically: wideWrap.scrollHeight > wideWrap.clientHeight,
      wideNote: scrolls(wideWrap.closest('.note-content')),
      fittingTable: scrolls(wrapOf(ids.markdown)),
      page: scrolls(document.documentElement),
    };
  }, ids);
  assert.deepEqual(scrolling, {wideTable: true, wideTableVertically: false, wideNote: false, fittingTable: false, page: false});
  const state = (await cellLines(page, ids.markdown)).find(cell => cell.text === 'State');
  assert.equal(state.lines, 1, `narrow window: "State" takes ${state.lines} lines`);
}

async function tableCases(page, ids) {
  const failures = [];
  for (const run of [wideWindowCases, narrowWindowCases]) {
    // A suite runs every case and reports all their failures at once.
    try {
      await run(page, ids);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${run.name}: ${error.message}`);
    }
  }
  assert.deepEqual(failures, []);
}

export async function checkMarkdownTables(page) {
  await page.setViewport(WIDE_WINDOW);
  const ids = await seedNotes(page);
  await runThenCleanUp('markdown tables', () => tableCases(page, ids), async () => {
    await page.setViewport(WIDE_WINDOW);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of Object.values(ids)) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
