import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { DOMUtils } from '../../dom-utils.js';
import { NotesAPI } from '../../api-client.js';
import { attachEditorSurface } from '../../editor-toolbar.js';
import { ApplicationState } from '../../application-state.js';
import { editedWindowHost, findNoteElement, isEditingInWindow, leaveEditingWindow, startEditingInWindow } from '../../editing-surface.js';
import { CommandGate } from './command-gate-service.js';
import { actionDeselectNote, actionSelectNote } from '../actions/selection-actions.js';
import { actionSaveNote } from '../actions/content-actions.js';
import { actionRefreshAndMaybeSelect } from '../actions/ui-actions.js';
import { buildWindowNoteTree } from './differential-view-service.js';
import { initializeEditSessionCollapseStateFromNoteElement } from './edit-session-collapse-service.js';
import { syncTagBar } from './tag-bar-service.js';
import { captureEditingFocus, placeCaretAtClickAnchor, restoreEditingFocus } from './viewport-hold-service.js';
import { hydrateImageFilePreviews } from './file-image-preview-service.js';
import { hydrateExcalidrawPreviews } from '../../excalidraw/excalidraw-preview-service.js';
import { hydrateRemoteImageProxies } from './remote-image-proxy-service.js';
import { queueMermaidDiagramRendering } from './mermaid-render-service.js';
import { updateCollapseAffordancesForNotes, watchFoldability } from './collapse-affordance-service.js';
import { markGalleryNotesIn } from './gallery-view-service.js';

// Editing a note in a floating window (agreed 2026-11-21, cases 1 to 8; docs/ui/state-handling.md,
// "Floating note windows"). A click on a note in a window edits it there, with the same editor
// as the list: the window's notes are drawn as the list draws its own (buildWindowNoteTree) in
// the page, slotted into the window, and the editor finds them there (editing-surface.js). The
// window's read-only drawing is hidden meanwhile and its refresh paused. The list draws its copy
// of the note with the pencil of a note edited elsewhere. A click outside the window, or Escape,
// saves and leaves edit mode as in the list; the window stays.

const EDITING_TREE_CLASS = 'floating-note-editing-tree';

const moduleState = ApplicationState.createFields('floating-note-editing', {
    // Whether this module listens for edit mode ending (from the first note edited in a window).
    isWatchingEditMode: false,
});

// Edit mode can end in several ways (Escape, a click outside, deleting the edited note, an
// undo, a lost connection, the note leaving the search): whichever it is, the window a note was
// edited in goes back to showing its notes. Deleting the edited note once left the window
// showing it as edited, and deleting it again failed with a 404 (the maintainer, 2026-11-22).
function watchEditModeEnding() {
    if (moduleState.isWatchingEditMode) return;
    moduleState.isWatchingEditMode = true;
    ModeContext.addListener((property, value) => {
        if (property === 'editing' && value === false) leaveEditingWindow();
    });
}

/**
 * A window as this module needs it: `id`, its note (`noteId`), its element (`element`), its
 * read-only drawing (`tree`) and `showNotes()`, which draws that again once editing leaves.
 */
function requireWindow(floatingWindow) {
    if (floatingWindow === null || typeof floatingWindow !== 'object'
        || typeof floatingWindow.noteId !== 'string' || !(floatingWindow.element instanceof HTMLElement)
        || !(floatingWindow.tree instanceof HTMLElement) || typeof floatingWindow.showNotes !== 'function') {
        throw new Error('A floating window to edit in needs its note, element, drawing and showNotes');
    }
}

// The window's notes, the edited one drawn for editing, in place of its read-only drawing.
// Null when that note is no longer in the window (moved out meanwhile).
async function drawEditableNotes(floatingWindow, noteId) {
    const answer = await NotesAPI.getFloatingNoteEditing(floatingWindow.noteId, noteId);
    if (answer.status === 'outside') return null;
    if (answer.status !== 'ready') throw new Error(`Unexpected floating window editing status: ${answer.status}`);
    // One per window, kept while switching between its notes (editing-surface.js holds it).
    let surface = floatingWindow.element.querySelector(`:scope > .${EDITING_TREE_CLASS}`);
    if (surface === null) {
        surface = document.createElement('div');
        surface.className = EDITING_TREE_CLASS;
        // In the page, so the editor (and the selection) work on it; slotted into the window's scroll area.
        floatingWindow.element.appendChild(surface);
        watchFoldability(surface);
    } else {
        surface.replaceChildren();
    }
    const noteElement = drawWindowNotes(surface, answer.structure, answer.notes, noteId);
    if (!floatingWindow.tree.hidden) floatingWindow.tree.hidden = true;
    return { surface, noteElement };
}

