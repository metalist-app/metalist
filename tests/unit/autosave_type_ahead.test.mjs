import { ApplicationState } from '../../app/static/js/modules/application-state.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// A note being edited autosaves 10 s after typing stops, and letters typed while the save
// runs are typed in after it (agreed 2026-10-31; docs/ready-to-build/commit-and-shutdown-protocol.md).

function moduleSource(path, exported) {
    const source = readFileSync(new URL(`../../app/static/js/modules/mode-manager/${path}`, import.meta.url), 'utf8')
        .replace(/^import[\s\S]*?from '[^']+';\s*/gm, '').replace(/^export /gm, '');
    return `${source}\nreturn { ${exported} };`;
}

function harness({ secondsSinceTyping }) {
    const inserted = [];
    const saves = [];
    const ModeContext = {
        isEditing: true,
        isDirty: true,
        currentNoteId: 'note-1',
        lastContentChangeTime: Date.now() - secondsSinceTyping * 1000,
        isEditingNote: (noteId) => noteId === 'note-1',
    };
    const Logger = { logAction() {}, logDebug() {}, logInit() {} };
    const gate = { busy: false };
    // Typed in while MetaList is busy, the letters would not count as a change.
    const document = { execCommand: (command, showUi, text) => inserted.push([command, text, gate.busy]) };
    const { TypeAhead } = new Function('ApplicationState', 'ModeContext', 'Logger', 'document',
        moduleSource('services/type-ahead-service.js', 'TypeAhead'))(ApplicationState, ModeContext, Logger, document);
    const keptDuringSave = [];
    const pressed = { keys: [] };
    const actionSaveNoteOnIdle = async (noteId) => {
        saves.push(noteId);
        for (const key of pressed.keys) {
            keptDuringSave.push([key.key, TypeAhead.keep({ metaKey: false, ctrlKey: false, altKey: false, ...key })]);
        }
    };
    const running = [];
    const CommandGate = {
        run: (name, command) => {
            gate.busy = true;
            const done = command().then(() => { gate.busy = false; });
            running.push(done);
            return done;
        },
    };
    const { checkAndSaveContent } = new Function(
        'ApplicationState', 'ModeContext', 'Logger', 'actionSaveNoteOnIdle', 'CommandGate', 'TypeAhead',
        'prefetchEditingLinkTitles', moduleSource('events/inactivity-events.js', 'checkAndSaveContent'),
    )(ApplicationState, ModeContext, Logger, actionSaveNoteOnIdle, CommandGate, TypeAhead, async () => {});
    return { checkAndSaveContent, inserted, saves, keptDuringSave, pressed, running };
}

test('a note saves 10 s after typing stops, not before', async () => {
    const early = harness({ secondsSinceTyping: 9 });
    early.checkAndSaveContent();
    assert.deepEqual(early.saves, []);
    const due = harness({ secondsSinceTyping: 10 });
    due.checkAndSaveContent();
    await Promise.all(due.running);
    assert.deepEqual(due.saves, ['note-1']);
});

test('letters typed during a save are typed in after it; other keys stay ignored', async () => {
    const h = harness({ secondsSinceTyping: 11 });
    h.pressed.keys = [{ key: 'H' }, { key: 'Backspace' }, { key: 'i' }, { key: ' ' }, { key: 'b', metaKey: true }, { key: 'Enter' }];
    h.checkAndSaveContent();
    await Promise.all(h.running);
    await Promise.resolve();
    assert.deepEqual(h.keptDuringSave, [['H', true], ['Backspace', false], ['i', true], [' ', true], ['b', false], ['Enter', false]]);
    assert.deepEqual(h.inserted, [['insertText', 'Hi ', false]]);
});

test('a save with nothing typed during it types nothing', async () => {
    const h = harness({ secondsSinceTyping: 11 });
    h.checkAndSaveContent();
    await Promise.all(h.running);
    assert.deepEqual(h.inserted, []);
});
