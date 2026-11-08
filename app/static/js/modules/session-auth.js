import { ApplicationState } from './application-state.js';
import { createUuid } from './uuid.js';

const sessionIdentity = ApplicationState.createFields('session-auth', {tabId: null});

export function initializeSessionIdentity() {
    if (sessionIdentity.tabId !== null) {
        return;
    }
    let tabId = sessionStorage.getItem('metalist_tab_id');
    if (tabId === null || tabId === '') {
        tabId = createUuid();
        sessionStorage.setItem('metalist_tab_id', tabId);
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