/**
 * A window's notes drawn into the empty `container` as the list draws its own (agreed
 * 2026-11-22): folded as saved with their fold arrows, galleries as their grid or outline,
 * pictures, diagrams and formulas filled in. Returns the edited note's element, or null.
 */
export function drawWindowNotes(container, structure, notes, editingNoteId) {
    const noteElement = buildWindowNoteTree(container, structure, notes, editingNoteId);
    finishDrawing(container);
    return noteElement;
}

function finishDrawing(container) {
    updateCollapseAffordancesForNotes(container.querySelectorAll('.note[data-note-id]'));
    markGalleryNotesIn(container);
    hydrateImageFilePreviews(container);
    void hydrateExcalidrawPreviews(container);
    hydrateRemoteImageProxies(container);
    void queueMermaidDiagramRendering(container);
}

// The window's notes by id, parent and fold, in the order drawn (the server's order too).
function drawnShape(surface) {
    return [...surface.querySelectorAll('.note[data-note-id]')]
        .map(note => `${note.dataset.noteId}<${note.dataset.parentId}:${note.dataset.isCollapsed}`).join(' ');
}

function answeredShape(structure, notes) {
    return structure.map(entry => {
        let parentId = '';
        if (entry.parentId !== null) parentId = entry.parentId;
        return `${entry.id}<${parentId}:${Boolean(notes[entry.id].flags.isCollapsed)}`;
    }).join(' ');
}

// After the list was drawn again (a note added, moved or deleted, here or in another view): the
// window draws its notes again when they changed shape, around the edited note, which keeps its
// caret and typing; one moved out from under the window's note is edited in the list (case 7).
// Notes only changed in text stay as they are until editing leaves the window (case 6).
async function followEditedNote(floatingWindow) {
    if (editedWindowHost() !== floatingWindow.element || !ModeContext.isEditing) return;
    const noteId = ModeContext.currentNoteId;
    const answer = await NotesAPI.getFloatingNoteEditing(floatingWindow.noteId, noteId);
    if (editedWindowHost() !== floatingWindow.element || ModeContext.currentNoteId !== noteId) return;
    if (answer.status === 'outside') {
        await actionDeselectNote();
        await actionSelectNote(noteId, { initialCaretVisibility: 'visible' });
        return;
    }
    const surface = floatingWindow.element.querySelector(`:scope > .${EDITING_TREE_CLASS}`);
    if (drawnShape(surface) === answeredShape(answer.structure, answer.notes)) return;
    const edited = findNoteElement(noteId);
    const focus = captureEditingFocus(edited);
    const fresh = document.createElement('div');
    const freshEdited = buildWindowNoteTree(fresh, answer.structure, answer.notes, noteId);
    // The edited note's own element goes where the fresh drawing has it, with the fresh notes under it.
    const editedChildren = edited.querySelector(':scope > .note-children');
    if (editedChildren !== null) editedChildren.remove();
    const freshChildren = freshEdited.querySelector(':scope > .note-children');
    if (freshChildren !== null) edited.appendChild(freshChildren);
    if (edited.dataset.parentId !== freshEdited.dataset.parentId) edited.dataset.parentId = freshEdited.dataset.parentId;
    freshEdited.replaceWith(edited);
    surface.replaceChildren(...fresh.children);
    finishDrawing(surface);
    if (focus !== null) restoreEditingFocus(edited, focus);
}

