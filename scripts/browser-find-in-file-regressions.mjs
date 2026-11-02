import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Find (Cmd+F) inside files (docs/ui/find.md, "Inside files"; the cases agreed 2026-11-01):
//   1. typing counts a file whose text holds the words as one stop of its note, however often
//      they occur in it; nothing on the page moves while typing
//   2. stopping on a file: a snippet of its text shows under its card, the words marked as the
//      current match; the card stays where it was (only what is below moves down)
//   3. a file in a folded note: the note opens for this view only, its snippet showing
//   4. moving on: the snippet goes; closing find: the snippet goes, what find opened folds back
//      with its first line where it was
//   5. a card already showing the search's snippet shows find's while find stops on it, and
//      the search's again after
//   6. a note's own text counts as before; text inside a snippet is no note's text
//   7. typing on while find stops on a file: its snippet stays on the page every frame, only
//      its text changing (it had gone and come back on every keystroke, 2026-11-01)
//   8. the server never counts more in a note than the page shows: a picture's card said
//      "Loading image preview..." to the server, gone from the page once drawn, so typing "lo"
//      stopped on words that were not there and find failed (2026-11-02)

const WINDOW = {width: 1100, height: 1400};
const REQUESTS_QUIET_MS = 300;
const TYPING_SETTLE_MS = 500;
const SETTLE_MS = 400;
const FIXTURE_TAG = 'findinfilefixture';
const LEASE_PAGES = [
  'Lease agreement between the landlord and Sam Rivera for the flat on Harbor Road.',
  'Rent is due on the first of each month. Rent is due even in holidays. Rent is due always.',
  'The deposit is returned within thirty days of the lease ending.',
];
const EXTRACTION_ATTEMPTS = 40;
const EXTRACTION_RETRY_MS = 250;

// Positions are multiples of a layout unit: Firefox lays out in 1/60 px, Chrome in 1/64 px.
const LAYOUT_UNITS_PER_PX = 60;
const layoutUnits = px => Math.round(px * LAYOUT_UNITS_PER_PX);

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

