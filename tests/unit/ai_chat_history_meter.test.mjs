import assert from 'node:assert/strict';
import test from 'node:test';

import { formatTokens, historyMeterView } from '../../app/static/js/modules/ai-chat/ai-chat-history-meter.js';

const NO_REQUEST = { total: 0, instructions: 0, history: 0, this_turn: 0 };

function meter(fields) {
    return {
        summary_tokens: 0, turn_count: 0, turn_tokens: 0, action_tokens: 0,
        budget_tokens: 32000, context_tokens: 1050000, last_request: NO_REQUEST, ...fields,
    };
}

test('tokens are written short', () => {
    assert.equal(formatTokens(950), '950');
    assert.equal(formatTokens(11400), '11.4k');
    assert.equal(formatTokens(32000), '32k');
    assert.equal(formatTokens(1050000), '1.05M');
});

test('the meter shows how much of the history budget the chat takes, part by part', () => {
    const view = historyMeterView(meter({
        summary_tokens: 1200, turn_count: 6, turn_tokens: 11000, action_tokens: 1200,
    }));
    assert.equal(view.percent, 42);
    assert.deepEqual(view.rows, [
        { label: 'Summary', tokens: '1.2k', share: '4%' },
        { label: 'Turns (6)', tokens: '11k', share: '34%' },
        { label: "Agent's records", tokens: '1.2k', share: '4%' },
        { label: 'Free until summary', tokens: '18.6k', share: '58%' },
    ]);
    assert.equal(view.limit, 'Summarizes at 32k, the most history a chat keeps (the model reads up to 1.05M)');
    assert.deepEqual(view.lastRequest, [], 'no answer yet: no last request');
});

test('a smaller model summarizes at a quarter of its context', () => {
    const view = historyMeterView(meter({ budget_tokens: 8192, context_tokens: 32768 }));
    assert.equal(view.percent, 0);
    assert.equal(view.limit, "Summarizes at 8.2k: a quarter of the model's 32.8k context");
});

test("the last answer's request is shown with its parts", () => {
    const view = historyMeterView(meter({
        last_request: { total: 48200, instructions: 9800, history: 13400, this_turn: 25000 },
    }));
    assert.deepEqual(view.lastRequest.map(row => `${row.label} ${row.tokens}`), [
        'Last request 48.2k', 'Instructions 9.8k', 'History 13.4k', 'Question, notes and pages 25k',
    ]);
});

test('a chat past its budget shows over 100% until the next Send summarizes it', () => {
    const view = historyMeterView(meter({ turn_tokens: 33000 }));
    assert.equal(view.percent, 103);
    assert.equal(view.rows.at(-1).tokens, '0');
});
