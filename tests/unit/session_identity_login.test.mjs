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
    const {CommandPalette} = await import('../../app/static/js/modules/command-palette/command-palette-controller.js');
    const {AiChatPanel} = await import('../../app/static/js/modules/ai-chat/ai-chat-panel-controller.js');
    const {ReminderSurface} = await import('../../app/static/js/modules/reminder-surface-service.js');
    const {PhoneMode} = await import('../../app/static/js/modules/phone/phone-mode.js');
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
    window.ModeManager = {init: async () => { headers.push(buildSessionHeaders(true)); }};
    t.mock.method(CommandPalette, 'init', async () => {});
    t.mock.method(CommandPalette, 'startUpdateNotice', () => {});
    t.mock.method(CommandPalette, 'startBackupReminder', async () => {});
    t.mock.method(CommandPalette, 'runSetupRequestedByAddress', async () => {});
    t.mock.method(AiChatPanel, 'init', async () => {});
    t.mock.method(PhoneMode, 'init', () => {});
    t.mock.method(Auth, 'revealMainApp', () => {});
    t.mock.method(ReminderSurface, 'start', async () => {});
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