// A small PDF whose pages hold these lines (Helvetica), with a correct cross-reference table.
function pdf(pages) {
  const fontNumber = 3;
  const firstPageNumber = 4;
  const objects = new Map([[1, '<< /Type /Catalog /Pages 2 0 R >>'], [fontNumber, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']]);
  const kids = [];
  pages.forEach((text, index) => {
    const pageNumber = firstPageNumber + index * 2;
    const stream = `BT /F1 12 Tf 20 700 Td (${text}) Tj ET`;
    objects.set(pageNumber, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${fontNumber} 0 R >> >> /Contents ${pageNumber + 1} 0 R >>`);
    objects.set(pageNumber + 1, `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    kids.push(`${pageNumber} 0 R`);
  });
  objects.set(2, `<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${pages.length} >>`);
  let out = '%PDF-1.4\n';
  const offsets = new Map();
  for (const number of [...objects.keys()].sort((a, b) => a - b)) {
    offsets.set(number, out.length);
    out += `${number} 0 obj\n${objects.get(number)}\nendobj\n`;
  }
  const xrefAt = out.length;
  const size = Math.max(...objects.keys()) + 1;
  out += `xref\n0 ${size}\n0000000000 65535 f \n`;
  for (let number = 1; number < size; number += 1) out += `${String(offsets.get(number)).padStart(10, '0')} 00000 n \n`;
  out += `trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`;
  return out;
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function search(page, text) {
  await page.focus('#search-input');
  await page.evaluate(() => document.getElementById('search-input').select());
  await page.keyboard.press('Backspace');
  if (text !== '') await page.keyboard.type(text);
  await page.waitForFunction(async expected => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.getExecutedSearchQuery() === expected;
  }, {}, text);
  await page.evaluate(() => document.getElementById('search-input').blur());
  await idle(page);
}

async function seedNotes(page) {
  return page.evaluate(async ({lease, tag}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const upload = async name => (await FilesAPI.uploadFile(new File([lease], name, {type: 'application/pdf'}))).file_id;
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tag);
      return note.id;
    };
    const cardFile = await upload('Lease.pdf');
    const foldedFile = await upload('Lease folded.pdf');
    // createNote puts each note at the top: made bottom-up, they read top-down.
    const folded = await make(`<div>Folded holder</div><div>a second line</div><div>![[${foldedFile}]]</div>`);
    const card = await make(`<div>![[${cardFile}]]</div><div>after the card</div>`);
    const text = await make('<div>Own text: rent is due today.</div>');
    const canvas = document.createElement('canvas');
    canvas.width = 120;
    canvas.height = 60;
    canvas.getContext('2d').fillRect(0, 0, canvas.width, canvas.height);
    const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    const pictureFile = (await FilesAPI.uploadFile(new File([png], 'Photo.png', {type: 'image/png'}))).file_id;
    const picture = await make(`<div>![[${pictureFile}]]</div><div>a picture caption, the loading dock</div>`);
    await NotesAPI.setCollapsedBulk([text, card, picture], false);
    await NotesAPI.setCollapsedBulk([folded], true);
    return {text, card, folded, picture};
  }, {lease: pdf(LEASE_PAGES), tag: FIXTURE_TAG});
}

async function waitUntilSearchable(page) {
  for (let attempt = 0; attempt < EXTRACTION_ATTEMPTS; attempt += 1) {
    await search(page, `${FIXTURE_TAG} "thirty days"`);
    const shown = await page.$$eval('.note-file-text-snippet', snippets => snippets.length);
    if (shown >= 1) return;
    await search(page, '');
    await pause(EXTRACTION_RETRY_MS);
  }
  assert.fail('the PDFs\' text was never searchable');
}

async function openFind(page) {
  await page.keyboard.down('Control');
  await page.keyboard.press('f');
  await page.keyboard.up('Control');
  await page.waitForSelector('#find-in-list-bar:not([hidden])');
}

async function typeFind(page, text) {
  await clickAndSelectAll(page, '#find-in-list-input');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(text);
  await pause(TYPING_SETTLE_MS);
  await idle(page);
  await pause(SETTLE_MS);
}

async function pressNext(page) {
  await page.keyboard.press('Enter');
  await pause(SETTLE_MS);
  await idle(page);
  await pause(SETTLE_MS);
}

function state(page, ids) {
  return page.evaluate(ids => {
    const noteOf = id => document.querySelector(`.note[data-note-id="${id}"]`);
    const describe = id => {
      const note = noteOf(id);
      // Left out by the search.
      if (note === null) return null;
      const card = note.querySelector('.note-file-reference-link');
      const findSnippet = note.querySelector('.note-find-snippet');
      const searchSnippet = note.querySelector('.note-file-text-snippet:not(.note-find-snippet)');
      return {
        top: note.getBoundingClientRect().top,
        cardTop: card === null ? null : card.getBoundingClientRect().top,
        cardBottom: card === null ? null : card.getBoundingClientRect().bottom,
        folded: note.classList.contains('collapsed'),
        findSnippet: findSnippet === null ? '' : findSnippet.textContent,
        searchSnippetShown: searchSnippet !== null && getComputedStyle(searchSnippet).display !== 'none',
      };
    };
    const current = CSS.highlights.get('metalist-find-current');
    let currentText = null;
    let currentInFindSnippet = false;
    if (current !== undefined && current.size > 0) {
      const range = [...current][0];
      currentText = range.toString();
      currentInFindSnippet = range.startContainer.parentElement.closest('.note-find-snippet') !== null;
    }
    const bar = document.getElementById('find-in-list-bar');
    return {
      count: bar === null || bar.hidden ? null : document.getElementById('find-in-list-count').textContent,
      currentText, currentInFindSnippet,
      text: describe(ids.text), card: describe(ids.card), folded: describe(ids.folded),
      scrollY: window.scrollY,
    };
  }, ids);
}

async function typingCountsFiles(page, ids) {
  const before = await state(page, ids);
  await openFind(page);
  await typeFind(page, 'rent is due');
  const typed = await state(page, ids);
  // The note's own text once; each file once, though "rent is due" is in it three times.
  assert.equal(typed.count, '1 of 3', '1: one stop for the note\'s text and one per file');
  assert.equal(typed.currentText, 'rent is due', '1: the first stop is the note\'s own text');
  assert.deepEqual([typed.card.top, typed.card.cardTop, typed.scrollY], [before.card.top, before.card.cardTop, before.scrollY],
    '1: typing moves nothing');
  assert.equal(typed.card.findSnippet, '', '1: no snippet until find stops on the file');
}

async function stopOnFile(page, ids) {
  const before = await state(page, ids);
  await pressNext(page);
  const onFile = await state(page, ids);
  assert.equal(onFile.count, '2 of 3', '2: the next stop is the file');
  assert.match(onFile.card.findSnippet, /Rent is due on the first of each month/, '2: its text shows under the card');
  assert.equal(onFile.currentInFindSnippet, true, '2: the words marked as the current match, in the snippet');
  assert.equal(onFile.currentText.toLowerCase(), 'rent is due');
  assert.equal(onFile.card.cardTop, before.card.cardTop, '2: the card stays where it was');
}

async function stopInFoldedNote(page, ids) {
  const before = await state(page, ids);
  await pressNext(page);
  const opened = await state(page, ids);
  assert.equal(opened.count, '3 of 3', '3: the folded note\'s file is the last stop');
  assert.equal(opened.folded.folded, false, '3: the folded note opens for this view');
  assert.match(opened.folded.findSnippet, /Rent is due/, '3: its file\'s snippet shows');
  assert.equal(opened.card.findSnippet, '', '4: moving on, the previous file\'s snippet goes');
  // Moving on, the previous card's snippet goes: the card stays, what is below moves up by it.
  assert.equal(opened.card.cardTop, before.card.cardTop, '4: the previous card stays where it was');
  // Compared in layout units, the browser's own steps (Firefox: 1/60 px): the two moves are
  // differences of measured positions, whose float rounding differs below one unit.
  assert.equal(layoutUnits(before.folded.top - opened.folded.top), layoutUnits(before.card.cardBottom - opened.card.cardBottom),
    '3: the folded note\'s first line moves up only by the snippet that went above it');
}

async function closingCleansUp(page, ids) {
  const opened = await state(page, ids);
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
  const closed = await state(page, ids);
  assert.equal(closed.count, null, '4: Escape closes find');
  assert.equal(closed.folded.findSnippet, '', '4: the snippet goes');
  assert.equal(closed.folded.folded, true, '4: what find opened folds back');
  assert.equal(closed.folded.top, opened.folded.top, '4: with its first line where it was');
}

async function searchSnippetGivesWay(page, ids) {
  await search(page, `${FIXTURE_TAG} "thirty days"`);
  const searched = await state(page, ids);
  assert.equal(searched.card.searchSnippetShown, true, '5: the search\'s snippet shows');
  await openFind(page);
  await typeFind(page, 'harbor road');
  // Both files hold it; find starts below its bar, at the folded note's: on to the card's.
  let onFile = await state(page, ids);
  if (onFile.card.findSnippet === '') {
    await pressNext(page);
    onFile = await state(page, ids);
  }
  assert.match(onFile.card.findSnippet, /Harbor Road/, '5: find\'s snippet shows while find stops on the file');
  assert.equal(onFile.card.searchSnippetShown, false, '5: in place of the search\'s');
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
  const closed = await state(page, ids);
  assert.equal(closed.card.findSnippet, '', '5: closing find, its snippet goes');
  assert.equal(closed.card.searchSnippetShown, true, '5: and the search\'s comes back');
}

async function snippetTextIsNoNoteText(page, ids) {
  // The search's snippet shows "thirty days": find counts it once, as the file, not as text.
  await openFind(page);
  await typeFind(page, 'thirty days');
  const found = await state(page, ids);
  assert.match(found.count, / of 2$/, '6: the shown snippet\'s words count only as their file (the card and the folded note\'s)');
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
}

// Typing one letter at a time, slower than find's pause, while find stops on a file: every
// frame from the snippet's first showing on, it is there.
async function snippetStaysWhileTyping(page, ids) {
  await search(page, FIXTURE_TAG);
  await openFind(page);
  await typeFind(page, 'thirty');
  await pressNext(page);
  const onFile = await state(page, ids);
  assert.ok(onFile.card.findSnippet !== '' || onFile.folded.findSnippet !== '', '7: find stops on a file');
  await page.evaluate(() => {
    window.__findSnippetMissingFrames = 0;
    window.__watchingFindSnippet = true;
    const watch = () => {
      if (!window.__watchingFindSnippet) return;
      if (document.querySelector('.note-find-snippet') === null) window.__findSnippetMissingFrames += 1;
      requestAnimationFrame(watch);
    };
    requestAnimationFrame(watch);
  });
  for (const letter of ' days') {
    await page.keyboard.type(letter);
    await pause(TYPING_SETTLE_MS);
  }
  await idle(page);
  const missing = await page.evaluate(() => {
    window.__watchingFindSnippet = false;
    return window.__findSnippetMissingFrames;
  });
  assert.equal(missing, 0, '7: the snippet never left the page while typing');
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
}

// What the server counts in each note shown open, against the marks the page can paint there.
function countsOverPage(page, text) {
  return page.evaluate(async text => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {ModeContextInstance: context} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {phraseRangesInNoteText} = await import('/static/js/modules/mode-manager/services/search-highlight-service.js');
    const answer = await NotesAPI.findInList({
      tabId: context.activeTabId, search: context.getExecutedSearchQuery(), isUntaggedView: context.isUntaggedView,
      text, fromRootIndex: 0, direction: 'forward',
    });
    const over = [];
    for (const match of answer.matches) {
      const note = document.querySelector(`.note[data-note-id="${match.noteId}"]`);
      if (note === null || note.classList.contains('collapsed')) continue;
      const content = [...note.children].find(child => child.classList.contains('note-content'));
      const shown = phraseRangesInNoteText(content, [text]).length;
      if (match.contentCount > shown) over.push(`${text}: server ${match.contentCount}, page ${shown}`);
    }
    return over;
  }, text);
}

async function loadingWordsAreNoText(page, ids) {
  await search(page, FIXTURE_TAG);
  await page.waitForSelector(`.note[data-note-id="${ids.picture}"] .note-file-image-preview:not([hidden])`);
  await idle(page);
  const over = [];
  for (const text of ['l', 'lo', 'loa', 'load', 'loadi', 'loading', 'i', 'im', 'image', 'p', 'pr', 'preview', 'a']) {
    over.push(...await countsOverPage(page, text));
  }
  assert.deepEqual(over, [], '8: no note counts words the page does not show');
  // Typing it into find: no failure, and the one stop is the caption's.
  await openFind(page);
  for (const letter of 'loading') {
    await page.keyboard.type(letter);
    await pause(TYPING_SETTLE_MS);
  }
  await idle(page);
  await pause(SETTLE_MS);
  const shown = await state(page, ids);
  assert.equal(shown.count, '1 of 1', '8: the caption\'s "loading" is the one stop');
  assert.equal(shown.currentText.toLowerCase(), 'loading', '8: marked in the caption');
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
}

export async function checkFindInFiles(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  await runThenCleanUp('find in files', async () => {
    await waitUntilSearchable(page);
    await search(page, FIXTURE_TAG);
    await attempt('1 typing counts files', () => typingCountsFiles(page, ids));
    await attempt('2 stopping on a file', () => stopOnFile(page, ids));
    await attempt('3 a file in a folded note', () => stopInFoldedNote(page, ids));
    await attempt('4 closing find', () => closingCleansUp(page, ids));
    await attempt('5 the search\'s snippet gives way', () => searchSnippetGivesWay(page, ids));
    await attempt('6 snippet text is no note text', () => snippetTextIsNoNoteText(page, ids));
    await attempt('7 the snippet stays while typing', () => snippetStaysWhileTyping(page, ids));
    await attempt('8 a card\'s loading words are no text', () => loadingWordsAreNoText(page, ids));
    assert.deepEqual(failures, []);
  }, async () => {
    await page.keyboard.press('Escape');
    await search(page, '');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of Object.values(ids)) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
