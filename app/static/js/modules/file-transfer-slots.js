import { ApplicationState } from './application-state.js';
import { HTTP_STATUS } from './http-status.js';

// The server takes at most four file transfers at once and answers 429 to more
// (app/api/upload_limits.py, MAX_CONCURRENT_ATTACHMENT_TRANSFERS): a list showing many
// pictures asked for them all at once and showed errors (2026-11-01, a folder of photos
// imported). A download here waits for one of as many slots; one still answered 429
// (another window's transfers) waits a moment and asks again.

export const MAX_CONCURRENT_TRANSFERS = 4;
const BUSY_RETRY_MS = 250;

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

function waitBeforeRetry() {
    return new Promise((resolve) => {
        setTimeout(resolve, BUSY_RETRY_MS);
    });
}

/**
 * Run transfer (async: its whole request, the body read too, so the server's slot is free
 * when it ends) in a slot. It answers { response, ...read }: a response answered 429 is
 * asked for again once a moment has passed.
 */
export async function inTransferSlot(transfer) {
    if (typeof transfer !== 'function') {
        throw new Error('inTransferSlot requires the transfer');
    }
    for (;;) {
        await takeSlot();
        const result = await transfer().finally(releaseSlot);
        if (result.response.status !== HTTP_STATUS.TOO_MANY_REQUESTS) return result;
        await waitBeforeRetry();
    }
}
