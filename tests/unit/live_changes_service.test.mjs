// Changes made in another view (multi-view editing step 3): the status revisions decide what this
// view takes again, and a change waits while the user is busy (live-changes-service.js).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { ApplicationState } from '../../app/static/js/modules/application-state.js';

function moduleSource(path) {
    return readFileSync(new URL(`../../app/static/js/modules/${path}`, import.meta.url), 'utf8')
        .replaceAll('\r\n', '\n')
        .replace(/^import[\s\S]*?from '[^']+';\s*/gm, '').replace(/^export /gm, '');
}

let harnessCount = 0;

function harness() {
    harnessCount += 1;
    const applied = [];
    const busy = { dialogs: [] };
    const listeners = {};
    const source = moduleSource('mode-manager/services/live-changes-service.js')
        .replace("ApplicationState.createFields('live-changes-service'", `ApplicationState.createFields('live-changes-service-test-${harnessCount}'`)
        .replaceAll("await import('../events/keyboard-events.js')", 'keyboardEvents')
        .replaceAll("await import('../actions/ui-actions.js')", 'uiActions');
    const dependencies = {
        ApplicationState,
        ErrorHandler: { handleApiError(error) { throw error; } },
        rethrowUnexpectedError(error) { throw error; },
        ModeContext: { get modalStack() { return busy.dialogs; }, isEditing: false },
        CommandGate: { isBusy: () => false },
        isContextMenuOpen: () => false,
        isFindBarOpen: () => false,
        isMovingNoteByDrag: () => false,
        isDebouncedSearchPending: () => false,
        isReferenceViewTransitionPending: () => false,
        askOtherTabsToCheckNow: () => {},
        captureNoteAnchor: () => null,
        captureWindowTopNote: () => null,
        keyboardEvents: { async adoptSharedSearchContexts() { applied.push('contexts'); } },
        uiActions: { async actionRefreshAndMaybeSelect(options) { applied.push(options.context); } },
        document: { hidden: false },
        window: { addEventListener(type, listener) { listeners[type] = listener; }, setTimeout: () => 1, clearTimeout() {} },
        performance: { now: () => 1_000_000 },
    };
    const api = new Function(...Object.keys(dependencies),
        `${source}\nreturn { recordNotesShown, noticeStatusRevisions, noticeOwnContextsChange };`)(...Object.values(dependencies));
    return { ...api, applied, busy, listeners };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

function status(notes, contexts) {
    return { authenticated: true, notes_revision: notes, search_contexts_revision: contexts, edit_locks_revision: 0 };
}

test('two scrolls in one tick of the clock are no error', () => {
    // Found 2026-11-15 (exit-edit-scroll, Firefox, CI): Firefox rounds its clock, two scroll
    // events read the same time, and a state set again is refused: the page showed a fatal error.
    const { noticeStatusRevisions, listeners } = harness();
    noticeStatusRevisions(status(1, 1));
    listeners.scroll();
    listeners.scroll();
});

test('the same revision recorded twice is no change', () => {
    // Found 2026-11-14: most view answers repeat the revision, and a state set again is refused.
    const { recordNotesShown } = harness();
    recordNotesShown(4);
    recordNotesShown(4);
});

test('only a notes revision later than the one shown is refreshed', async () => {
    const { recordNotesShown, noticeStatusRevisions, applied } = harness();
    recordNotesShown(4);
    noticeStatusRevisions(status(4, 1));
    await settle();
    assert.deepEqual(applied, []);
    noticeStatusRevisions(status(5, 1));
    await settle();
    assert.deepEqual(applied, ['changed-elsewhere']);
});

test('the first contexts revision is the one loaded; a later one is taken again', async () => {
    const { recordNotesShown, noticeStatusRevisions, applied } = harness();
    recordNotesShown(4);
    noticeStatusRevisions(status(4, 7));
    await settle();
    assert.deepEqual(applied, []);
    noticeStatusRevisions(status(4, 8));
    await settle();
    assert.deepEqual(applied, ['contexts']);
});

test('a change waits while a dialog is open', async () => {
    const { recordNotesShown, noticeStatusRevisions, applied, busy } = harness();
    recordNotesShown(4);
    busy.dialogs = ['commandPalette'];
    noticeStatusRevisions(status(5, 1));
    await settle();
    assert.deepEqual(applied, []);
    busy.dialogs = [];
    noticeStatusRevisions(status(5, 1));
    await settle();
    assert.deepEqual(applied, ['changed-elsewhere']);
});

test('a change to the contexts this view made itself is not taken again', async () => {
    const { recordNotesShown, noticeStatusRevisions, noticeOwnContextsChange, applied } = harness();
    recordNotesShown(4);
    noticeStatusRevisions(status(4, 7));
    noticeOwnContextsChange({ before: 7, after: 8 });
    noticeStatusRevisions(status(4, 8));
    await settle();
    assert.deepEqual(applied, []);
});

test('a change another view made before this view\'s own is still taken', async () => {
    const { recordNotesShown, noticeStatusRevisions, noticeOwnContextsChange, applied } = harness();
    recordNotesShown(4);
    noticeStatusRevisions(status(4, 7));
    noticeOwnContextsChange({ before: 8, after: 9 });
    noticeStatusRevisions(status(4, 9));
    await settle();
    assert.deepEqual(applied, ['contexts']);
});
