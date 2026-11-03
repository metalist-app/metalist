import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A link to an @password or @username note works like that note's own row (docs/ui/references.md;
// agreed 2026-10-26): its value (a password as dots) is copied by its copy button, with no stop
// at the note on the way, and the rest of the link goes to the note. A password shows as eight
// dots, its text never in the page until its eye is clicked (2026-11-03): before, it was its
// text, blurred, and a click on the value copied it.
const MASK = '\u2022'.repeat(8);

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
const PASSWORD = 'hunter2-correct-horse';
const USERNAME = 'tom@example.org';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function seedNotes(page) {
  return page.evaluate(async ({password, username}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const ids = {};
    ids.password = await make(`<div>${password}</div>`, '@password');
    ids.username = await make(`<div>${username}</div>`, '@username');
    ids.holder = await make(`<div>The bank: [[${ids.username}]] and [[${ids.password}]] to sign in</div>`, '');
    return ids;
  }, {password: PASSWORD, username: USERNAME});
}

function linkTo(ids, target) {
  return `#notes-container .note[data-note-id="${ids.holder}"] .note-reference-link[data-ref-note-id="${target}"]`;
}

async function copiedBy(page, selector) {
  await page.evaluate(() => {
    window.__copied = [];
    navigator.clipboard.writeText = async text => { window.__copied.push(text); };
  });
  await page.click(selector);
  await pause(SETTLE_MS);
  await idle(page);
  return page.evaluate(async () => {
    const {isViewingReferenceSource} = await import('/static/js/modules/mode-manager/services/reference-source-navigation-service.js');
    return {copied: window.__copied, followed: isViewingReferenceSource()};
  });
}

async function linkCases(page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  const passwordLink = linkTo(ids, ids.password);
  const ownPassword = `#notes-container .note[data-note-id="${ids.password}"] > .note-content`;
  const passwordValue = `${passwordLink} .meta-credential-password .meta-credential-value`;
  const goBack = async () => {
    await page.click('#reference-source-indicator-clear');
    await pause(SETTLE_MS);
    await idle(page);
  };
  await attempt('the password in a link and in its own note is dots, never blurred', async () => {
    const shown = await page.$$eval('#notes-container .meta-credential-password .meta-credential-value',
      values => values.map(value => [value.textContent, getComputedStyle(value).filter, value.getAttribute('aria-label')]));
    assert.equal(shown.length, 2);
    for (const value of shown) assert.deepEqual(value, [MASK, 'none', 'Hidden password']);
  });
  await attempt('the password is nowhere in the page text, even selected', async () => {
    const text = await page.evaluate(() => {
      window.getSelection().selectAllChildren(document.body);
      const selected = window.getSelection().toString();
      window.getSelection().removeAllRanges();
      return [document.body.innerText, document.body.textContent, selected];
    });
    for (const shown of text) assert.ok(!shown.includes(PASSWORD));
  });
  await attempt('the copy button copies the password and stays', async () => {
    assert.deepEqual(await copiedBy(page, `${passwordLink} [data-value-action="copy"]`), {copied: [PASSWORD], followed: false});
    assert.deepEqual(await copiedBy(page, `${ownPassword} [data-value-action="copy"]`), {copied: [PASSWORD], followed: false});
  });
  await attempt('the copy button copies the username and stays', async () => {
    assert.deepEqual(await copiedBy(page, `${linkTo(ids, ids.username)} [data-value-action="copy"]`), {copied: [USERNAME], followed: false});
  });
  await attempt('a username has no eye', async () => {
    assert.equal(await page.$$eval('#notes-container .meta-credential-username [data-value-action="show"]', eyes => eyes.length), 0);
  });
  await attempt('the eye shows the password in monospace until clicked again, and stays', async () => {
    const eye = `${passwordLink} [data-value-action="show"]`;
    assert.deepEqual(await copiedBy(page, eye), {copied: [], followed: false});
    const shown = await page.$eval(passwordValue, value => [value.textContent, getComputedStyle(value).fontFamily.includes('Mono'),
      value.nextElementSibling.querySelector('[data-value-action="show"]').getAttribute('aria-pressed')]);
    assert.deepEqual(shown, [PASSWORD, true, 'true']);
    // Only that row: the note's own row stays dots.
    assert.equal(await page.$eval(`${ownPassword} .meta-credential-value`, value => value.textContent), MASK);
    await copiedBy(page, eye);
    assert.equal(await page.$eval(passwordValue, value => value.textContent), MASK);
  });
  await attempt("clicking the note's own dots edits it and copies nothing", async () => {
    const result = await copiedBy(page, `${ownPassword} .meta-credential-value`);
    assert.deepEqual(result.copied, []);
    assert.equal(await page.evaluate(() => document.querySelector('.note.editing')?.dataset.noteId), ids.password);
    await page.keyboard.press('Escape');
    await pause(SETTLE_MS);
    await idle(page);
  });
  await attempt('clicking the dots in a link goes to the note and copies nothing', async () => {
    assert.deepEqual(await copiedBy(page, passwordValue), {copied: [], followed: true});
    await goBack();
  });
  await attempt('the reference icon goes to the note', async () => {
    assert.deepEqual(await copiedBy(page, `${passwordLink} .note-reference-link-icon`),
      {copied: [], followed: true});
    await goBack();
  });
  assert.deepEqual(failures, []);
}

export async function checkCredentialLinks(page) {
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('credential links', () => linkCases(page, ids), async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.holder, ids.username, ids.password]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
