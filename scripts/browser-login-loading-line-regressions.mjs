import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {assertWithinLayoutStep} from './browser-validation/login-logo-geometry.mjs';

// The line under the loading screen's progress bar (docs/ui/login-screen.md, Loading): the
// step at the bar's left edge, the time at its right edge, and every step on one line and
// readable. The steps are read from the server's source, so a longer wording fails here.
const ELAPSED_SHORT = {milliseconds: 0, shown: '0s'};
const ELAPSED_MINUTE = {milliseconds: 59_000, shown: '59s'};
const ELAPSED_LONG = {milliseconds: 659_000, shown: '10m 59s'};
// On a phone the longest time leaves too little room, so a step may be cut there.
const WINDOWS = [
  {width: 1280, height: 800, elapsedShownWhole: [ELAPSED_SHORT, ELAPSED_MINUTE, ELAPSED_LONG]},
  {width: 375, height: 812, elapsedShownWhole: [ELAPSED_SHORT, ELAPSED_MINUTE]},
];
const STATUS_SOURCE_FILES = ['app/api/routes/auth.py', 'app/services/content_cache.py', 'app/services/note_store.py'];
const STATUS_MESSAGE = /hydration_state\.(?:set_phase|begin)\([^)]*?message="([^"]+)"/g;
// The opening message and one for each of the six phases (hydration_state.py).
const STATUS_MESSAGE_COUNT = 7;
const FAILURE_TEXT = 'Your password was accepted, but the workspace could not finish opening: a reason long enough to need several lines.';
const FAILURE_ELAPSED = ELAPSED_MINUTE;

async function readStatusMessages() {
  const sources = await Promise.all(STATUS_SOURCE_FILES.map(path => readFile(new URL(`../${path}`, import.meta.url), 'utf8')));
  const messages = sources.flatMap(source => [...source.matchAll(STATUS_MESSAGE)].map(match => match[1]));
  assert.equal(messages.length, STATUS_MESSAGE_COUNT, `The loading steps were not all found: ${messages.join(', ')}`);
  return messages;
}

async function showLoadingScreen(page) {
  await page.evaluate(async () => {
    const {Auth} = await import('/static/js/modules/auth.js');
    document.getElementById('login-page').style.display = 'flex';
    document.getElementById('login-panel').dataset.revealed = 'true';
    // With no form showing, the loading view swaps in without the slide.
    document.getElementById('login-form-view').hidden = true;
    Auth._showLoginLoadingPanel('', 0);
    Auth._stopLoadingElapsed();
  });
}

async function showStep(page, message, elapsedMilliseconds) {
  await page.evaluate(async (message, elapsedMilliseconds) => {
    const {Auth} = await import('/static/js/modules/auth.js');
    Auth._resetHydrationUI();
    Auth._updateHydrationUI({message, overall_percent: 0});
    Auth._loadingStartedAt = performance.now() - elapsedMilliseconds;
    Auth._showLoadingElapsed();
  }, message, elapsedMilliseconds);
}

async function showFailure(page, text) {
  await page.evaluate(text => {
    const message = document.getElementById('login-loading-message');
    message.dataset.state = 'error';
    message.textContent = text;
  }, text);
}

async function readLine(page) {
  return page.evaluate(() => {
    const textRange = element => {
      const range = document.createRange();
      range.selectNodeContents(element);
      return range;
    };
    const message = document.getElementById('login-loading-message');
    const elapsed = document.getElementById('login-loading-elapsed');
    const bar = document.querySelector('.login-progress-track').getBoundingClientRect();
    const messageRange = textRange(message);
    return {
      barLeft: bar.left,
      barRight: bar.right,
      stepLeft: messageRange.getBoundingClientRect().left,
      timeRight: textRange(elapsed).getBoundingClientRect().right,
      step: message.textContent,
      time: elapsed.textContent,
      // A run of text below the one before it is a new line. (Equal tops cannot tell: the "…"
      // comes from another font, so its run has its own top on the same line.)
      stepLineCount: [...messageRange.getClientRects()].filter((rect, index, rects) => index === 0 || rect.top >= rects[index - 1].bottom).length,
      isStepCut: message.scrollWidth > message.clientWidth,
    };
  });
}

function assertOnTheBarEdges(line, label) {
  assertWithinLayoutStep(line.stepLeft, line.barLeft, `${label}: the step must start at the bar's left edge`);
  assertWithinLayoutStep(line.timeRight, line.barRight, `${label}: the time must end at the bar's right edge`);
}

async function checkStep(page, message, elapsed, window) {
  await showStep(page, message, elapsed.milliseconds);
  const line = await readLine(page);
  const label = `"${message}" at ${elapsed.shown}, ${window.width}px window`;
  assert.equal(line.step, `${message}…`, label);
  assert.equal(line.time, elapsed.shown, label);
  assertOnTheBarEdges(line, label);
  assert.equal(line.stepLineCount, 1, `${label}: the step must stay on one line`);
  if (window.elapsedShownWhole.includes(elapsed)) {
    assert.equal(line.isStepCut, false, `${label}: the step must be shown whole; shorten its wording`);
  }
}

async function checkFailure(page, window) {
  await showStep(page, 'Any step', FAILURE_ELAPSED.milliseconds);
  await showFailure(page, FAILURE_TEXT);
  const line = await readLine(page);
  const label = `A failure, ${window.width}px window`;
  assert.equal(line.time, FAILURE_ELAPSED.shown, label);
  assertOnTheBarEdges(line, label);
  assert(line.stepLineCount > 1, `${label}: a failure must wrap so it can be read`);
  assert.equal(line.isStepCut, false, `${label}: a failure must be shown whole`);
}

export async function checkLoginLoadingLine(browser, origin) {
  const messages = await readStatusMessages();
  const page = await browser.newPage();
  try {
    await page.goto(new URL('/', origin).href, {waitUntil: 'load'});
    await page.waitForSelector('[data-app-ready="true"]');
    await showLoadingScreen(page);
    for (const window of WINDOWS) {
      await page.setViewport({width: window.width, height: window.height});
      for (const message of messages) {
        for (const elapsed of [ELAPSED_SHORT, ELAPSED_MINUTE, ELAPSED_LONG]) {
          await checkStep(page, message, elapsed, window);
        }
      }
      await checkFailure(page, window);
    }
  } finally {
    await page.close();
  }
}
