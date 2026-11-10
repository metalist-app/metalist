import { ApplicationState } from './application-state.js';

// A skin paints the first letter of the list's first note, and of the note after each ornament
// (every fourth note has one below it), from a sheet of letter tiles, so CSS has to know which
// letter it is: the note gets data-initial="T". A letter followed by
// punctuation is left unmarked: CSS puts both in ::first-letter, and the tile would hide it.
const PAINTED_INITIAL = /^[A-Za-z](?!\p{P})/u;
const OPENING_NOTES = ':scope > .note:nth-child(4n + 1)';
const MARKED_NOTES = ':scope > .note[data-initial]';
const NOTE_CONTENT = ':scope > .note-content';

const moduleState = ApplicationState.createFields('skin-initials', {
    observer: null,
    isMarkingScheduled: false,
});

function notesContainer() {
    const container = document.getElementById('notes-container');
    if (container === null) {
        throw new Error('The painted initial needs #notes-container');
    }
    return container;
}

function paintedInitialOf(note) {
    const content = note.querySelector(NOTE_CONTENT);
    if (content === null) {
        return null;
    }
    const text = content.textContent.trimStart();
    return PAINTED_INITIAL.test(text) ? text[0].toUpperCase() : null;
}

function clearMarks(container, keptNotes) {
    for (const note of container.querySelectorAll(MARKED_NOTES)) {
        if (!keptNotes.includes(note)) {
            delete note.dataset.initial;
        }
    }
}

function markOpeningNotes() {
    const container = notesContainer();
    const openingNotes = Array.from(container.querySelectorAll(OPENING_NOTES));
    clearMarks(container, openingNotes);
    for (const note of openingNotes) {
        const initial = paintedInitialOf(note);
        if (initial === null) {
            delete note.dataset.initial;
        } else if (note.dataset.initial !== initial) {
            note.dataset.initial = initial;
        }
    }
}

function scheduleMarking() {
    if (moduleState.isMarkingScheduled) {
        return;
    }
    moduleState.isMarkingScheduled = true;
    requestAnimationFrame(() => {
        moduleState.isMarkingScheduled = false;
        if (moduleState.observer !== null) {
            markOpeningNotes();
        }
    });
}

export function setSkinInitialsActive(isActive) {
    if (typeof isActive !== 'boolean') {
        throw new Error('setSkinInitialsActive requires a boolean');
    }
    if (isActive === (moduleState.observer !== null)) {
        return;
    }
    if (!isActive) {
        moduleState.observer.disconnect();
        moduleState.observer = null;
        clearMarks(notesContainer(), []);
        return;
    }
    moduleState.observer = new MutationObserver(scheduleMarking);
    moduleState.observer.observe(notesContainer(), { childList: true, subtree: true, characterData: true });
    markOpeningNotes();
}
