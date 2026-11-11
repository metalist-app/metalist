import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { buildContextMenuItems } from '../../app/static/js/modules/context-menu/context-menu-registry.js';

const CONTEXT_MENU_SERVICE_URL = new URL(
    '../../app/static/js/modules/context-menu/context-menu-service.js',
    import.meta.url,
);
const CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);


function backgroundMenu() {
    const noop = () => {};
    return buildContextMenuItems(
        {
            kind: 'view', searchAllowsNewNotes: true, isMac: true, isEditing: false, canPasteNoteAtTop: false, canGoToTop: false, canGoToBottom: false,
            isUntaggedView: false, theme: 'system', sortMode: 'normal', dateRangeKind: 'none', dateRangeField: 'updated', fileFilterKind: 'none', fileFilterKinds: ['image', 'pdf', 'markdown'],
        },
        {
            onAddNoteAtTop: noop, onUndo: noop, onRedo: noop, onExpandAll: noop, onCollapseAll: noop, onFullyExpandAll: noop, onFullyCollapseAll: noop,
            onSetUntaggedView: noop, onSetSortMode: noop,
            onSetDateRangeField: noop, onSetDateRangePreset: noop, onOpenCustomDateRange: noop, onSetFileFilter: noop,
            onSetTheme: noop, onNewTab: noop, onOpenNamespace: noop, onOpenReminders: noop,
            onExportViewHtml: noop, onPrintView: noop, onLogOut: noop,
        },
    );
}


// The chat and the virtual folders open with their tabs, always on screen; the menu's Show became
// Themes alone (the maintainer, 2026-11-02).
test('the background menu has no chat or folders switch: Themes lists the themes alone', () => {
    const items = backgroundMenu();
    assert.equal(items.find((item) => item.id === 'show'), undefined);
    const themes = items.find((item) => item.id === 'themes');
    assert.equal(themes.label, 'Themes');
    assert.deepEqual(themes.submenu.map((item) => item.label), ['System', 'Light', 'Dark', 'Fathom', 'Ye Olde Scrypte']);
});


test('context menu renderer provides the shared chat bubble icon without emphasis styling', () => {
    const serviceSource = readFileSync(CONTEXT_MENU_SERVICE_URL, 'utf8');
    const cssSource = readFileSync(CSS_URL, 'utf8');

    assert.match(serviceSource, /chat:\s*\[\s*'M4 5h16v11H9l-5 4z'/);
    assert.doesNotMatch(serviceSource, /item\.emphasized|is-emphasized/);
    assert.doesNotMatch(cssSource, /is-emphasized/);
});
