import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A link to an @password or @username note works like that note's own row (docs/ui/references.md;
// agreed 2026-10-26): its value (a password blurred) is copied by a click, with no stop at the
// note on the way, and the link's reference icon still goes to the note. The click on the value
// used to follow the link, and the link showed the password in plain text.

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
  const passwordValue = `${linkTo(ids, ids.password)} .meta-credential-password .meta-credential-value`;
  await attempt('the password in a link is blurred', async () => {
    const filter = await page.$eval(passwordValue, value => getComputedStyle(value).filter);
    assert.match(filter, /blur/);
  });
  await attempt('clicking the password copies it and stays', async () => {
    assert.deepEqual(await copiedBy(page, passwordValue), {copied: [PASSWORD], followed: false});
  });
  await attempt('clicking the username copies it and stays', async () => {
    const usernameValue = `${linkTo(ids, ids.username)} .meta-credential-username .meta-credential-value`;
    assert.deepEqual(await copiedBy(page, usernameValue), {copied: [USERNAME], followed: false});
  });
  await attempt('the reference icon goes to the note', async () => {
    assert.deepEqual(await copiedBy(page, `${linkTo(ids, ids.password)} .note-reference-link-icon`),
      {copied: [], followed: true});
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
