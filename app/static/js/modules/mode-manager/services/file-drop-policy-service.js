// While a note is being edited, dropped files go in it wherever they are let go; with none being
// edited, each file gets its own note (the maintainer, 2026-11-19; before, only files let go on
// the note being edited went in it, and a drop a few pixels outside it went to the top level).
export function shouldCreateTopNoteForFileDrop({
    isEditing,
    currentNoteId,
    hasEditingDropTarget,
}) {
    if (typeof isEditing !== 'boolean') {
        throw new Error('File drop isEditing must be a boolean');
    }
    if (currentNoteId !== null && typeof currentNoteId !== 'string') {
        throw new Error('File drop currentNoteId must be a string or null');
    }
    if (isEditing && (typeof currentNoteId !== 'string' || currentNoteId.length === 0)) {
        throw new Error('File drop requires currentNoteId while editing');
    }
    if (!isEditing && currentNoteId !== null) {
        throw new Error('File drop cannot have currentNoteId outside editing mode');
    }
    if (typeof hasEditingDropTarget !== 'boolean') {
        throw new Error('File drop hasEditingDropTarget must be a boolean');
    }

    if (!isEditing) {
        return true;
    }
    return !hasEditingDropTarget;
}
