import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Summarize Now (docs/ui/ai-chat.md, Long chats): every turn the AI still sees becomes a
// summary, whose entry lands at the end of the chat where it was chosen. While it is
// made, the chat says so there and Send waits (Enter says why). Afterwards the chat
// scrolls the minimum distance to show the entry's header line; opening it keeps that
// line in place. Clear during a summary drops it.
//
// The page stands in for the server's chat: a transcript of answered turns, and a
// Summarize Now that answers when the test lets it.

const SETTLE_MS = 300;
const TURN_COUNT = 6;
const LONG_ANSWER_SENTENCES = 12;
// How late the fake server answers a read of the chat, for the Clear-during-a-summary race.
const SLOW_SESSION_MS = 300;

async function installFakeServer(page) {
    await page.evaluate(async ({turnCount, sentences}) => {
        const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
        const {stateValuesEqual} = await import('/static/js/modules/application-state.js');
        const {provider, model} = AiChatPanel._getSettings();
        const groups = [{provider, label: 'OpenAI', models: [model]}];
        if (!stateValuesEqual(AiChatPanel._modelGroups, groups)) AiChatPanel._modelGroups = groups;
        AiChatPanel._syncSettingsControls();
        const fake = {originalFetch: window.fetch, transcript: [], summaries: [], chats: 0, summarizeRequests: 0, sessionDelayMs: 0,
            release: null};
        window.chatSummaryTest = fake;
        const message = (id, role, content) => ({
            id, role, content, rendered_content: role === 'assistant' ? `<p>${content}</p>` : '',
            thinking: '', rendered_thinking: '', status: 'complete', error: '', provider: 'openai', model,
            visibility: 'sent', activities: [],
        });
        fake.addTurn = (number) => fake.transcript.push(
            message(`user-${number}`, 'user', `Question ${number}`),
            message(`assistant-${number}`, 'assistant', `Answer ${number}. ${'A long sentence of the answer. '.repeat(sentences)}`),
        );
        for (let number = 1; number <= turnCount; number += 1) fake.addTurn(number);
        const json = (body, status) => new Response(JSON.stringify(body), {
            status, headers: {'Content-Type': 'application/json'},
        });
        window.fetch = async (url, options) => {
            const path = new URL(url, location.href).pathname;
            const method = options && options.method ? options.method : 'GET';
            if (path === '/api2/ai/session' && method === 'GET') {
                // The chat as it was when asked, answered after sessionDelayMs.
                const answer = {messages: [...fake.transcript], summaries: [...fake.summaries]};
                await new Promise(resolve => setTimeout(resolve, fake.sessionDelayMs));
                return json(answer, 200);
            }
            if (path === '/api2/ai/session' && method === 'DELETE') {
                fake.transcript.splice(0);
                fake.summaries.splice(0);
                return json({message: 'Chat cleared'}, 200);
            }
            if (path === '/api2/ai/history-meter') {
                // A token per four characters of what the AI still sees directly.
                const sent = fake.transcript.filter(shown => shown.visibility === 'sent');
                const turnTokens = Math.round(sent.reduce((total, shown) => total + shown.content.length, 0) / 4);
                return json({
                    summary_tokens: fake.summaries.length > 0 ? 50 : 0, turn_count: sent.length / 2,
                    turn_tokens: turnTokens, action_tokens: 0, budget_tokens: 32000, context_tokens: 1050000,
                    last_request: {total: 48200, instructions: 9800, history: 13400, this_turn: 25000},
                }, 200);
            }
            if (path === '/api2/ai/chat') {
                fake.chats += 1;
                return json({detail: 'No Send expected'}, 409);
            }
            if (path === '/api2/ai/chat/summarize') {
                fake.summarizeRequests += 1;
                await new Promise(resolve => { fake.release = resolve; });
                if (fake.transcript.length === 0) return new Response('{"type":"nothing"}\n', {status: 200});
                for (const shown of fake.transcript) shown.visibility = 'summarized';
                for (const summary of fake.summaries) summary.visibility = 'summarized';
                fake.summaries.push({
                    id: `summary-${fake.summaries.length + 1}`, content: 'The chat so far, in short.',
                    rendered_content: '<ul><li>The chat so far, in short.</li><li>Second point.</li></ul>',
                    after_message_id: fake.transcript.at(-1).id, visibility: 'sent',
                });
                return new Response('{"type":"summarized"}\n', {status: 200});
            }
            return fake.originalFetch(url, options);
        };
        await AiChatPanel._loadSession({shouldScrollToBottom: true});
    }, {turnCount: TURN_COUNT, sentences: LONG_ANSWER_SENTENCES});
}

