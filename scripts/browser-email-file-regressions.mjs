import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Email files (.eml) as cards (docs/ui/references.md, "Email files"; the maintainer,
// 2026-11-03: emails open in the viewer, nothing of them drawn in the note): an email's card has
// the EMAIL pill, its subject and sender as its name, Open and Download; Open shows its subject,
// From/To/Cc/Date, its sanitized body and its attachments, each downloading itself, its text
// selectable; a note that is only an email has nothing to fold; a search finds the note by a
// word of the email's body.

const WINDOW = {width: 1100, height: 900};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const CARD_WAIT_MS = 4000;
const LONG_PARAGRAPHS = 30;

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

// A plan email in HTML with two attachments, and a long plain one, built as Mail writes them.
function emails() {
  const boundary = 'b1';
  const plan = [
    'From: Ada Lovelace <ada@example.org>', 'To: Grace Hopper <grace@example.org>', 'Cc: Linus <linus@example.org>',
    'Subject: =?utf-8?b?UsOpdW5pb246IHRoZSBwbGFu?=', 'Date: Thu, 29 Oct 2026 10:15:00 -0700', 'MIME-Version: 1.0',
    `Content-Type: multipart/mixed; boundary="${boundary}"`, '',
    `--${boundary}`, 'Content-Type: text/html; charset=utf-8', '',
    '<html><head><script>alert(1)</script></head><body><p>Hi <b>Grace</b>,</p><p><a href="https://example.org/plan">Open the plan</a></p></body></html>',
    `--${boundary}`, 'Content-Type: text/csv', 'Content-Disposition: attachment; filename="team.csv"', '', 'Name,Role', 'Ada,Analyst',
    `--${boundary}`, 'Content-Type: application/pdf', 'Content-Disposition: attachment; filename="plan.pdf"', '', '%PDF-1.4 plan',
    `--${boundary}--`, '',
  ].join('\r\n');
  const body = Array.from({length: LONG_PARAGRAPHS}, (_, index) => `Paragraph ${index + 1}: the engine weaves algebraic patterns like a Jacquard loom.`);
  const long = ['From: Ada Lovelace <ada@example.org>', 'To: Grace Hopper <grace@example.org>', 'Subject: Notes on the engine',
    'Date: Thu, 29 Oct 2026 08:00:00 -0700', 'Content-Type: text/plain; charset=utf-8', '', ...body, ''].join('\r\n');
  return {plan, long};
}

async function seedNotes(page) {
  return page.evaluate(async ({plan, long}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const upload = async (text, name) => (await FilesAPI.uploadFile(new File([text], name, {type: 'message/rfc822'}))).file_id;
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, '');
      return note.id;
    };
    const planFile = await upload(plan, 'plan.eml');
    const longFile = await upload(long, 'long.eml');
    const planNote = await make(`<div>![[${planFile}]]</div>`);
    const longNote = await make(`<div>The long one:</div><div>![[${longFile}]]</div>`);
    return {planFile, longFile, planNote, longNote};
  }, emails());
}

const noteOf = id => `.note[data-note-id="${id}"]`;

async function cardShows(page, ids) {
  await page.waitForSelector(`${noteOf(ids.planNote)} .note-file-reference-name`, {timeout: CARD_WAIT_MS});
  const card = await page.$eval(noteOf(ids.planNote), note => ({
    pill: note.querySelector('.note-file-reference-badge').textContent,
    name: note.querySelector('.note-file-reference-name').textContent,
    buttons: [...note.querySelectorAll('.note-file-action')].map(button => button.textContent),
    drawnInNote: note.querySelector('[class*="note-file-email"]') !== null,
    // The note's own flag, which its arrow follows (differential-view-service.js).
    canFold: note.dataset.isCollapsible === 'true',
  }));
  assert.deepEqual(card, {pill: 'EMAIL', name: 'Réunion: the plan · Ada Lovelace', buttons: ['Open', 'Download'], drawnInNote: false, canFold: false});
}

