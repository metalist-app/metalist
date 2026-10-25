import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The AI tagging dialogs on MetaList's own dialogs (agreed case by case 2026-10-25): AI-Proposed
// Tags and AI Tagging Vocabulary open like every other dialog (a × at the top right, the shared
// button row), 560 px wide; a refused or failed Apply/Save opens the error dialog over them with
// the choices kept and nothing moved; Apply's result is a corner card; a vocabulary that cannot
// be read shows the error and leaves nothing open; Escape, a click outside and × close them.

const WINDOW = {width: 1280, height: 900};
const DIALOG_WIDTH_PX = 560;
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const POLL_MS = 100;
const CARD_WAIT_MS = 3000;
const OPEN_DIALOG_MS = 400;

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

// Runs the palette command itself, as choosing it in the palette does.
async function runCommand(page, endpointId) {
  await page.evaluate(id => {
    void import('/static/js/modules/command-palette/command-palette-controller.js')
      .then(({CommandPalette}) => CommandPalette._endpoints.find(endpoint => endpoint.id === id).execute());
  }, endpointId);
  await pause(OPEN_DIALOG_MS);
  await idle(page);
}

// Answers requests whose path ends with `suffix` with `status` and `body`.
async function answerRequests(page, suffix, status, body) {
  await page.evaluate(({ending, status, body}) => {
    const originalFetch = window.fetch;
    window.aiTaggingTest = {restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname.endsWith(ending)) {
        return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
      }
      return originalFetch(input, init);
    };
  }, {ending: suffix, status, body});
}

async function restoreRequests(page) {
  await page.evaluate(() => {
    if (window.aiTaggingTest) window.aiTaggingTest.restore();
  });
}

async function dialogState(page, modalSelector) {
  return page.evaluate(selector => {
    const modal = document.querySelector(selector);
    const shown = modal instanceof HTMLElement && modal.getClientRects().length > 0;
    if (!shown) return {shown: false};
    const content = modal.querySelector('.modal-content');
    const row = content.querySelector('.dialog-actions');
    return {
      shown: true,
      isNativeDialog: modal.tagName === 'DIALOG',
      inModalStack: modal.classList.contains('modal'),
      width: Math.round(content.getBoundingClientRect().width),
      hasClose: content.querySelector(':scope > .modal-close-button') !== null,
      hasRow: row !== null,
      buttons: [...content.querySelectorAll('.dialog-actions button')].map(button => button.textContent.trim()),
      sharedRow: content.querySelector('.dialog-actions [data-modal-safe-focus]') !== null,
      layout: [...content.querySelectorAll('input, select, button, h2, p')]
        .filter(element => element.getClientRects().length > 0)
        .map(element => {
          const rect = element.getBoundingClientRect();
          return [element.tagName, Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
        }),
    };
  }, modalSelector);
}

async function errorText(page) {
  return page.evaluate(() => {
    const text = document.querySelector('#error-dialog .error-dialog-text');
    return text === null ? null : text.textContent;
  });
}

async function waitForCard(page, text) {
  const until = Date.now() + CARD_WAIT_MS;
  while (Date.now() < until) {
    const texts = await page.$$eval('.floating-message .floating-message-text', nodes => nodes.map(node => node.textContent));
    if (texts.includes(text)) return true;
    await pause(POLL_MS);
  }
  return false;
}

async function modalStackDepth(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.modalStack.length;
  });
}

async function closeEverything(page) {
  for (let press = 0; press < 2; press += 1) {
    await page.keyboard.press('Escape');
    await settle(page);
  }
  await restoreRequests(page);
  await idle(page);
}

const PROPOSALS = '#ai-proposed-tags-modal';
const VOCABULARY = '#ai-tagging-vocabulary-modal';

async function openProposals(page) {
  await runCommand(page, 'form.proposals');
  assert.equal((await dialogState(page, PROPOSALS)).shown, true, 'AI-Proposed Tags opens as a MetaList dialog');
}

