import assert from 'node:assert/strict';
import test from 'node:test';

import { buildContextMenuItems } from '../../app/static/js/modules/context-menu/context-menu-registry.js';
import { tabContextActionsHtml } from '../../app/static/js/modules/mode-manager/services/tab-context-actions.js';

// Menu rules (docs/ready-to-build/dialog-and-menu-conventions.md, rule 8; agreed case by case
// 2026-10-24): "…" exactly when a dialog asks for more first, destructive items last and red,
// items that cannot apply hidden, the current choice ticked (picking it changes nothing),
// no separator line above a menu's first item, Title Case labels.

const VIEW_HANDLER_NAMES = [
    'onAddNoteAtTop', 'onPasteNoteAtTop', 'onPasteReferenceAtTop', 'onUndo', 'onRedo', 'onGoToTop', 'onGoToBottom', 'onFullyExpandAll',
    'onFullyCollapseAll', 'onSetUntaggedView', 'onSetSortMode', 'onSetDateRangeField', 'onSetDateRangePreset',
    'onOpenCustomDateRange', 'onSetFileFilter', 'onToggleAiChat', 'onToggleTabs',
    'onToggleNoteTags', 'onSetTheme', 'onNewTab', 'onOpenNamespace', 'onOpenReminders',
    'onExportViewHtml', 'onPrintView', 'onLogOut',
];

function viewHandlers(calls) {
    return Object.fromEntries(VIEW_HANDLER_NAMES.map((name) => [name, (...args) => calls.push([name, ...args])]));
}

function viewMenu(overrides, calls) {
    return buildContextMenuItems({
        kind: 'view', isMac: true, isEditing: false, canPasteNoteAtTop: true, canGoToTop: true, canGoToBottom: true,
        isUntaggedView: false, theme: 'system', sortMode: 'normal', dateRangeKind: 'none', dateRangeField: 'updated',
        fileFilterKind: 'none', areTabsVisible: false, isAiChatVisible: false, areNoteTagsVisible: false,
        ...overrides,
    }, viewHandlers(calls));
}

const NOTE_HANDLER_NAMES = [
    'onCopySelection', 'onAddSelectionAsTag', 'onAddStyle', 'onRemoveFormatting', 'onCopyNote', 'onPasteNote',
    'onPasteNoteChild', 'onPasteReference', 'onPasteReferenceChild', 'onPasteReferenceHere', 'onOpenReferenceSource',
    'onMakeImageBigger', 'onMakeImageSmaller', 'onResetImageSize', 'onExportNoteHtml', 'onExportViewHtml',
    'onPrintNote', 'onPrintView', 'onViewNoteFullscreen', 'onFullyExpandNote', 'onFullyCollapseNote', 'onAddNoteAtTop',
    'onAddSiblingNote', 'onAddChildNote', 'onDeleteNote', 'onMoveNoteToTop', 'onMoveNoteToBottom', 'onMoveNoteUp',
    'onMoveNoteDown', 'onIndentNote', 'onOutdentNote',
];

function noteMenu() {
    return buildContextMenuItems({
        kind: 'note', noteId: 'note-1', noteTimestamps: { created: 'Oct 24, 2026', updated: 'Oct 24, 2026' }, isMac: true,
        hasChildren: true, canMoveToTop: true, canMoveToBottom: true, canMoveUp: true, canMoveDown: true,
        canIndent: true, canOutdent: true,
    }, Object.fromEntries(NOTE_HANDLER_NAMES.map((name) => [name, () => {}])));
}

function find(items, id) {
    const item = items.find((candidate) => candidate.id === id);
    assert.notEqual(item, undefined, `menu item ${id} is missing`);
    return item;
}

function labels(items) {
    return items.map((item) => item.label);
}

test('export and print in the note menu say they ask first', () => {
    const items = noteMenu();
    assert.deepEqual(labels(find(items, 'export').submenu), ['Note as HTML…', 'View as HTML…']);
    assert.deepEqual(labels(find(items, 'print').submenu), ['Note…', 'View…']);
});

test('Delete Note is red, last among the note menu actions', () => {
    const items = noteMenu();
    const actions = items.filter((item) => item.kind === undefined);
    const deleteNote = actions[actions.length - 1];
    assert.equal(deleteNote.id, 'delete-note');
    assert.equal(deleteNote.danger, true);
    assert.equal(deleteNote.separated, true);
    for (const item of actions.slice(0, -1)) {
        assert.notEqual(item.danger, true, `${item.label} must not be red`);
    }
});

test('the view menu names what each item does', () => {
    const items = viewMenu({}, []);
    assert.equal(find(items, 'export-view-html').label, 'Export View as HTML…');
    assert.equal(find(items, 'print-view').label, 'Print View…');
    assert.equal(find(items, 'reminders').label, 'Open Reminders');
    assert.equal(find(items, 'open-namespace').label, 'Open/Switch Vault…');
    assert.equal(find(items, 'log-out').danger, undefined, 'logging out loses nothing: not red');
});

