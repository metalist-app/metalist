import assert from 'node:assert/strict';

import {installRequestMonitor, waitForAppQuiet} from './browser-app-idle.mjs';

// The vault's one AI conversation, live in every view (multi-view editing step 5;
// docs/ready-to-build/multi-view-editing.md, "Step 5's cases"). Two browser tabs on one vault:
// "here" (the suite's page, in front, where what shows is checked) and "there" (a second tab, in
// the background, which acts: a hidden tab does not follow the conversation itself). The server
// answers from a slow scripted AI (tests/fixtures/scripted-ai/slow-answer.json: five parts, a
// second apart).

export const SHARED_AI_CHAT_SUITE = 'shared-ai-chat';
export const SHARED_AI_CHAT_SCRIPT = 'tests/fixtures/scripted-ai/slow-answer.json';

const REQUESTS_QUIET_MS = 300;
const FIRST_PART = 'Part one.';
const LAST_PART = 'Part five.';
// The live state is asked for every half second while an answer is written: a part shows within it.
const SHOWS_WITHIN_MS = 4000;
// A whole answer takes five seconds; two in a row about ten.
const ANSWERED_WITHIN_MS = 20000;

// How often a wait on the background tab checks.
const BACKGROUND_POLL_MS = 200;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

function chatTexts(page) {
  return page.evaluate(() => [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')]
    .map(message => message.textContent.trim()));
}

async function openChat(page) {
  await page.evaluate(async () => {
    const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
    // Showing the chat is a shared preference: a tab loaded before another showed it finds it shown
    // without its models loaded.
    if (!document.body.classList.contains('pref-show-ai-chat')) await AiChatPanel._setVisible(true);
    else if (!AiChatPanel._hasModels()) await AiChatPanel._loadModels();
  });
  await page.waitForFunction(async () => {
    const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
    return AiChatPanel._hasModels() && !AiChatPanel._isLoadingModels;
  // A background tab paints no frames: the default check (each animation frame) would never run.
  }, {polling: BACKGROUND_POLL_MS}).catch(async error => {
    const state = await page.evaluate(async () => {
      const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
      return {shown: document.body.classList.contains('pref-show-ai-chat'), hidden: document.hidden,
        hasModels: AiChatPanel._hasModels(), loading: AiChatPanel._isLoadingModels};
    });
    throw new Error(`open chat: the AI models should load, saw ${JSON.stringify(state)} (${error.message})`);
  });
}

function typeQuestion(page, text) {
  return page.evaluate(text => {
    const input = document.getElementById('ai-chat-input');
    input.focus();
    input.value = text;
    input.dispatchEvent(new Event('input', {bubbles: true}));
  }, text);
}

async function send(page, text) {
  await typeQuestion(page, text);
  await page.evaluate(() => {
    const input = document.getElementById('ai-chat-input');
    input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    input.blur();
  });
}

async function waitForChat(page, label, check, ...args) {
  await page.waitForFunction(check, {timeout: ANSWERED_WITHIN_MS}, ...args).catch(async error => {
    throw new Error(`${label}: the chat here showed ${JSON.stringify(await chatTexts(page))} (${error.message})`);
  });
}

async function clearThere(there) {
  await there.evaluate(() => document.getElementById('ai-chat-clear').click());
}

// Case 1: a question sent there and its answer show here as they are written.
async function liveAnswerCase(here, there) {
  await send(there, 'Question from the other tab');
  await waitForChat(here, 'live answer, first part', first => {
    const texts = [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')].map(m => m.textContent);
    return texts.length === 2 && texts[0].includes('Question from the other tab') && texts[1].includes(first);
  }, FIRST_PART);
  const partial = (await chatTexts(here))[1];
  assert.ok(!partial.includes(LAST_PART), `live answer: the answer should show here before it is whole, got "${partial}"`);
  assert.equal(await here.evaluate(() => document.getElementById('ai-chat-send').textContent), 'Stop',
    'live answer: Stop shows here for the answer the other tab is writing');
  await waitForChat(here, 'live answer, whole', last => [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')]
    .some(message => message.textContent.includes(last)), LAST_PART);
}

// Case 11: a question typed there shows here, and the box here cannot be typed in until it is left.
async function questionBoxCase(here, there) {
  await typeQuestion(there, 'Being typed over there');
  await here.waitForFunction(() => {
    const input = document.getElementById('ai-chat-input');
    return input.readOnly && input.value === 'Being typed over there' && input.title === 'Being typed in another tab';
  }, {timeout: SHOWS_WITHIN_MS}).catch(error => { throw new Error(`question box: the box here should follow and be locked (${error.message})`); });
  await there.evaluate(() => {
    const input = document.getElementById('ai-chat-input');
    input.value = '';
    input.dispatchEvent(new Event('input', {bubbles: true}));
    // A background tab's box never had the focus, so blur() sends no event: send the one the box
    // gets when it is left.
    input.dispatchEvent(new FocusEvent('blur'));
  });
  await here.waitForFunction(() => {
    const input = document.getElementById('ai-chat-input');
    return !input.readOnly && input.value === '';
  }, {timeout: SHOWS_WITHIN_MS}).catch(error => { throw new Error(`question box: the box here should open once left there (${error.message})`); });
}

// Cases 6 and 7: a question sent here while the other tab's answer is written waits its turn, then
// is answered; Stop here ends the answer the other tab's question is getting.
async function waitingAndStopCase(here, there) {
  await clearThere(there);
  await waitForChat(here, 'cleared from the other tab', () => document.querySelectorAll('#ai-chat-messages .ai-chat-message').length === 0);
  await send(there, 'First, from the other tab');
  await waitForChat(here, 'first answer begins', first => [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')]
    .some(message => message.textContent.includes(first)), FIRST_PART);
  await send(here, 'Second, from this tab');
  await waitForChat(here, 'second waits', () => [...document.querySelectorAll('#ai-chat-messages .ai-chat-working-label')]
    .some(label => label.textContent === 'Waiting'));
  await waitForChat(here, 'second answered after the first', last => {
    const texts = [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')].map(m => m.textContent);
    return texts.length === 4 && texts[1].includes(last) && texts[2].includes('Second, from this tab') && texts[3].includes(last);
  }, LAST_PART);
  await idle(here);

  await send(there, 'Third, to be stopped');
  await waitForChat(here, 'third answer begins', first => {
    const texts = [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')].map(m => m.textContent);
    return texts.length === 6 && texts[5].includes(first);
  }, FIRST_PART);
  await here.click('#ai-chat-send');
  await waitForChat(here, 'stopped here', () => [...document.querySelectorAll('#ai-chat-messages .ai-chat-message')]
    .at(-1).textContent.includes('Cancelled by user'));
  const stopped = (await chatTexts(here)).at(-1);
  assert.ok(!stopped.includes(LAST_PART), `stop: the answer should end before it is whole, got "${stopped}"`);
}

// Case 8: Clear Chat there empties the chat here.
async function clearCase(here, there) {
  await clearThere(there);
  await waitForChat(here, 'cleared from the other tab', () => document.querySelectorAll('#ai-chat-messages .ai-chat-message').length === 0);
}

export async function checkSharedAiChat(here, browser) {
  await here.bringToFront();
  const there = await browser.newPage();
  const errors = [];
  there.on('pageerror', error => errors.push(error.message));
  await installRequestMonitor(there);
  await there.goto(here.url());
  await there.waitForSelector('[data-app-ready="true"]');
  await here.bringToFront();
  await openChat(here);
  await openChat(there);
  await idle(here);
  try {
    await liveAnswerCase(here, there);
    await questionBoxCase(here, there);
    await waitingAndStopCase(here, there);
    await clearCase(here, there);
    await pause(REQUESTS_QUIET_MS);
    assert.deepEqual(errors, [], 'the other tab should raise no errors');
  } finally {
    await there.close();
  }
}
