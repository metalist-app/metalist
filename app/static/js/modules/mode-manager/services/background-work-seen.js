import { stateValuesEqual } from '../../application-state.js';

// When each running piece of work was first seen, by key (background-work-cards.js). Kept apart
// from the cards so that it runs without the page.

/**
 * The first-seen times for the work listed now: a piece seen at an earlier listing keeps its
 * time, a new one gets `now`, one no longer listed is dropped. Returns `earlier` itself when
 * nothing changed, whatever order the server listed the work in: the state store refuses a
 * change to an equal value, and it compares values, not the order of their keys.
 */
export function firstSeenTimes(earlier, work, now) {
    const times = {};
    for (const entry of work) {
        if (Object.hasOwn(earlier, entry.key)) {
            times[entry.key] = earlier[entry.key];
        } else {
            times[entry.key] = now;
        }
    }
    if (stateValuesEqual(times, earlier)) return earlier;
    return Object.freeze(times);
}
