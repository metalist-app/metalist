import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Field messages (docs/ui/modals.md, "Errors and status"; agreed
// case by case 2026-10-25, step 5b): what is wrong with a field's value floats just under
// that field, over what is below. Nothing moves, focus stays in the field, and the message
// leaves once the value is fine.
// - Passwords: "Passwords do not match." under Confirm once the confirmation stops being the
//   start of the new password; a missing or short entry shows only in the dimmed button's
//   tooltip.
// - Search suggestion windows: a bad day count under its slot's field, not saved.
// - Reminders: a past date or time, in amber, under the date field.

const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const OPEN_DIALOG_MS = 400;
// The space between a field and its message (main.css, .field-message).
const MESSAGE_GAP_PX = 4;
const NEW_PASSWORD = 'correct horse battery staple';
const PAST_DATE = '2020-01-15';

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

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function openFromPalette(page, method, argument) {
  await page.evaluate(async ({method, argument}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    void CommandPalette[method](...argument);
  }, {method, argument});
  await pause(OPEN_DIALOG_MS);
  await idle(page);
}

// Where every field and button of the dialog sits.
async function layout(page, modalSelector) {
  return page.$eval(modalSelector, modal => [...modal.querySelectorAll('input, button, select, textarea')]
    .filter(element => element.getClientRects().length > 0)
    .map(element => {
      const rect = element.getBoundingClientRect();
      return [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
    }));
}

// The message floating under the field, if any, and where both are.
async function messageUnder(page, fieldSelector) {
  return page.$eval(fieldSelector, field => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: Math.round(rect.left), top: Math.round(rect.top), bottom: Math.round(rect.bottom)};
    };
    const message = field.id === '' ? null : document.getElementById(`${field.id}-message`);
    const shown = message !== null && message.getClientRects().length > 0;
    return {
      text: shown ? message.textContent : null,
      kind: shown ? message.dataset.kind : null,
      field: box(field),
      message: shown ? box(message) : null,
      fieldFocused: document.activeElement === field,
    };
  });
}

function assertUnder(state, label) {
  assert.notEqual(state.message, null, `${label}: a message floats under the field`);
  assert.equal(state.message.top, state.field.bottom + MESSAGE_GAP_PX, `${label}: the message sits just under the field`);
  assert.equal(state.message.left, state.field.left, `${label}: the message lines up with the field`);
}

async function closeEverything(page) {
  for (let press = 0; press < 2; press += 1) {
    await page.keyboard.press('Escape');
    await settle(page);
  }
  await idle(page);
}

async function passwordCase(page) {
  await openFromPalette(page, 'openAddPassword', []);
  await page.waitForSelector('#new-password', {visible: true});
  const submit = '[data-password-submit]';
  assert.equal(await page.$eval(submit, button => button.title), 'Enter a new password.',
    'the dimmed button says what is missing');
  assert.equal((await messageUnder(page, '#confirm-password')).text, null, 'nothing is said before typing');
  const before = await layout(page, '#add-password-modal');
  await page.type('#new-password', NEW_PASSWORD);
  await page.type('#confirm-password', 'correct');
  await settle(page);
  assert.equal((await messageUnder(page, '#confirm-password')).text, null,
    'a confirmation that is still the start of the password says nothing');
  await page.type('#confirm-password', 'x');
  await settle(page);
  const mismatch = await messageUnder(page, '#confirm-password');
  assert.equal(mismatch.text, 'Passwords do not match.');
  assert.equal(mismatch.kind, 'error');
  assertUnder(mismatch, 'mismatch');
  assert.equal(mismatch.fieldFocused, true, 'focus stays in Confirm');
  assert.deepEqual(await layout(page, '#add-password-modal'), before, 'nothing in the dialog moves');
  await page.keyboard.press('Backspace');
  await page.type('#confirm-password', NEW_PASSWORD.slice('correct'.length));
  await settle(page);
  assert.equal((await messageUnder(page, '#confirm-password')).text, null, 'a matching confirmation clears the message');
  assert.equal(await page.$eval(submit, button => [button.disabled, button.title].join('|')), 'false|',
    'the button is ready, with no tooltip');
  assert.deepEqual(await layout(page, '#add-password-modal'), before, 'nothing in the dialog moved');
  await closeEverything(page);
}

async function suggestionWindowCase(page) {
  await openFromPalette(page, 'openSearchSuggestionStatistics', []);
  const slot = '.search-window-row[data-window-index="0"] .search-window-days-input';
  await page.waitForSelector(slot, {visible: true});
  const saved = await page.$eval(slot, input => input.value);
  const before = await layout(page, '#search-suggestion-statistics-modal');
  await page.click(slot, {clickCount: 3});
  await page.type(slot, '0');
  await page.keyboard.press('Tab');
  await idle(page);
  const bad = await messageUnder(page, slot);
  assert.notEqual(bad.text, null, 'a bad day count is explained');
  assert.match(bad.text, /must be between 1 and \d+ days/);
  assertUnder(bad, 'day count');
  assert.deepEqual(await layout(page, '#search-suggestion-statistics-modal'), before, 'nothing in the dialog moves');
  await page.click(slot, {clickCount: 3});
  await page.type(slot, saved);
  await page.keyboard.press('Tab');
  await idle(page);
  assert.equal((await messageUnder(page, slot)).text, null, 'a good day count clears the message');
  await closeEverything(page);
}

async function reminderCase(page) {
  await openFromPalette(page, 'openReminders', [{search: ''}]);
  await page.waitForSelector('#reminder-date', {visible: true});
  await page.$eval('#reminder-date', (input, date) => {
    input.value = date;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }, PAST_DATE);
  await settle(page);
  const past = await messageUnder(page, '#reminder-date');
  assert.notEqual(past.text, null, 'a past date is pointed out');
  assert.match(past.text, /in the past/);
  assert.equal(past.kind, 'warning', 'in amber: it is a warning, not an error');
  assertUnder(past, 'past date');
  await closeEverything(page);
}

export async function checkFieldMessages(page) {
  const failures = [];
  const cases = [['password', passwordCase], ['suggestion windows', suggestionWindowCase], ['reminder', reminderCase]];
  for (const [label, run] of cases) {
    try {
      await run(page);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
      console.log(`FAIL ${label}: ${error.message}`);
      await closeEverything(page);
    }
  }
  if (failures.length > 0) throw new assert.AssertionError({message: failures.join('\n')});
}
