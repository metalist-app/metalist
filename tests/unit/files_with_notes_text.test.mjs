import assert from 'node:assert/strict';
import test from 'node:test';

import {
    deletedNotesAndFilesText, filesAfterNotesText, filesDeletedTooSentence,
} from '../../app/static/js/modules/files-with-notes-text.js';

const MIB = 1024 * 1024;

// What Delete Folder with its notes and Delete Notes (Current View) say of the files that go
// with the notes (the maintainer, 2026-11-18).
test('the files are said with their count and size, after the notes', () => {
    assert.equal(filesAfterNotesText({ noteCount: 1289, fileCount: 212, fileBytes: 1800 * MIB }), ' and their 212 files (1.8 GB)');
    assert.equal(filesAfterNotesText({ noteCount: 1, fileCount: 1, fileBytes: 2 * MIB }), ' and its 1 file (2.0 MB)');
    assert.equal(filesAfterNotesText({ noteCount: 1, fileCount: 3, fileBytes: 2 * MIB }), ' and its 3 files (2.0 MB)');
    assert.equal(filesAfterNotesText({ noteCount: 4, fileCount: 1, fileBytes: 2 * MIB }), ' and their 1 file (2.0 MB)');
});

test('nothing is said of files when none goes', () => {
    assert.equal(filesAfterNotesText({ noteCount: 4, fileCount: 0, fileBytes: 0 }), '');
    assert.equal(filesDeletedTooSentence({ noteCount: 4, fileCount: 0, fileBytes: 0 }), '');
    assert.equal(deletedNotesAndFilesText({ noteCount: 4, fileCount: 0 }), 'Deleted 4 notes.');
});

test('the files as a sentence of their own, and in the message after', () => {
    assert.equal(filesDeletedTooSentence({ noteCount: 4, fileCount: 2, fileBytes: 2 * MIB }), ' Their 2 files (2.0 MB) are deleted too.');
    assert.equal(filesDeletedTooSentence({ noteCount: 1, fileCount: 1, fileBytes: 2 * MIB }), ' Its 1 file (2.0 MB) is deleted too.');
    assert.equal(deletedNotesAndFilesText({ noteCount: 4, fileCount: 2 }), 'Deleted 4 notes and 2 files.');
    assert.equal(deletedNotesAndFilesText({ noteCount: 1, fileCount: 1 }), 'Deleted 1 note and 1 file.');
});

test('a count that is no whole number is refused', () => {
    assert.throws(() => filesAfterNotesText({ noteCount: 1, fileCount: undefined, fileBytes: 0 }), /whole counts/);
});
