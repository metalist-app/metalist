import assert from 'node:assert/strict';
import test from 'node:test';

import { backupGroups, backupRow, backupWhenText, backupsWithChosenFile } from '../../app/static/js/modules/modals/backup-list-row.js';

// Restore From Backup lists each backup by its vault, when it was made, its size and where it
// is kept (the maintainer, 2026-11-18: it was one long line of the file's name, KB and a
// cut-off timestamp).
const READER = { locale: 'en-US', timeZone: 'America/Los_Angeles' };
const BACKUP = {
    backup_id: 'folder::thomas::thomas-20261119-024902-285133.metalist-backup.tar.gz',
    filename: 'thomas-20261119-024902-285133.metalist-backup.tar.gz',
    namespace: 'thomas', created_at: '2026-11-19T02:49:02Z', size_bytes: 239312896, source: 'folder',
};

test('a backup is its vault, when it was made in the reader\'s time, its size and where it is kept', () => {
    assert.deepEqual(backupRow(BACKUP, READER), {
        id: BACKUP.backup_id, vault: 'thomas', when: 'Nov 18, 2026, 6:49 PM', size: '228.2 MB',
        source: 'Backup folder', fileName: BACKUP.filename,
    });
});

test('a backup MetaList keeps in the vault\'s own folder says so', () => {
    assert.equal(backupRow({ ...BACKUP, source: 'internal' }, READER).source, 'Kept by MetaList');
});

test('the time follows the reader\'s language and time zone', () => {
    assert.equal(backupWhenText('2026-11-19T02:49:02Z', { locale: 'en-GB', timeZone: 'Europe/London' }), '19 Nov 2026, 02:49');
});

test('a backup with no time, or one that is no date, is refused', () => {
    assert.throws(() => backupRow({ ...BACKUP, created_at: '' }, READER), /created_at/);
    assert.throws(() => backupWhenText('yesterday', READER), /not a date/);
});

// Choose File… (the maintainer, 2026-11-19): a backup picked anywhere on this computer.
const CHOSEN = { ...BACKUP, backup_id: `file::thomas::${BACKUP.filename}`, source: 'file' };

test('a file picked with Choose File… says so', () => {
    assert.equal(backupRow(CHOSEN, READER).source, 'Chosen file');
});

test('a backup kept somewhere unknown is refused', () => {
    assert.throws(() => backupRow({ ...BACKUP, source: 'elsewhere' }, READER), /somewhere unknown/);
});

test('a chosen file goes on top of the list, in place of one chosen before', () => {
    const other = { ...CHOSEN, backup_id: 'file::thomas::other.metalist-backup.tar.gz' };
    assert.deepEqual(backupsWithChosenFile([BACKUP], CHOSEN), [CHOSEN, BACKUP]);
    assert.deepEqual(backupsWithChosenFile([CHOSEN, BACKUP], other), [other, BACKUP]);
    assert.throws(() => backupsWithChosenFile([BACKUP], BACKUP), /chosen file/);
});

// Grouped by vault (the maintainer, 2026-11-19: the vaults' backups were mixed by time).
test('the list is grouped by vault: a chosen file, the open vault, then the others by name', () => {
    const of = (namespace, id) => ({ ...BACKUP, namespace, backup_id: id });
    const [zed, clasNewest, thomasNewest, clasOlder] = [of('zed', 'z1'), of('cla', 'c1'), of('thomas', 't1'), of('cla', 'c2')];
    const chosen = { ...CHOSEN, namespace: 'dad' };
    assert.deepEqual(backupGroups([chosen, zed, clasNewest, thomasNewest, clasOlder], 'thomas'), [
        { title: 'Chosen file: dad', backups: [chosen] },
        { title: 'thomas', backups: [thomasNewest] },
        { title: 'cla', backups: [clasNewest, clasOlder] },
        { title: 'zed', backups: [zed] },
    ]);
});

test('an open vault with no backups has no group', () => {
    assert.deepEqual(backupGroups([BACKUP], 'other').map((group) => group.title), ['thomas']);
    assert.deepEqual(backupGroups([], 'thomas'), []);
});
