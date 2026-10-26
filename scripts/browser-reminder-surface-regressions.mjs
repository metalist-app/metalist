import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The Reminders popup handles its own clicks (docs/ui/reminders.md): pressing
// "Dismiss" while a note is being edited clears the reminder on the first press,
// and the note stays in edit mode with its caret, as pressing any floating card does.

// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
const MS_PER_MINUTE = 60 * 1000;
const ACKNOWLEDGE_SELECTOR = '#reminder-surface [data-reminder-surface-action="acknowledge"]';
const OPEN_REMINDERS_SELECTOR = '#reminder-surface [data-reminder-surface-open-registry]';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

function modeState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {editing: mode.isEditing, current: mode.currentNoteId};
  });
}

async function createNote(page, html) {
  return page.evaluate(async html => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, html, '');
    return note.id;
  }, html);
}

// A one-time reminder that came due a minute ago, so the popup shows it at once.
async function createDueReminder(page, title) {
  return page.evaluate(async ({title, minute}) => {
    const {ReminderStore} = await import('/static/js/modules/reminder-store.js');
    await ReminderStore.create({
      note_id: null, title, details: '', attachment_type: 'unattached',
      schedule_kind: 'one_time', time_mode: 'date_time',
      scheduled_at: new Date(Date.now() - minute).toISOString(), scheduled_date: null,
      recurrence_rule: null, pre_reminder: null, persistence_mode: 'keep_until_seen', status: 'active',
    });
    const matching = ReminderStore.snapshot().reminders.filter(reminder => reminder.title === title);
    if (matching.length !== 1) throw new Error(`Expected one reminder titled ${title}`);
    return matching[0].id;
  }, {title, minute: MS_PER_MINUTE});
}

async function reminderIds(page) {
  return page.evaluate(async () => {
    const {ReminderStore} = await import('/static/js/modules/reminder-store.js');
    await ReminderStore.refresh();
    return ReminderStore.snapshot().reminders.map(reminder => reminder.id);
  });
}

export async function checkReminderSurfaceWhileEditing(page) {
  const noteId = await createNote(page, '<p>A note being edited while a reminder comes due</p>');
  let reminderId = null;
  await runThenCleanUp('reminder surface', async () => {
    reminderId = await createDueReminder(page, 'Water the plants');
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await page.waitForSelector(ACKNOWLEDGE_SELECTOR, {visible: true});

    const box = await (await page.$(`.note[data-note-id="${noteId}"] > .note-content`)).boundingBox();
    await page.mouse.click(box.x + box.width - 10, box.y + box.height / 2);
    await idle(page);
    assert.deepEqual(await modeState(page), {editing: true, current: noteId}, 'the note is being edited');

    await page.click(ACKNOWLEDGE_SELECTOR);
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal((await reminderIds(page)).includes(reminderId), false, 'one press of Dismiss clears the reminder');
    assert.deepEqual(await modeState(page), {editing: true, current: noteId}, 'the note stays in edit mode');

    // Its title opens Reminders, which saves and leaves the note first, as every dialog does.
    reminderId = await createDueReminder(page, 'Call the dentist');
    // The popup looks again when the tab becomes visible.
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForSelector(OPEN_REMINDERS_SELECTOR, {visible: true});
    // The popup draws its items again as the reminder snapshot refreshes; press once it has settled.
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal((await modeState(page)).editing, true, 'still editing when the second reminder shows');
    await page.click(OPEN_REMINDERS_SELECTOR);
    await page.waitForSelector('#reminder-modal', {visible: true});
    await idle(page);
    assert.equal((await modeState(page)).editing, false, 'opening Reminders leaves edit mode');
    await page.keyboard.press('Escape');
    await pause(SETTLE_MS);
    await idle(page);
  }, async () => {
    await page.evaluate(async ({noteId, reminderId}) => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      const {ReminderStore} = await import('/static/js/modules/reminder-store.js');
      await ReminderStore.refresh();
      if (reminderId !== null && ReminderStore.snapshot().reminders.some(reminder => reminder.id === reminderId)) {
        await ReminderStore.delete(reminderId);
      }
      await NotesAPI.deleteNote(noteId);
    }, {noteId, reminderId});
  });
}

// Reminder cards wait behind an open dialog (docs/ui/reminders.md; agreed 2026-10-26): a dialog
// is what the user is working in, so nothing floats over it. A due card covered the Reminders
// dialog's Add Reminder button (CI, Firefox at 800 x 600, 2026-10-26). Cases 1-6 as agreed.
const CARD_SELECTOR = '#reminder-surface .reminder-surface-item';
const SMALL_WINDOW = {width: 800, height: 600};
// Browsers place boxes on a layout grid: 1/64 px in Chrome, 1/60 px in Firefox.
const LAYOUT_STEP_PX = 1 / 60;

// What is drawn at a point: the card, or the dialog (and which control).
function topAt(page, point) {
  return page.evaluate(({x, y}) => {
    const hit = document.elementFromPoint(x, y);
    return {
      isCard: hit !== null && hit.closest('#reminder-surface') !== null,
      inDialog: hit !== null && hit.closest('.modal') !== null,
    };
  }, point);
}

