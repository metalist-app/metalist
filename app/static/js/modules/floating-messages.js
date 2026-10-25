// Floating messages (docs/ui/floating-messages.md): cards in the upper-right corner, just
// left of the floating buttons (on the phone, under the search header). A new card goes
// below the others; when one leaves, the ones below move up. Nothing on the page moves for
// them and they never take focus.
// - A passing card leaves by itself: news after 4 s, longer for a long message (up to
//   10 s); an error after 10 s. Hovering a card pauses its timer.
// - A lasting card stays until it is replaced or closed, such as "Not saved,
//   reconnecting…" for as long as the connection is lost.
// - A progress card says what is running ("Saving vault ports…") and leaves when it ends.
// - A lasting problem that puts the user's work at risk and is still there after
//   STATUS_ESCALATE_SECONDS opens a dialog over its card, which closes when the problem ends.
// The last few messages are kept for Recent Messages, in this page's memory only (progress
// cards are not news, so they are not kept).

import { ApplicationState } from './application-state.js';
import { MS_PER_SECOND } from './time-units.js';

const STACK_ID = 'floating-messages';
const TYPES = new Set(['info', 'success', 'error', 'connection']);
const NEWS_MIN_SECONDS = 4;
const NEWS_MAX_SECONDS = 10;
const ERROR_SECONDS = 10;
// Reading time for news longer than 4 s covers: about 17 characters a second.
const READING_MS_PER_CHARACTER = 60;
// Matches the .floating-message opacity transition in main.css.
const FADE_MS = 200;
const RECENT_LIMIT = 20;
const STATUS_ESCALATE_SECONDS = 30;
// Errors are announced at once; the rest wait for a pause in what is being read.
const ROLE_BY_TYPE = { info: 'status', success: 'status', error: 'alert', connection: 'status' };

const floatingState = ApplicationState.createFields('floating-messages', {
    // Newest last: { text, detail, type, shownAtMs }.
    recent: [],
    // By card key: { timer, close } while a lasting problem waits to escalate or has.
    escalations: {},
});

// How long news stays: 4 s, or the time a long message takes to read, up to 10 s.
export function newsMilliseconds(text) {
    if (typeof text !== 'string' || text.length === 0) {
        throw new Error('newsMilliseconds requires message text');
    }
    const reading = text.length * READING_MS_PER_CHARACTER;
    return Math.min(Math.max(reading, NEWS_MIN_SECONDS * MS_PER_SECOND), NEWS_MAX_SECONDS * MS_PER_SECOND);
}

function passingMilliseconds(type, text) {
    if (type === 'error') {
        return ERROR_SECONDS * MS_PER_SECOND;
    }
    return newsMilliseconds(text);
}

function stack() {
    const existing = document.getElementById(STACK_ID);
    if (existing) {
        return existing;
    }
    const created = document.createElement('div');
    created.id = STACK_ID;
    created.className = 'floating-messages';
    document.body.appendChild(created);
    return created;
}

// On the phone the cards hang just under the search header, whose height its pills change.
function placeUnderSearchHeader(container) {
    const header = document.querySelector('.controls');
    if (!(header instanceof HTMLElement)) {
        throw new Error('Floating messages need the search header (.controls)');
    }
    container.style.setProperty('--search-header-bottom', `${Math.round(header.getBoundingClientRect().bottom)}px`);
}

function validateSpec(spec) {
    if (spec === null || typeof spec !== 'object') {
        throw new Error('A floating message needs its description');
    }
    if (typeof spec.text !== 'string' || spec.text.length === 0) {
        throw new Error('A floating message needs text');
    }
    if (!TYPES.has(spec.type)) {
        throw new Error(`Unknown floating message type: ${spec.type}`);
    }
    if (typeof spec.detail !== 'string') {
        throw new Error('A floating message needs detail text (empty for none)');
    }
    for (const flag of ['isClosable', 'isLasting']) {
        if (typeof spec[flag] !== 'boolean') {
            throw new Error(`A floating message needs ${flag}`);
        }
    }
    if (spec.key !== null && (typeof spec.key !== 'string' || spec.key.length === 0)) {
        throw new Error('A floating message key is a name or null');
    }
}

function remember(spec) {
    const entry = { text: spec.text, detail: spec.detail, type: spec.type, shownAtMs: Date.now() };
    floatingState.recent = [...floatingState.recent, entry].slice(-RECENT_LIMIT);
}

function leave(card) {
    if (card.dataset.leaving === 'true') {
        return;
    }
    card.dataset.leaving = 'true';
    card.classList.remove('is-shown');
    setTimeout(() => card.remove(), FADE_MS);
}

// The card's countdown pauses while the pointer is over it and resumes where it paused.
function startCountdown(card, milliseconds) {
    const countdown = { remaining: milliseconds, startedAt: Date.now(), timer: null };
    countdown.timer = setTimeout(() => leave(card), countdown.remaining);
    card.addEventListener('mouseenter', () => {
        clearTimeout(countdown.timer);
        countdown.remaining -= Date.now() - countdown.startedAt;
    });
    card.addEventListener('mouseleave', () => {
        countdown.startedAt = Date.now();
        countdown.timer = setTimeout(() => leave(card), countdown.remaining);
    });
}

