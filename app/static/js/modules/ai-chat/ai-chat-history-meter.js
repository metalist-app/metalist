/**
 * The chat's history meter (docs/ui/ai-chat.md, Long chats): a thin bar above the
 * message box with "History N%", filling as the chat grows. The automatic summary
 * happens when it would pass 100%. Hovering shows what the history is made of, and what
 * the latest answer's last request to the model was made of.
 *
 * The numbers come from the server (GET /ai/history-meter), counted as the automatic
 * summary counts them.
 */

import { escapeHtml } from '../html-escape.js';

const PERCENT = 100;
const THOUSAND = 1000;
const MILLION = 1000000;
const TOKEN_FIELDS = ['summary_tokens', 'turn_count', 'turn_tokens', 'action_tokens', 'budget_tokens', 'context_tokens'];
const REQUEST_FIELDS = ['total', 'instructions', 'history', 'this_turn'];
// One decimal for thousands (11.4k), two for millions (1.05M).
const THOUSANDS_DECIMALS = 1;
const MILLIONS_DECIMALS = 2;
// The history may take a quarter of the model's context (chat_compaction.py).
const HISTORY_SHARE_OF_CONTEXT = 4;

function requireCount(value, name) {
    if (!Number.isInteger(value) || value < 0) {
        throw new Error(`History meter ${name} must be a count`);
    }
}

export function validateHistoryMeter(meter) {
    if (!meter || typeof meter !== 'object' || !meter.last_request || typeof meter.last_request !== 'object') {
        throw new Error('History meter must be an object with its last request');
    }
    for (const field of TOKEN_FIELDS) requireCount(meter[field], field);
    for (const field of REQUEST_FIELDS) requireCount(meter.last_request[field], `last_request.${field}`);
    if (meter.budget_tokens < 1) {
        throw new Error('History meter budget must be positive');
    }
    return meter;
}

function trimmed(value, decimals) {
    return value.toFixed(decimals).replace(/\.?0+$/, '');
}

/** Tokens the way the meter writes them: 950, 11.4k, 1.05M. */
export function formatTokens(tokens) {
    requireCount(tokens, 'tokens');
    if (tokens < THOUSAND) return String(tokens);
    if (tokens < MILLION) return `${trimmed(tokens / THOUSAND, THOUSANDS_DECIMALS)}k`;
    return `${trimmed(tokens / MILLION, MILLIONS_DECIMALS)}M`;
}

function share(tokens, budget) {
    return `${Math.round((tokens / budget) * PERCENT)}%`;
}

/** What the meter shows: its percentage, the history rows, the limit, the last request. */
export function historyMeterView(meter) {
    validateHistoryMeter(meter);
    const budget = meter.budget_tokens;
    const used = meter.summary_tokens + meter.turn_tokens + meter.action_tokens;
    const free = Math.max(budget - used, 0);
    let limit = `Summarizes at ${formatTokens(budget)}: a quarter of the model's ${formatTokens(meter.context_tokens)} context`;
    if (budget * HISTORY_SHARE_OF_CONTEXT < meter.context_tokens) {
        limit = `Summarizes at ${formatTokens(budget)}, the most history a chat keeps (the model reads up to ${formatTokens(meter.context_tokens)})`;
    }
    const request = meter.last_request;
    let lastRequest = [];
    if (request.total > 0) {
        lastRequest = [
            { label: 'Last request', share: '', tokens: formatTokens(request.total) },
            { label: 'Instructions', share: '', tokens: formatTokens(request.instructions) },
            { label: 'History', share: '', tokens: formatTokens(request.history) },
            { label: 'Question, notes and pages', share: '', tokens: formatTokens(request.this_turn) },
        ];
    }
    return {
        percent: Math.round((used / budget) * PERCENT),
        rows: [
            { label: 'Summary', tokens: formatTokens(meter.summary_tokens), share: share(meter.summary_tokens, budget) },
            { label: `Turns (${meter.turn_count})`, tokens: formatTokens(meter.turn_tokens), share: share(meter.turn_tokens, budget) },
            { label: "Agent's records", tokens: formatTokens(meter.action_tokens), share: share(meter.action_tokens, budget) },
            { label: 'Free until summary', tokens: formatTokens(free), share: share(free, budget) },
        ],
        limit,
        lastRequest,
    };
}

function rowsHtml(rows) {
    return rows.map((row) => {
        let shareCell = '';
        if (row.share !== '') shareCell = `<span>${escapeHtml(row.share)}</span>`;
        return `<div class="ai-chat-history-meter-row"><span>${escapeHtml(row.label)}</span>`
            + `<span>${escapeHtml(row.tokens)}</span>${shareCell}</div>`;
    }).join('');
}

/** Show the meter in its element (index.html #ai-chat-history-meter). */
export function renderHistoryMeter(element, meter) {
    if (!(element instanceof HTMLElement)) {
        throw new Error('renderHistoryMeter requires the meter element');
    }
    const view = historyMeterView(meter);
    element.querySelector('.ai-chat-history-meter-fill').style.width = `${Math.min(view.percent, PERCENT)}%`;
    element.querySelector('.ai-chat-history-meter-label').textContent = `History ${view.percent}%`;
    let lastRequest = '';
    if (view.lastRequest.length > 0) {
        lastRequest = `<div class="ai-chat-history-meter-section">${rowsHtml(view.lastRequest)}</div>`;
    }
    element.querySelector('.ai-chat-history-meter-details').innerHTML = (
        `<div class="ai-chat-history-meter-section">${rowsHtml(view.rows)}</div>`
        + `<p class="ai-chat-history-meter-limit">${escapeHtml(view.limit)}</p>${lastRequest}`
    );
    element.hidden = false;
}
