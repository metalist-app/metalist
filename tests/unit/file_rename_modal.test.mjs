import assert from 'node:assert/strict';
import test from 'node:test';

const originalSessionStorage = globalThis.sessionStorage;
globalThis.sessionStorage = {
    getItem() {
        return null;
    },
    setItem() {},
};

const { splitFileExtension } = await import('../../app/static/js/modules/modals/file-rename-modal.js');

if (typeof originalSessionStorage === 'undefined') {
    delete globalThis.sessionStorage;
} else {
    globalThis.sessionStorage = originalSessionStorage;
}

// The same split as app/utils/file_names.py split_extension: the dialog edits the stem
// and shows the extension fixed beside it.
test('the extension starts at the last dot, unless that dot is first or last', () => {
    assert.deepEqual(splitFileExtension('scan_0042.pdf'), { stem: 'scan_0042', extension: '.pdf' });
    assert.deepEqual(splitFileExtension('archive.tar.gz'), { stem: 'archive.tar', extension: '.gz' });
    assert.deepEqual(splitFileExtension('Makefile'), { stem: 'Makefile', extension: '' });
    assert.deepEqual(splitFileExtension('.bashrc'), { stem: '.bashrc', extension: '' });
    assert.deepEqual(splitFileExtension('notes.'), { stem: 'notes.', extension: '' });
    assert.throws(() => splitFileExtension(null), /requires a name string/);
});
