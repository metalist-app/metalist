import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Error dialogs (docs/ui/modals.md, "Errors and status"; agreed case by case
// 2026-10-25, step 5a): an action that is refused or fails opens a small error dialog over
// the dialog the user was in.
// - The dialog underneath stays open with what was typed, and nothing in it moves.
// - One error dialog lists every problem; it has no button: ×, Escape or a click outside
//   closes it, and only it.
// - Closing it puts focus in the first field at fault, which keeps a red outline (no size
//   change) until its value changes.
// - Input mistakes that crashed to the red error screen show here instead.
// - A dialog that fails to load shows the error, and closing it closes both.

const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const OPEN_DIALOG_MS = 400;
// A port outside 1–65535.
const LOW_PORT = '0';

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

// Where every field and button of the dialog sits, and the dialog's own box.
async function layout(page, modalSelector) {
  return page.$eval(modalSelector, modal => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
    };
    return {
      dialog: box(modal.querySelector('.modal-content')),
      controls: [...modal.querySelectorAll('input, button, select, textarea')]
        .filter(element => element.getClientRects().length > 0).map(box),
    };
  });
}

async function errorDialog(page) {
  return page.evaluate(() => {
    const dialog = document.querySelector('#error-dialog [role="alertdialog"]');
    if (dialog === null) return null;
    const text = dialog.querySelector('.error-dialog-text');
    const items = [...text.querySelectorAll('li')].map(item => item.textContent);
    return {
      problems: items.length > 0 ? items : [text.textContent],
      buttons: [...dialog.querySelectorAll('button')].map(button => button.getAttribute('aria-label')),
      hasFocus: dialog.contains(document.activeElement),
    };
  });
}

async function fatalShown(page) {
  return page.evaluate(() => document.getElementById('fatal-error-overlay') !== null);
}

async function fieldState(page, selector) {
  return page.$eval(selector, field => ({
    value: field.value,
    focused: document.activeElement === field,
    atFault: field.classList.contains('field-at-fault'),
    outline: getComputedStyle(field).outlineStyle,
    box: [field.getBoundingClientRect().width, field.getBoundingClientRect().height].map(Math.round),
  }));
}

async function isShown(page, selector) {
  return page.evaluate(target => {
    const element = document.querySelector(target);
    return element instanceof HTMLElement && element.getClientRects().length > 0;
  }, selector);
}

// The field emptied, then the text typed key by key. A triple-click does not select a number
// field's text in Firefox, where Backspace then left all but the last digit (CI, 2026-10-26).
async function typeInto(page, selector, text) {
  await page.click(selector);
  await page.$eval(selector, field => { field.value = ''; });
  await page.type(selector, text);
}

async function closeEverything(page) {
  for (let press = 0; press < 2; press += 1) {
    await page.keyboard.press('Escape');
    await settle(page);
  }
  await idle(page);
}

async function createExistingCase(page) {
  await openFromPalette(page, 'openCreateNamespace', []);
  await typeInto(page, '#create-namespace-name', 'default');
  const before = await layout(page, '#create-namespace-modal');
  const nameBox = (await fieldState(page, '#create-namespace-name')).box;
  await page.click('#create-namespace-submit-btn');
  await idle(page);
  const shown = await errorDialog(page);
  assert.notEqual(shown, null, 'pressing Create with an existing name opens an error dialog');
  assert.deepEqual(shown.problems, ['That vault already exists. Pick another name.']);
  assert.deepEqual(shown.buttons, ['Close'], 'the error dialog has only its ×');
  assert.equal(shown.hasFocus, true, 'focus moves into the error dialog');
  assert.deepEqual(await layout(page, '#create-namespace-modal'), before, 'nothing in Create Vault moves');
  await page.keyboard.press('Escape');
  await settle(page);
  assert.equal(await errorDialog(page), null, 'Escape closes the error dialog');
  assert.equal(await isShown(page, '#create-namespace-modal'), true, 'Escape leaves Create Vault open');
  const name = await fieldState(page, '#create-namespace-name');
  assert.deepEqual([name.value, name.focused, name.atFault, name.outline], ['default', true, true, 'solid'],
    'the name keeps its text, has focus and a red outline');
  assert.deepEqual(name.box, nameBox, 'the outline changes no size');
  assert.deepEqual(await layout(page, '#create-namespace-modal'), before, 'nothing in Create Vault moved');
  await page.keyboard.type('x');
  assert.equal((await fieldState(page, '#create-namespace-name')).atFault, false, 'typing clears the outline');
  await closeEverything(page);
}

async function createSeveralCase(page) {
  await openFromPalette(page, 'openCreateNamespace', []);
  await typeInto(page, '#create-namespace-name', 'Bad Name');
  await typeInto(page, '#create-namespace-http-port', LOW_PORT);
  await page.click('#create-namespace-submit-btn');
  await idle(page);
  const shown = await errorDialog(page);
  assert.notEqual(shown, null, 'pressing Create with two mistakes opens an error dialog');
  assert.deepEqual(shown.problems, [
    'A vault name may use only lowercase letters, digits and -.',
    'HTTP port must be between 1 and 65535.',
  ], 'one error dialog lists both problems');
  // A click outside the error dialog closes it, and only it.
  await page.mouse.click(2, 2);
  await settle(page);
  assert.equal(await errorDialog(page), null, 'a click outside closes the error dialog');
  assert.equal(await isShown(page, '#create-namespace-modal'), true, 'the click outside leaves Create Vault open');
  assert.equal((await fieldState(page, '#create-namespace-name')).focused, true, 'focus goes to the first field at fault');
  assert.equal((await fieldState(page, '#create-namespace-http-port')).atFault, true, 'the port is outlined too');
  await closeEverything(page);
}

