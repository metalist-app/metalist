import { ApplicationState } from './application-state.js';
import { ModeContextInstance as ModeContext } from './mode-manager/mode-context.js';
import { INITIAL_HOST_ATTRIBUTE } from './skin-olde-words.js';

// A skin paints the first letter of the list's first note, and of the note after each ornament
// (every fourth note has one below it), from a sheet of letter tiles, so CSS has to know which
// letter it is: the note gets data-initial="T". A letter followed by
// punctuation is left unmarked: CSS puts both in ::first-letter, and the tile would hide it.
const PAINTED_INITIAL = /^[A-Za-z](?!\p{P})/u;
const ROOT_NOTES = ':scope > .note';
const MARK_NAMES = ['opening', 'initial', 'ornament', 'arrowColour'];
const ARROW_COLOURS = ['red', 'blue'];
const MARK_ON = 'true';
const NOTES_PER_ORNAMENT = 4;
const ORNAMENT_COUNT = 12;
const LETTER_FIRST = /^[A-Za-z]/;
const BLOCK_DISPLAYS = new Set(['block', 'flow-root', 'list-item']);
const EDITING_CLASS = 'editing';
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

function setMark(note, name, value) {
    if (value === null) {
        delete note.dataset[name];
    } else if (note.dataset[name] !== value) {
        note.dataset[name] = value;
    }
}

// The first letter belongs to the block that holds the first text, however it is wrapped, and
// whatever invisible thing comes before it: Firefox draws ::first-letter only on that block.
function firstTextNode(content) {
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => (node.nodeValue.trim() === '' ? NodeFilter.FILTER_SKIP : NodeFilter.FILTER_ACCEPT),
    });
    return walker.nextNode();
}

function initialHostOf(content) {
    const text = firstTextNode(content);
    if (text === null || !LETTER_FIRST.test(text.nodeValue.trimStart())) {
        return null;
    }
    let host = text.parentElement;
    while (host !== content && !BLOCK_DISPLAYS.has(getComputedStyle(host).display)) {
        host = host.parentElement;
    }
    return host;
}

function clearInitialHosts(content, keptHost) {
    for (const marked of [content, ...content.querySelectorAll(`[${INITIAL_HOST_ATTRIBUTE}]`)]) {
        if (marked !== keptHost && marked.hasAttribute(INITIAL_HOST_ATTRIBUTE)) {
            marked.removeAttribute(INITIAL_HOST_ATTRIBUTE);
        }
    }
}

// Whether the note gets a big letter.
function markInitialHost(note, isOpening) {
    const content = note.querySelector(NOTE_CONTENT);
    if (content === null) {
        return false;
    }
    const text = firstTextNode(content);
    const host = isOpening && text !== null && !note.classList.contains(EDITING_CLASS) ? initialHostOf(content) : null;
    clearInitialHosts(content, host);
    if (host === null) {
        return false;
    }
    if (!host.hasAttribute(INITIAL_HOST_ATTRIBUTE)) {
        host.setAttribute(INITIAL_HOST_ATTRIBUTE, '');
    }
    redrawLetterForNewText(host, text);
    return true;
}

// Firefox keeps a block's first-letter box when the block's text is replaced in place, as
// folding and unfolding a note does, and then draws no letter. Rebuilding the block once for
// each new text brings it back, inside one frame, so nothing flickers.
function redrawLetterForNewText(host, text) {
    if (text.hasLetterBeenDrawn === true) {
        return;
    }
    text.hasLetterBeenDrawn = true;
    const shownDisplay = host.style.display;
    host.style.display = 'none';
    host.getBoundingClientRect();
    host.style.display = shownDisplay;
    if (host.getAttribute('style') === '') {
        host.removeAttribute('style');
    }
}

function clearMarks(container) {
    for (const note of container.querySelectorAll(ROOT_NOTES)) {
        markInitialHost(note, false);
        for (const name of MARK_NAMES) {
            setMark(note, name, null);
        }
    }
}

// Arrows take turns among the notes that have one. A note keeps its colour as the page's window
// moves: the first note already coloured sets the turn for the rest.
function markArrowColours(notes) {
    const withArrows = notes.filter((note) => note.dataset.canCollapse === 'true');
    for (const note of notes) {
        if (!withArrows.includes(note)) {
            setMark(note, 'arrowColour', null);
        }
    }
    const anchorIndex = Math.max(withArrows.findIndex((note) => note.dataset.arrowColour !== undefined), 0);
    const anchor = withArrows[anchorIndex];
    if (anchor === undefined) {
        return;
    }
    const anchorTurn = anchor.dataset.arrowColour === undefined ? 0 : ARROW_COLOURS.indexOf(anchor.dataset.arrowColour);
    withArrows.forEach((note, index) => {
        const turn = (((anchorTurn + index - anchorIndex) % ARROW_COLOURS.length) + ARROW_COLOURS.length) % ARROW_COLOURS.length;
        setMark(note, 'arrowColour', ARROW_COLOURS[turn]);
    });
}

// Counted from the top of the list, not of the page: on a long list the page holds only a window
// of it, and that window moves as you scroll or fold, which must not move the letters and ornaments.
function markRootNotes() {
    const container = notesContainer();
    const windowStart = ModeContext.getRootWindowStart();
    Array.from(container.querySelectorAll(ROOT_NOTES)).forEach((note, index) => {
        const position = windowStart + index;
        const isOpening = position % NOTES_PER_ORNAMENT === 0;
        const hasOrnament = (position + 1) % NOTES_PER_ORNAMENT === 0;
        setMark(note, 'opening', isOpening ? MARK_ON : null);
        setMark(note, 'initial', markInitialHost(note, isOpening) ? paintedInitialOf(note) : null);
        setMark(note, 'ornament', hasOrnament ? String((((position + 1) / NOTES_PER_ORNAMENT) - 1) % ORNAMENT_COUNT) : null);
    });
    markArrowColours(Array.from(container.querySelectorAll(ROOT_NOTES)));
}

// A note entering or leaving edit mode, gaining or losing its arrow, or any change to what the list holds.
function changesTheMarks(mutation) {
    if (mutation.type !== 'attributes' || mutation.attributeName !== 'class') {
        return true;
    }
    const wasEditing = (mutation.oldValue === null ? '' : mutation.oldValue).split(' ').includes(EDITING_CLASS);
    return wasEditing !== mutation.target.classList.contains(EDITING_CLASS);
}

function scheduleMarking() {
    if (moduleState.isMarkingScheduled) {
        return;
    }
    moduleState.isMarkingScheduled = true;
    requestAnimationFrame(() => {
        moduleState.isMarkingScheduled = false;
        if (moduleState.observer !== null) {
            markRootNotes();
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
        clearMarks(notesContainer());
        return;
    }
    moduleState.observer = new MutationObserver((mutations) => {
        if (mutations.some(changesTheMarks)) {
            scheduleMarking();
        }
    });
    moduleState.observer.observe(notesContainer(), {
        childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class', 'data-can-collapse'], attributeOldValue: true,
    });
    markRootNotes();
}
