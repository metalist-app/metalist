import assert from 'node:assert/strict';
import test from 'node:test';

// Every import was refused (422) once the checklist sent files ticked against their kind: the
// API client built the request field by field and left the two new lists out (2026-11-01).
// The body carries every field the server's ImportFolderRequest requires.
const IMPORT_REQUEST_FIELDS = [
    'source', 'folderPath', 'splitMode', 'contentFormat', 'prefixFolder', 'addToExisting',
    'excludedGroups', 'excludedFiles', 'includedFiles', 'keepsMarkdownAsFiles', 'previewKinds', 'compressesImages', 'imageLongestSide',
];

test('an import request carries every field the server requires, the checklist\'s files too', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    const hadWindow = typeof globalThis.window !== 'undefined';
    if (!hadWindow) globalThis.window = {};
    t.after(() => {
        if (!hadWindow) delete globalThis.window;
        if (typeof originalSessionStorage === 'undefined') {
            delete globalThis.sessionStorage;
        } else {
            globalThis.sessionStorage = originalSessionStorage;
        }
    });
    const { NotesAPI } = await import('../../app/static/js/modules/api-client.js');
    const body = JSON.parse(NotesAPI._importBody({
        source: 'files', folderPath: '/notes', splitMode: 'none', contentFormat: 'rich', prefixFolder: 'Notes',
        addToExisting: true, excludedGroups: ['hidden'], excludedFiles: ['a.png'], includedFiles: ['.config/b.txt'],
        keepsMarkdownAsFiles: true, previewKinds: ['pdf'], compressesImages: true, imageLongestSide: 1920,
    }, 'previewImport'));
    assert.deepEqual(Object.keys(body).sort(), [...IMPORT_REQUEST_FIELDS].sort());
    assert.deepEqual(body.excludedFiles, ['a.png']);
    assert.deepEqual(body.includedFiles, ['.config/b.txt']);
    assert.equal(body.compressesImages, true);
    assert.equal(body.imageLongestSide, 1920);
});
