// The floating message when an import finishes: what came in and the folder it went into.
export function importFinishedMessage(noteCount, prefixFolder) {
    const notes = `${noteCount} ${noteCount === 1 ? 'note' : 'notes'}`;
    if (prefixFolder === '') return `Imported ${notes}.`;
    return `Imported ${notes} into ${prefixFolder}.`;
}
