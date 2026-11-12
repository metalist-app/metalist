import assert from 'node:assert/strict';
import test from 'node:test';


async function restoreModalAnswering(t, {status, body}) {
    const originalFetch = globalThis.fetch;
    const originalSessionStorage = globalThis.sessionStorage;
    const storedValues = new Map();
    globalThis.sessionStorage = {
        getItem: (key) => (storedValues.has(key) ? storedValues.get(key) : null),
        setItem: (key, value) => storedValues.set(key, value),
        removeItem: (key) => storedValues.delete(key),
    };
    globalThis.fetch = async () => ({
        ok: false,
        status,
        headers: {get: () => 'application/json'},
        json: async () => body,
    });
    t.after(() => {
        globalThis.fetch = originalFetch;
        if (typeof originalSessionStorage === 'undefined') {
            delete globalThis.sessionStorage;
        } else {
            globalThis.sessionStorage = originalSessionStorage;
        }
    });
    const { BackupRestoreModal } = await import('../../app/static/js/modules/modals/backup-restore-modal.js');
    const modal = new BackupRestoreModal();
    modal._buildAuthHeaders = () => ({});
    return modal;
}


test('a restore the server refuses shows only its message', async (t) => {
    const detail = "This backup has no attached files; restoring it would delete this vault's files. Choose another backup.";
    const modal = await restoreModalAnswering(t, {status: 400, body: {detail, inputRejected: true}});

    await assert.rejects(modal._authRequest('/api2/backup/restore', 'POST', {}), (error) => {
        assert.equal(error.message, detail);
        return true;
    });
});


test('any other failed request keeps its status', async (t) => {
    const modal = await restoreModalAnswering(t, {status: 500, body: {detail: 'Backup archive is damaged'}});

    await assert.rejects(modal._authRequest('/api2/backup/restore', 'POST', {}), (error) => {
        assert.equal(error.message, 'Request failed (500): Backup archive is damaged');
        return true;
    });
});
