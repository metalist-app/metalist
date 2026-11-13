import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Password Audit's Go to (docs/ui/password-audit.md; the maintainer, 2026-11-12: "the
// go-to should take you directly to the root note that the password is in instead of bringing up
// that floating thing"). It opens the password's top-level note as following a link to it does: a
// Source note view; the panel stays where it is; back returns to the view before, and the first
// view's × to the search, where the list is as it was. Cases agreed 2026-11-12; positions exact.

const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const WINDOW = {width: 1280, height: 520};
const DESKTOP_WINDOW = {width: 1280, height: 900};
const LIST_SCROLL_PX = 140;
const SOURCE_NOTE_LABEL = 'Source note';
const ESCAPES_AFTER_A_FAILURE = 3;

async function settle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function applyPreference(page, key, value) {
  await page.evaluate(async ({key, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(key, value);
  }, {key, value});
}

// Bank of Lisbon > its password note; Email, a top-level note with a password region; a password
// note of its own at the top level.
async function createPasswords(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const bank = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(bank.id, 'Bank of Lisbon', 'audit-check');
    const nested = await NotesAPI.createChild(bank.id, '');
    await NotesAPI.saveNote(nested.id, 'lisbon2024', '@password');
    const mail = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(mail.id, 'Email login ((lisbon2024))', '((@password)) audit-check');
    const lone = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(lone.id, 'hunter2', '@password');
    return {bank: bank.id, nested: nested.id, mail: mail.id, lone: lone.id};
  });
}

async function read(page) {
  return page.evaluate(label => {
    const panel = document.getElementById('password-audit-panel');
    const box = panel.getBoundingClientRect();
    const chip = document.getElementById('reference-source-indicator');
    const firstNote = document.querySelector('#notes-container > .note');
    return {
      panel: {left: box.left, top: box.top},
      isReferenceView: chip.classList.contains('is-shown'),
      chipLabel: document.getElementById('reference-source-indicator-label').textContent.trim(),
      firstNoteId: firstNote === null ? null : firstNote.dataset.noteId,
      floatingWindows: document.querySelectorAll('.floating-note-window').length,
      search: document.getElementById('search-input').value,
      scrollY: window.scrollY,
      label,
    };
  }, SOURCE_NOTE_LABEL);
}

// The view a Go to opens; which note it shows first is asserted by the caller, so a wrong one
// is named rather than waited for.
async function activeViewId(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.activeTabId;
  });
}

async function goTo(page, rootNoteId) {
  const before = await activeViewId(page);
  await page.click(`#password-audit-panel [data-audit-go="${rootNoteId}"]`);
  // Each Go to opens a view of its own, as following a link does.
  await page.waitForFunction(async previous => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.activeTabId !== previous
      && document.getElementById('reference-source-indicator').classList.contains('is-shown');
  }, {}, before);
  await settle(page);
  return read(page);
}

async function weakCount(page) {
  return page.evaluate(() => Number(/(\d+) weak/.exec(document.querySelector('.password-audit-summary').textContent)[1]));
}

// The first view, as one a link opened, is left with its ×: back to the search.
async function leaveView(page) {
  await page.waitForSelector('#reference-source-indicator-clear', {visible: true});
  await page.click('#reference-source-indicator-clear');
  await settle(page);
  return read(page);
}

async function back(page) {
  await page.waitForSelector('#reference-view-chip-back', {visible: true});
  await page.click('#reference-view-chip-back');
  await settle(page);
  return read(page);
}

