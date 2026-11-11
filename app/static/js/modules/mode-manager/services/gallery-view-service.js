import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { scrollWindowToYFastAnimated } from './animated-scroll-service.js';

// A @gallery note shows its pictures as a grid, its children hidden (app/services/note_gallery.py),
// or, switched to an outline, its children like any note's. The switch is remembered per note, in
// the vault's preferences, like any deliberate choice (docs/future-plans/gallery.md).
const OUTLINE_PREFERENCE = 'pref.gallery_outline_notes';
const OUTLINE_CLASS = 'is-gallery-outline';
const GALLERY_NOTES = '#notes-container .note[data-note-tags*="@gallery"]';
const SWITCH_SELECTOR = ':scope > .note-content .meta-gallery-switch';
const SWITCH_LABELS = { grid: 'Show as outline', outline: 'Show as grid' };

const moduleState = ApplicationState.createFields('gallery-view', {
    outlineNoteIds: [],
    observer: null,
    isMarkScheduled: false,
});

function setOutlineClass(note, isOutline) {
    if (note.classList.contains(OUTLINE_CLASS) !== isOutline) {
        note.classList.toggle(OUTLINE_CLASS, isOutline);
    }
    const toggle = note.querySelector(SWITCH_SELECTOR);
    if (toggle === null) {
        return;
    }
    const label = isOutline ? SWITCH_LABELS.outline : SWITCH_LABELS.grid;
    if (toggle.title !== label) {
        toggle.title = label;
        toggle.setAttribute('aria-label', label);
    }
}

function markGalleryNotes() {
    const outline = new Set(moduleState.outlineNoteIds);
    for (const note of document.querySelectorAll(GALLERY_NOTES)) {
        setOutlineClass(note, outline.has(note.dataset.noteId));
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
        moduleState.observer.observe(container, { childList: true, subtree: true });
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
