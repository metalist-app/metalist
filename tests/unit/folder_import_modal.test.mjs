import assert from 'node:assert/strict';
import test from 'node:test';

// The folder import dialog opens for one source after another, and for the same one twice
// (2026-10-31: opening it again for the same source crashed with "Redundant state change").
test('the folder import opens again for the same source and for another one', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    // The dialog's imports (the AI's tag suggestions, the login) set globals on the page.
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
    const { FolderImportModal } = await import('../../app/static/js/modules/modals/folder-import-modal.js');
    const modal = new FolderImportModal(async () => {}, () => ({ provider: 'openai' }));
    const opened = [];
    modal.open = async () => {
        opened.push(modal.getInitialModalState().source);
    };
    await modal.openFor('obsidian');
    await modal.openFor('obsidian');
    await modal.openFor('markdown');
    await modal.openFor('markdown');
    assert.deepEqual(opened, ['obsidian', 'obsidian', 'markdown', 'markdown']);
});