async function proposalsLookCase(page) {
  await runCommand(page, 'form.proposals');
  const state = await dialogState(page, PROPOSALS);
  assert.equal(state.shown, true, 'AI-Proposed Tags opens as a MetaList dialog');
  assert.equal(state.isNativeDialog, false, 'not the browser\'s own dialog');
  assert.equal(state.inModalStack, true, 'a .modal like every other dialog');
  assert.equal(state.width, DIALOG_WIDTH_PX, 'as wide as before');
  assert.equal(state.hasClose, true, 'with its × at the top right');
  assert.deepEqual(state.buttons, ['Cancel', 'Apply'], 'Cancel, then Apply at the right');
  assert.equal(state.sharedRow, true, 'from the shared button row');
  await closeEverything(page);
}

async function proposalsRefusedCase(page) {
  await openProposals(page);
  await page.select(`${PROPOSALS} select[name="action"]`, 'remove');
  await page.type(`${PROPOSALS} input[name="tag"]`, 'trip');
  const before = await dialogState(page, PROPOSALS);
  await answerRequests(page, '/proposals/manage', 400, {detail: 'No proposals to change (test).'});
  await page.click('#ai-proposals-apply');
  await idle(page);
  assert.equal(await errorText(page), 'No proposals to change (test).', 'a refused Apply opens the error dialog');
  assert.deepEqual((await dialogState(page, PROPOSALS)).layout, before.layout, 'nothing in the dialog moves');
  await page.keyboard.press('Escape');
  await settle(page);
  assert.equal(await errorText(page), null, 'Escape closes the error dialog');
  const kept = await page.evaluate(selector => ({
    action: document.querySelector(`${selector} select[name="action"]`).value,
    tag: document.querySelector(`${selector} input[name="tag"]`).value,
  }), PROPOSALS);
  assert.deepEqual(kept, {action: 'remove', tag: 'trip'}, 'the choices are kept');
  await closeEverything(page);
}

async function proposalsResultCase(page) {
  await openProposals(page);
  await answerRequests(page, '/proposals/manage', 200, {proposals: 3, notes: 2, changed: false});
  await page.click('#ai-proposals-apply');
  await idle(page);
  assert.equal(await waitForCard(page, '3 proposals updated across 2 notes.'), true, 'the result is a corner card');
  assert.equal((await dialogState(page, PROPOSALS)).shown, true, 'the dialog stays open');
  await closeEverything(page);
}

async function closingCase(page) {
  for (const [label, close] of [
    ['Escape', target => target.keyboard.press('Escape')],
    ['a click outside', target => target.mouse.click(2, 2)],
    ['×', target => target.click(`${PROPOSALS} .modal-close-button`)],
  ]) {
    await openProposals(page);
    await close(page);
    await settle(page);
    assert.equal((await dialogState(page, PROPOSALS)).shown, false, `${label} closes it`);
    assert.equal(await modalStackDepth(page), 0, `${label} leaves nothing open`);
  }
}

async function vocabularyCase(page) {
  await runCommand(page, 'form.tagging_vocabulary');
  const state = await dialogState(page, VOCABULARY);
  assert.equal(state.shown, true, 'AI Tagging Vocabulary opens as a MetaList dialog');
  assert.equal(state.inModalStack, true, 'a .modal like every other dialog');
  assert.deepEqual(state.buttons, ['Cancel', 'Save'], 'Cancel, then Save at the right');
  assert.equal(state.sharedRow, true, 'from the shared button row');
  await closeEverything(page);
}

async function vocabularyLoadFailureCase(page) {
  await answerRequests(page, '/proposals/settings', 500, {detail: 'The tagging settings could not be read (test).'});
  try {
    await runCommand(page, 'form.tagging_vocabulary');
    const shown = await errorText(page);
    assert.notEqual(shown, null, 'a vocabulary that cannot be read shows an error dialog');
    await page.keyboard.press('Escape');
    await settle(page);
    assert.equal(await errorText(page), null, 'Escape closes it');
    assert.equal((await dialogState(page, VOCABULARY)).shown, false, 'and nothing else is open');
    assert.equal(await modalStackDepth(page), 0, 'no dialog is left open');
  } finally {
    await restoreRequests(page);
  }
}

export async function checkAiTaggingDialogs(page) {
  await page.setViewport(WINDOW);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const failures = [];
  const cases = [
    ['proposals look', proposalsLookCase], ['proposals refused', proposalsRefusedCase],
    ['proposals result', proposalsResultCase], ['closing', closingCase],
    ['vocabulary', vocabularyCase], ['vocabulary load failure', vocabularyLoadFailureCase],
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