// The edited note takes the caret where clicked (`clickAnchor`, captured from the note as it was
// drawn when clicked; null puts it at the end), its tag bar and the toolbar, as entering edit
// mode in the list does (ui-actions.js).
function startEditingElement(noteId, noteElement, clickAnchor) {
    initializeEditSessionCollapseStateFromNoteElement(noteElement);
    DOMUtils.setNoteEditable(noteElement, true);
    syncTagBar(noteElement);
    DOMUtils.revealCaret(noteElement);
    if (clickAnchor === null) {
        DOMUtils.focusNoteEdge(noteElement, 'end');
    } else {
        placeCaretAtClickAnchor(noteElement, clickAnchor);
    }
    attachEditorSurface(noteId, DOMUtils.getNoteContent(noteElement));
    const content = DOMUtils.getNoteContentHTML(noteElement);
    if (ModeContext.currentContent !== content) ModeContext.setCurrentContent(content);
}

function stopEditingIn(floatingWindow) {
    const hadFocus = floatingWindow.element.contains(document.activeElement);
    for (const surface of floatingWindow.element.querySelectorAll(`:scope > .${EDITING_TREE_CLASS}`)) surface.remove();
    floatingWindow.tree.hidden = false;
    floatingWindow.showNotes();
    // Left with Escape (or anything else that kept the focus in it): the window keeps the focus,
    // so a second Escape closes it (case 3).
    if (hadFocus) floatingWindow.element.focus({ preventScroll: true });
}

/**
 * Edits `noteId`, a note in `floatingWindow`, there (case 1): a note edited elsewhere is saved
 * and left first. `clickAnchor` (captureClickAnchorFor on the clicked drawing) puts the caret
 * where clicked; null puts it at the end.
 */
export async function editNoteInWindow(floatingWindow, noteId, clickAnchor) {
    requireWindow(floatingWindow);
    if (typeof noteId !== 'string' || noteId === '') throw new Error('editNoteInWindow requires a note id');
    if (ModeContext.isEditing) {
        await actionDeselectNote();
    }
    const drawn = await drawEditableNotes(floatingWindow, noteId);
    if (drawn === null) return;
    watchEditModeEnding();
    ModeContext.setCurrentNoteId(noteId);
    ModeContext.setEditing(true);
    startEditingInWindow({
        tree: drawn.surface,
        host: floatingWindow.element,
        windowNoteId: floatingWindow.noteId,
        leave: () => stopEditingIn(floatingWindow),
        switchTo: (nextNoteId, clickAnchor) => switchNoteInWindow(floatingWindow, nextNoteId, clickAnchor),
        follow: () => {
            void CommandGate.runWhenFree('floatingNote.follow', () => followEditedNote(floatingWindow));
        },
        redraw: () => redrawEditedNote(floatingWindow),
    });
    // The view takes the note's lock, and the list draws its copy with the pencil.
    await actionRefreshAndMaybeSelect({ startedAt: performance.now() });
    // Refused (another view edits it): the refresh left edit mode, and the window with it.
    if (!ModeContext.isEditing || ModeContext.currentNoteId !== noteId || !isEditingInWindow()) return;
    startEditingElement(noteId, drawn.noteElement, clickAnchor);
}

// The edited note as the server has it now (a copied note was pasted into it): drawn again and
// still edited, the caret at its end. It showed blank in the window while the list showed the
// pasted text (the maintainer, 2026-11-22).
async function redrawEditedNote(floatingWindow) {
    const noteId = ModeContext.currentNoteId;
    const drawn = await drawEditableNotes(floatingWindow, noteId);
    if (drawn === null) throw new Error('The note edited in a floating window is no longer in it');
    startEditingElement(noteId, drawn.noteElement, null);
}

// Another note of the same window, from a click or a key in it, or a new note made there: the
// note edited now is saved, then the window draws the other for editing. False, changing nothing
// shown, when the note is not under the window's note.
async function switchNoteInWindow(floatingWindow, noteId, clickAnchor) {
    if (ModeContext.currentNoteId === noteId) return true;
    await actionSaveNote(ModeContext.currentNoteId);
    const drawn = await drawEditableNotes(floatingWindow, noteId);
    if (drawn === null) return false;
    ModeContext.setCurrentContent(null);
    ModeContext.setCurrentNoteId(noteId);
    ModeContext.resetEditSessionState({ startedCollapsed: false });
    await actionRefreshAndMaybeSelect({ startedAt: performance.now() });
    if (!ModeContext.isEditing || ModeContext.currentNoteId !== noteId || !isEditingInWindow()) return true;
    startEditingElement(noteId, drawn.noteElement, clickAnchor);
    return true;
}
