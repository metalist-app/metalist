import assert from 'node:assert/strict';
import test from 'node:test';

import { describeDroppedItems } from '../../app/static/js/modules/mode-manager/services/dropped-folders.js';

// A browser hands a dropped folder over as a File it can't read: uploading it failed with
// "File drop failed: NetworkError…" (the maintainer, 2026-11-02). Its entry says it is a folder.
function item(isDirectory) {
    return { kind: 'file', webkitGetAsEntry: () => ({ isDirectory, isFile: !isDirectory }) };
}

function transfer(items) {
    return { items, files: [] };
}

test('a drop of files has no folder', () => {
    assert.deepEqual(describeDroppedItems(transfer([item(false), item(false)])), { folderCount: 0, itemCount: 2 });
});

test('a dropped folder is counted as one, with whatever came with it', () => {
    assert.deepEqual(describeDroppedItems(transfer([item(true)])), { folderCount: 1, itemCount: 1 });
    assert.deepEqual(describeDroppedItems(transfer([item(true), item(false)])), { folderCount: 1, itemCount: 2 });
    assert.deepEqual(describeDroppedItems(transfer([item(true), item(true)])), { folderCount: 2, itemCount: 2 });
});

test('text dragged along is not an item of the drop', () => {
    assert.deepEqual(describeDroppedItems(transfer([{ kind: 'string' }, item(true)])), { folderCount: 1, itemCount: 1 });
});

test('a browser without entries fails loudly', () => {
    assert.throws(() => describeDroppedItems(transfer([{ kind: 'file' }])), /webkitGetAsEntry/);
});

// Browsers hand a folder's contents out in batches, so a large folder needs several reads.
const BATCH = 2;

function fileEntry(name, size) {
    return { isFile: true, isDirectory: false, name, file: (resolve) => resolve({ name, size }) };
}

function folderEntry(name, children) {
    return {
        isFile: false, isDirectory: true, name,
        createReader() {
            let next = 0;
            return {
                readEntries(resolve) {
                    resolve(children.slice(next, next + BATCH));
                    next += BATCH;
                },
            };
        },
    };
}

test('a dropped folder is read to its last file, every batch, its paths inside it', async () => {
    const { readDroppedFolder } = await import('../../app/static/js/modules/mode-manager/services/dropped-folders.js');
    const photos = folderEntry('Photos', [
        fileEntry('a.jpg', 1), fileEntry('b.jpg', 2), fileEntry('c.jpg', 3),
        folderEntry('trip', [fileEntry('d.jpg', 4), folderEntry('empty', [])]),
        fileEntry('.DS_Store', 5),
    ]);
    const folder = await readDroppedFolder(photos);
    assert.equal(folder.name, 'Photos');
    assert.deepEqual(folder.files.map(({ path, size }) => [path, size]),
        [['a.jpg', 1], ['b.jpg', 2], ['c.jpg', 3], ['trip/d.jpg', 4], ['.DS_Store', 5]]);
    assert.deepEqual(folder.files[3].file, { name: 'd.jpg', size: 4 });
});
