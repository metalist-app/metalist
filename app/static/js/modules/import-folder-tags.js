// The import's folder tags are never proposed by the AI (PLAN.md, slice 2b): a note has its
// own folder's tag from its file, and on any other note it would be wrong.

/** proposals ({ noteId: [tags] }) without the folder tags, and without notes left with none. */
export function withoutFolderTags(proposals, folderTags) {
    const excluded = new Set(folderTags.map((tag) => tag.toLowerCase()));
    const kept = {};
    for (const [noteId, tags] of Object.entries(proposals)) {
        const allowed = tags.filter((tag) => !excluded.has(tag.toLowerCase()));
        if (allowed.length > 0) {
            kept[noteId] = allowed;
        }
    }
    return kept;
}