async function openViewer(page, noteId) {
  await page.click(`${noteOf(noteId)} .note-file-open`);
  await page.waitForSelector('.file-viewer-drawing:not([style*=hidden])', {timeout: CARD_WAIT_MS});
  return (await page.$('.file-viewer-drawing')).contentFrame();
}

async function closeViewer(page) {
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('.file-viewer-overlay') === null);
}

async function viewerShows(page, ids) {
  const frame = await openViewer(page, ids.planNote);
  const shown = await frame.evaluate(() => ({
    subject: document.querySelector('.file-viewer-email-subject').textContent,
    headers: [...document.querySelectorAll('.file-viewer-email-row')].map(row => `${row.children[0].textContent}: ${row.children[1].textContent}`),
    hasScript: document.querySelector('script') !== null,
    link: document.querySelector('.note-content a').getAttribute('href'),
    bold: document.querySelector('.note-content b').textContent,
    attachments: [...document.querySelectorAll('.file-viewer-email-attachment')].map(button => button.textContent),
    selectable: getComputedStyle(document.querySelector('.note-content p')).userSelect,
  }));
  assert.deepEqual(shown, {
    subject: 'Réunion: the plan',
    headers: ['From: Ada Lovelace <ada@example.org>', 'To: Grace Hopper <grace@example.org>', 'Cc: Linus <linus@example.org>',
      'Date: Thu, 29 Oct 2026 10:15:00 -0700'],
    hasScript: false, link: 'https://example.org/plan', bold: 'Grace',
    // "Name,Role", the email's CRLF line break and "Ada,Analyst": 22 bytes.
    attachments: ['team.csv22 B', 'plan.pdf13 B'],
    selectable: 'text',
  });
  await closeViewer(page);
}

async function attachmentDownloads(page, ids) {
  const frame = await openViewer(page, ids.planNote);
  const download = page.waitForResponse(response => response.url().endsWith(`/files/${ids.planFile}/email/attachments/0`));
  await (await frame.$('.file-viewer-email-attachment')).click();
  const response = await download;
  assert.equal(response.status(), 200);
  assert.equal(response.headers()['content-disposition'], "attachment; filename*=UTF-8''team.csv");
  await closeViewer(page);
  assert.equal(await page.$('.note.editing'), null, 'downloading edits nothing');
}

async function longBodyShowsWhole(page, ids) {
  const frame = await openViewer(page, ids.longNote);
  const text = await frame.evaluate(() => document.body.innerText);
  assert.ok(text.includes('Paragraph 1:') && text.includes(`Paragraph ${LONG_PARAGRAPHS}:`), 'the whole body, in the viewer');
  await closeViewer(page);
}

async function foundBySearch(page, ids) {
  await page.click('#search-input', {clickCount: 3});
  await page.keyboard.type('"jacquard loom"');
  await page.keyboard.press('Enter');
  await idle(page);
  const found = await page.$$eval('#notes-container > .note[data-note-id]', notes => notes.map(note => note.dataset.noteId));
  assert.ok(found.includes(ids.longNote), `a word of the email's body finds its note (${found})`);
  assert.ok(!found.includes(ids.planNote), 'and not the other email\'s note');
  await page.click('#search-input', {clickCount: 3});
  await page.keyboard.press('Backspace');
  await page.keyboard.press('Enter');
  await idle(page);
}

export async function checkEmailFiles(page) {
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
  await runThenCleanUp('email files', async () => {
    await attempt('1 the card: EMAIL, subject and sender, Open and Download', () => cardShows(page, ids));
    await attempt('2 Open: subject, headers, sanitized body, attachments', () => viewerShows(page, ids));
    await attempt('3 an attachment downloads from the viewer', () => attachmentDownloads(page, ids));
    await attempt('4 a long body shows whole in the viewer', () => longBodyShowsWhole(page, ids));
    await attempt('5 a search finds the note by a word of the email', () => foundBySearch(page, ids));
    assert.deepEqual(failures, []);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.planNote, ids.longNote]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
