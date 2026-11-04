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
    const wizard = {
        choices, openGeneration: 1, isCurrentOpen: (generation) => generation === 1,
        choose(key, value) { this.choices = { ...this.choices, [key]: value }; },
    };
    const step = importSteps({ withSourceStep: true, withSummaryAndRun: true }).find((candidate) => candidate.key === 'images');
    step.wire(screen, wizard);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    assert.equal(sizesRedrawn, false);
    assert.match(line.innerHTML, /2 images/);
    assert.deepEqual(cards.map((card) => card.text.textContent.startsWith('about ')), [true, true, true, true]);
});


// A slow estimate (a folder of big photos) answered after the import was done and the
// walkthrough closed, and writing it into the closed walkthrough was fatal (2026-11-02).
test('an estimate answered after the walkthrough closed is dropped', async (t) => {
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
    const estimateImportImages = NotesAPI.estimateImportImages;
    t.after(() => { NotesAPI.estimateImportImages = estimateImportImages; });
    let isOpen = true;
    NotesAPI.estimateImportImages = async () => {
        isOpen = false;
        return { imageCount: 2, imageBytes: 8_000_000, compressedBytes: { 1280: 1, 1920: 2, 2560: 3, 3840: 4 } };
    };
    const line = { innerHTML: '', isConnected: false };
    const screen = { querySelector: () => line, querySelectorAll: () => [] };
    const wizard = {
        choices: { ...importChoices(), source: 'obsidian', folderPath: '/vault', folderName: 'vault', imageCount: 2, prefixText: 'vault', imagesAs: 'compressed' },
        openGeneration: 1, isCurrentOpen: (generation) => isOpen && generation === 1,
        choose() { throw new Error('Modal state not initialized: importWizard'); },
    };
    const step = importSteps({ withSourceStep: true, withSummaryAndRun: true }).find((candidate) => candidate.key === 'images');
    step.wire(screen, wizard);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    assert.equal(line.innerHTML, '');
});

// Picking Compress while the first estimate ran asked again for the same choices, and the second
// answer wrote what the first had: a redundant state change, fatal (2026-11-02).
test('two estimates for the same choices write it once', async (t) => {
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
    const estimateImportImages = NotesAPI.estimateImportImages;
    t.after(() => { NotesAPI.estimateImportImages = estimateImportImages; });
    NotesAPI.estimateImportImages = async () => ({ imageCount: 2, imageBytes: 8, compressedBytes: { 1280: 1, 1920: 2, 2560: 3, 3840: 4 } });
    const line = { innerHTML: '', isConnected: true };
    const screen = { querySelector: () => line, querySelectorAll: () => [] };
    const wizard = {
        choices: { ...importChoices(), source: 'obsidian', folderPath: '/vault', folderName: 'vault', imageCount: 2, prefixText: 'vault', imagesAs: 'compressed' },
        openGeneration: 1, isCurrentOpen: (generation) => generation === 1,
        choose(key, value) {
            if (JSON.stringify(this.choices[key]) === JSON.stringify(value)) throw new Error(`Redundant state change: ${key}`);
            this.choices = { ...this.choices, [key]: value };
        },
    };
    const step = importSteps({ withSourceStep: true, withSummaryAndRun: true }).find((candidate) => candidate.key === 'images');
    step.wire(screen, wizard);
    step.wire(screen, wizard);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    assert.match(line.innerHTML, /2 images/);
});
