import { isTurnTaken, takeTurn } from '../../app/static/js/modules/mode-manager/services/turns.js';

// Stand-ins for CommandGate (command-gate-service.js, which needs the page) in tests that run a
// module's source with its dependencies given by name.

// No command runs; background work takes real turns (turns.js).
export function freeGate() {
    return {
        isBusy: () => false,
        isTurnTaken,
        runBackground(name, work) {
            if (isTurnTaken()) throw new Error(`runBackground called while a turn is taken (name=${name})`);
            return takeTurn(name, work);
        },
        queueBackground: takeTurn,
        noteRefreshOutsideTurns() {},
        refreshesOutsideTurns: () => [],
    };
}

// The test is the turn: what it calls runs at once, as when a command has called it.
export function gateWithTheTurn() {
    return {
        ...freeGate(),
        isTurnTaken: () => true,
        runBackground() { throw new Error('the test holds the turn: nothing takes another'); },
    };
}
