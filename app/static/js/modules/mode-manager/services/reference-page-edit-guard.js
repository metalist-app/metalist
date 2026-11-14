// What may be added or moved on a reference page (docs/ready-to-build/reference-cards.md, §4):
// anything inside a linked note, nothing outside it, so every note added there shows the next time
// the reference is followed. A linked note is one the page's hidden search names; the page shows
// it as a root, so a note is inside when one of the notes it is nested in is linked.
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { ErrorHandler } from '../../error-handler.js';
import { MS_PER_SECOND } from '../../time-units.js';
import * as Logger from '../mode-logger.js';
import {
    getActiveReferenceSourceQuery,
    isViewingReferenceSource,
} from './reference-source-navigation-service.js';

// The agreed wording (decided 2026-11-13) says next "Click the grey to open the whole note.",
// added once the grey parents open the whole note.
const REFUSAL_MESSAGE = 'Only notes inside the linked note can be added here.';
const REFUSAL_BANNER_SECONDS = 6;
const NOTE_ID_SEPARATOR = /\s+OR\s+/;
// What would be added or moved, and where it would land.
const KINDS = new Set(['root', 'child', 'sibling', 'afterParent', 'outdent', 'indent', 'move', 'drop']);

function linkedNoteIds() {
    return new Set(getActiveReferenceSourceQuery().trim().split(NOTE_ID_SEPARATOR));
}

function requireNoteElement(noteId) {
    if (typeof noteId !== 'string' || noteId === '') {
        throw new Error('The reference page guard requires a note id');
    }
    const element = document.querySelector(`#notes-container .note[data-note-id="${CSS.escape(noteId)}"]`);
    if (element === null) {
        throw new Error(`Note ${noteId} is not on the reference page`);
    }
    return element;
}

function parentNoteElement(noteElement) {
    if (noteElement.parentElement === null) {
        return null;
    }
    return noteElement.parentElement.closest('.note');
}

// Below a linked note (the linked note itself is not below one).
function isBelowLinkedNote(noteElement, linked) {
    for (let parent = parentNoteElement(noteElement); parent !== null; parent = parentNoteElement(parent)) {
        if (linked.has(parent.dataset.noteId)) {
            return true;
        }
    }
    return false;
}

// Whether the note's parent is below a linked note: a sibling of the parent stays inside.
function isParentBelowLinkedNote(noteElement, linked) {
    const parent = parentNoteElement(noteElement);
    return parent !== null && isBelowLinkedNote(parent, linked);
}

function landsInside(kind, noteId, besideNoteId, linked) {
    if (kind === 'root') {
        return false;
    }
    const note = requireNoteElement(noteId);
    if (kind === 'child') {
        // Under the note: inside when the note is a linked note or below one.
        if (linked.has(noteId)) {
            return true;
        }
        return isBelowLinkedNote(note, linked);
    }
    if (kind === 'sibling' || kind === 'indent' || kind === 'move') {
        // Beside the note, or under the note just above it: inside when the note is below a
        // linked note. Beside the linked note itself is outside it.
        return isBelowLinkedNote(note, linked);
    }
    if (kind === 'afterParent' || kind === 'outdent') {
        // One level out, beside the note's parent: inside when that parent is below a linked note.
        return isParentBelowLinkedNote(note, linked);
    }
    // A note dropped beside besideNoteId: inside when both are below a linked note.
    return isBelowLinkedNote(note, linked) && isBelowLinkedNote(requireNoteElement(besideNoteId), linked);
}

/**
 * On a reference page, refuses what would leave a note outside the linked notes, with the agreed
 * message; returns true when refused. kind: 'root', 'child' (under noteId), 'sibling' (after noteId), 'afterParent' (after
 * noteId's parent), 'outdent', 'indent', 'move' (up or down among its siblings) or 'drop' (beside
 * besideNoteId; '' for every other kind). Anywhere else nothing is refused.
 */
export function refuseOutsideLinkedNote(kind, noteId, besideNoteId) {
    if (!KINDS.has(kind)) {
        throw new Error(`Unknown reference page edit: ${kind}`);
    }
    if (typeof besideNoteId !== 'string' || (kind === 'drop') !== (besideNoteId !== '')) {
        throw new Error('refuseOutsideLinkedNote takes the note dropped beside, and only for a drop');
    }
    if (!isViewingReferenceSource()) {
        return false;
    }
    if (landsInside(kind, noteId, besideNoteId, linkedNoteIds())) {
        return false;
    }
    Logger.logNoop('Reference page edit refused: it would land outside the linked note', { kind, noteId });
    ErrorHandler.showInfoBanner(REFUSAL_MESSAGE, REFUSAL_BANNER_SECONDS * MS_PER_SECOND);
    return true;
}

/**
 * The search a new or moved note takes its tags from: none on a reference page, whose hidden search
 * names notes by id (a page never gives a note a tag); the search shown anywhere else.
 */
export function searchQueryForNewNotes() {
    if (isViewingReferenceSource()) {
        return '';
    }
    return ModeContext.searchQuery;
}
