import assert from 'node:assert/strict';
import test from 'node:test';

// A kind on the import's Files screen opens to list its files (the maintainer, 2026-11-12:
// "I tried clicking on the expand so I could see the individual files, and it is completely
// unresponsive"). Building the list threw: it still read the 100 MB limit's flag, removed
// with the limit.
test('an opened kind on the Files screen lists its files, each ticked as its kind is', async (t) => {
    // Its imports (the login) read the page's storage and set globals on it.
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
    const { importSteps, importChoices } = await import('../../app/static/js/modules/wizard/import-wizard-steps.js');
    const kindsStep = importSteps({ withSourceStep: true, withSummaryAndRun: true }).find((step) => step.key === 'kinds');
    const choices = {
        ...importChoices(),
        source: 'files',
        scan: {
            freeBytes: 1000000,
            groups: [{ key: 'pdf', label: 'PDF', fileCount: 2, bytes: 300, files: [['Taxes/2025.pdf', 200], ['manual.pdf', 100]] }],
        },
        openKinds: ['pdf'],
    };
    const html = kindsStep.render(choices);
    assert.match(html, /aria-expanded="true"/);
    assert.match(html, /<input type="checkbox" data-wizard-file="Taxes\/2025\.pdf" data-wizard-file-kind="pdf" checked>/);
    assert.match(html, /<input type="checkbox" data-wizard-file="manual\.pdf" data-wizard-file-kind="pdf" checked>/);
});
