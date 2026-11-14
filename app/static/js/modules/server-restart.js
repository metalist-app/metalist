// Waits while this vault's server restarts (Manage Vault Ports, after its ports or sharing
// changed): first for the old server to stop answering, then for the new one to answer, at the
// address it comes back on. Waiting only for an answer could catch the old server in the moment
// before it stops, and move into nothing.
import { isAnsweredStatus } from './http-status.js';
import { MS_PER_SECOND } from './time-units.js';
import { rethrowUnexpectedError } from './expected-errors.js';

const POLL_INTERVAL_MS = 200;
const REQUEST_TIMEOUT_MS = 1000;
// The server restarts half a second after its answer; one that has not stopped by then won't.
const STOP_WAIT_SECONDS = 15;
// Starting again can take a while on a busy or slow computer.
const START_WAIT_SECONDS = 120;
const STATUS_PATH = '/maintenance';

async function settledFetch(url, options) {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), REQUEST_TIMEOUT_MS);
    const [outcome] = await Promise.allSettled([fetch(url, {
        ...options, method: 'GET', cache: 'no-store', signal: abortController.signal,
    })]);
    clearTimeout(timeoutId);
    if (outcome.status === 'rejected') {
        rethrowUnexpectedError(outcome.reason);
    }
    return outcome;
}

async function pageServerAnswers() {
    const outcome = await settledFetch(STATUS_PATH, {});
    return outcome.status === 'fulfilled' && isAnsweredStatus(outcome.value.status);
}

// Another port is another origin, whose answer the page may not read: any answer means it is up.
async function serverAtAnswers(origin) {
    if (origin === window.location.origin) {
        return pageServerAnswers();
    }
    const outcome = await settledFetch(`${origin}${STATUS_PATH}`, { mode: 'no-cors' });
    return outcome.status === 'fulfilled';
}

function sleep(delayMs) {
    return new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function waitUntil(answers, isAnswering, limitSeconds, failure) {
    const deadline = Date.now() + limitSeconds * MS_PER_SECOND;
    while (await answers() !== isAnswering) {
        if (Date.now() > deadline) {
            throw new Error(failure);
        }
        await sleep(POLL_INTERVAL_MS);
    }
}

// The page's address once its vault listens on newPort: the same, when the page was not opened on
// the port that changed (behind a proxy, say).
export function addressAfterRestart({ location, portBefore, newPort }) {
    if (!Number.isInteger(portBefore) || !Number.isInteger(newPort)) {
        throw new Error('addressAfterRestart needs whole-number ports');
    }
    const url = new URL(location.href);
    if (url.port !== String(portBefore)) {
        return url.href;
    }
    url.port = String(newPort);
    return url.href;
}

export async function waitForServerRestart({ newOrigin }) {
    if (typeof newOrigin !== 'string' || newOrigin.length === 0) {
        throw new Error('waitForServerRestart needs the origin the server comes back on');
    }
    await waitUntil(pageServerAnswers, false, STOP_WAIT_SECONDS,
        `The vault's server did not restart within ${STOP_WAIT_SECONDS} seconds`);
    await waitUntil(() => serverAtAnswers(newOrigin), true, START_WAIT_SECONDS,
        `The vault's server did not come back within ${START_WAIT_SECONDS} seconds`);
}
