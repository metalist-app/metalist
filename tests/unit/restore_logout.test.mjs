import assert from 'node:assert/strict';
import test from 'node:test';

// Restoring the open vault restarts the server, which ends the session. Background
// requests answered "not logged in" meanwhile (a tab-state save, seen in the core
// browser suite) must not send the page to Session locked before the restore dialog
// reloads it into the login screen (docs/BUGS.md, 2026-10-18). The browser suite
// `restore-session` drives the real dialog.

function createStorage() {
    const values = new Map();
    return {
        getItem: (key) => (values.has(key) ? values.get(key) : null),
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: (key) => values.delete(key),
    };
}

globalThis.sessionStorage = createStorage();
globalThis.localStorage = createStorage();
const navigations = [];
globalThis.window = { location: { replace: (url) => navigations.push(url) } };
globalThis.document = { body: { replaceChildren() {} } };
const { Auth } = await import('../../app/static/js/modules/auth.js');
const { setRestoringOpenVault } = await import('../../app/static/js/modules/restore-session-end.js');

function freshAuth(t) {
    navigations.length = 0;
    // A logout from an earlier test would otherwise make forceLogout return early.
    if (Auth._forcingLogout) Auth._forcingLogout = false;
    t.mock.method(Auth, 'clearSessionState', () => {});
}

test('a "not logged in" answer while the open vault is restored does not lock the page', (t) => {
    freshAuth(t);
    setRestoringOpenVault(true);
    // The dialog marks it again once the server answers that the vault restarted.
    setRestoringOpenVault(true);

    Auth.forceLogout('Session expired');

    assert.deepEqual(navigations, []);
    setRestoringOpenVault(false);
});

test('after a failed restore a lost session locks the page as usual', (t) => {
    freshAuth(t);
    setRestoringOpenVault(true);
    setRestoringOpenVault(false);

    Auth.forceLogout('Session expired');

    assert.deepEqual(navigations, ['/locked']);
});

test('the restore state must be a boolean', () => {
    assert.throws(() => setRestoringOpenVault('yes'), /requires a boolean/);
});
