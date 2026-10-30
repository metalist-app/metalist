import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { getTagBarValue, setTagBarValue } from './tag-bar-service.js';
import { appendStyleTagToken } from './add-style-service.js';
import { insertPlan } from './insert-format-plan.js';
import { actionSaveNote } from '../actions/content-actions.js';

const LINE_BREAK = '\n';

// Insert LaTeX, Insert CSV and Insert Mermaid Diagram (smart previews, slice 5; docs/ui/
// content-formatting.md, "Previews while editing"; agreed 2026-10-26, built 2026-10-29).
// Each declares the region and types its delimiters where the caret (or the right-click)
// is, the caret inside, so a preview shows as soon as something is typed:
// - in an @markdown note, LaTeX is `$$…$$` and a diagram a ```mermaid fence;
// - otherwise the region is a wrapper no other text or tag of the note uses (chosen as
//   Add Style chooses one), its tag (`(((@LaTeX)))`) added to the tag bar; a wrapper the
//   tag bar already gives the format is used again.
// Selected text goes inside the delimiters. A kind the whole note already is (@LaTeX,
// @csv, @mermaid) is not offered. The text goes in as typing (one ⌘Z removes it).

// The line holding `node`: the editor keeps each line in an element of its own, a child
// of the note's content (the first line can be text straight in the content).
function lineOf(content, node) {
    let line = node;
    while (line.parentNode !== content && line !== content) line = line.parentNode;
    return line;
}

// Whether the caret's line has any text before (or after) the range.
function lineHasTextBefore(content, range) {
    const line = lineOf(content, range.startContainer);
    const before = document.createRange();
    before.setStart(line === content ? content : line, 0);
    before.setEnd(range.startContainer, range.startOffset);
    return before.toString().trim() !== '';
}

function lineHasTextAfter(content, range) {
    const line = lineOf(content, range.endContainer);
    const after = document.createRange();
    after.setStart(range.endContainer, range.endOffset);
    const end = line === content ? content : line;
    after.setEnd(end, end.childNodes.length);
    return after.toString().trim() !== '';
}

function typeText(text) {
    if (!document.execCommand('insertText', false, text)) {
        throw new Error('The browser did not type the inserted format');
    }
}

// Types the plan around `range` in the note being edited and leaves the caret inside.
async function insertInto(noteId, range, kind) {
    if (!ModeContext.isEditingNote(noteId)) {
        throw new Error(`Insert ${kind} needs the note being edited: ${noteId}`);
    }
    const noteElement = document.querySelector(`.note[data-note-id="${noteId}"]`);
    const content = noteElement === null ? null : noteElement.querySelector(':scope > .note-content');
    if (!(content instanceof HTMLElement) || !(range instanceof Range) || !content.contains(range.startContainer)) {
        throw new Error('Insert goes in the text of the note being edited');
    }
    const tagBarText = getTagBarValue(noteElement);
    const selected = range.toString();
    const plan = insertPlan({ kind, tagBarText, contentText: content.textContent, hasSelection: selected !== '' });
    let open = plan.open;
    let close = plan.close;
    // A fence starts and ends a line of its own.
    if (plan.isBlock && lineHasTextBefore(content, range)) open = `${LINE_BREAK}${open}`;
    if (plan.isBlock && lineHasTextAfter(content, range)) close = `${close}${LINE_BREAK}`;
    content.focus({ preventScroll: true });
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    typeText(`${open}${plan.start}${selected}${close}`);
    // Back over the closing delimiter: the caret sits where the region's text goes on.
    for (let index = 0; index < close.length; index += 1) selection.modify('move', 'backward', 'character');
    if (plan.tagToken === null) return;
    const caret = selection.getRangeAt(0).cloneRange();
    setTagBarValue(noteElement, appendStyleTagToken(tagBarText, plan.tagToken));
    await actionSaveNote(noteId);
    content.focus({ preventScroll: true });
    selection.removeAllRanges();
    selection.addRange(caret);
}

// From the note menu: where it was right-clicked (reference-insert-point-service.js).
export async function insertFormatAt(noteId, range, kind) {
    await insertInto(noteId, range, kind);
}

// From the command palette: at the caret of the note being edited.
export async function insertFormatAtCaret(kind) {
    const noteId = ModeContext.currentNoteId;
    const selection = window.getSelection();
    if (!ModeContext.isEditing || typeof noteId !== 'string' || selection === null || selection.rangeCount === 0) {
        throw new Error('Insert needs a caret in the note being edited');
    }
    await insertInto(noteId, selection.getRangeAt(0).cloneRange(), kind);
}
