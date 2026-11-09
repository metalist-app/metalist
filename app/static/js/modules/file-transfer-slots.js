import { ApplicationState } from './application-state.js';

// A page's file transfers go a few at a time, the rest waiting their turn: a folder's uploads
// and a list showing many pictures make steadier progress that way.

export const MAX_CONCURRENT_TRANSFERS = 4;

const moduleState = ApplicationState.createFields('file-transfer-slots', {
    inFlight: 0,
    // Transfers waiting for a slot, first come first served: each one's go-ahead.
    waiting: Object.freeze([]),
});

async function takeSlot() {
    if (moduleState.inFlight < MAX_CONCURRENT_TRANSFERS) {
        moduleState.inFlight = moduleState.inFlight + 1;
        return;
    }
    await new Promise((resolve) => {
        moduleState.waiting = Object.freeze([...moduleState.waiting, resolve]);
    });
}

// A slot freed goes straight to the transfer waiting longest.
function releaseSlot() {
    if (moduleState.waiting.length > 0) {
        const [next, ...rest] = moduleState.waiting;
        moduleState.waiting = Object.freeze(rest);
        next();
        return;
    }
    moduleState.inFlight = moduleState.inFlight - 1;
}

/** Run transfer (async: its whole request, the body read too) in a slot and answer what it answers. */
export async function inTransferSlot(transfer) {
    if (typeof transfer !== 'function') {
        throw new Error('inTransferSlot requires the transfer');
    }
    await takeSlot();
    return transfer().finally(releaseSlot);
}