test('the tag menu says the tag editor asks first', () => {
    const items = buildContextMenuItems(
        { kind: 'tag', tag: 'project', source: 'tag-bar', explanation: { heading: 'About this tag', lines: ['A tag.'] } },
        { onEditTagRelationships: () => {} },
    );
    assert.equal(items[0].label, 'Edit Tag Relationships…');
});

test('a sorted tab hides adding and pasting at the top', () => {
    for (const sortMode of ['alphabetical', 'created', 'normal-reversed']) {
        const ids = viewMenu({ sortMode }, []).map((item) => item.id);
        for (const hidden of ['add-note-at-top', 'paste-note-at-top', 'paste-reference-at-top']) {
            assert.equal(ids.includes(hidden), false, `${hidden} must be hidden in a ${sortMode} tab`);
        }
    }
    const ids = viewMenu({ sortMode: 'normal' }, []).map((item) => item.id);
    for (const shown of ['add-note-at-top', 'paste-note-at-top', 'paste-reference-at-top']) {
        assert.equal(ids.includes(shown), true, `${shown} must show in a normal tab`);
    }
});

test('no menu opens with a separator line above its first item', () => {
    for (const overrides of [{ isEditing: true }, { isEditing: true, canGoToTop: false, canGoToBottom: false }]) {
        const items = viewMenu(overrides, []);
        assert.notEqual(items[0].separated, true, `${items[0].label} must not carry a separator line`);
    }
});

test('the current choice is ticked, not greyed, and picking it changes nothing', () => {
    const calls = [];
    const items = viewMenu({ theme: 'dark', sortMode: 'alphabetical', dateRangeKind: 'today', fileFilterKind: 'image' }, calls);
    const currentChoices = [
        [find(items, 'view').submenu, 'view-all-notes'],
        [find(items, 'sort-by').submenu, 'sort-by-alphabetical'],
        [find(items, 'date-range').submenu, 'date-range-field-updated'],
        [find(items, 'date-range').submenu, 'date-range-today'],
        [find(items, 'file-filter').submenu, 'file-filter-image'],
        [find(items, 'theme').submenu, 'theme-dark'],
    ];
    for (const [submenu, id] of currentChoices) {
        const item = find(submenu, id);
        assert.equal(item.checked, true, `${id} must be ticked`);
        assert.equal(item.enabled, true, `${id} must not be greyed`);
        item.onSelect();
    }
    assert.deepEqual(calls, [], 'picking the current choice must change nothing');
    for (const submenu of [find(items, 'sort-by').submenu, find(items, 'theme').submenu]) {
        for (const item of submenu) {
            assert.equal(item.enabled, true, `${item.label} must not be greyed`);
        }
    }
});

test('view menu labels are in Title Case', () => {
    const items = viewMenu({}, []);
    assert.equal(find(items, 'sort-by').label, 'Sort by');
    assert.equal(find(items, 'date-range').label, 'Date Range');
    assert.equal(find(items, 'file-filter').label, 'Notes with Files');
    assert.deepEqual(labels(find(items, 'view').submenu), ['All Notes', 'Untagged Notes']);
    assert.deepEqual(labels(find(items, 'sort-by').submenu),
        ['Normal', 'Datetime Created', 'Datetime Last Updated', 'Alphabetical', 'Content Volume', 'Reverse Order']);
    assert.deepEqual(labels(find(items, 'date-range').submenu),
        ['Last Updated', 'Created', 'Any Date', 'Today', 'Last 7 Days', 'Last 30 Days', 'This Year', 'Custom Range…']);
    assert.deepEqual(labels(find(items, 'file-filter').submenu),
        ['All Notes', 'Any File', 'Images', 'PDFs', 'Markdown Files']);
});

test('the tabs overlay says what + and − do, and hides − for a single tab', () => {
    const several = tabContextActionsHtml({ tabId: 'tab-1', isAtTabLimit: false, canDelete: true });
    assert.match(several, /class="tab-context-action duplicate-context "[^>]*title="Duplicate Tab"/);
    assert.match(several, /delete-context "[^>]*title="Delete Tab"[^>]*aria-hidden="false"/);
    const single = tabContextActionsHtml({ tabId: 'tab-1', isAtTabLimit: false, canDelete: false });
    assert.match(single, /delete-context is-hidden"[^>]*aria-hidden="true"/);
    // At the tab limit + stays, greyed: the reason is discoverable.
    const full = tabContextActionsHtml({ tabId: 'tab-1', isAtTabLimit: true, canDelete: true });
    assert.match(full, /duplicate-context is-disabled"[^>]*aria-disabled="true"/);
});
