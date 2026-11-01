import assert from 'node:assert/strict';
import test from 'node:test';

// The import wizard opens for one source after another, and for the same one twice
// (2026-10-31: the import dialog it replaced crashed opening again for the same source,
// with "Redundant state change").
test('the import wizard opens again for the same source and for another one', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    // Its imports (the AI's tag suggestions, the login) set globals on the page.
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
    const { ImportWizard } = await import('../../app/static/js/modules/wizard/setup-wizards.js');
    const services = { getAiSettings: () => ({ provider: 'openai' }), saveAiSettings: async () => {}, afterImport: async () => {} };
    const wizard = new ImportWizard(services);
    const opened = [];
    wizard.open = async () => {
        opened.push(wizard.initialChoices().source);
    };
    for (const source of ['obsidian', 'obsidian', 'markdown', 'markdown']) {
        await wizard.openFor(source);
    }
    assert.deepEqual(opened, ['obsidian', 'obsidian', 'markdown', 'markdown']);
});
