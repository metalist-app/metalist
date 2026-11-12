import assert from 'node:assert/strict';
import test from 'node:test';

test('login and workspace requests retain the authenticated tab identity when browser storage is cleared', async t => {
    const stored = new Map();
    globalThis.sessionStorage = {
        getItem: key => stored.get(key) ?? null,
        setItem: (key, value) => stored.set(key, String(value)),
    };
    globalThis.window = {};
    globalThis.document = {
        body: {classList: {add() {}, remove() {}}, dataset: {}},
        getElementById: id => {
            assert.equal(id, 'login-password');
            return {value: 'fixture-password'};
        },
    };
    t.after(() => {
        delete globalThis.sessionStorage;
        delete globalThis.window;
        delete globalThis.document;
    });
    const {Auth} = await import('../../app/static/js/modules/auth.js');
    const {buildSessionHeaders} = await import('../../app/static/js/modules/session-auth.js');
    t.mock.method(Auth, 'setupEventListeners', () => {});
    t.mock.method(Auth, 'checkAuthStatus', async () => false);
    await Auth.init();
    const loginId = stored.get('metalist_tab_id');
    assert.ok(loginId);
    const headers = [];
    t.mock.method(globalThis, 'fetch', async (_url, options) => {
        headers.push(options.headers);
        return {ok: true, text: async () => JSON.stringify({hydration_required: true})};
    });
    t.mock.method(Auth, '_clearLoginError', () => {});
    t.mock.method(Auth, '_setLoginSubmitBusy', () => {});
    t.mock.method(Auth, '_runHydrationFlow', async () => {
        stored.delete('metalist_tab_id');
    });
    // The workspace's code (app-start.js) needs a browser; a stand-in makes its one request and
    // says the page is ready the way it does, through Auth.
    t.mock.method(Auth, 'loadApp', async () => ({
        startWorkspace: async ({onStage}) => {
            onStage('initializing the workspace UI');
            headers.push(buildSessionHeaders(true));
            document.body.dataset.appReady = 'true';
        },
        afterWorkspaceReady: async ({auth}) => auth.announceWorkspaceReady(),
    }));
    await Auth.handleLogin({preventDefault() {}});
    assert.equal(document.body.dataset.appReady, 'true');
    // The login, the workspace's start, and saying the page has finished starting.
    assert.equal(headers.length, 3);
    assert.ok(headers.every(header => header['X-Metalist-Tab-Id'] === loginId));
});

test('saying the page has finished starting reads the whole reply', async t => {
    const stored = new Map([['metalist_tab_id', 'fixture-tab']]);
    globalThis.sessionStorage = {
        getItem: key => stored.get(key) ?? null,
        setItem: (key, value) => stored.set(key, String(value)),
    };
    globalThis.window = {};
    globalThis.document = {body: {classList: {add() {}, remove() {}}, dataset: {}}};
    t.after(() => {
        delete globalThis.sessionStorage;
        delete globalThis.window;
        delete globalThis.document;
    });
    const {Auth} = await import('../../app/static/js/modules/auth.js');
    const {initializeSessionIdentity} = await import('../../app/static/js/modules/session-auth.js');
    initializeSessionIdentity();
    const reply = new Response('{"status":"success"}');
    t.mock.method(globalThis, 'fetch', async () => reply);
    await Auth.announceWorkspaceReady();
    // A browser counts a request as open until its reply is read, so an unread one
    // means the page never goes quiet for anything waiting on its network to settle.
    assert.equal(reply.bodyUsed, true);
});
