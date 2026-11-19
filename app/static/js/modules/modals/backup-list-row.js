import { formatByteSize } from '../byte-sizes.js';

// One backup as a row of Restore From Backup's list (the maintainer, 2026-11-18: each was one
// long line of its file name, its size in KB and a cut-off timestamp): the vault it holds, when
// it was made in the reader's own time and words, how big it is, and where it is kept. The file
// name is the row's tooltip.

// The backup folder the user chose, a file picked with Choose File…, or the backups MetaList
// keeps in the vault's own folder.
export const SOURCE_CHOSEN_FILE = 'file';
const SOURCE_LABELS = Object.freeze({ folder: 'Backup folder', file: 'Chosen file', internal: 'Kept by MetaList' });

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

function sourceLabel(source) {
    if (!Object.hasOwn(SOURCE_LABELS, source)) {
        throw new Error(`A backup is kept somewhere unknown: ${source}`);
    }
    return SOURCE_LABELS[source];
}

// The list with a file picked with Choose File… on top, in place of any picked before.
export function backupsWithChosenFile(backups, chosen) {
    if (!Array.isArray(backups) || !chosen || chosen.source !== SOURCE_CHOSEN_FILE) {
        throw new Error('backupsWithChosenFile requires the list and a chosen file');
    }
    return [chosen, ...backups.filter((backup) => backup.source !== SOURCE_CHOSEN_FILE)];
}

const CHOSEN_FILE_GROUP = 'Chosen file';

// The list in groups, a vault each (the maintainer, 2026-11-19: the vaults' backups were mixed
// by time): a file picked with Choose File… first, then the open vault, then the other vaults
// by name. Within a group the backups keep their order, newest first.
export function backupGroups(backups, openVault) {
    if (!Array.isArray(backups) || typeof openVault !== 'string') {
        throw new Error('backupGroups requires the list and the open vault');
    }
    const chosen = backups.filter((backup) => backup.source === SOURCE_CHOSEN_FILE);
    const listed = backups.filter((backup) => backup.source !== SOURCE_CHOSEN_FILE);
    const otherVaults = [...new Set(listed.map((backup) => backup.namespace))]
        .filter((vault) => vault !== openVault)
        .sort((first, second) => first.localeCompare(second));
    const groups = [];
    if (chosen.length > 0) {
        groups.push({ title: `${CHOSEN_FILE_GROUP}: ${chosen[0].namespace}`, backups: chosen });
    }
    for (const vault of [openVault, ...otherVaults]) {
        const ofVault = listed.filter((backup) => backup.namespace === vault);
        if (ofVault.length > 0) groups.push({ title: vault, backups: ofVault });
    }
    return groups;
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
        source: sourceLabel(backup.source),
        fileName: backup.filename,
    };
}
