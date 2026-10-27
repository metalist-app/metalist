import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Floating messages (docs/ui/modals.md, "Errors and status"; agreed case by
// case 2026-10-24):
// - cards float in the upper-right corner, just left of the floating buttons (≡, chat,
//   scroll), their tops level with the first button; on the phone, under the search
//   header, the full width less the page's side padding;
// - a new card goes below the others; when one leaves, the ones below move up;
// - ordinary news leaves by itself after 4 s; hovering pauses its timer and moving away
//   resumes it;
// - a lost connection shows a lasting "Not saved, reconnecting…" card for as long as it
//   lasts, editing locked; once back it is replaced, in the same place, by "Reconnected";
// - nothing on the page moves: scroll, notes and focus stay as they were;
// - Recent Messages in the palette lists what was shown, newest first, with times.

const WIDE_WINDOW = {width: 1280, height: 900};
const PHONE = {width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3};
// The space between a card and the buttons beside it, and between two cards.
const GAP_PX = 8;
// The phone page's side padding (main.css, .container under 640 px).
const PHONE_SIDE_PX = 8;
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// Ordinary news stays this long (floating-messages.js).
const NEWS_MS = 4000;
// How far either side of a timer's end the checks look: before it, the card is still
// there; after it (and the card's fade), it is gone.
const TIMER_MARGIN_MS = 600;
const HOVER_AFTER_MS = 1000;
// Held past the 4 s the card would have stayed without the hover.
const HOVER_HOLD_MS = 5500;
// The status poll runs every 5 s; a lost or restored connection shows within two polls.
const CONNECTION_WAIT_MS = 12000;
// The connection card is still there after longer than ordinary news would stay.
const CONNECTION_HOLD_MS = NEWS_MS + 2000;
const NOTE_COUNT = 30;
const POLL_MS = 100;
const SCROLL_TO_PX = 400;
const CONNECTED_TEXT = 'Not saved, reconnecting…';
const RECONNECTED_TEXT = 'Reconnected';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

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

async function show(page, message, type, options) {
  await page.evaluate(async ({message, type, options}) => {
    const {ErrorHandler} = await import('/static/js/modules/error-handler.js');
    if (type === 'info') ErrorHandler.showInfoBanner(message, options.duration);
    else ErrorHandler.showErrorBanner(message, type, options.duration, {closable: options.closable});
  }, {message, type, options});
  await settle(page);
}

// Each shown card's text and rectangle, top to bottom.
async function cards(page) {
  return page.evaluate(() => [...document.querySelectorAll('.floating-message')].map(card => {
    const rect = card.getBoundingClientRect();
    return {
      text: card.querySelector('.floating-message-text').textContent,
      type: card.dataset.type,
      hasClose: card.querySelector('.floating-message-close') !== null,
      left: Math.round(rect.left), right: Math.round(rect.right),
      top: Math.round(rect.top), bottom: Math.round(rect.bottom),
    };
  }));
}

async function card(page, text) {
  const found = (await cards(page)).find(entry => entry.text === text);
  assert.notEqual(found, undefined, `the card "${text}" shows`);
  return found;
}

async function hasCard(page, text) {
  return (await cards(page)).some(entry => entry.text === text);
}

// Waits up to `timeoutMs` for the card to show; whether it did.
async function waitForCard(page, text, timeoutMs) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    if (await hasCard(page, text)) return true;
    await pause(POLL_MS);
  }
  return false;
}

