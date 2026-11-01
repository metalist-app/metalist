import assert from 'node:assert/strict';
import test from 'node:test';

// Picking a longest side did nothing once the estimate came back (2026-11-01): the estimate
// drew the size cards again, and the new cards were never wired to clicks. The cards the
// user clicks stay; only their text takes the estimate.
test('the image estimate fills in the size cards on screen without replacing them', async (t) => {
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
    const { importChoices, importSteps } = await import('../../app/static/js/modules/wizard/import-wizard-steps.js');
    const sides = ['1280', '1920', '2560', '3840'];
    const estimateImportImages = NotesAPI.estimateImportImages;
    t.after(() => { NotesAPI.estimateImportImages = estimateImportImages; });
    NotesAPI.estimateImportImages = async () => ({
        imageCount: 2, imageBytes: 8_000_000, compressedBytes: { 1280: 100_000, 1920: 200_000, 2560: 400_000, 3840: 900_000 },
    });
    const cards = sides.map((side) => {
        const text = { textContent: '…' };
        return { dataset: { choiceValue: side }, querySelector: (selector) => (selector === '.wizard-choice-text' ? text : null), text };
    });
    let sizesRedrawn = false;
    const sizes = { set innerHTML(_html) { sizesRedrawn = true; }, get innerHTML() { return ''; } };
    const line = { innerHTML: '', isConnected: true };
    const screen = {
        querySelector: (selector) => ({ '.wizard-image-estimate': line, '.wizard-image-sizes': sizes })[selector],
        querySelectorAll: (selector) => (selector.includes('imageLongestSide') ? cards : []),
    };
    const choices = {
        ...importChoices(), source: 'obsidian', folderPath: '/vault', folderName: 'vault', imageCount: 2,
        prefixText: 'vault', imagesAs: 'compressed',
    };
    const wizard = { choices, choose(key, value) { this.choices = { ...this.choices, [key]: value }; } };
    const step = importSteps({ withSourceStep: true, withSummaryAndRun: true }).find((candidate) => candidate.key === 'images');
    step.wire(screen, wizard);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    assert.equal(sizesRedrawn, false);
    assert.match(line.innerHTML, /2 images/);
    assert.deepEqual(cards.map((card) => card.text.textContent.startsWith('about ')), [true, true, true, true]);
});
