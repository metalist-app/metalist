import assert from 'node:assert/strict';
import test from 'node:test';

async function session(t, name, entries) {
    const stored = new Map(entries);
    globalThis.sessionStorage = {
        getItem: key => stored.get(key) ?? null,
        setItem: (key, value) => stored.set(key, String(value)),
    };
    t.after(() => { delete globalThis.sessionStorage; });
    const api = await import(`../../app/static/js/modules/session-auth.js?test=${name}`);
    return {api, stored};
}

test('requests before session initialization fail without silently creating an identity', async t => {
    const {api, stored} = await session(t, 'uninitialized', []);
    assert.throws(() => api.buildSessionHeaders(false), /not been initialized/);
    assert.equal(stored.size, 0);
});

test('a new page creates one identity and keeps it even if storage changes', async t => {
    const {api, stored} = await session(t, 'new-page', []);
    api.initializeSessionIdentity();
    const tabId = api.getRequiredTabId();
    assert.match(tabId, /^[0-9a-f-]{36}$/);
    assert.equal(stored.get('metalist_tab_id'), tabId);
    stored.set('metalist_tab_id', 'unrelated-identity');
    api.initializeSessionIdentity();
    assert.equal(api.buildSessionHeaders(false)['X-Metalist-Tab-Id'], tabId);
    assert.equal(stored.get('metalist_tab_id'), 'unrelated-identity');
});

test('reload reuses stored identity and active requests no longer depend on storage access', async t => {
    const {api} = await session(t, 'reload', [['metalist_tab_id', 'existing-tab']]);
    api.initializeSessionIdentity();
    globalThis.sessionStorage.getItem = () => { throw new Error('Storage no longer accessible'); };
    assert.equal(api.getRequiredTabId(), 'existing-tab');
    assert.deepEqual(api.buildSessionHeaders(true), {
        'X-Metalist-Tab-Id': 'existing-tab', 'Content-Type': 'application/json',
    });
});
