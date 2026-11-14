import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// A reference page keeps every note added there inside a linked note
// (docs/ready-to-build/reference-cards.md, §4). The guard and the actions run with their
// view and transport replaced: the guard reads the page's nested notes from the DOM. The page
// shows the linked note BAZ as a root (its parent bar is not on the page).

const BAR = 'bar-root';
const BAZ = 'baz-linked';
const BAZ_CHILD = 'baz-child';
const BAZ_GRANDCHILD = 'baz-grandchild';

const guardSource = readFileSync(
    new URL('../../app/static/js/modules/mode-manager/services/reference-page-edit-guard.js', import.meta.url),
    'utf8',
);
const guardBody = guardSource
    .slice(guardSource.indexOf('// The agreed wording'))
    .replace(/^export /gm, '');

// BAZ (linked, shown as a root) > BAZ_CHILD > BAZ_GRANDCHILD, nested as the page renders them.
function referencePageDocument() {
    const notes = new Map();
    function addNote(noteId, parent) {
        const childrenContainer = { closest: () => parent };
        notes.set(noteId, { dataset: { noteId }, parentElement: childrenContainer });
    }
    addNote(BAZ, null);
    addNote(BAZ_CHILD, notes.get(BAZ));
    addNote(BAZ_GRANDCHILD, notes.get(BAZ_CHILD));
    return {
        querySelector(selector) {
            const match = /data-note-id="([^"]+)"/.exec(selector);
            assert.ok(match, `unexpected selector ${selector}`);
            return notes.get(match[1]) ?? null;
        },
    };
}

function guardHarness({ onReferencePage }) {
    const banners = [];
    const create = new Function(
        'ModeContext', 'ErrorHandler', 'MS_PER_SECOND', 'Logger', 'getActiveReferenceSourceQuery',
        'isViewingReferenceSource', 'document', 'CSS',
        `${guardBody}\nreturn { refuseOutsideLinkedNote };`,
    );
    const guard = create(
        { searchQuery: 'search text' },
        { showInfoBanner(message) { banners.push(message); } },
        1000,
        { logNoop() {} },
        () => BAZ,
        () => onReferencePage,
        referencePageDocument(),
        { escape: (value) => value },
    );
    return { guard, banners };
}

test('on a reference page notes may be added only inside the linked note', () => {
    const { guard, banners } = guardHarness({ onReferencePage: true });

    assert.equal(guard.refuseOutsideLinkedNote('child', BAZ, ''), false, 'a child of the linked note');
    assert.equal(guard.refuseOutsideLinkedNote('child', BAZ_CHILD, ''), false, 'a child further down');
    assert.equal(guard.refuseOutsideLinkedNote('sibling', BAZ_CHILD, ''), false, 'beside a note inside');
    assert.equal(guard.refuseOutsideLinkedNote('outdent', BAZ_GRANDCHILD, ''), false, 'out one level, still inside');
    assert.deepEqual(banners, []);

    // Beside the linked note, or out past it: outside it.
    assert.equal(guard.refuseOutsideLinkedNote('sibling', BAZ, ''), true);
    assert.equal(guard.refuseOutsideLinkedNote('outdent', BAZ_CHILD, ''), true);
    assert.equal(guard.refuseOutsideLinkedNote('root', '', ''), true);
    assert.equal(banners.length, 3);
    assert.equal(banners[0], 'Only notes inside the linked note can be added here.');
});

test('away from reference pages a child may be added anywhere', () => {
    const { guard, banners } = guardHarness({ onReferencePage: false });

    assert.equal(guard.refuseOutsideLinkedNote('child', BAR, ''), false);
    assert.deepEqual(banners, []);
});

const actionsSource = readFileSync(
    new URL('../../app/static/js/modules/mode-manager/actions/note-actions.js', import.meta.url),
    'utf8',
);

function sliceFunction(startMarker, endMarker) {
    const start = actionsSource.indexOf(startMarker);
    const end = actionsSource.indexOf(endMarker, start);
    assert.ok(start >= 0 && end > start, `${startMarker} not found`);
    return actionsSource.slice(start, end).replace(/^export /gm, '');
}

function actionHarness(actionSource, actionName) {
    const events = [];
    const ModeContext = { currentNoteId: BAR, isEditing: true, isDirty: true, editSessionHasEdits: true };
    const dependencies = {
        ModeContext,
        Logger: { logAction() {}, logDebug() {}, LogCategory: { DEBUG: 'debug' } },
        performance: { now: () => 0 },
        refuseOutsideLinkedNote(kind, noteId, besideNoteId) {
            events.push(`guard:${kind}:${noteId}:${besideNoteId}`);
            return true;
        },
        searchQueryForNewNotes() { return ''; },
        NotesAPI: {
            async createChild() { events.push('create-child'); return { id: 'new-note' }; },
        },
        async actionSaveNote() { events.push('save'); },
        async createNote() { throw new Error('a note is being edited'); },
        async actionSwitchNotes() { events.push('switch'); },
        async actionSelectNote() { events.push('select'); },
        resolveNotePasteResponse() { throw new Error('nothing is pasted'); },
        scrollNoteIntoView() {},
        window: { requestAnimationFrame(callback) { callback(); } },
        ErrorHandler: { showErrorBanner() {} },
        COPIED_NOTE_MISSING_BANNER_SECONDS: 1,
        MS_PER_SECOND: 1000,
    };
    const names = Object.keys(dependencies);
    const run = new Function(...names, `${actionSource}\nreturn ${actionName};`)(
        ...names.map((name) => dependencies[name]),
    );
    return { run, events };
}

test('⌘⇧Return under a note outside the linked note adds nothing', async () => {
    const { run, events } = actionHarness(
        sliceFunction('export async function createChildNote()', 'export async function moveNoteUp('),
        'createChildNote',
    );

    await run();

    assert.deepEqual(events, [`guard:child:${BAR}:`]);
});

test('Paste as child under a note outside the linked note pastes nothing', async () => {
    const { run, events } = actionHarness(
        sliceFunction('async function pasteAsChild(actionName, requestPaste)', 'export async function actionPasteNoteSibling()'),
        'pasteAsChild',
    );

    const pasted = await run('actionPasteNoteChild', async () => {
        events.push('paste-child');
        return { status: 'pasted', id: 'new-note' };
    });

    assert.equal(pasted, false);
    assert.deepEqual(events, [`guard:child:${BAR}:`]);
});
