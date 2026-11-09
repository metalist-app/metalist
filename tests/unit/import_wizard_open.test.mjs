import assert from 'node:assert/strict';
import test from 'node:test';

// The import wizard starts with no source chosen (the maintainer, 2026-11-01: none picked for
// you; Next stays greyed until one is), every time it opens.
test('the import wizard starts with no source chosen, and asks for one', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    // Its imports (the login) set globals on the page.
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
    const services = {
        getAiSettings: () => ({ provider: 'openai' }), saveAiSettings: async () => {}, announceImport: () => {}, afterImport: async () => {}, showDroppedImport: async () => {},
        setPassword: async () => {}, openPasswordGenerator: async () => {},
    };
    const wizard = new ImportWizard(services);
    const choices = wizard.initialChoices();
    assert.equal(choices.source, '');
    const sourceStep = wizard._wizardSteps.find((step) => step.key === 'source');
    assert.equal(sourceStep.missing(choices, null), 'Choose what you are importing.');
    assert.equal(sourceStep.missing({ ...choices, source: 'markdown' }, null), '');
});