function menuLabels(page) {
    return page.$$eval('.context-menu.is-visible button', buttons => buttons
        .filter(button => button.getClientRects().length).map(button => button.textContent.trim()));
}

// The menu is read once it shows: Firefox draws it a moment later (CI, 2026-11-04).
async function rightClickAnswer(page, messageId) {
    await page.click(`[data-message-id="${messageId}"] .ai-chat-message-content`, {button: 'right'});
    await page.waitForSelector('.context-menu.is-visible button', {visible: true});
}

// Where an element's top and bottom sit, measured from the top of the chat's scroll area,
// and `end`: where the last item's bottom sits when the chat is scrolled to its end (above
// the chat's bottom padding).
function placeInChat(page, selector) {
    return page.evaluate(selector => {
        const chat = document.getElementById('ai-chat-messages');
        const box = chat.getBoundingClientRect();
        const element = document.querySelector(selector).getBoundingClientRect();
        const end = box.height - parseFloat(getComputedStyle(chat).paddingBottom);
        return {top: element.top - box.top, bottom: element.bottom - box.top, end};
    }, selector);
}

async function chooseSummarizeNow(page, messageId) {
    await rightClickAnswer(page, messageId);
    assert.deepEqual(await menuLabels(page), ['Copy Response', 'Summarize Now']);
    const buttons = await page.$$('.context-menu.is-visible button');
    await buttons[1].click();
    await page.waitForFunction(() => window.chatSummaryTest.release !== null);
    // A click while the menu still shows only closes it: the next step waits for it to go.
    await page.waitForFunction(() => document.querySelector('.context-menu.is-visible') === null);
}

async function finishSummary(page) {
    await page.evaluate(() => { const release = window.chatSummaryTest.release; window.chatSummaryTest.release = null; release(); });
    await page.waitForFunction(async () => {
        const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
        return !AiChatPanel._isSummarizing;
    });
    await waitForAppQuiet(page, SETTLE_MS);
}