async function closeCard(page, text) {
  assert.equal((await card(page, text)).hasClose, true, `the card "${text}" has a ×`);
  const box = await page.evaluateHandle(target => [...document.querySelectorAll('.floating-message')]
    .find(node => node.querySelector('.floating-message-text').textContent === target)
    .querySelector('.floating-message-close'), text);
  const rect = await box.asElement().boundingBox();
  await page.mouse.click(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.waitForFunction(target => ![...document.querySelectorAll('.floating-message .floating-message-text')]
    .some(node => node.textContent === target), {}, text);
  await settle(page);
}

async function clearCards(page) {
  await page.evaluate(async () => {
    const {ErrorHandler} = await import('/static/js/modules/error-handler.js');
    ErrorHandler.hideErrorBanner();
  });
  await page.waitForFunction(() => document.querySelector('.floating-message') === null);
  await settle(page);
}

// Where the floating buttons are: the leftmost edge any of them reaches, and the first
// one's top.
async function floatingButtons(page) {
  return page.evaluate(() => {
    const buttons = [...document.querySelectorAll('.global-controls > button')]
      .filter(button => button.getClientRects().length > 0);
    return {
      left: Math.round(Math.min(...buttons.map(button => button.getBoundingClientRect().left))),
      top: Math.round(Math.min(...buttons.map(button => button.getBoundingClientRect().top))),
    };
  });
}

async function cornerCase(page) {
  await show(page, 'Corner news', 'info', {duration: NEWS_MS});
  const buttons = await floatingButtons(page);
  const shown = await card(page, 'Corner news');
  assert.equal(shown.top, buttons.top, 'the card is level with the first floating button');
  assert.equal(shown.right, buttons.left - GAP_PX, 'the card ends just left of the floating buttons');
  await clearCards(page);
}

async function chatShownCase(page) {
  await page.click('#chat-toggle-button');
  await page.waitForSelector('#ai-chat-panel', {visible: true});
  await idle(page);
  try {
    await show(page, 'Beside the chat', 'info', {duration: NEWS_MS});
    const buttons = await floatingButtons(page);
    const shown = await card(page, 'Beside the chat');
    assert.equal(shown.top, buttons.top, 'with the chat shown, the card is level with the first floating button');
    assert.equal(shown.right, buttons.left - GAP_PX, 'with the chat shown, the card ends just left of the floating buttons');
  } finally {
    await clearCards(page);
    await page.click('#chat-toggle-button');
    await idle(page);
  }
}

async function pageState(page) {
  return page.evaluate(() => ({
    scrollY: Math.round(window.scrollY),
    notes: [...document.querySelectorAll('.note > .note-content')].slice(0, 12)
      .map(node => Math.round(node.getBoundingClientRect().top)),
    bodyFirst: document.body.firstElementChild.id,
    focused: document.activeElement === document.body ? 'body' : document.activeElement.id,
  }));
}

async function pageStaysCase(page) {
  await page.evaluate(top => window.scrollTo(0, top), SCROLL_TO_PX);
  await page.focus('#search-input');
  await settle(page);
  const before = await pageState(page);
  assert.equal(before.scrollY, SCROLL_TO_PX, 'the page is scrolled for the check');
  await show(page, 'Still page one', 'info', {duration: NEWS_MS});
  await show(page, 'Still page two', 'error', {duration: NEWS_MS, closable: true});
  assert.deepEqual(await pageState(page), before, 'showing cards moves nothing and keeps focus');
  await closeCard(page, 'Still page two');
  assert.deepEqual(await pageState(page), before, 'closing a card with × moves nothing and keeps focus');
  await clearCards(page);
  assert.deepEqual(await pageState(page), before, 'cards leaving move nothing');
  await page.evaluate(() => document.activeElement.blur());
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
}

async function stackingCase(page) {
  await show(page, 'First news', 'info', {duration: NEWS_MS});
  await show(page, 'Second news', 'error', {duration: NEWS_MS, closable: true});
  await show(page, 'Third news', 'error', {duration: NEWS_MS, closable: true});
  const shown = await cards(page);
  assert.deepEqual(shown.map(entry => entry.text), ['First news', 'Second news', 'Third news'],
    'a new card goes below the others');
  const [first, second, third] = shown;
  assert.equal(second.top, first.bottom + GAP_PX, 'the second card sits just below the first');
  assert.equal(third.top, second.bottom + GAP_PX, 'the third card sits just below the second');
  assert.equal(second.right, first.right, 'the cards share their right edge');
  await closeCard(page, 'Second news');
  const after = await cards(page);
  assert.deepEqual(after.map(entry => entry.text), ['First news', 'Third news'], 'the closed card leaves');
  assert.equal(after[0].top, first.top, 'the card above stays where it was');
  assert.equal(after[1].top, first.bottom + GAP_PX, 'the card below moves up into the gap');
  await clearCards(page);
}

async function timerCase(page) {
  // The mouse rests away from the corner, so no hover holds the card.
  await page.mouse.move(1, WIDE_WINDOW.height - 1);
  await show(page, 'Timed news', 'info', {duration: NEWS_MS});
  await pause(NEWS_MS - TIMER_MARGIN_MS);
  assert.equal(await hasCard(page, 'Timed news'), true, 'ordinary news is still there just before 4 s');
  await pause(TIMER_MARGIN_MS * 2);
  assert.equal(await hasCard(page, 'Timed news'), false, 'ordinary news has left just after 4 s');
}

async function hoverCase(page) {
  await page.mouse.move(1, WIDE_WINDOW.height - 1);
  await show(page, 'Hovered news', 'info', {duration: NEWS_MS});
  await pause(HOVER_AFTER_MS);
  const shown = await card(page, 'Hovered news');
  await page.mouse.move((shown.left + shown.right) / 2, (shown.top + shown.bottom) / 2);
  await pause(HOVER_HOLD_MS);
  assert.equal(await hasCard(page, 'Hovered news'), true, 'hovering keeps the card past its 4 s');
  await page.mouse.move(1, WIDE_WINDOW.height - 1);
  const remaining = NEWS_MS - HOVER_AFTER_MS;
  await pause(remaining - TIMER_MARGIN_MS);
  assert.equal(await hasCard(page, 'Hovered news'), true, 'after the hover, the timer resumes where it paused');
  await pause(TIMER_MARGIN_MS * 2);
  assert.equal(await hasCard(page, 'Hovered news'), false, 'after the hover, the card leaves when its time runs out');
}

async function editingLocked(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return !mode.isConnected && document.querySelector('.note-content.disconnected-state') !== null;
  });
}

