import { ApplicationState } from './application-state.js';
import { createUuid } from './uuid.js';

const sessionIdentity = ApplicationState.createFields('session-auth', {tabId: null});

// A browser tab keeps its view (its id names it to the server: its place, its undo) in
// sessionStorage, as closing a tab is deliberate; the installed phone app (added to the home
// screen, one window) keeps it in localStorage, so the phone ending the app in the background does
// not lose its place (multi-view editing §9). Each vault has its own address, so its own storage:
// one view per vault.
export function initializeSessionIdentity() {
    initializeIdentityIn(sessionStorage);
}

export function initializeInstalledAppIdentity() {
    initializeIdentityIn(localStorage);
}

function initializeIdentityIn(storage) {
    if (sessionIdentity.tabId !== null) {
        return;
    }
    let tabId = storage.getItem('metalist_tab_id');
    if (tabId === null || tabId === '') {
        tabId = createUuid();
        storage.setItem('metalist_tab_id', tabId);
    }
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('Invalid browser tab identity');
    }
    // Storage preserves identity across reloads; the initialized page owns it
    // for all requests. Losing/changing storage cannot rotate a logged-in ID.
    sessionIdentity.tabId = tabId;
}

export function getRequiredTabId() {
    if (sessionIdentity.tabId === null) {
        throw new Error('Browser session identity has not been initialized');
    }
    return sessionIdentity.tabId;
}


export function buildSessionHeaders(includeContentType) {
    if (typeof includeContentType !== 'boolean') {
        throw new Error('buildSessionHeaders requires boolean includeContentType');
    }

    const headers = {
        'X-Metalist-Tab-Id': getRequiredTabId(),
    };
    if (includeContentType) {
        headers['Content-Type'] = 'application/json';
    }
    return headers;
}
