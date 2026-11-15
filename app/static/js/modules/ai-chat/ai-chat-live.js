// The vault's one AI conversation, live in every view (multi-view editing step 5;
// docs/design/multi-view-editing.md, "Step 5's cases"). Each view asks the server how the
// conversation stands (`GET /ai/chat/live`): every half second while an answer is being written, a
// question waits, the AI asks one or another view types one; at the status check's pace otherwise
// (status-check-interval.js), and at once when another tab of this browser changed the chat; not while
// the tab is hidden. The panel takes it (AiChatPanel._applyLiveState): it loads the chat again when
// its mark changed, shows the questions waiting, the AI's question, Stop, and another view's typing.
import { ApplicationState } from '../application-state.js';
import { rethrowUnexpectedError } from '../expected-errors.js';
import { AiApiError, loadAiChatLive } from './ai-chat-api.js';
import { whenAskedToCheckNow } from '../views-in-this-browser.js';
import { statusCheckIntervalMs } from '../status-check-interval.js';
import { proposalRequest } from './bulk-proposal-ui.js';
import { TAG_FOCUS_CHOICES, describeScopeQuestion, scopeAnswerValue } from './bulk-scope-question.js';

const LIVELY_POLL_MS = 500;

const liveState = ApplicationState.createFields('ai-chat-live', {
    isFollowing: false,
});

function requireLiveState(state) {
    if (state === null || typeof state !== 'object') {
        throw new Error('AI chat live state must be an object');
    }
    if (typeof state.mark !== 'string' || typeof state.isAnswering !== 'boolean' || !Array.isArray(state.waiting)) {
        throw new Error('AI chat live state must carry its mark, whether it answers and the questions waiting');
    }
    if (state.question !== null && (typeof state.question !== 'object' || typeof state.question.question_id !== 'string')) {
        throw new Error('AI chat live state question must be a question event or null');
    }
    if (state.composer === null || typeof state.composer !== 'object') {
        throw new Error('AI chat live state composer must be an object');
    }
}

export function isLively(state) {
    return [
        state.isAnswering, state.waiting.length > 0, state.question !== null, Object.keys(state.composer).length > 0,
    ].includes(true);
}

// Ask, apply, ask again: applyLiveState(state, askedAtMs) gets each answer with when it was asked,
// so what was shown since (a card the stream opened) is not undone by an older answer.
export function followAiChatLive(applyLiveState) {
    if (typeof applyLiveState !== 'function') {
        throw new Error('followAiChatLive requires what to do with each state');
    }
    if (liveState.isFollowing) {
        throw new Error('The AI chat is followed already');
    }
    liveState.isFollowing = true;
    let delayMs = statusCheckIntervalMs();
    let nextTimer = 0;
    let isAsking = false;
    let isAskedAgain = false;
    const askOnce = async () => {
        if (document.hidden) {
            delayMs = statusCheckIntervalMs();
            return;
        }
        const askedAtMs = performance.now();
        const state = await loadAiChatLive();
        requireLiveState(state);
        delayMs = isLively(state) ? LIVELY_POLL_MS : statusCheckIntervalMs();
        await applyLiveState(state, askedAtMs);
    };
    const tick = () => {
        window.clearTimeout(nextTimer);
        isAsking = true;
        askOnce()
            .catch((error) => {
                // The server out of reach (a restart): ask again later; anything else is a bug.
                rethrowUnexpectedError(error);
                if (!(error instanceof AiApiError)) throw error;
                delayMs = statusCheckIntervalMs();
            })
            .finally(() => {
                isAsking = false;
                if (isAskedAgain) {
                    isAskedAgain = false;
                    tick();
                    return;
                }
                nextTimer = window.setTimeout(tick, delayMs);
            });
    };
    // Another tab of this browser changed the chat (a Send, Stop, Clear, typing): ask now.
    whenAskedToCheckNow(() => {
        if (isAsking) {
            isAskedAgain = true;
            return;
        }
        tick();
    });
    tick();
}

/**
 * The AI's question about which notes to tag, in a view other than the one whose answer asked it
 * (case 9): its choices as buttons, the focus as a select when it is to be chosen. Resolves once
 * the server took an answer, or with 'cancelled' when the question went (answered elsewhere, the
 * answer stopped); the card is removed either way.
 */
export function showScopeQuestionCard({ event, host, signal }) {
    const question = describeScopeQuestion(event);
    if (!(host instanceof HTMLElement)) throw new TypeError('Scope question card requires a host element');
    const card = document.createElement('section');
    card.className = 'ai-chat-confirmation';
    card.setAttribute('aria-label', 'Choose the notes');
    const label = document.createElement('p');
    label.className = 'ai-chat-confirmation-label';
    label.textContent = event.label;
    let focusSelect = null;
    if (question.focusDefault !== null) {
        focusSelect = document.createElement('select');
        for (const [value, text] of TAG_FOCUS_CHOICES) {
            const option = focusSelect.appendChild(document.createElement('option'));
            option.value = value;
            option.textContent = text;
        }
        focusSelect.value = question.focusDefault;
    }
    const selectedFocus = () => (focusSelect === null ? null : focusSelect.value);
    const error = document.createElement('p');
    error.setAttribute('role', 'alert');
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'secondary-btn';
    cancel.textContent = 'Cancel';
    const choices = [];
    const all = document.createElement('button');
    all.type = 'button';
    all.textContent = question.allLabel;
    choices.push([all, 'all']);
    if (question.prefixLabel !== null) {
        const prefix = document.createElement('button');
        prefix.type = 'button';
        prefix.className = 'secondary-btn';
        prefix.textContent = question.prefixLabel;
        choices.push([prefix, 'prefix']);
    }
    const actions = document.createElement('div');
    actions.className = 'form-actions';
    actions.append(cancel, ...choices.map(([button]) => button));
    card.append(label);
    if (focusSelect !== null) card.append(focusSelect);
    card.append(actions, error);
    host.append(card);
    const controls = [cancel, ...choices.map(([button]) => button)];
    return new Promise((resolve) => {
        const abandon = () => {
            card.remove();
            resolve('cancelled');
        };
        if (signal.aborted) {
            abandon();
            return;
        }
        signal.addEventListener('abort', abandon, { once: true });
        const answer = async (value) => {
            for (const control of controls) control.disabled = true;
            error.textContent = '';
            // lint: allow-JS001 rationale="submit an external HTTP answer; rethrow internal failures"
            try {
                await proposalRequest('answer', { question_id: event.question_id, value }, signal);
            // lint: allow-JS001 rationale="cancellation and HTTP rejection (answered elsewhere first) are expected; internal errors propagate"
            } catch (caught) {
                rethrowUnexpectedError(caught);
                if (signal.aborted) return;
                if (!(caught instanceof AiApiError)) throw caught;
                error.textContent = caught.message;
                for (const control of controls) control.disabled = false;
                return;
            }
            signal.removeEventListener('abort', abandon);
            card.remove();
            resolve(value);
        };
        cancel.addEventListener('click', () => answer('cancel'));
        for (const [button, choice] of choices) {
            button.addEventListener('click', () => answer(scopeAnswerValue(event, choice, selectedFocus())));
        }
    });
}
