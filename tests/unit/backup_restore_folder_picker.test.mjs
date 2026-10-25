import assert from 'node:assert/strict';
import test from 'node:test';


test('restore modal can choose and save a backup folder without creating a backup', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = {
        getItem() {
            return null;
        },
        setItem() {},
        removeItem() {},
    };
    t.after(() => {
        if (typeof originalSessionStorage === 'undefined') {
            delete globalThis.sessionStorage;
        } else {
            globalThis.sessionStorage = originalSessionStorage;
        }
    });

    const { BackupRestoreModal } = await import(
        '../../app/static/js/modules/modals/backup-restore-modal.js'
    );
    const modal = new BackupRestoreModal();
    let state = modal.getInitialModalState();
    const requests = [];
    let reloaded = false;
    modal.getModalState = () => state;
    modal.updateModalState = (updates) => {
        state = { ...state, ...updates };
    };
    modal.renderModalContent = () => {};
    // The progress card (floating-messages.js) needs the page.
    modal._showProgress = () => {};
    modal._endProgress = () => {};
    modal.loadBackups = async () => {
        reloaded = true;
    };
    modal._authRequest = async (url, method, body) => {
        requests.push({ url, method, body });
        if (method === 'GET') {
            return {
                folder_path: '',
                selected_namespaces: ['default'],
                available_namespaces: ['default', 'henry'],
                retention_count: 30,
            };
        }
        if (url.endsWith('/folder/pick')) {
            return {
                selected: true,
                folder_path: '/Users/example/MetaList Backups',
            };
        }
        return {
            folder_path: '/Users/example/MetaList Backups',
            selected_namespaces: ['default'],
            available_namespaces: ['default', 'henry'],
            retention_count: 30,
        };
    };

    await modal.chooseBackupFolder();

    assert.deepEqual(requests, [
        {
            url: '/api2/backup/settings',
            method: 'GET',
            body: null,
        },
        {
            url: '/api2/backup/folder/pick',
            method: 'POST',
            body: {},
        },
        {
            url: '/api2/backup/settings',
            method: 'PUT',
            body: {
                folder_path: '/Users/example/MetaList Backups',
                selected_namespaces: ['default'],
                retention_count: 30,
            },
        },
    ]);
    assert.equal(reloaded, true);
});