// The status poll's requests fail as if the server were unreachable.
async function cutConnection(page) {
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.floatingMessageTest = {restore: () => { window.fetch = originalFetch; }};
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname.endsWith('/auth/status')) throw new TypeError('Failed to fetch');
      return originalFetch(input, init);
    };
  });
}

async function connectionCase(page) {
  await cutConnection(page);
  try {
    assert.equal(await waitForCard(page, CONNECTED_TEXT, CONNECTION_WAIT_MS), true,
      `a lost connection shows "${CONNECTED_TEXT}"`);
    await settle(page);
    const lost = await card(page, CONNECTED_TEXT);
    assert.equal(lost.hasClose, false, 'the connection card has no ×');
    assert.equal(await editingLocked(page), true, 'editing is locked while the connection is lost');
    await pause(CONNECTION_HOLD_MS);
    assert.equal(await hasCard(page, CONNECTED_TEXT), true, 'the connection card stays while the connection is lost');
    assert.equal((await cards(page)).filter(entry => entry.text === CONNECTED_TEXT).length, 1,
      'later failed polls add no second connection card');
    await page.evaluate(() => window.floatingMessageTest.restore());
    assert.equal(await waitForCard(page, RECONNECTED_TEXT, CONNECTION_WAIT_MS), true,
      `a restored connection shows "${RECONNECTED_TEXT}"`);
    await settle(page);
    assert.equal(await hasCard(page, CONNECTED_TEXT), false, 'the connection card leaves once the connection is back');
    const back = await card(page, RECONNECTED_TEXT);
    assert.equal(back.top, lost.top, '"Reconnected" takes the connection card\'s place');
    assert.equal(await editingLocked(page), false, 'editing is unlocked once the connection is back');
  } finally {
    await page.evaluate(() => {
      if (window.floatingMessageTest) window.floatingMessageTest.restore();
    });
    await clearCards(page);
  }
}