function buildCard(spec) {
    const card = document.createElement('div');
    card.className = `floating-message floating-message-${spec.type}`;
    card.dataset.type = spec.type;
    card.setAttribute('role', ROLE_BY_TYPE[spec.type]);
    if (spec.key !== null) {
        card.dataset.key = spec.key;
    }
    const text = document.createElement('span');
    text.className = 'floating-message-text';
    // Plain text: messages can quote what the user typed or what an AI answered.
    text.textContent = spec.text;
    card.appendChild(text);
    if (spec.detail !== '') {
        card.title = spec.detail;
    }
    if (spec.isClosable) {
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'floating-message-close';
        close.setAttribute('aria-label', 'Close');
        close.textContent = '×';
        // The press leaves focus (and the caret) where it was.
        close.addEventListener('mousedown', event => event.preventDefault());
        close.addEventListener('click', () => leave(card));
        card.appendChild(close);
    }
    if (!spec.isLasting) {
        startCountdown(card, passingMilliseconds(spec.type, spec.text));
    }
    return card;
}

function keyedCard(key) {
    return [...stack().querySelectorAll('.floating-message')]
        .find(card => card.dataset.key === key && card.dataset.leaving !== 'true');
}

function reveal(card) {
    // One frame hidden first, so the fade-in runs.
    requestAnimationFrame(() => card.classList.add('is-shown'));
}

export const FloatingMessages = {
    // spec: { text, type, detail, isClosable, isLasting, key }. A keyed card already
    // showing keeps its place and takes the new text.
    show(spec) {
        validateSpec(spec);
        const container = stack();
        placeUnderSearchHeader(container);
        if (spec.key !== null) {
            const existing = keyedCard(spec.key);
            if (existing) {
                existing.querySelector('.floating-message-text').textContent = spec.text;
                return;
            }
        }
        const card = buildCard(spec);
        container.appendChild(card);
        remember(spec);
        reveal(card);
    },

    // The keyed card gives its place to a new one, such as "Reconnected" for "Not saved,
    // reconnecting…". Nothing happens when no such card shows.
    replace(key, spec) {
        validateSpec(spec);
        const existing = keyedCard(key);
        if (!existing) {
            return;
        }
        const card = buildCard(spec);
        existing.before(card);
        existing.remove();
        remember(spec);
        card.classList.add('is-shown');
    },

    // A card saying what is running, until end(key).
    showProgress(key, text) {
        const spec = { text, type: 'info', detail: '', isClosable: false, isLasting: true, key };
        validateSpec(spec);
        if (keyedCard(key)) {
            throw new Error(`Progress card ${key} is already showing`);
        }
        const container = stack();
        placeUnderSearchHeader(container);
        const card = buildCard(spec);
        container.appendChild(card);
        reveal(card);
    },

    // The keyed card leaves, if it shows.
    end(key) {
        const card = keyedCard(key);
        if (card) {
            leave(card);
        }
    },

    // The keyed lasting card's problem, still there after STATUS_ESCALATE_SECONDS, opens a
    // dialog saying what it means (another dialog already showing is left alone).
    escalateAfter(key, text) {
        if (Object.hasOwn(floatingState.escalations, key)) {
            return;
        }
        const timer = setTimeout(async () => {
            // Loaded when needed: the dialog brings the app's mode state, which this module's
            // unit tests (and the login page) do without.
            const { isErrorDialogOpen, showErrorDialogClosedBy } = await import('./modals/error-dialog.js');
            if (!keyedCard(key) || isErrorDialogOpen() || !Object.hasOwn(floatingState.escalations, key)) {
                return;
            }
            const { close } = showErrorDialogClosedBy([{ text, fieldId: null }]);
            floatingState.escalations = { ...floatingState.escalations, [key]: { timer: null, close } };
        }, STATUS_ESCALATE_SECONDS * MS_PER_SECOND);
        floatingState.escalations = { ...floatingState.escalations, [key]: { timer, close: null } };
    },

    // The problem has ended: no dialog will open for it, and one that did closes.
    endEscalation(key) {
        if (!Object.hasOwn(floatingState.escalations, key)) {
            return;
        }
        const escalation = floatingState.escalations[key];
        clearTimeout(escalation.timer);
        if (escalation.close !== null) {
            escalation.close();
        }
        const remaining = { ...floatingState.escalations };
        delete remaining[key];
        floatingState.escalations = remaining;
    },

    // Every card leaves.
    dismissAll() {
        for (const card of stack().querySelectorAll('.floating-message')) {
            leave(card);
        }
    },

    // Newest first.
    recentMessages() {
        return [...floatingState.recent].reverse();
    },

    // Signing out forgets them.
    forgetRecent() {
        if (floatingState.recent.length > 0) {
            floatingState.recent = [];
        }
    },
};
