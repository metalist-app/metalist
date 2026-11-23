import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';
import { CONFIG } from '../../config.js';
import { recordCommand } from '../../problem-reports/input-recorder.js';
import { isTurnTaken, takeTurn } from './turns.js';

const WATCHDOG_TIMEOUT_MS = 15000;

const moduleState = ApplicationState.createFields('command-gate-service', {
    busy: false,
    busyName: null,
    busyStartedAt: null,
    watchdogId: null,
    // What asked for a list refresh outside any turn, each once (refreshesOutsideTurns).
    refreshesOutsideTurns: [],
});


function clearWatchdog() {
    if (moduleState.watchdogId === null) {
        return;
    }
    clearTimeout(moduleState.watchdogId);
    moduleState.watchdogId = null;
}

function armWatchdog(timeoutMs) {
    clearWatchdog();
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
        return;
    }
    moduleState.watchdogId = setTimeout(() => {
        if (!moduleState.busy) {
            return;
        }
        const elapsedMs = moduleState.busyStartedAt === null ? null : performance.now() - moduleState.busyStartedAt;
        throw new Error(
            `CommandGate watchdog: command stuck busy name=${moduleState.busyName} elapsedMs=${elapsedMs}`
        );
    }, timeoutMs);
}

const FREE_POLL_MS = 50;

export const CommandGate = {
    // A command is running, or waiting for background work to finish.
    isBusy() {
        return moduleState.busy;
    },

    // A command or background work is running or waiting its turn (turns.js). Background work
    // that may be skipped (a poll) asks this and skips its round.
    isTurnTaken() {
        return isTurnTaken();
    },

    /**
     * Background work that changes the notes or the tabs shown (the infinite scroll, a change
     * made in another view): it takes a turn, so a command asked for meanwhile runs after it,
     * not beside it. No loading state: the page stays usable. The caller asks isTurnTaken()
     * first, in the same task, and skips its round when one is: calling this then is a defect.
     */
    runBackground(name, asyncFn) {
        if (isTurnTaken()) {
            throw new Error(`CommandGate.runBackground called while a turn is taken (name=${name})`);
        }
        return takeTurn(name, asyncFn);
    },

    /**
     * A list refresh asked for with no turn taken takes one of its own (ui-actions.js), so it is
     * safe; it is also noted here by what asked, each asker once. Many controls still do their
     * work outside the gate (a sort order, a filter, folding a note): the list says which, for
     * the day they become commands (docs/future-plans/one-writer-refactoring.md, idea 4).
     */
    noteRefreshOutsideTurns(context) {
        if (typeof context !== 'string' || context === '') throw new Error('noteRefreshOutsideTurns requires what asked');
        if (!moduleState.refreshesOutsideTurns.includes(context)) {
            moduleState.refreshesOutsideTurns = [...moduleState.refreshesOutsideTurns, context];
        }
    },

    refreshesOutsideTurns() {
        return [...moduleState.refreshesOutsideTurns];
    },

    /**
     * Background work that must not be skipped (the server closed a reference page; a refresh
     * asked for outside any turn): it runs when its turn comes, after whatever runs now.
     * asyncFn must not be awaited from inside a turn: it would wait for the turn awaiting it.
     */
    queueBackground(name, asyncFn) {
        return takeTurn(name, asyncFn);
    },

    // For work that finishes in the background (an AI answer, a click that
    // follows the press that entered edit mode): waits until no command runs,
    // instead of being dropped as run() drops a command while another runs.
    async runWhenFree(name, asyncFn, options) {
        while (moduleState.busy || ModeContext.isLoading) {
            await new Promise((resolve) => setTimeout(resolve, FREE_POLL_MS));
        }
        return this.run(name, asyncFn, options);
    },

    run(name, asyncFn, options) {
        if (typeof name !== 'string' || name.length === 0) {
            throw new Error('CommandGate.run requires non-empty name');
        }
        if (typeof asyncFn !== 'function') {
            throw new Error('CommandGate.run requires async function');
        }

        let resolvedOptions = null;
        if (options !== undefined) {
            resolvedOptions = options;
        }

        if (
            resolvedOptions !== null
            && (typeof resolvedOptions !== 'object' || Array.isArray(resolvedOptions))
        ) {
            throw new Error('CommandGate.run options must be an object or null');
        }

        if (moduleState.busy) {
            Logger.logNoop('Command dropped while busy', {
                requested: name,
                busyName: moduleState.busyName,
            });
            recordCommand(name, 0, 'dropped');
            return Promise.resolve(null);
        }
        if (ModeContext.isLoading) {
            throw new Error(`CommandGate.run called while ModeContext.isLoading (name=${name})`);
        }

        ModeContext.setLoading(true);
        if (resolvedOptions !== null && resolvedOptions.showLoadingImmediately === true) {
            document.body.classList.add(CONFIG.CLASSES.LOADING);
        }
        moduleState.busy = true;
        moduleState.busyName = name;
        moduleState.busyStartedAt = performance.now();
        let watchdogTimeoutMs = WATCHDOG_TIMEOUT_MS;
        if (resolvedOptions !== null && resolvedOptions.disableWatchdog === true) {
            watchdogTimeoutMs = 0;
        } else if (resolvedOptions !== null && Number.isFinite(resolvedOptions.timeoutMs)) {
            watchdogTimeoutMs = resolvedOptions.timeoutMs;
        }
        armWatchdog(watchdogTimeoutMs);

        Logger.logAction('command_gate.start', { name });

        const startedAt = performance.now();
        // Failed unless the command finishes: the outcome is recorded without catching anything.
        let outcome = 'failed';
        // The command's work starts once background work in progress has finished (turns.js);
        // the gate is busy from now, so input meanwhile is dropped as during the command.
        // With no turn taken the work still starts after the caller's own task, as before turns.
        return takeTurn(name, () => Promise.resolve().then(asyncFn))
            .then((value) => {
                outcome = 'ok';
                return value;
            })
            .finally(() => {
                recordCommand(name, performance.now() - startedAt, outcome);
                Logger.logAction('command_gate.finish', { name });
                moduleState.busy = false;
                moduleState.busyName = null;
                moduleState.busyStartedAt = null;
                        clearWatchdog();
                ModeContext.setLoading(false);
            });
    },
};