async function recentMessagesCase(page) {
  await show(page, 'Recent one', 'info', {duration: NEWS_MS});
  await show(page, 'Recent two', 'error', {duration: NEWS_MS, closable: true});
  await clearCards(page);
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.open();
  });
  await page.type('#command-palette-input', 'recent messages');
  await idle(page);
  assert.notEqual(await page.$('#command-palette-results [data-endpoint-id="form.recent_messages"]'), null,
    'the palette offers Recent Messages');
  await page.click('#command-palette-results [data-endpoint-id="form.recent_messages"]');
  await page.waitForSelector('#recent-messages-modal .recent-message', {visible: true});
  const rows = await page.$$eval('#recent-messages-modal .recent-message', nodes => nodes.map(node => ({
    text: node.querySelector('.recent-message-text').textContent,
    time: node.querySelector('.recent-message-time').textContent,
  })));
  assert.deepEqual(rows.slice(0, 2).map(row => row.text), ['Recent two', 'Recent one'], 'the newest message is listed first');
  for (const row of rows) assert.match(row.time, /^\d{1,2}:\d{2}:\d{2}/, 'each message shows its time');
  assert.equal(rows.some(row => row.text === CONNECTED_TEXT), true, 'the connection card is listed too');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#recent-messages-modal', {hidden: true});
  await idle(page);
}

// The same page at a phone's size: a second page would sign this one out.
async function phoneCase(page) {
  await page.setViewport(PHONE);
  await page.reload();
  try {
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await show(page, 'Phone news', 'info', {duration: NEWS_MS});
    const header = await page.$eval('.controls', node => Math.round(node.getBoundingClientRect().bottom));
    const shown = await card(page, 'Phone news');
    assert.equal(shown.top, header + GAP_PX, 'on the phone the card sits just under the search header');
    assert.equal(shown.left, PHONE_SIDE_PX, 'on the phone the card starts at the page\'s side padding');
    // The page's own width: the window's less a scrollbar. A phone's scrollbar floats over
    // the page; Firefox's phone emulation keeps the desktop's, which takes 15 px.
    const pageWidth = await page.evaluate(() => document.documentElement.clientWidth);
    assert.equal(shown.right, pageWidth - PHONE_SIDE_PX, 'on the phone the card ends at the page\'s side padding');
  } finally {
    await page.setViewport(WIDE_WINDOW);
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
  }
}

async function seedNotes(page) {
  return page.evaluate(async count => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (let index = 0; index < count; index += 1) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>Floating message note ${index}</p>`, '');
      ids.push(note.id);
    }
    return ids;
  }, NOTE_COUNT);
}

export async function checkFloatingMessages(page) {
  await page.setViewport(WIDE_WINDOW);
  const noteIds = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('floating messages', async () => {
    // Every case runs, and their assertion failures are reported together.
    const failures = [];
    const cases = [
      ['corner', () => cornerCase(page)], ['chat shown', () => chatShownCase(page)],
      ['page stays', () => pageStaysCase(page)], ['stacking', () => stackingCase(page)],
      ['timer', () => timerCase(page)], ['hover', () => hoverCase(page)],
      ['connection', () => connectionCase(page)],
      // After the connection case: it lists that case's card too.
      ['recent messages', () => recentMessagesCase(page)],
      ['phone', () => phoneCase(page)],
    ];
    for (const [label, run] of cases) {
      try {
        await run();
      } catch (error) {
        if (!(error instanceof assert.AssertionError)) throw error;
        failures.push(`${label}: ${error.message}`);
        console.log(`FAIL ${label}: ${error.message}`);
        await page.keyboard.press('Escape');
        await idle(page);
      }
    }
    if (failures.length > 0) throw new assert.AssertionError({message: failures.join('\n')});
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, noteIds);
  });
}
