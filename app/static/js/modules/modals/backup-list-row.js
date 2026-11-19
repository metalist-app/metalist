import { formatByteSize } from '../byte-sizes.js';

// One backup as a row of Restore From Backup's list (the maintainer, 2026-11-18: each was one
// long line of its file name, its size in KB and a cut-off timestamp): the vault it holds, when
// it was made in the reader's own time and words, how big it is, and where it is kept. The file
// name is the row's tooltip.

const SOURCE_FOLDER = 'folder';
// The backup folder the user chose, or the backups MetaList keeps in the vault's own folder.
const SOURCE_LABELS = Object.freeze({ folder: 'Backup folder', local: 'Kept by MetaList' });

// "Nov 18, 2026, 6:49 PM" in the reader's language and time zone.
export function backupWhenText(createdAt, { locale, timeZone }) {
    if (typeof createdAt !== 'string' || typeof locale !== 'string' || typeof timeZone !== 'string') {
        throw new Error('backupWhenText requires when the backup was made, a language and a time zone');
    }
    const made = new Date(createdAt);
    if (Number.isNaN(made.getTime())) {
        throw new Error(`A backup's time is not a date: ${createdAt}`);
    }
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(made);
}

// The row's four columns and its tooltip.
export function backupRow(backup, reader) {
    if (!backup || typeof backup !== 'object') {
        throw new Error('Invalid backup list entry');
    }
    for (const field of ['backup_id', 'filename', 'namespace', 'created_at']) {
        if (typeof backup[field] !== 'string' || backup[field].length === 0) {
            throw new Error(`Backup entry missing ${field}`);
        }
    }
    if (!Number.isInteger(backup.size_bytes) || backup.size_bytes < 0) {
        throw new Error('Backup entry missing size_bytes');
    }
    return {
        id: backup.backup_id,
        vault: backup.namespace,
        when: backupWhenText(backup.created_at, reader),
        size: formatByteSize(backup.size_bytes),
        source: backup.source === SOURCE_FOLDER ? SOURCE_LABELS.folder : SOURCE_LABELS.local,
        fileName: backup.filename,
    };
}
