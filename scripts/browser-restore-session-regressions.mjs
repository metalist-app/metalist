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
// The checks a tab shown again runs: backup, trim, password audit, reminders.
const REMINDER_CHECKS = 4;
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
            '/api2/backup/list': {backups: [backup], can_choose_file: false, current_namespace: 'default'},
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

// Choose File… (the maintainer, 2026-11-19): a backup kept anywhere on this computer. The page
// stands in for the server and its file dialog (tests/unit/test_restore_chosen_backup_file.py
// covers the server): the list offers the button, and the dialog answers with `picked`.
const CHOSEN_PATH = '/Users/example/Downloads/other-20261119-064000-123456.metalist-backup.tar.gz';
const CHOSEN = Object.freeze({
    backup_id: 'file::other::other-20261119-064000-123456.metalist-backup.tar.gz',
    filename: 'other-20261119-064000-123456.metalist-backup.tar.gz', namespace: 'other',
    created_at: '2026-11-19T14:40:00Z', size_bytes: 4096, source: 'file',
});

async function openRestoreWith(page, {canChooseFile, picked}) {
    await page.evaluate(async ({backup, canChooseFile, picked}) => {
        const originalFetch = window.fetch;
        window.chooseFileTest = {originalFetch};
        const reply = body => new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
        window.fetch = async (url, options) => {
            const path = new URL(url, location.href).pathname;
            if (path === '/api2/backup/list') return reply({backups: [backup], can_choose_file: canChooseFile, current_namespace: 'default'});
            if (path === '/api2/backup/restore/file/pick') return reply(picked);
            return originalFetch(url, options);
        };
        const {BackupRestoreModal} = await import('/static/js/modules/modals/backup-restore-modal.js');
        await new BackupRestoreModal().open();
    }, {backup: BACKUP, canChooseFile, picked});
    await page.waitForSelector('#restore-backup-btn', {visible: true});
}

async function closeRestore(page) {
    await page.click('#close-backup-modal-btn');
    await page.waitForFunction(() => document.querySelector('#backup-restore-modal .modal-content') === null
        || document.getElementById('backup-restore-modal').style.display === 'none');
    await page.evaluate(() => { window.fetch = window.chooseFileTest.originalFetch; });
    await waitForAppQuiet(page, SETTLE_MS);
}

function restoreList(page) {
    return page.evaluate(() => ({
        // Each row under its group's heading: the vault, or the chosen file.
        rows: [...document.querySelectorAll('#backup-select .backup-restore-row')].map(row => ({
            vault: (() => {
                let heading = row.previousElementSibling;
                while (!heading.classList.contains('backup-restore-group')) heading = heading.previousElementSibling;
                return heading.textContent;
            })(),
            source: row.querySelector('.backup-restore-source').textContent,
            tooltip: row.title, isChosen: row.querySelector('input').checked,
        })),
        target: document.getElementById('backup-target-namespace').value,
        hasButton: document.getElementById('backup-restore-choose-file-btn') !== null,
    }));
}

async function checkChooseFile(page) {
    const listed = {vault: 'default', source: 'Kept by MetaList', tooltip: BACKUP.filename};

    await openRestoreWith(page, {canChooseFile: false, picked: {selected: false, backups: [], file_path: ''}});
    assert.equal((await restoreList(page)).hasButton, false, 'from another computer: no Choose File…');
    await closeRestore(page);

    await openRestoreWith(page, {canChooseFile: true, picked: {selected: false, backups: [], file_path: ''}});
    await page.click('#backup-restore-choose-file-btn');
    await waitForAppQuiet(page, SETTLE_MS);
    assert.deepEqual(await restoreList(page), {rows: [{...listed, isChosen: true}], target: 'default', hasButton: true},
        'the file dialog cancelled: the list stays as it was');
    await closeRestore(page);

    await openRestoreWith(page, {canChooseFile: true, picked: {selected: true, backups: [CHOSEN], file_path: CHOSEN_PATH}});
    await page.click('#backup-restore-choose-file-btn');
    await page.waitForFunction(() => document.querySelectorAll('#backup-select .backup-restore-row').length > 1);
    assert.deepEqual(await restoreList(page), {
        rows: [{vault: 'Chosen file: other', source: 'Chosen file', tooltip: CHOSEN_PATH, isChosen: true}, {...listed, isChosen: false}],
        target: 'other', hasButton: true,
    }, 'a chosen file: a row on top, chosen, saying where it is; its vault is the target');
    await closeRestore(page);

    await openRestoreWith(page, {canChooseFile: true, picked: {selected: false, backups: [], file_path: ''}});
    assert.deepEqual((await restoreList(page)).rows, [{...listed, isChosen: true}], 'opened again: the chosen file is gone from the list');
    await closeRestore(page);
    console.log('PASS Choose File… puts a backup from anywhere on top of the restore list');
}

export async function checkRestoreSession(page) {
    await checkChooseFile(page);
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

    // The tab is shown again (after a look at another tab) while the dialog waits to be closed (the maintainer's
    // dad, 2026-11-18): the reminder checks that run then (backup, trim, password audit,
    // reminders) are refused too, and must show no red error.
    const refusedBefore = await page.evaluate(() => window.restoreSessionTest.unauthorized);
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForFunction(before => window.restoreSessionTest.unauthorized >= before.refused + before.checks,
        {}, {refused: refusedBefore, checks: REMINDER_CHECKS});
    await waitForAppQuiet(page, SETTLE_MS);
    assert.equal(await page.$('#fatal-error-overlay'), null, 'a request refused after the restore should show no red error');
    assert(await page.evaluate(() => document.body.textContent.includes('Close this modal to reload the app')),
        'the dialog still says the backup was restored');
    console.log('PASS requests refused after a restore show no red error');
}