function middle(box) {
  return {x: box.x + box.width / 2, y: box.y + box.height / 2};
}

async function stackCorner(page) {
  return page.$eval('#reminder-surface', stack => {
    const rect = stack.getBoundingClientRect();
    return {right: rect.right, bottom: rect.bottom};
  });
}

async function cardBox(page) {
  return page.$eval(CARD_SELECTOR, card => {
    const rect = card.getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
  });
}

// Every button of the open dialog is what a press there reaches.
async function dialogButtonsReachable(page, dialogSelector) {
  return page.$$eval(`${dialogSelector} button`, buttons => buttons
    .filter(button => button.getClientRects().length > 0)
    .filter(button => {
      const rect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return rect.bottom > 0 && rect.top < innerHeight && !(hit !== null && (hit === button || button.contains(hit)));
    })
    .map(button => button.textContent.trim()));
}

async function openReminders(page) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.openReminders({search: ''});
  });
  await page.waitForSelector('#reminder-title', {visible: true});
  await pause(SETTLE_MS);
  await idle(page);
}

async function closeDialogs(page) {
  await page.keyboard.press('Escape');
  await pause(SETTLE_MS);
  await idle(page);
}

export async function checkReminderCardsBehindDialogs(page) {
  const viewport = page.viewport();
  const reminders = [];
  await runThenCleanUp('reminder cards behind dialogs', async () => {
    await page.setViewport(SMALL_WINDOW);
    reminders.push(await createDueReminder(page, 'Call Henry'));
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await page.waitForSelector(CARD_SELECTOR, {visible: true});
    await pause(SETTLE_MS);
    // 5: with no dialog open the card floats above the page.
    const card = await cardBox(page);
    const corner = await stackCorner(page);
    assert.equal((await topAt(page, middle(card))).isCard, true, '5: with no dialog open, the card is on top');

    // 1: Reminders open with a card due; every button of the dialog takes its press.
    await openReminders(page);
    assert.deepEqual(await dialogButtonsReachable(page, '#reminder-modal'), [], '1: no button of Reminders is covered');
    assert.equal((await topAt(page, middle(card))).isCard, false, '1: the card waits behind the dialog');
    await page.click('[data-reminder-save]');
    await page.waitForFunction(() => document.querySelector('#error-dialog .error-dialog-text')?.textContent === 'Add a title for the reminder.');
    // 4: an error dialog over the dialog; both above the card.
    assert.equal((await topAt(page, middle(card))).isCard, false, '4: the card stays behind the error dialog too');
    await closeDialogs(page);

    // 3: a reminder comes due while the dialog is open: behind it.
    reminders.push(await createDueReminder(page, 'Water the plants'));
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await pause(SETTLE_MS);
    await idle(page);
    const cards = await page.$$eval(CARD_SELECTOR, items => items.map(item => {
      const rect = item.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return hit !== null && hit.closest('#reminder-surface') !== null;
    }));
    assert(cards.length > 0 && cards.every(isOnTop => !isOnTop), '3: a card that comes due while the dialog is open waits behind it');

    // 2: the dialog closes; the card is on top again, where it was, and Dismiss works at once.
    await closeDialogs(page);
    const back = await cardBox(page);
    assert.equal((await topAt(page, middle(back))).isCard, true, '2: the card is on top again');
    // The stack keeps its corner (a card added meanwhile makes it taller, not moved).
    const cornerNow = await stackCorner(page);
    assert(Math.abs(cornerNow.right - corner.right) <= LAYOUT_STEP_PX && Math.abs(cornerNow.bottom - corner.bottom) <= LAYOUT_STEP_PX,
      `2: in the same corner (${JSON.stringify(cornerNow)} instead of ${JSON.stringify(corner)})`);
    const before = (await reminderIds(page)).length;
    // The cards draw again as the reminder snapshot refreshes; press once they have settled.
    await pause(SETTLE_MS);
    await idle(page);
    await page.click(ACKNOWLEDGE_SELECTOR);
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal((await reminderIds(page)).length, before - 1, '2: Dismiss works on the first press');

    // 6: pressing a card's title opens Reminders over the card.
    await page.waitForSelector(OPEN_REMINDERS_SELECTOR, {visible: true});
    const title = await page.$eval(OPEN_REMINDERS_SELECTOR, element => {
      const rect = element.getBoundingClientRect();
      return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
    });
    await page.click(OPEN_REMINDERS_SELECTOR);
    await page.waitForSelector('#reminder-modal', {visible: true});
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal((await topAt(page, title)).isCard, false, '6: Reminders opens over the card');
    assert.deepEqual(await dialogButtonsReachable(page, '#reminder-modal'), [], '6: no button of Reminders is covered');
    await closeDialogs(page);
  }, async () => {
    await page.setViewport(viewport);
    await page.evaluate(async ids => {
      const {ReminderStore} = await import('/static/js/modules/reminder-store.js');
      await ReminderStore.refresh();
      for (const id of ids) {
        if (ReminderStore.snapshot().reminders.some(reminder => reminder.id === id)) await ReminderStore.delete(id);
      }
    }, reminders);
  });
}
