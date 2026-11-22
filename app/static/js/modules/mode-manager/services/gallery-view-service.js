import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { scrollWindowToYFastAnimated } from './animated-scroll-service.js';

// A @gallery note shows its pictures as a grid, its children hidden (app/services/note_gallery.py),
// or, switched to an outline, its children like any note's. The switch is remembered per note, in
// the vault's preferences, like any deliberate choice (docs/future-plans/gallery.md).
const OUTLINE_PREFERENCE = 'pref.gallery_outline_notes';
const OUTLINE_CLASS = 'is-gallery-outline';
// A gallery is drawn by a note in the list, or by a note inside an embed, which shows its source
// as the list does (embedded_references.py, note-embed-gallery): the same grid, switch and choice.
const EMBEDDED_GALLERY_CLASS = 'note-embed-gallery';
const GALLERY_ELEMENT_SELECTOR = `.${EMBEDDED_GALLERY_CLASS}[data-embed-note-id], .note[data-note-id]`;
const GALLERY_NOTES = `#notes-container .note[data-note-tags*="@gallery"], #notes-container .${EMBEDDED_GALLERY_CLASS}[data-embed-note-id]`;
const SWITCH_CLASS_SELECTOR = '.meta-gallery-switch';
const LISTED_ARROW_SELECTOR = ':scope > .note-collapse-toggle';
const EMBEDDED_ARROW_SELECTOR = ':scope > .note-embed-body > .note-embed-collapse-toggle';
// A note that is only an embed holds it: the note's own arrow folds the source, and the embed's
// first note shows none (docs/ui/references.md).
const HELD_EMBED_ROOT_SELECTOR = '.note-embed-held .note-embed-root';
const SWITCH_LABELS = { grid: 'Show as outline', outline: 'Show as grid' };
const PLACE_DECIMALS = 2;

const moduleState = ApplicationState.createFields('gallery-view', {
    outlineNoteIds: [],
    observer: null,
    isMarkScheduled: false,
});

function isEmbedded(gallery) {
    return gallery.classList.contains(EMBEDDED_GALLERY_CLASS);
}

function isShown(element) {
    return element !== null && element.getClientRects().length > 0;
}

// The arrow that folds this gallery: the note's, the embedded note's, or, for the first note of
// an embed its note holds, that note's.
function foldArrowOf(gallery) {
    if (!isEmbedded(gallery)) {
        return gallery.querySelector(LISTED_ARROW_SELECTOR);
    }
    const arrow = gallery.querySelector(EMBEDDED_ARROW_SELECTOR);
    if (isShown(arrow) || !gallery.matches(HELD_EMBED_ROOT_SELECTOR)) {
        return arrow;
    }
    return gallery.closest('.note[data-note-id]').querySelector(LISTED_ARROW_SELECTOR);
}

// The gallery's own switch: a note's text can hold an embedded gallery, whose switch is not the
// note's.
function switchOf(gallery) {
    const own = Array.from(gallery.querySelectorAll(SWITCH_CLASS_SELECTOR)).find((toggle) => galleryElementOf(toggle) === gallery);
    return own === undefined ? null : own;
}

// The gallery an element (a tile, the switch) is in: the embedded note or the listed note
// drawing it, whichever is nearer. null outside any.
export function galleryElementOf(element) {
    return element.closest(GALLERY_ELEMENT_SELECTOR);
}

// The id of the note whose gallery this is: an embed's source, not the note holding the embed.
export function galleryNoteIdOf(gallery) {
    const noteId = isEmbedded(gallery) ? gallery.dataset.embedNoteId : gallery.dataset.noteId;
    if (typeof noteId !== 'string' || noteId === '') {
        throw new Error('A gallery must name its note');
    }
    return noteId;
}

// Whether the list shows this note as a note of its own (not only inside an embed).
export function isGalleryNoteListed(noteId) {
    return document.querySelector(`#notes-container .note[data-note-id="${noteId}"]`) !== null;
}

function setPlace(toggle, property, value) {
    if (toggle.style[property] !== value) {
        toggle.style[property] = value;
    }
}

