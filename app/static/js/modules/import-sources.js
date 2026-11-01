// What can be imported (PLAN.md, slices 1 and 1c; app/services/obsidian_import/sources.py):
// each opens the same folder import dialog with its own words.
export const IMPORT_SOURCES = Object.freeze([
    Object.freeze({
        key: 'obsidian', title: 'Import Obsidian Vault', label: 'Obsidian', choiceLabel: 'Obsidian vault',
    }),
    Object.freeze({
        key: 'markdown', title: 'Import Markdown Folder', label: 'Markdown', choiceLabel: 'Markdown folder',
    }),
]);

export function importSource(key) {
    const source = IMPORT_SOURCES.find((candidate) => candidate.key === key);
    if (source === undefined) {
        throw new Error(`Unknown import source: ${key}`);
    }
    return source;
}
