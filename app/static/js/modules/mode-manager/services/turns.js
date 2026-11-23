import { ApplicationState } from '../../application-state.js';

/**
 * Turns: one thing at a time changes the page's notes and tabs (docs/ui/command-gate.md,
 * "Turns"; docs/future-plans/one-writer-refactoring.md, idea 4).
 *
 * A command, a piece of background work (the infinite scroll moving its band, a change made in
 * another view, a link title that arrived) and what the server sends (a reference page it closed)
 * each take a turn, and turns run in the order they were asked for. Before, only commands took
 * turns among themselves: background work looked whether a command ran when it started, then ran
 * beside whatever started after, and the two agreed through flags read every few milliseconds, so
 * which went next was the order of timers. A list refresh that woke after a tab change asked for
 * the tab shown before (GitHub's reference-views run in Firefox, 2026-11-22).
 *
 * This module knows nothing of the page, so a unit test runs it as it is (tests/unit/turns.test.mjs).
 */
const moduleState = ApplicationState.createFields('turns', {
    // Resolves when the last turn asked for has finished; null when none is taken.
    lastFinished: null,
    // Turns asked for and not yet finished: the one running and those waiting.
    unfinished: 0,
    // The name of the turn whose work is running, for logs and errors; null between turns.
    running: null,
});

/** Whether a turn is running or waiting: work that may be skipped (a poll) skips its round. */
export function isTurnTaken() {
    return moduleState.unfinished > 0;
}

/** The name of the turn whose work is running, or null. */
export function turnRunning() {
    return moduleState.running;
}

/**
 * Runs `work` once every turn asked for before it has finished, and resolves (or rejects) with
 * what it does. With no turn taken, `work` starts at once, before this returns, as it did when it
 * was called directly. The turn counts as taken from this call on. `work` must not wait for a
 * turn it asks for itself: that one waits for this one.
 */
export function takeTurn(name, work) {
    if (typeof name !== 'string' || name === '') throw new Error('takeTurn requires a name');
    if (typeof work !== 'function') throw new Error('takeTurn requires the work to do');
    const before = moduleState.lastFinished;
    let finish;
    const finished = new Promise((resolve) => { finish = resolve; });
    moduleState.lastFinished = finished;
    moduleState.unfinished += 1;
    const start = () => {
        moduleState.running = name;
        return work();
    };
    let outcome;
    if (before === null) {
        // A promise of what work() does, a failure as it starts included.
        outcome = new Promise((resolve) => { resolve(start()); });
    } else {
        outcome = before.then(start);
    }
    return outcome
        .finally(() => {
            moduleState.running = null;
            moduleState.unfinished -= 1;
            if (moduleState.lastFinished === finished) moduleState.lastFinished = null;
            finish();
        });
}