// The switch sits right under the note's fold arrow, on the arrow's own axis, wherever the arrow
// is: beside a heading the arrow is lower (fold-arrow-alignment-service.js), and a switch at a
// fixed height sat on top of it or off to one side (the maintainer, 2026-11-18). With no arrow
// shown it keeps the stylesheet's place.
function placeUnderFoldArrow(note, toggle) {
    const arrow = foldArrowOf(note);
    const parent = toggle.offsetParent;
    if (!isShown(arrow) || parent === null) {
        setPlace(toggle, 'left', '');
        setPlace(toggle, 'top', '');
        return;
    }
    const origin = parent.getBoundingClientRect();
    const arrowBox = arrow.getBoundingClientRect();
    setPlace(toggle, 'left', `${(arrowBox.left - origin.left - parent.clientLeft).toFixed(PLACE_DECIMALS)}px`);
    setPlace(toggle, 'top', `${(arrowBox.bottom - origin.top - parent.clientTop).toFixed(PLACE_DECIMALS)}px`);
}

function setOutlineClass(note, isOutline) {
    if (note.classList.contains(OUTLINE_CLASS) !== isOutline) {
        note.classList.toggle(OUTLINE_CLASS, isOutline);
    }
    const toggle = switchOf(note);
    if (toggle === null) {
        return;
    }
    placeUnderFoldArrow(note, toggle);
    const label = isOutline ? SWITCH_LABELS.outline : SWITCH_LABELS.grid;
    if (toggle.title !== label) {
        toggle.title = label;
        toggle.setAttribute('aria-label', label);
    }
}

function markGalleryNotes() {
    const outline = new Set(moduleState.outlineNoteIds);
    for (const note of document.querySelectorAll(GALLERY_NOTES)) {
        setOutlineClass(note, outline.has(galleryNoteIdOf(note)));
    }
}

function markSoon() {
    if (moduleState.isMarkScheduled) {
        return;
    }
    moduleState.isMarkScheduled = true;
    requestAnimationFrame(() => {
        moduleState.isMarkScheduled = false;
        markGalleryNotes();
    });
}

// The saved list, each time the preferences are applied (command-palette-controller.js).
export function receiveGalleryOutlineNotes(savedText) {
    const noteIds = JSON.parse(savedText);
    if (!Array.isArray(noteIds) || noteIds.some((noteId) => typeof noteId !== 'string')) {
        throw new Error(`${OUTLINE_PREFERENCE} must be a list of note ids`);
    }
    if (JSON.stringify(noteIds) !== JSON.stringify(moduleState.outlineNoteIds)) {
        moduleState.outlineNoteIds = noteIds;
    }
    if (moduleState.observer === null) {
        const container = document.getElementById('notes-container');
        if (container === null) {
            throw new Error('Galleries need #notes-container');
        }
        moduleState.observer = new MutationObserver(markSoon);
        // A fold arrow that moves (its `style`) takes its note's switch with it.
        moduleState.observer.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });
    }
    markGalleryNotes();
}

export function isGalleryOutline(noteId) {
    return moduleState.outlineNoteIds.includes(noteId);
}