async function auditCases(page, ids) {
  await page.setViewport(WINDOW);
  await settle(page);
  await page.evaluate(scrollPx => window.scrollTo(0, scrollPx), LIST_SCROLL_PX);
  await settle(page);
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.openPasswordAudit();
  });
  await page.waitForFunction(() => document.querySelector('.password-audit-summary')?.textContent.includes('passwords:'));
  await settle(page);
  const before = await read(page);
  assert.equal(before.isReferenceView, false, 'the audit opens on the list as it was');

  // Switching between 3 and 4 regroups from the scores the audit has: nothing is asked again,
  // leaks least of all (the maintainer, 2026-11-12).
  const audits = [];
  const countAudits = request => { if (request.url().endsWith('/notes/password-audit')) audits.push(request.url()); };
  page.on('request', countAudits);
  const weakAt3 = await weakCount(page);
  await page.click('#password-audit-panel [data-audit-weak="4"]');
  await settle(page);
  const weakAt4 = await weakCount(page);
  await page.click('#password-audit-panel [data-audit-weak="3"]');
  await settle(page);
  page.off('request', countAudits);
  assert.deepEqual(audits, [], 'switching the threshold asks the server nothing');
  assert.ok(weakAt4 >= weakAt3, `below 4 flags at least what below 3 does (${weakAt4} < ${weakAt3})`);
  assert.equal(await weakCount(page), weakAt3, 'and back at 3 it is as it was');

  // Case 1: a password note under Bank of Lisbon opens Bank of Lisbon's view.
  const nested = await goTo(page, ids.bank);
  assert.equal(nested.firstNoteId, ids.bank, 'the view shows the top-level note the password is in');
  assert.equal(nested.chipLabel, SOURCE_NOTE_LABEL, 'as following a link to it does');
  // Case 3: the panel stays where it is; case 6: no floating window.
  assert.deepEqual(nested.panel, before.panel, 'the panel does not move');
  assert.equal(nested.floatingWindows, 0, 'nothing opens in a floating window');

  // Case 2 and 4: a top-level password note opens its own view, a second view on the first.
  const lone = await goTo(page, ids.lone);
  assert.equal(lone.firstNoteId, ids.lone, 'a top-level password note opens its own view');
  assert.deepEqual(lone.panel, before.panel, 'the panel does not move');

  // Case 4 and 5: back returns to the first view, and its × to the list exactly as it was, as
  // after following links.
  const backOnce = await back(page);
  assert.equal(backOnce.isReferenceView, true, 'back returns to the first view');
  assert.equal(backOnce.firstNoteId, ids.bank);
  const backTwice = await leaveView(page);
  assert.equal(backTwice.isReferenceView, false, 'and then to the list');
  assert.equal(backTwice.search, before.search, 'the search is as it was');
  assert.equal(backTwice.scrollY, before.scrollY, 'the list is where it was');
  assert.deepEqual(backTwice.panel, before.panel, 'the panel is still where it was');

  // Replace…: a strong password to copy, nothing changed until Save; then the old one is kept in
  // a note under it, listed to delete.
  await page.click(`#password-audit-panel [data-audit-replace="${ids.lone}:note:0"]`);
  await page.waitForSelector('#password-audit-panel .password-audit-replacing');
  const newPassword = await page.$eval('#password-audit-panel .password-audit-new', element => element.textContent);
  assert.ok(newPassword.length >= 16 && newPassword !== 'hunter2', 'a strong new password is offered');
  await page.click(`#password-audit-panel [data-audit-save="${ids.lone}:note:0"]`);
  await page.waitForFunction(() => document.querySelector('.password-audit-summary').textContent.includes('passwords:')
      && document.querySelector('.password-audit-replacing') === null);
  await settle(page);
  const kept = await page.evaluate(() => [...document.querySelectorAll('.password-audit-group')]
    .filter(group => group.querySelector('h4').textContent.startsWith('Replaced, to delete'))
    .map(group => [...group.querySelectorAll('.password-audit-label')].map(label => label.textContent)));
  assert.equal(kept.length, 1, 'the old password is listed to delete');
  assert.ok(kept[0].every(label => /^Replaced \d{4}-\d{2}-\d{2}: •+$/.test(label)), JSON.stringify(kept));
  const panelText = await page.$eval('#password-audit-panel', element => element.textContent);
  assert.ok(!panelText.includes('hunter2') && !panelText.includes(newPassword), 'no password shows once saved');
  console.log('PASS password audit: Go to opens the password\'s top-level note as a link does, and back returns to the list as it was');
}

// While the panel is open it updates itself as notes change, checking only what is new (the
// maintainer, 2026-11-13; cases agreed the same day): in place, no Checking…, the panel where it
// was; Replace… follows its password while the note around it changes, and keeps the new password
// to copy when the password leaves its note.
async function editNote(page, noteId, content, tags) {
  await page.evaluate(async ({noteId, content, tags}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(noteId, content, tags);
  }, {noteId, content, tags});
}

