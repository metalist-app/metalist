import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A change of what the view shows is a command, whatever asks for it (agreed with the maintainer
// 2026-11-22, cases 1 to 5; docs/ui/command-gate.md, "Turns"). The list is sorted by Created.
// 1. The × of the sort chip (and of the Untagged chip) while background work has the turn: the
//    change waits for it, then is made. It started at once, beside it.
// 2. A view entry chosen in the command palette while background work has the turn: the same.
// 3. A palette entry chosen while another command runs: it waits for that command, then runs.
// 4. The × clicked twice quickly: the server is asked once.
// 5. (Everything else is as before: a click during a command is ignored.)

const WINDOW = {width: 1200, height: 800};
const REQUESTS_QUIET_MS = 300;
// Long enough for a change that does not wait to have asked the server.
const WOULD_HAVE_ASKED_MS = 400;
const ROWS_TO_LOOK_THROUGH = 12;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// What this view shows now.
function view(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {sort: mode.activeTabSortMode, untagged: mode.isUntaggedView};
  });
}

function setView(page, name, value) {
  return page.evaluate(async ({name, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette[name](value);
  }, {name, value});
}

// Takes the turn and keeps it until letGo: background work, or a command.
async function hold(page, kind) {
  await idle(page);
  await page.evaluate(async (kind) => {
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    const held = new Promise((resolve) => { window.__letTurnGo = resolve; });
    if (kind === 'command') {
      void CommandGate.run('test.heldCommand', () => held);
    } else {
      void CommandGate.runBackground('test.heldBackgroundWork', () => held);
    }
  }, kind);
}

async function letGo(page) {
  await page.evaluate(() => window.__letTurnGo());
  await idle(page);
}

// Opens the palette on `query` with the entry `endpointId` highlighted.
async function paletteOn(page, query, endpointId) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.open();
  });
  await page.waitForSelector('#command-palette-input', {visible: true});
  await page.type('#command-palette-input', query);
  await page.waitForSelector(`#command-palette-results [data-endpoint-id="${endpointId}"]`);
  const selected = () => page.$eval('#command-palette-results .command-palette-row.selected', row => row.dataset.endpointId);
  for (let row = 0; row < ROWS_TO_LOOK_THROUGH && (await selected()) !== endpointId; row += 1) {
    await page.keyboard.press('ArrowDown');
  }
  assert.equal(await selected(), endpointId, `the palette highlights ${endpointId}`);
}

async function closePalette(page) {
  const isOpen = await page.evaluate(() => {
    const modal = document.getElementById('command-palette-modal');
    return modal !== null && modal.style.display !== 'none' && document.querySelector('#command-palette-input') !== null;
  });
  if (isOpen) await page.keyboard.press('Escape');
  await idle(page);
}

async function theChipsWaitForBackgroundWork(page, asked) {
  await setView(page, 'setSortMode', 'created');
  await idle(page);
  let before = asked.length;
  await hold(page, 'background');
  await page.click('#root-sort-indicator-clear');
  await pause(WOULD_HAVE_ASKED_MS);
  assert.deepEqual({asked: asked.length - before, ...await view(page)}, {asked: 0, sort: 'created', untagged: false},
    'the sort chip\'s ×: nothing is asked while background work has the turn');
  await letGo(page);
  assert.deepEqual({asked: asked.length - before, sort: (await view(page)).sort}, {asked: 1, sort: 'normal'},
    'then the order is changed, once');

  await setView(page, 'setIsUntaggedView', true);
  await idle(page);
  before = asked.length;
  await hold(page, 'background');
  await page.click('#untagged-view-indicator-clear');
  await pause(WOULD_HAVE_ASKED_MS);
  assert.deepEqual({asked: asked.length - before, untagged: (await view(page)).untagged}, {asked: 0, untagged: true},
    'the Untagged chip\'s ×: nothing is asked while background work has the turn');
  await letGo(page);
  assert.deepEqual({asked: asked.length - before, untagged: (await view(page)).untagged}, {asked: 1, untagged: false},
    'then the view is changed, once');
}

async function aPaletteEntryWaitsForBackgroundWork(page, asked) {
  await paletteOn(page, 'created', 'view.sort_mode.created');
  const before = asked.length;
  await hold(page, 'background');
  await page.keyboard.press('Enter');
  await pause(WOULD_HAVE_ASKED_MS);
  assert.deepEqual({asked: asked.length - before, sort: (await view(page)).sort}, {asked: 0, sort: 'normal'},
    'a palette entry: nothing is asked while background work has the turn');
  await letGo(page);
  assert.deepEqual({asked: asked.length - before, sort: (await view(page)).sort}, {asked: 1, sort: 'created'},
    'then the order is changed, once');
  await closePalette(page);
}

async function aPaletteEntryWaitsForACommand(page, asked) {
  await paletteOn(page, 'normal', 'view.sort_mode.normal');
  const before = asked.length;
  await hold(page, 'command');
  await page.keyboard.press('Enter');
  await pause(WOULD_HAVE_ASKED_MS);
  assert.deepEqual({asked: asked.length - before, sort: (await view(page)).sort}, {asked: 0, sort: 'created'},
    'a palette entry: nothing is asked while another command runs');
  await letGo(page);
  await page.waitForFunction(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.activeTabSortMode === 'normal';
  });
  await idle(page);
  assert.equal(asked.length - before, 1, 'then the order is changed, once');
  await closePalette(page);
}

async function twoQuickClicksAskOnce(page, asked) {
  await setView(page, 'setSortMode', 'created');
  await idle(page);
  const before = asked.length;
  await page.evaluate(() => {
    const clear = document.getElementById('root-sort-indicator-clear');
    clear.click();
    clear.click();
  });
  await idle(page);
  assert.deepEqual({asked: asked.length - before, sort: (await view(page)).sort}, {asked: 1, sort: 'normal'},
    'the × clicked twice: the server is asked once');
}

export async function checkViewCommands(page) {
  await page.setViewport(WINDOW);
  // Each request that changes the order or the Untagged view of a search context.
  const asked = [];
  const note = request => {
    if (request.method() === 'POST' && /\/tab-state\/(sort-mode|untagged)/.test(request.url())) asked.push(request.url());
  };
  page.on('request', note);
  await runThenCleanUp('view commands', async () => {
    await idle(page);
    await theChipsWaitForBackgroundWork(page, asked);
    await aPaletteEntryWaitsForBackgroundWork(page, asked);
    await aPaletteEntryWaitsForACommand(page, asked);
    await twoQuickClicksAskOnce(page, asked);
  }, async () => {
    page.off('request', note);
    await page.evaluate(() => { if (typeof window.__letTurnGo === 'function') window.__letTurnGo(); });
    await closePalette(page);
    await setView(page, 'setIsUntaggedView', false);
    await setView(page, 'setSortMode', 'normal');
    await idle(page);
  });
}
