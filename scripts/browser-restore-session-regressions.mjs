import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Restoring the open vault restarts the server, which ends the session (docs/BUGS.md,
// 2026-10-18). A background request the restarted server answers "not logged in" (a
// tab-state save, as seen in the core suite) must not send the page to Session locked:
// the dialog says the backup was restored and, when closed, reloads into the login
// screen.
//
// The page stands in for the server: the restore answers that the open vault restarted,
// and every other request after it is answered "not logged in".

const SETTLE_MS = 300;
const BACKUP = Object.freeze({
    backup_id: 'b1', filename: 'default-backup.tar.gz', namespace: 'default',
    created_at: '2026-10-24T10:00:00Z', size_bytes: 2048, source: 'internal',
});

// The answers the page gets in place of the server's, by path.
async function installFakeServer(page) {
    await page.evaluate(async (backup) => {
        const fake = {originalFetch: window.fetch, isRestored: false, unauthorized: 0};
        window.restoreSessionTest = fake;
        const answers = {
            '/api2/backup/list': {backups: [backup]},
            '/api2/backup/restore/preflight': {same_namespace: true, target_exists: true,
                target_requires_password: false, target_is_active: true},
            '/api2/backup/restore': {backup_filename: backup.filename, target_namespace: backup.namespace,
                active_namespace_restarted: true, open_namespace_suggested: false},
        };
        const reply = (body, status) => new Response(JSON.stringify(body), {
            status, headers: {'Content-Type': 'application/json'},
        });
        window.fetch = async (url, options) => {
            const path = new URL(url, location.href).pathname;
            if (fake.isRestored && path.startsWith('/api2/')) {
                fake.unauthorized += 1;
                return reply({detail: 'Not authenticated'}, 401);
            }
            if (path in answers) {
                if (path === '/api2/backup/restore') fake.isRestored = true;
                return reply(answers[path], 200);
            }
            return fake.originalFetch(url, options);
        };
    }, BACKUP);
}

async function restoreOpenVaultThroughDialog(page) {
    await page.evaluate(async () => {
        const {BackupRestoreModal} = await import('/static/js/modules/modals/backup-restore-modal.js');
        await new BackupRestoreModal().open();
    });
    await page.waitForSelector('#restore-backup-btn', {visible: true});
    await page.click('#restore-backup-btn');
    await page.waitForFunction(() => document.getElementById('restore-backup-btn')?.textContent.trim() === 'Restore Backup');
    await page.click('#restore-backup-btn');
    await page.waitForFunction(() => document.body.textContent.includes('Backup restored successfully'));
}

export async function checkRestoreSession(page) {
    const appUrl = page.url();
    await installFakeServer(page);
    await restoreOpenVaultThroughDialog(page);

    // The restarted server answers a background tab-state request "not logged in".
    const outcome = await page.evaluate(async () => {
        const {deleteTabOnServer} = await import('/static/js/modules/mode-manager/services/tab-state-service.js');
        const [result] = await Promise.allSettled([deleteTabOnServer('restore-session-test-tab')]);
        return {status: result.status, unauthorized: window.restoreSessionTest.unauthorized};
    });
    assert.equal(outcome.status, 'rejected', 'the request was refused');
    assert(outcome.unauthorized >= 1, 'the server answered "not logged in"');
    await waitForAppQuiet(page, SETTLE_MS);

    assert.equal(page.url(), appUrl, 'the page stays instead of going to Session locked');
    assert(await page.evaluate(() => document.body.textContent.includes('Close this modal to reload the app')),
        'the dialog still says the backup was restored');
    console.log('PASS restoring the open vault keeps the page off Session locked');
}