// Waits for the panel's next update after a change and says what it showed on the way.
async function nextUpdate(page, change) {
  await page.evaluate(() => {
    const summary = document.querySelector('#password-audit-panel .password-audit-summary');
    window.__auditSummaries = [];
    window.__auditObserver = new MutationObserver(() => window.__auditSummaries.push(summary.textContent));
    window.__auditObserver.observe(summary, {childList: true, characterData: true, subtree: true});
  });
  const asked = [];
  const countAudits = request => { if (request.url().endsWith('/notes/password-audit')) asked.push(JSON.parse(request.postData()).fresh); };
  page.on('request', countAudits);
  const answered = page.waitForResponse(response => response.url().endsWith('/notes/password-audit'));
  await change();
  await answered;
  await settle(page);
  page.off('request', countAudits);
  const shown = await page.evaluate(() => {
    window.__auditObserver.disconnect();
    return window.__auditSummaries;
  });
  return {asked, shown};
}

async function groupLabels(page) {
  return page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#password-audit-panel .password-audit-group')]
    .map(group => [group.dataset.auditGroup, [...group.querySelectorAll('.password-audit-label')].map(label => label.textContent)])));
}

async function liveUpdateCases(page, ids) {
  const panelBefore = (await read(page)).panel;
  // Email's password, reused with the bank's, made strong: neither is reused now, one fewer weak.
  const strong = await nextUpdate(page, () => editNote(page, ids.mail, 'Email login ((Rk7$qPz!w2Lm#9vT))', '((@password)) audit-check'));
  assert.deepEqual(strong.asked, [false], 'one update, which checks only what changed');
  assert.ok(strong.shown.every(text => text.includes('passwords:')), `no Checking… on the way (${JSON.stringify(strong.shown)})`);
  const afterStrong = await groupLabels(page);
  assert.equal(afterStrong.reused, undefined, 'nothing is reused any more');
  assert.deepEqual(afterStrong.weak, ['Bank of Lisbon'], 'only the bank is weak');
  assert.deepEqual((await read(page)).panel, panelBefore, 'the panel does not move');

  // A new password note appears in its groups.
  const shopId = await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    return (await NotesAPI.createNote(null, '')).id;
  });
  await nextUpdate(page, () => editNote(page, shopId, 'Shop login ((qwerty))', '((@password)) audit-check'));
  assert.deepEqual((await groupLabels(page)).weak, ['Bank of Lisbon', 'Shop login ••••••••']);

  // Replace… stays with its password while the note around it changes, and Save would put the
  // new one where it is now.
  await page.click(`#password-audit-panel [data-audit-replace="${shopId}:region:0"]`);
  const generated = await page.$eval('#password-audit-panel .password-audit-new', element => element.textContent);
  await nextUpdate(page, () => editNote(page, shopId, 'Shop login, renamed ((qwerty))', '((@password)) audit-check'));
  const followed = await page.evaluate(id => {
    const row = document.querySelector(`#password-audit-panel [data-audit-row="${id}:region:0"]`);
    return {
      label: row.querySelector('.password-audit-label').textContent,
      password: row.querySelector('.password-audit-new').textContent,
      canSave: row.querySelector('[data-audit-save]') !== null,
    };
  }, shopId);
  assert.deepEqual(followed, {label: 'Shop login, renamed ••••••••', password: generated, canSave: true});

  // Its note deleted: the new password stays to copy, as it may be in use on the site; no Save.
  await nextUpdate(page, () => page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNote(id);
  }, shopId));
  const gone = await page.evaluate(() => {
    const form = document.querySelector('#password-audit-panel .password-audit-replacing');
    return {
      password: form.querySelector('.password-audit-new').textContent,
      hint: form.querySelector('.password-audit-hint').textContent,
      canSave: form.querySelector('[data-audit-save]') !== null,
    };
  });
  assert.deepEqual(gone, {password: generated, hint: 'This password is no longer in its note.', canSave: false});
  await page.click('#password-audit-panel [data-audit-cancel]');
  assert.equal(await page.$('#password-audit-panel .password-audit-replacing'), null, 'Cancel puts it away');
  console.log('PASS password audit while open: updates in place as passwords change, checking only what changed; Replace… follows its password');
}

