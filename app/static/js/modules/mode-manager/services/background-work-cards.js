import { ApplicationState } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { FloatingMessages } from '../../floating-messages.js';
import { workProgressParts } from './background-work-text.js';

// The server's work beside the user's (reading PDF text, an import), shown as it goes (the
// maintainer, 2026-11-02: "if there's stuff being computed in the background, I would like
// the user to have some awareness of that"): a floating card per piece of work, its label,
// "3 of 7" and a bar, gone when the work is done. Work done within a second shows no card.
// Asked every few seconds with the status poll (polling-service.js), and often while there
// is work, or just after the user started some (an import, dropped files).

const CARD_KEY_PREFIX = 'background-work.';
const QUICK_POLL_MS = 500;
// Work this young shows no card yet: a card coming and going at once would only flicker.
const SHOW_AFTER_MS = 1000;

const moduleState = ApplicationState.createFields('background-work-cards', {
    // When each running piece of work was first seen, by key.
    firstSeenAt: Object.freeze({}),
    // The keys a screen shows itself (the import walkthrough's own bar), shown in no card.
    shownElsewhere: Object.freeze([]),
    quickPollTimer: null,
    check: null,
});

function cardKey(key) {
    return `${CARD_KEY_PREFIX}${key}`;
}

// When a piece of work listed now was first seen: at an earlier listing, or now when this is
// the first listing it is in.
function firstSeenTime(key, now) {
    if (Object.hasOwn(moduleState.firstSeenAt, key)) return moduleState.firstSeenAt[key];
    return now;
}

/** Draw the cards for the work the server listed; the cards of work gone leave. */
export function showBackgroundWork(work, now) {
    if (!Array.isArray(work)) {
        throw new Error('showBackgroundWork requires the listed work');
    }
    const firstSeenAt = {};
    for (const entry of work) {
        if (typeof entry.key !== 'string' || typeof entry.label !== 'string' || !Number.isInteger(entry.done)
            || !Number.isInteger(entry.total) || !Number.isInteger(entry.elapsedSeconds)) {
            throw new Error('Background work listed malformed');
        }
        firstSeenAt[entry.key] = firstSeenTime(entry.key, now);
        const isOldEnough = now - firstSeenAt[entry.key] >= SHOW_AFTER_MS;
        if (isOldEnough && !moduleState.shownElsewhere.includes(entry.key)) {
            FloatingMessages.showWorkProgress(cardKey(entry.key), workProgressParts(entry), entry.done, entry.total);
        } else {
            FloatingMessages.end(cardKey(entry.key));
        }
    }
    for (const key of Object.keys(moduleState.firstSeenAt)) {
        if (!Object.hasOwn(firstSeenAt, key)) FloatingMessages.end(cardKey(key));
    }
    if (JSON.stringify(firstSeenAt) !== JSON.stringify(moduleState.firstSeenAt)) {
        moduleState.firstSeenAt = Object.freeze(firstSeenAt);
    }
    return work.length > 0;
}

/** Ask the server now, and keep asking often while there is work. */
export async function checkBackgroundWork() {
    if (moduleState.check !== null) return;
    moduleState.check = (async () => {
        const answer = await NotesAPI.fetchBackgroundWork();
        const isRunning = showBackgroundWork(answer.work, Date.now());
        if (isRunning && moduleState.quickPollTimer === null) {
            moduleState.quickPollTimer = window.setTimeout(() => {
                moduleState.quickPollTimer = null;
                void checkBackgroundWork();
            }, QUICK_POLL_MS);
        }
    })().finally(() => {
        moduleState.check = null;
    });
    await moduleState.check;
}

/** A screen showing key's progress itself: no card for it meanwhile. */
export function setShownElsewhere(key, isShownElsewhere) {
    const others = moduleState.shownElsewhere.filter((shown) => shown !== key);
    const next = isShownElsewhere ? [...others, key] : others;
    if (JSON.stringify(next) !== JSON.stringify(moduleState.shownElsewhere)) {
        moduleState.shownElsewhere = Object.freeze(next);
    }
    if (isShownElsewhere) FloatingMessages.end(cardKey(key));
}
