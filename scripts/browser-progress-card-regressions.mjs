import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Progress and lasting problems (docs/ui/modals.md, "Errors and status"; agreed
// case by case 2026-10-25, step 5c):
// - while a dialog's action runs, a lasting card in the corner says so, and leaves when it
//   ends; the dialog writes no status line and nothing in it moves;
// - a lost connection still lost after 30 s opens a dialog over its card, which closes by
//   itself once the connection is back.

const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const OPEN_DIALOG_MS = 400;
const POLL_MS = 100;
// The status poll runs every 5 s; a lost or restored connection shows within two polls.
const CONNECTION_WAIT_MS = 12000;
// A lasting problem becomes a dialog after this long (floating-messages.js).
const ESCALATE_MS = 30000;
// How far either side of the 30 s the checks look.
const ESCALATE_MARGIN_MS = 2000;
const ESCALATION_TEXT = "MetaList can't reach its server. Changes can't be saved until it's back; MetaList keeps trying.";
// A port no vault uses, so saving it changes something.
const FREE_PORT = '18999';

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

async function openFromPalette(page, method) {
  await page.evaluate(async name => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    void CommandPalette[name]();
  }, method);
  await pause(OPEN_DIALOG_MS);
  await idle(page);
}

async function cardTexts(page) {
  return page.$$eval('.floating-message .floating-message-text', nodes => nodes.map(node => node.textContent));
}

async function waitForCard(page, text, timeoutMs) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    if ((await cardTexts(page)).includes(text)) return true;
    await pause(POLL_MS);
  }
  return false;
}

async function layout(page, modalSelector) {
  return page.$eval(modalSelector, modal => [...modal.querySelectorAll('input, button, select, textarea, p, h3')]
    .filter(element => element.getClientRects().length > 0)
    .map(element => {
      const rect = element.getBoundingClientRect();
      return [element.tagName, Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
    }));
}

// Requests whose path ends with `suffix` wait until the test lets them go.
async function holdRequests(page, suffix) {
  await page.evaluate(ending => {
    const originalFetch = window.fetch;
    let release = null;
    const released = new Promise(resolve => { release = resolve; });
    window.progressTest = {release, restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (new Request(input, init).method !== 'GET' && url.pathname.endsWith(ending)) await released;
      return originalFetch(input, init);
    };
  }, suffix);
}

async function closeEverything(page) {
  for (let press = 0; press < 2; press += 1) {
    await page.keyboard.press('Escape');
    await settle(page);
  }
  await idle(page);
}

async function progressCase(page, {method, modal, prepare, button, suffix, text}) {
  await openFromPalette(page, method);
  await prepare(page);
  await holdRequests(page, suffix);
  try {
    const before = await layout(page, modal);
    await page.click(button);
    await settle(page);
    assert.equal(await waitForCard(page, text, OPEN_DIALOG_MS), true, `"${text}" shows in the corner while it runs`);
    assert.deepEqual(await layout(page, modal), before, 'nothing in the dialog moves while it runs');
    await page.evaluate(() => window.progressTest.release());
    await idle(page);
    assert.equal((await cardTexts(page)).includes(text), false, `"${text}" leaves when it ends`);
  } finally {
    await page.evaluate(() => {
      window.progressTest.release();
      window.progressTest.restore();
    });
    await idle(page);
    await closeEverything(page);
  }
}

const PORT_FIELD = '.namespace-ports-input[data-field="port"]';

async function typePort(page, port) {
  await page.click(PORT_FIELD, {clickCount: 3});
  await page.type(PORT_FIELD, port);
}

async function portsCase(page) {
  await openFromPalette(page, 'openManageNamespacePorts');
  const saved = await page.$eval(PORT_FIELD, input => input.value);
  await closeEverything(page);
  try {
    await progressCase(page, {
      method: 'openManageNamespacePorts', modal: '#manage-namespace-ports-modal',
      prepare: target => typePort(target, FREE_PORT),
      button: '#manage-namespace-ports-save-btn', suffix: '/namespaces/ports', text: 'Saving vault ports…',
    });
  } finally {
    // The port goes back as it was.
    await openFromPalette(page, 'openManageNamespacePorts');
    await typePort(page, saved);
    await page.click('#manage-namespace-ports-save-btn');
    await idle(page);
  }
  assert.equal(await page.$$eval('#manage-namespace-ports-modal .namespace-modal-status', nodes =>
    nodes.filter(node => node.textContent.trim() !== '').length), 0, 'Manage Vault Ports writes no status line');
  await closeEverything(page);
}

async function idleTimeoutCase(page) {
  await progressCase(page, {
    method: 'openSessionTimeoutSettings', modal: '#session-timeout-modal',
    prepare: async () => {
      await page.waitForSelector('#session-timeout-save-btn:not([disabled])');
    },
    button: '#session-timeout-save-btn', suffix: '/settings/session-timeout', text: 'Saving idle timeout…',
  });
}

async function connectionCase(page) {
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.progressTest = {restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname.endsWith('/auth/status')) throw new TypeError('Failed to fetch');
      return originalFetch(input, init);
    };
  });
  try {
    assert.equal(await waitForCard(page, 'Not saved, reconnecting…', CONNECTION_WAIT_MS), true, 'the connection card shows');
    const lostAt = Date.now();
    await pause(ESCALATE_MS - ESCALATE_MARGIN_MS - (Date.now() - lostAt));
    assert.equal(await page.$('#error-dialog'), null, 'no dialog before 30 s');
    await pause(ESCALATE_MARGIN_MS * 2);
    const escalated = await page.evaluate(() => {
      const text = document.querySelector('#error-dialog .error-dialog-text');
      return text === null ? null : text.textContent;
    });
    assert.equal(escalated, ESCALATION_TEXT, 'after 30 s the lost connection becomes a dialog');
    assert.equal((await cardTexts(page)).includes('Not saved, reconnecting…'), true, 'the card stays under it');
    await page.evaluate(() => window.progressTest.restore());
    assert.equal(await waitForCard(page, 'Reconnected', CONNECTION_WAIT_MS), true, 'the connection comes back');
    await settle(page);
    assert.equal(await page.$('#error-dialog'), null, 'the dialog closes by itself once the connection is back');
  } finally {
    await page.evaluate(() => window.progressTest.restore());
    await closeEverything(page);
  }
}

export async function checkProgressCards(page) {
  const failures = [];
  const cases = [['ports', portsCase], ['idle timeout', idleTimeoutCase], ['connection', connectionCase]];
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
