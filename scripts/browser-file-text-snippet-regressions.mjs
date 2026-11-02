import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The snippet under a PDF's card when a quoted phrase of the search is in the PDF's text
// (docs/ui/references.md, "File text snippets"; the cases agreed 2026-11-01, interaction
// principles 1, 2, 4 and 5):
//   1. a matched card shows a line of the PDF's text with the phrase marked; a note that is
//      only a card gets no fold arrow from it
//   2. clicking the snippet edits the note: the card turns into its line, the snippet goes,
//      the note's top stays where it was
//   3. Escape brings the card and its snippet back exactly where they were; nothing scrolls
//   4. folding a note hides the snippet and moves nothing: the note's top and the card stay
//      exactly where they were, its arrow stays; unfolding brings the snippet back with the card
//      where it was. (Folding used to move a first-line card 9 px up, with or without a snippet:
//      fixed 2026-11-01, scripts/browser-folded-file-regressions.mjs.)

const WINDOW = {width: 1100, height: 900};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const FIXTURE_TAG = 'filetextsnippetfixture';
const PHRASE = 'rent is due';
const HIGHLIGHT_NAME = 'metalist-search';
// A PDF's text is read in the background after it arrives: the search is run again until it is.
const EXTRACTION_ATTEMPTS = 40;
const EXTRACTION_RETRY_MS = 250;
const LEASE_PAGES = [
  'Lease agreement between the landlord and Sam Rivera for the flat on Harbor Road.',
  'Rent is due on the first of each month, paid to the landlord account.',
  'The deposit is returned within thirty days of the lease ending.',
];

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

// The search runs as it is typed; Enter on a search already run would add a note.
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
    const upload = async (text, name) => (await FilesAPI.uploadFile(new File([text], name, {type: 'application/pdf'}))).file_id;
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tag);
      return note.id;
    };
    const cardFile = await upload(lease, 'Lease.pdf');
    const foldFile = await upload(lease, 'Lease copy.pdf');
    // A note that is only a card, and one with lines under its card (it folds).
    const cardNote = await make(`<div>![[${cardFile}]]</div>`);
    const foldNote = await make(`<div>![[${foldFile}]]</div><div>first line under the card</div><div>second line under the card</div>`);
    await NotesAPI.setCollapsedBulk([cardNote, foldNote], false);
    return {cardNote, foldNote};
  }, {lease: pdf(LEASE_PAGES), tag: FIXTURE_TAG});
}

// Where a note and its card are, and what it shows.
function noteState(page, noteId) {
  return page.evaluate((noteId, highlightName) => {
    const note = document.querySelector(`.note[data-note-id="${noteId}"]`);
    const card = note.querySelector('.note-file-reference-link');
    const snippet = note.querySelector('.note-file-text-snippet');
    const marks = CSS.highlights.has(highlightName)
      ? [...CSS.highlights.get(highlightName)].filter(range => snippet !== null && snippet.contains(range.startContainer)).map(range => range.toString())
      : [];
    return {
      noteTop: note.getBoundingClientRect().top,
      cardTop: card === null ? null : card.getBoundingClientRect().top,
      snippet: snippet === null ? '' : snippet.textContent,
      snippetInCard: snippet !== null && card !== null && card.contains(snippet),
      marks,
      editing: note.classList.contains('editing'),
      canCollapse: note.dataset.canCollapse,
      scrollY: window.scrollY,
    };
  }, noteId, HIGHLIGHT_NAME);
}

// The search, once the PDFs' text has been read in the background.
async function searchOnceExtracted(page, ids) {
  for (let attempt = 0; attempt < EXTRACTION_ATTEMPTS; attempt += 1) {
    await search(page, `${FIXTURE_TAG} "${PHRASE}"`);
    const states = [await noteState(page, ids.cardNote), await noteState(page, ids.foldNote)];
    if (states.every(state => state.snippet !== '')) return;
    await search(page, '');
    await new Promise(resolve => setTimeout(resolve, EXTRACTION_RETRY_MS));
  }
  assert.fail('the PDFs\' text was never searchable');
}

async function snippetShows(page, ids) {
  for (const noteId of [ids.cardNote, ids.foldNote]) {
    const state = await noteState(page, noteId);
    assert.match(state.snippet, /Rent is due on the first of each month/, 'a line of the PDF\'s text');
    assert.equal(state.snippetInCard, true, 'inside the card, so a click on it does what a click on the card does');
    assert.deepEqual(state.marks, ['Rent is due'], 'the phrase marked as search highlights are');
  }
  assert.equal((await noteState(page, ids.cardNote)).canCollapse, 'false', 'a one-card note gets no fold arrow from its snippet');
  assert.equal((await noteState(page, ids.foldNote)).canCollapse, 'true', 'a note with lines under its card still folds');
}

async function editThenEscape(page, ids) {
  const before = await noteState(page, ids.foldNote);
  const box = await (await page.$(`.note[data-note-id="${ids.foldNote}"] .note-file-text-snippet`)).boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await idle(page);
  const editing = await noteState(page, ids.foldNote);
  assert.equal(editing.editing, true, '2: clicking the snippet edits the note');
  assert.equal(editing.snippet, '', '2: the card turns into its line and the snippet goes');
  assert.equal(editing.noteTop, before.noteTop, '2: the note\'s top stays where it was');
  assert.equal(editing.scrollY, before.scrollY, '2: nothing scrolls');

  await page.keyboard.press('Escape');
  await idle(page);
  const after = await noteState(page, ids.foldNote);
  assert.equal(after.editing, false, '3: Escape leaves editing');
  assert.equal(after.snippet, before.snippet, '3: the snippet comes back');
  assert.equal(after.cardTop, before.cardTop, '3: the card is exactly where it was');
  assert.equal(after.noteTop, before.noteTop, '3: the note\'s top too');
  assert.equal(after.scrollY, before.scrollY, '3: nothing scrolls');
}

async function foldThenUnfold(page, ids) {
  const toggle = `.note[data-note-id="${ids.foldNote}"] > .note-collapse-toggle`;
  const before = await noteState(page, ids.foldNote);
  assert.notEqual(before.snippet, '', '4: the snippet shows before folding');
  await page.click(toggle);
  await idle(page);
  const folded = await noteState(page, ids.foldNote);
  assert.equal(folded.snippet, '', '4: a folded note shows no snippet');
  assert.equal(folded.noteTop, before.noteTop, '4: the note\'s top stays where it was');
  assert.equal(folded.cardTop, before.cardTop, '4: the card on its first line stays exactly where it was');
  assert.equal(folded.canCollapse, 'true', '4: its arrow stays, to open it again');

  await page.click(toggle);
  await idle(page);
  const unfolded = await noteState(page, ids.foldNote);
  assert.equal(unfolded.snippet, before.snippet, '4: unfolding brings the snippet back');
  assert.equal(unfolded.cardTop, before.cardTop, '4: the card where it was');
  assert.equal(unfolded.scrollY, before.scrollY, '4: nothing scrolls');
}

export async function checkFileTextSnippets(page) {
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
  await runThenCleanUp('file text snippets', async () => {
    await searchOnceExtracted(page, ids);
    await attempt('1 a matched card shows the snippet', () => snippetShows(page, ids));
    await attempt('2-3 edit, then Escape', () => editThenEscape(page, ids));
    await attempt('4 fold, then unfold', () => foldThenUnfold(page, ids));
    assert.deepEqual(failures, []);
  }, async () => {
    await search(page, '');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.cardNote, ids.foldNote]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
