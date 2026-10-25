import assert from 'node:assert/strict';
import test from 'node:test';


const RESTORE_TRANSITION_UNTIL_KEY = 'metalist_restore_transition_until_ms';


test('different-name import into the active namespace suppresses errors before the request starts', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    const storedValues = new Map();
    globalThis.sessionStorage = {
        getItem(key) {
            return storedValues.has(key) ? storedValues.get(key) : null;
        },
        setItem(key, value) {
            storedValues.set(key, value);
        },
        removeItem(key) {
            storedValues.delete(key);
        },
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
    modal.getModalState = () => ({
        preflight: {
            same_namespace: false,
            target_is_active: true,
            target_exists: true,
            target_requires_password: true,
        },
        overwriteConfirmText: 'default',
        targetPassword: 'password',
        importLaunchProfile: {
            port: '8002',
            httpsPort: '8445',
        },
    });
    modal._validateRestoreSelection = () => ({
        selectedBackup: {
            backup_id: 'folder:henry:backup.tar.gz',
            source: 'folder',
            filename: 'backup.tar.gz',
            namespace: 'henry',
        },
        targetNamespace: 'default',
    });
    modal.updateModalState = () => {};
    modal.renderModalContent = () => {};
    // The progress card (floating-messages.js) needs the page.
    modal._showProgress = () => {};
    modal._endProgress = () => {};
    modal._authRequest = async () => {
        const rawUntil = storedValues.get(RESTORE_TRANSITION_UNTIL_KEY);
        assert.equal(typeof rawUntil, 'string');
        assert.ok(Number.parseInt(rawUntil, 10) > Date.now());
        return {
            active_namespace_restarted: true,
            backup_filename: 'backup.tar.gz',
            target_namespace: 'default',
            open_namespace_suggested: false,
        };
    };

    await modal._submitConfirmedRestore();
});