export async function checkAiChatSummary(page) {
    await page.evaluate(async () => {
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        await CommandPalette.applyPreference('pref.show_ai_chat', true);
    });
    await page.waitForFunction(async () => {
        const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
        return !AiChatPanel._isLoadingModels;
    });
    await installFakeServer(page);
    try {
        const latest = `assistant-${TURN_COUNT}`;

        // The history meter sits above the message box and shows how full the history is.
        await page.waitForSelector('#ai-chat-history-meter:not([hidden])');
        const meterBefore = await page.$eval('.ai-chat-history-meter-label', node => node.textContent);
        assert.match(meterBefore, /^History [1-9]\d*%$/, 'the meter shows the history taken');
        await page.hover('#ai-chat-history-meter');
        const details = await page.$eval('.ai-chat-history-meter-details', node => ({
            shown: getComputedStyle(node).display !== 'none',
            rows: [...node.querySelectorAll('.ai-chat-history-meter-row > span:first-child')].map(cell => cell.textContent),
        }));
        assert(details.shown, 'hovering the meter shows its breakdown');
        assert.deepEqual(details.rows, ['Summary', `Turns (${TURN_COUNT})`, "Agent's records", 'Free until summary',
            'Last request', 'Instructions', 'History', 'Question, notes and pages']);
        await page.mouse.move(0, 0);
        const chatBox = await page.$eval('#ai-chat-messages', node => node.getBoundingClientRect().height);

        // At the end of the chat: the working line, then the entry, land at the end and
        // the chat scrolls just far enough to show them.
        const before = await placeInChat(page, `[data-message-id="${latest}"]`);
        assert.equal(Math.round(before.bottom), Math.round(before.end), 'the chat starts scrolled to its end');
        await chooseSummarizeNow(page, latest);
        const working = await placeInChat(page, '.ai-chat-summary-pending');
        assert.equal(Math.round(working.bottom), Math.round(working.end), 'the working line shows at the end');
        assert.match(await page.$eval('.ai-chat-summary-pending', node => node.textContent), /Summarizing earlier conversation/);

        // Enter while it works sends nothing and says why.
        await page.click('#ai-chat-input');
        await page.type('#ai-chat-input', 'Too soon');
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => [...document.querySelectorAll('.floating-message-text')]
            .some(node => node.textContent === 'Wait for the summary to finish'));
        assert.equal(await page.evaluate(() => window.chatSummaryTest.chats), 0, 'Enter sent nothing');
        assert.equal(await page.$eval('#ai-chat-input', input => input.value), 'Too soon', 'the message stays');

        await finishSummary(page);
        const entry = await placeInChat(page, '[data-summary-id="summary-1"]');
        assert.equal(Math.round(entry.bottom), Math.round(entry.end), 'the entry shows at the end, just in view');
        const latestAfter = await placeInChat(page, `[data-message-id="${latest}"]`);
        assert(latestAfter.bottom < entry.top, 'the entry sits after the latest turn');
        assert.equal(await page.$$eval('.ai-chat-summary-pending', nodes => nodes.length), 0);
        const meterAfter = await page.$eval('.ai-chat-history-meter-label', node => node.textContent);
        assert.equal(meterAfter, 'History 0%', 'after Summarize Now only the short summary is left');
        assert.equal(await page.$eval('#ai-chat-messages', node => node.getBoundingClientRect().height), chatBox,
            'the meter updating moves nothing');

        // Opening the entry keeps its header line where it is.
        const headerBefore = await placeInChat(page, '[data-summary-id="summary-1"] > summary');
        await page.click('[data-summary-id="summary-1"] > summary');
        await waitForAppQuiet(page, SETTLE_MS);
        const headerAfter = await placeInChat(page, '[data-summary-id="summary-1"] > summary');
        assert.equal(Math.round(headerAfter.top), Math.round(headerBefore.top), 'opening the entry keeps its header line still');
        await page.click('[data-summary-id="summary-1"] > summary');

        // Nothing new since the summary: the menu has no Summarize Now.
        await rightClickAnswer(page, latest);
        assert.deepEqual(await menuLabels(page), ['Copy Response'], 'nothing to summarize: no Summarize Now');
        await page.keyboard.press('Escape');

        // Scrolled up, reading: the chat scrolls down just far enough to show the entry.
        await page.evaluate(number => window.chatSummaryTest.addTurn(number), TURN_COUNT + 1);
        await page.evaluate(async () => {
            const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
            await AiChatPanel._loadSession({shouldScrollToBottom: false});
            document.getElementById('ai-chat-messages').scrollTop = 0;
        });
        await chooseSummarizeNow(page, 'assistant-1');
        await finishSummary(page);
        const second = await placeInChat(page, '[data-summary-id="summary-2"]');
        assert.equal(Math.round(second.bottom), Math.round(second.end), 'the new entry shows at the bottom edge');

        // Clear while a summary is made: the chat ends empty and the summary is dropped. The
        // chat read again after the summary lands late: Clear waited for the summary but not
        // for that read, which put the chat back after Clear emptied it (Firefox, CI, 2026-11-04).
        await page.evaluate(delayMs => { window.chatSummaryTest.sessionDelayMs = delayMs; }, SLOW_SESSION_MS);
        await page.evaluate(number => window.chatSummaryTest.addTurn(number), TURN_COUNT + 2);
        await page.evaluate(async () => {
            const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
            await AiChatPanel._loadSession({shouldScrollToBottom: true});
        });
        await chooseSummarizeNow(page, `assistant-${TURN_COUNT + 2}`);
        await page.click('#ai-chat-clear');
        await finishSummary(page);
        await page.waitForFunction(() => document.querySelectorAll('#ai-chat-messages > *').length === 0);
    } finally {
        await page.evaluate(() => { window.fetch = window.chatSummaryTest.originalFetch; delete window.chatSummaryTest; });
    }
    console.log('PASS Summarize Now lands at the end, comes into view, waits for Send and Clear');
}