const REMINDER = '#password-audit-reminder-notice';
const DAY_MS = 24 * 60 * 60 * 1000;
const HALF_A_YEAR_DAYS = 200;

async function reminderText(page) {
  return page.evaluate(selector => {
    const notice = document.querySelector(selector);
    return notice === null ? null : notice.querySelector('.backup-reminder-text').textContent;
  }, REMINDER);
}

async function checkReminder(page) {
  await page.evaluate(async () => {
    const {PasswordAuditReminder} = await import('/static/js/modules/password-audit/password-audit-reminder.js');
    await PasswordAuditReminder.check();
  });
  await settle(page);
  return reminderText(page);
}

async function passwordCount(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    return (await NotesAPI.passwordCount()).passwordCount;
  });
}

// The reminder to audit (the maintainer, 2026-11-12): only with a password; at once when no audit
// ever ran; gone once one runs; back when the last one is old; × hides it for a week.
async function reminderCases(page) {
  const after = await checkReminder(page);
  assert.equal(after, null, 'an audit that ran takes the reminder away');
  await page.evaluate(async (days, dayMs) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.password_audit.last_audited_at', new Date(Date.now() - days * dayMs).toISOString());
  }, HALF_A_YEAR_DAYS, DAY_MS);
  // The audit left passwords to fix (reused, weak), so the card says how many still need attention.
  const issues = await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    return Number(CommandPalette._preferences.getRaw('pref.password_audit.open_issues'));
  });
  assert.ok(issues > 0, 'the audit counted passwords still to fix');
  // The live updates left the bank's alone to fix, so it says so in the singular.
  assert.equal(issues, 1, 'the updates while open kept the count of passwords to fix');
  assert.equal(await checkReminder(page), 'Time to check your passwords: 1 still needs attention.');
  await page.click(`${REMINDER} button[title="Hide for a week"]`);
  await settle(page);
  assert.equal(await reminderText(page), null, '× hides it');
  const hiddenDays = await page.evaluate(async dayMs => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    return (new Date(CommandPalette._preferences.getRaw('pref.password_audit_reminder_hidden_until')) - Date.now()) / dayMs;
  }, DAY_MS);
  assert.ok(hiddenDays > 6.99 && hiddenDays <= 7, `for a week (${hiddenDays} days)`);
  assert.equal(await checkReminder(page), null, 'and it stays hidden');
  console.log('PASS password audit reminder: only with a password, at once when never audited, gone after an audit, back sooner while passwords need attention, × hides it for a week');
}

export async function checkPasswordAudit(page) {
  await applyPreference(page, 'pref.animated_transitions', false);
  await applyPreference(page, 'pref.password_audit_reminder', 'every_3_months');
  if (await passwordCount(page) === 0) {
    assert.equal(await checkReminder(page), null, 'a vault with no password is not reminded');
  }
  const ids = await createPasswords(page);
  await page.reload({waitUntil: 'networkidle0'});
  await page.waitForFunction(() => document.body.dataset.appReady === 'true');
  await page.waitForSelector(REMINDER, {visible: true});
  assert.equal(await reminderText(page), 'Time to check your passwords: they have never been audited.');
  await runThenCleanUp('password audit', async () => {
    await auditCases(page, ids);
    await liveUpdateCases(page, ids);
    await reminderCases(page);
  }, async () => {
    for (let press = 0; press < ESCAPES_AFTER_A_FAILURE; press += 1) await page.keyboard.press('Escape');
    await page.evaluate(async () => {
      const {closePasswordAudit} = await import('/static/js/modules/password-audit/password-audit-panel.js');
      closePasswordAudit();
    });
    await page.setViewport(DESKTOP_WINDOW);
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, [ids.bank, ids.mail, ids.lone]);
    await applyPreference(page, 'pref.animated_transitions', true);
    await applyPreference(page, 'pref.password_audit_reminder', 'off');
  });
}
