import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Email files (.eml) as cards (docs/ui/references.md, "Email files"; agreed 2026-10-29):
// an embedded email shows its subject, From/To/Cc/Date, its sanitized body and its
// attachments, each downloading itself; a long body is cut until Show all, which edits
// nothing; a note that is only an email folds to one line (EML, subject, sender), kept in its
// boxes so folding moves nothing (the maintainer, 2026-11-01:
// scripts/browser-folded-file-regressions.mjs checks the positions); a
// search finds the note by a word of the email's body.

const WINDOW = {width: 1100, height: 900};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const CARD_WAIT_MS = 4000;
// A folded email's one line: no taller than this many lines.
const ONE_LINE = 1.5;
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

const cardOf = id => `.note[data-note-id="${id}"] .note-file-email-embed[data-preview-state="loaded"]`;

async function cardText(page, id) {
  return page.$eval(cardOf(id), embed => ({
    subject: embed.querySelector('.note-file-email-subject').textContent,
    headers: [...embed.querySelectorAll('.note-file-email-header')].map(row => `${row.children[0].textContent}: ${row.children[1].textContent}`),
    bodyHtml: embed.querySelector('.note-file-email-body').innerHTML,
    attachments: [...embed.querySelectorAll('.note-file-email-attachment')].map(button => button.textContent),
  }));
}

async function cardShows(page, ids) {
  await page.waitForSelector(cardOf(ids.planNote), {timeout: CARD_WAIT_MS});
  assert.deepEqual(await cardText(page, ids.planNote), {
    subject: 'Réunion: the plan',
    headers: ['From: Ada Lovelace <ada@example.org>', 'To: Grace Hopper <grace@example.org>', 'Cc: Linus <linus@example.org>',
      'Date: Thu, 29 Oct 2026 10:15:00 -0700'],
    bodyHtml: '<p>Hi <b>Grace</b>,</p><p><a href="https://example.org/plan" target="_blank" rel="noopener noreferrer">Open the plan</a></p>',
    // "Name,Role", the email's CRLF line break and "Ada,Analyst": 22 bytes.
    attachments: ['team.csv22 B', 'plan.pdf13 B'],
  });
}

async function attachmentDownloads(page, ids) {
  const download = page.waitForResponse(response => response.url().endsWith(`/files/${ids.planFile}/email/attachments/0`));
  await page.click(`${cardOf(ids.planNote)} .note-file-email-attachment[data-attachment-index="0"]`);
  const response = await download;
  assert.equal(response.status(), 200);
  assert.equal(response.headers()['content-disposition'], "attachment; filename*=UTF-8''team.csv");
  assert.equal(await page.$('.note.editing'), null, 'downloading edits nothing');
  // What is saved (the page has read the response the click downloaded).
  const saved = await page.evaluate(async fileId => {
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    const payload = await FilesAPI.downloadEmailAttachment(fileId, 0);
    return [payload.filename, await payload.blob.text()];
  }, ids.planFile);
  assert.deepEqual(saved, ['team.csv', 'Name,Role\r\nAda,Analyst']);
}

async function showAll(page, ids) {
  await page.waitForSelector(cardOf(ids.longNote), {timeout: CARD_WAIT_MS});
  const more = `${cardOf(ids.longNote)} .note-file-email-more`;
  const cut = await page.$eval(`${cardOf(ids.longNote)} .note-file-email-body`, body => ({cut: body.scrollHeight > body.clientHeight}));
  assert.deepEqual(cut, {cut: true}, 'a long body is cut');
  assert.equal(await page.$eval(more, button => [button.hidden, button.textContent].join()), 'false,Show all');
  await page.evaluate(selector => document.querySelector(selector).scrollIntoView({block: 'center'}), more);
  await page.click(more);
  await settle(page);
  const open = await page.$eval(`${cardOf(ids.longNote)} .note-file-email-body`, body => body.scrollHeight <= body.clientHeight);
  assert.equal(open, true, 'Show all shows the whole body');
  assert.equal(await page.$eval(more, button => button.textContent), 'Show less');
  assert.equal(await page.$('.note.editing'), null, 'Show all edits nothing');
}

async function foldsToOneLine(page, ids) {
  const note = `.note[data-note-id="${ids.planNote}"]`;
  await page.evaluate(selector => document.querySelector(selector).scrollIntoView({block: 'center'}), note);
  await page.click(`${note} > .note-collapse-toggle`);
  await idle(page);
  const folded = await page.$eval(note, element => {
    const content = element.querySelector(':scope > .note-content');
    const line = content.querySelector('.note-file-email-line');
    return {
      isCollapsed: element.classList.contains('collapsed'),
      lineText: [...line.children].map(child => child.textContent),
      lineShown: getComputedStyle(line).display,
      cardShown: getComputedStyle(content.querySelector('.note-file-email-body')).display,
      lines: line.getBoundingClientRect().height / Number.parseFloat(getComputedStyle(content).lineHeight),
    };
  });
  assert.deepEqual([folded.isCollapsed, folded.lineText, folded.lineShown, folded.cardShown],
    [true, ['EML', 'Réunion: the plan', 'Ada Lovelace'], 'flex', 'none'], 'folded: the one line');
  assert.ok(folded.lines <= ONE_LINE, `folded: its line is one line tall (${folded.lines} lines)`);
  await page.click(`${note} > .note-collapse-toggle`);
  await idle(page);
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
    await attempt('1 the card: subject, headers, sanitized body, attachments', () => cardShows(page, ids));
    await attempt('2 an attachment downloads', () => attachmentDownloads(page, ids));
    await attempt('3 a long body is cut until Show all', () => showAll(page, ids));
    await attempt('4 a note that is only an email folds to one line', () => foldsToOneLine(page, ids));
    await attempt('5 a search finds the note by a word of the email', () => foundBySearch(page, ids));
    assert.deepEqual(failures, []);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.planNote, ids.longNote]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
