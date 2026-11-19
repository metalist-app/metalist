import { formatByteSize } from './byte-sizes.js';

// The files that go with notes deleted in bulk, as the confirmations say them (Delete Folder
// with its notes, Delete Notes (Current View); the maintainer, 2026-11-18): only the files
// those notes use and nothing else does, counted by the server (files_of_deleted_notes.py),
// so what is said is what is deleted. Nothing is said when no file goes.

const ONE = 1;

function requireCounts({ noteCount, fileCount, fileBytes }) {
    const counts = [noteCount, fileCount, fileBytes];
    if (!counts.every((count) => Number.isInteger(count) && count >= 0)) {
        throw new Error('The files that go with notes need whole counts of notes, files and bytes');
    }
}

// ' and their 212 files (1.8 GB)', to follow 'its 1289 notes'; '' when no file goes.
export function filesAfterNotesText({ noteCount, fileCount, fileBytes }) {
    requireCounts({ noteCount, fileCount, fileBytes });
    if (fileCount === 0) return '';
    const whose = noteCount === ONE ? 'its' : 'their';
    const files = fileCount === ONE ? 'file' : 'files';
    return ` and ${whose} ${fileCount} ${files} (${formatByteSize(fileBytes)})`;
}

// A sentence of its own: 'Their 212 files (1.8 GB) are deleted too.'; '' when no file goes.
export function filesDeletedTooSentence({ noteCount, fileCount, fileBytes }) {
    requireCounts({ noteCount, fileCount, fileBytes });
    if (fileCount === 0) return '';
    const whose = noteCount === ONE ? 'Its' : 'Their';
    const files = fileCount === ONE ? 'file' : 'files';
    const verb = fileCount === ONE ? 'is' : 'are';
    return ` ${whose} ${fileCount} ${files} (${formatByteSize(fileBytes)}) ${verb} deleted too.`;
}

// What was deleted, for the message after: 'Deleted 3 notes and 2 files.'
export function deletedNotesAndFilesText({ noteCount, fileCount }) {
    requireCounts({ noteCount, fileCount, fileBytes: 0 });
    const notes = noteCount === ONE ? 'note' : 'notes';
    if (fileCount === 0) return `Deleted ${noteCount} ${notes}.`;
    const files = fileCount === ONE ? 'file' : 'files';
    return `Deleted ${noteCount} ${notes} and ${fileCount} ${files}.`;
}