async function renameSameCase(page) {
  await openFromPalette(page, 'openRenameCurrentNamespace', []);
  await typeInto(page, '#rename-namespace-name', 'default');
  await page.click('#rename-namespace-submit-btn');
  await idle(page);
  assert.equal(await fatalShown(page), false, 'a rename to the current name is not a crash');
  const shown = await errorDialog(page);
  assert.notEqual(shown, null, 'a rename to the current name opens an error dialog');
  assert.deepEqual(shown.problems, ["That is the vault's current name. Pick another name."]);
  await closeEverything(page);
}

async function portsCase(page) {
  await openFromPalette(page, 'openManageNamespacePorts', []);
  const field = '.namespace-ports-input[data-field="port"]';
  await typeInto(page, field, LOW_PORT);
  await page.click('#manage-namespace-ports-save-btn');
  await idle(page);
  const shown = await errorDialog(page);
  assert.notEqual(shown, null, 'saving a port out of range opens an error dialog');
  assert.deepEqual(shown.problems, ['default HTTP port must be between 1 and 65535.']);
  await page.keyboard.press('Escape');
  await settle(page);
  assert.equal((await fieldState(page, field)).focused, true, 'focus goes to the port');
  await closeEverything(page);
}

async function aiKeyCase(page) {
  await openFromPalette(page, 'openAiAgentSettings', [false]);
  const before = await layout(page, '#ai-agent-settings-modal');
  await page.click('#ai-agent-key-save');
  await idle(page);
  const shown = await errorDialog(page);
  assert.notEqual(shown, null, 'Save Key with no key opens an error dialog');
  assert.match(shown.problems[0], /^Paste your .+ API key first\.$/);
  assert.deepEqual(await layout(page, '#ai-agent-settings-modal'), before, 'nothing in AI Agent Settings moves');
  await page.keyboard.press('Escape');
  await settle(page);
  assert.equal((await fieldState(page, '#ai-agent-api-key')).focused, true, 'focus goes to the key field');
  assert.deepEqual(await layout(page, '#ai-agent-settings-modal'), before, 'nothing in AI Agent Settings moved');
  await closeEverything(page);
}

// The password request is answered with a refusal here, so the vault never gets a password.
async function passwordFailureCase(page) {
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.errorDialogTest = {restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (new Request(input, init).method !== 'GET' && url.pathname.includes('/password')) {
        return new Response(JSON.stringify({detail: 'The password could not be set (test).'}),
          {status: 400, headers: {'Content-Type': 'application/json'}});
      }
      return originalFetch(input, init);
    };
  });
  try {
    await openFromPalette(page, 'openAddPassword', []);
    const password = 'correct horse battery staple';
    await page.type('#new-password', password);
    await page.type('#confirm-password', password);
    await settle(page);
    await page.click('[data-password-submit]');
    await idle(page);
    const shown = await errorDialog(page);
    assert.notEqual(shown, null, 'a failed Add Password opens an error dialog');
    assert.deepEqual(shown.problems, ['The password could not be set (test).']);
    assert.equal(await isShown(page, '#new-password'), true, 'the form stays under the error dialog');
    assert.equal((await fieldState(page, '#new-password')).value, password, 'what was typed is kept');
  } finally {
    await page.evaluate(() => window.errorDialogTest.restore());
    await closeEverything(page);
  }
}

async function loadFailureCase(page) {
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.errorDialogTest = {restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname.endsWith('/auth/namespaces')) {
        return new Response(JSON.stringify({detail: 'The vault list could not be read (test).'}),
          {status: 500, headers: {'Content-Type': 'application/json'}});
      }
      return originalFetch(input, init);
    };
  });
  try {
    // Create Vault reads the vault list as it opens.
    await openFromPalette(page, 'openCreateNamespace', []);
    const shown = await errorDialog(page);
    assert.notEqual(shown, null, 'a dialog that fails to load shows an error dialog');
    assert.match(shown.problems[0], /The vault list could not be read \(test\)\.$/, 'it says why');
    await page.keyboard.press('Escape');
    await settle(page);
    assert.equal(await errorDialog(page), null, 'Escape closes the error dialog');
    assert.equal(await isShown(page, '#create-namespace-modal'), false, 'and the dialog that failed to load');
    // Open Vault reads it before it opens.
    await openFromPalette(page, 'openOpenNamespace', []);
    assert.equal(await fatalShown(page), false, 'a failed read before Open Vault is not a crash');
    assert.notEqual(await errorDialog(page), null, 'a failed read before Open Vault shows an error dialog');
    await page.keyboard.press('Escape');
    await settle(page);
    const stack = await page.evaluate(async () => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      return mode.modalStack.length;
    });
    assert.equal(stack, 0, 'no dialog is left open');
  } finally {
    await page.evaluate(() => window.errorDialogTest.restore());
    await closeEverything(page);
  }
}

export async function checkErrorDialogs(page) {
  const failures = [];
  const cases = [
    ['create, existing name', createExistingCase], ['create, two mistakes', createSeveralCase],
    ['rename, same name', renameSameCase], ['ports', portsCase], ['AI key', aiKeyCase],
    ['password failure', passwordFailureCase], ['load failure', loadFailureCase],
  ];
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