async function saveOutline(noteId, isOutline) {
    if (isGalleryOutline(noteId) === isOutline) {
        return;
    }
    const noteIds = isOutline
        ? [...moduleState.outlineNoteIds, noteId]
        : moduleState.outlineNoteIds.filter((outlineId) => outlineId !== noteId);
    const { CommandPalette } = await import('../../command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(OUTLINE_PREFERENCE, JSON.stringify(noteIds));
}

const LISTED_NOTE_SELECTOR = '.note[data-note-id]';
const GALLERY_TAGGED_SELECTOR = '.note[data-note-tags*="@gallery"]';

/**
 * A note under a gallery is about to be edited: each gallery above it becomes an outline, as if
 * its switch had been clicked, and stays one (the maintainer, 2026-11-21). A gallery note being
 * edited shows the notes under it; clicking one of them took the gallery out of edit mode, its
 * grid came back and hid the very note that was clicked. Shown at once, before anything else
 * changes, then saved like any use of the switch.
 */
export async function showGalleriesAboveAsOutline(noteId) {
    if (typeof noteId !== 'string' || noteId === '') {
        throw new Error('showGalleriesAboveAsOutline requires a note id');
    }
    const note = listedNote(noteId);
    if (note === null) {
        return;
    }
    await showAsOutlineFrom(note.parentElement.closest(LISTED_NOTE_SELECTOR));
}

/**
 * A note is about to be made under this one (a new child of the note being edited): the note,
 * if it is a gallery, and each gallery above it become outlines, so the new note shows.
 */
export async function showGalleryAndThoseAboveAsOutline(noteId) {
    if (typeof noteId !== 'string' || noteId === '') {
        throw new Error('showGalleryAndThoseAboveAsOutline requires a note id');
    }
    await showAsOutlineFrom(listedNote(noteId));
}

function listedNote(noteId) {
    return document.querySelector(`#notes-container ${LISTED_NOTE_SELECTOR}[data-note-id="${noteId}"]`);
}

// The gallery notes from this one up (null: none), each made an outline at once, then saved.
async function showAsOutlineFrom(firstNote) {
    const galleryIds = [];
    let note = firstNote;
    while (note !== null) {
        if (note.matches(GALLERY_TAGGED_SELECTOR) && !isGalleryOutline(note.dataset.noteId)) {
            setOutlineClass(note, true);
            galleryIds.push(note.dataset.noteId);
        }
        note = note.parentElement.closest(LISTED_NOTE_SELECTOR);
    }
    for (const galleryId of galleryIds) {
        await saveOutline(galleryId, true);
    }
}

// The switch beside a gallery's fold arrow: the note's first line stays where it is; only what
// is under its text changes.
export async function toggleGalleryOutline(noteId) {
    if (typeof noteId !== 'string' || noteId === '') {
        throw new Error('toggleGalleryOutline requires a note id');
    }
    await saveOutline(noteId, !isGalleryOutline(noteId));
}

function shownNoteContent(noteId) {
    const content = document.querySelector(`#notes-container .note[data-note-id="${noteId}"] > .note-content`);
    if (content === null || content.getClientRects().length === 0) {
        return null;
    }
    return content;
}

// Into view by the least scrolling, below the search controls; nothing moves when it is in view.
function scrollIntoViewMinimally(element) {
    const controls = document.querySelector('.controls');
    if (!(controls instanceof HTMLElement)) {
        throw new Error('The search controls are missing');
    }
    const topLimit = controls.getBoundingClientRect().bottom;
    const rect = element.getBoundingClientRect();
    if (rect.top < topLimit) {
        scrollWindowToYFastAnimated(window.scrollY + rect.top - topLimit);
        return;
    }
    if (rect.bottom > window.innerHeight) {
        const overflow = rect.bottom - window.innerHeight;
        const roomAbove = rect.top - topLimit;
        scrollWindowToYFastAnimated(window.scrollY + Math.min(overflow, roomAbove));
    }
}

// Go to note, from a gallery picture shown full screen: the gallery becomes an outline, the
// folded notes above the picture's note open for this view only (as find opens them;
// docs/ui/find.md), and the note comes into view.
export async function goToGalleryItem(galleryNoteId, itemNoteId) {
    if (typeof galleryNoteId !== 'string' || typeof itemNoteId !== 'string') {
        throw new Error('goToGalleryItem requires the gallery note and the picture note');
    }
    await saveOutline(galleryNoteId, true);
    markGalleryNotes();
    let content = shownNoteContent(itemNoteId);
    if (content === null) {
        if (ModeContext.findRevealNoteId !== itemNoteId) {
            ModeContext.setFindRevealNoteId(itemNoteId);
        }
        const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
        await actionRefreshAndMaybeSelect({ context: 'gallery', animateNoteChanges: false });
        markGalleryNotes();
        content = shownNoteContent(itemNoteId);
    }
    if (content === null) {
        throw new Error(`Go to note: note ${itemNoteId} is not shown`);
    }
    scrollIntoViewMinimally(content);
}
