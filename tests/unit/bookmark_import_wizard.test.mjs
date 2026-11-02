import assert from 'node:assert/strict';
import test from 'node:test';

// Importing a browser's bookmarks export (docs/ready-to-build/bookmark-import.md): recognized
// by its first line, its own File step, and the walkthrough opened with a dropped file.

const SERVICES = {
    getAiSettings: () => ({ provider: 'openai' }), saveAiSettings: async () => {}, afterImport: async () => {},
    setPassword: async () => {}, openPasswordGenerator: async () => {},
};

function withPageGlobals(t) {
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
}

test('an export is recognized by its first line, never by its name', async (t) => {
    withPageGlobals(t);
    const { hasWebPageName, isBookmarksExportFile, isBookmarksExportText } = await import('../../app/static/js/modules/wizard/bookmarks-file.js');
    assert.equal(isBookmarksExportText('<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<DL></DL>'), true);
    assert.equal(isBookmarksExportText('﻿\n  <!doctype netscape-bookmark-file-1>'), true);
    assert.equal(isBookmarksExportText('<!DOCTYPE html><html></html>'), false);
    assert.equal(hasWebPageName(new File(['x'], 'Bookmarks.HTM')), true);
    assert.equal(hasWebPageName(new File(['x'], 'notes.txt')), false);
    // A renamed export is still one; an export named as anything but a web page is never read.
    assert.equal(await isBookmarksExportFile(new File(['<!DOCTYPE NETSCAPE-Bookmark-file-1>'], 'renamed.html')), true);
    assert.equal(await isBookmarksExportFile(new File(['<!DOCTYPE html><p>page</p>'], 'page.html')), false);
    assert.equal(await isBookmarksExportFile(new File(['<!DOCTYPE NETSCAPE-Bookmark-file-1>'], 'bookmarks.txt')), false);
});

test('bookmarks go Source, File, Summary, Import', async (t) => {
    withPageGlobals(t);
    const { ImportWizard } = await import('../../app/static/js/modules/wizard/setup-wizards.js');
    const wizard = new ImportWizard(SERVICES);
    const choices = { ...wizard.initialChoices(), source: 'bookmarks' };
    const keys = wizard._wizardSteps.filter((step) => step.applies(choices)).map((step) => step.key);
    assert.deepEqual(keys, ['source', 'bookmarksFile', 'summary', 'importing']);
});

test('the File step asks for an export, and says why a file isn\'t one', async (t) => {
    withPageGlobals(t);
    const { ImportWizard } = await import('../../app/static/js/modules/wizard/setup-wizards.js');
    const wizard = new ImportWizard(SERVICES);
    const fileStep = wizard._wizardSteps.find((step) => step.key === 'bookmarksFile');
    const choices = { ...wizard.initialChoices(), source: 'bookmarks' };
    assert.equal(fileStep.missing(choices, null), 'Choose the bookmarks file first.');
    const notAnExport = { ...choices, bookmarksFileName: 'page.html', bookmarksProblem: 'That file isn\'t a bookmarks export.' };
    assert.equal(fileStep.missing(notAnExport, null), 'That file isn\'t a bookmarks export.');
    const chosen = { ...choices, bookmarksFileName: 'bookmarks.html', bookmarkCount: 5, prefixText: '' };
    assert.equal(fileStep.missing(chosen, null), '');
});

test('a dropped file opens the walkthrough with it chosen; the menu opens it with nothing chosen', async (t) => {
    withPageGlobals(t);
    const { ImportWizard } = await import('../../app/static/js/modules/wizard/setup-wizards.js');
    const wizard = new ImportWizard(SERVICES);
    wizard.setPresetChoices({ source: 'bookmarks', bookmarksFileName: 'bookmarks.html', bookmarkCount: 5, prefixText: 'Bookmarks' });
    const dropped = wizard.initialChoices();
    assert.equal(dropped.source, 'bookmarks');
    assert.equal(dropped.bookmarksFileName, 'bookmarks.html');
    assert.equal(dropped.prefixText, 'Bookmarks');
    wizard.setPresetChoices(null);
    assert.equal(wizard.initialChoices().source, '');
});
