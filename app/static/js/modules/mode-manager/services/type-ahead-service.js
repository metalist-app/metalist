import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';

// Keys typed while a clicked note is still opening. MetaList ignores keys while a command
// runs (keyboard-events.js), so on a slow machine or connection the first letters typed
// after a click were lost. The plain characters typed then are kept and typed into the
// clicked note once it is editable, at its caret, as ordinary typing (agreed 2026-10-28).
// Shortcuts and other keys pressed then are still ignored.

// No note is opening; also what a command that never ran (MetaList was busy) finishes.
const NONE = 0;

// Each opening has its own number. The application state keeps copies of objects, so an
// opening is told apart by its number, never by an object's identity.
const moduleState = ApplicationState.createFields('type-ahead-service', {
    opening: NONE,
    lastOpening: NONE,
    openingNoteId: '',
    typed: '',
});

// The application state refuses a change to the value it holds already.
function clearTyped() {
    if (moduleState.typed !== '') {
        moduleState.typed = '';
    }
}

// A key that types one character: a letter, a digit, a symbol or a space, with no
// Command, Control or Option.
function typesCharacter(event) {
    return [...event.key].length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey;
}

export const TypeAhead = {
    NONE,

    // The clicked note starts opening, inside the command that opens it: keep what is typed
    // until it has. Returns this opening's number, for finish.
    begin(noteId) {
        if (typeof noteId !== 'string' || noteId === '') {
            throw new Error('TypeAhead.begin requires a note id');
        }
        const opening = moduleState.lastOpening + 1;
        moduleState.lastOpening = opening;
        moduleState.opening = opening;
        if (moduleState.openingNoteId !== noteId) {
            moduleState.openingNoteId = noteId;
        }
        clearTyped();
        return opening;
    },

    // Keeps a key pressed while busy when a clicked note is opening and the key types a
    // character; returns whether it was kept.
    keep(event) {
        if (moduleState.opening === NONE || !typesCharacter(event)) {
            return false;
        }
        moduleState.typed += event.key;
        return true;
    },

    // The opening's command has finished: what was typed meanwhile goes into the note, if
    // it is the one being edited now. NONE (the command never ran) changes nothing.
    finish(opening) {
        if (opening === NONE || moduleState.opening !== opening) {
            return;
        }
        const typed = moduleState.typed;
        const noteId = moduleState.openingNoteId;
        moduleState.opening = NONE;
        clearTyped();
        if (typed === '' || !ModeContext.isEditingNote(noteId)) {
            return;
        }
        Logger.logAction('type_ahead.insert', { noteId, length: typed.length });
        document.execCommand('insertText', false, typed);
    },
};
