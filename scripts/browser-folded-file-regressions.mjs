import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Folding a note whose first line holds a file moves nothing (interaction principle 1:
// docs/ui/interaction-principles.md; the maintainer chose 2026-11-01 to keep a file's grey box
// when folded, so folding only hides what is below). Before, folding drew the box flat and the
// file jumped up and left: a card 9 px up and 11 px left, an email 13 px up.
//   1. a file card on the first line (a PDF): the card's name and the fold arrow stay put
//   2. a link to a file inside the first line's text: the link's name stays put
//   3. a picture on the first line: its picture stays put
//   4. an email on the first line: its card stays put (folded, it shows one line of it)
//   5. text first, a card further down: the text stays put (it did before)
// Unfolding puts everything back where it was too.

// Tall enough for every case: folding a note never shortens the page under the window, which
// would make the browser scroll it up.
const WINDOW = {width: 1100, height: 1600};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const FIXTURE_TAG = 'foldedfilefixture';
const LOADED_WAIT_MS = 6000;

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
  return page.evaluate(async tag => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const upload = async (blob, name, type) => (await FilesAPI.uploadFile(new File([blob], name, {type}))).file_id;
    const canvas = document.createElement('canvas');
    canvas.width = 200;
    canvas.height = 120;
    const context = canvas.getContext('2d');
    context.fillStyle = 'teal';
    context.fillRect(0, 0, canvas.width, canvas.height);
    const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    const email = ['From: Ada <ada@example.org>', 'To: Grace <grace@example.org>', 'Subject: The plan',
      'Date: Thu, 29 Oct 2026 10:15:00 -0700', 'Content-Type: text/plain; charset=utf-8', '', 'Hello there', 'Line two'].join('\r\n');
    const pdf = await upload('%PDF-1.4 lease', 'Lease.pdf', 'application/pdf');
    const picture = await upload(png, 'Teal.png', 'image/png');
    const mail = await upload(email, 'plan.eml', 'message/rfc822');
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tag);
      return note.id;
    };
    const ids = {
      card: await make(`<div>![[${pdf}]]</div><div>a line under the card</div>`),
      link: await make(`<div>see [[${pdf}]] here</div><div>a line under the link</div>`),
      picture: await make(`<div>![[${picture}]]</div><div>a line under the picture</div>`),
      email: await make(`<div>![[${mail}]]</div><div>a line under the email</div>`),
      text: await make(`<div>text comes first</div><div>![[${pdf}]]</div>`),
    };
    await NotesAPI.setCollapsedBulk(Object.values(ids), false);
    return ids;
  }, FIXTURE_TAG);
}

// What each case watches on the first line.
const WATCHED = {
  card: '.note-file-reference-name',
  link: '.note-file-reference-name',
  picture: '.note-file-image-preview-frame',
  // Folded, an email shows one line of its card: the card is what stays put.
  email: '.note-file-email-card',
  text: '.note-content > div',
};

function place(page, noteId, watched) {
  return page.evaluate((noteId, watched) => {
    const note = document.querySelector(`.note[data-note-id="${noteId}"]`);
    const element = note.querySelector(watched);
    const arrow = note.querySelector(':scope > .note-collapse-toggle');
    const rect = element.getBoundingClientRect();
    return {top: rect.top, left: rect.left, arrowTop: arrow.getBoundingClientRect().top, folded: note.classList.contains('collapsed')};
  }, noteId, watched);
}

async function toggleFold(page, noteId) {
  await page.click(`.note[data-note-id="${noteId}"] > .note-collapse-toggle`);
  await idle(page);
}

async function foldMovesNothing(page, noteId, watched) {
  // In view first: clicking an arrow below the window would scroll the page to it.
  await page.evaluate(noteId => document.querySelector(`.note[data-note-id="${noteId}"]`).scrollIntoView({block: 'center'}), noteId);
  await idle(page);
  const open = await place(page, noteId, watched);
  await toggleFold(page, noteId);
  const folded = await place(page, noteId, watched);
  assert.equal(folded.folded, true, 'the note folds');
  assert.deepEqual({top: folded.top, left: folded.left, arrowTop: folded.arrowTop},
    {top: open.top, left: open.left, arrowTop: open.arrowTop}, 'folding moves neither the first line nor its arrow');
  await toggleFold(page, noteId);
  const reopened = await place(page, noteId, watched);
  assert.deepEqual({top: reopened.top, left: reopened.left, arrowTop: reopened.arrowTop},
    {top: open.top, left: open.left, arrowTop: open.arrowTop}, 'unfolding puts it back');
}

export async function checkFoldedFiles(page) {
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
  await runThenCleanUp('folded files', async () => {
    await search(page, FIXTURE_TAG);
    await page.waitForSelector(`.note[data-note-id="${ids.picture}"] .note-file-image-preview:not([hidden])`, {timeout: LOADED_WAIT_MS});
    await page.waitForSelector(`.note[data-note-id="${ids.email}"] .note-file-email-subject`, {timeout: LOADED_WAIT_MS});
    await idle(page);
    await attempt('1 a file card first', () => foldMovesNothing(page, ids.card, WATCHED.card));
    await attempt('2 a link to a file in the first line', () => foldMovesNothing(page, ids.link, WATCHED.link));
    await attempt('3 a picture first', () => foldMovesNothing(page, ids.picture, WATCHED.picture));
    await attempt('4 an email first', () => foldMovesNothing(page, ids.email, WATCHED.email));
    await attempt('5 text first', () => foldMovesNothing(page, ids.text, WATCHED.text));
    assert.deepEqual(failures, []);
  }, async () => {
    await search(page, '');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of Object.values(ids)) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
