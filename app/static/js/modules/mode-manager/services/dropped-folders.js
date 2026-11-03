import { ApplicationState } from '../../application-state.js';

// Folders dropped from the desktop (docs/ready-to-build/desktop-drops-into-folders.md). A
// browser hands a dropped folder over as a File it can't read, so a drop is looked at before
// anything is uploaded: its entries say which items are folders. Read during the drop event
// itself; the browser empties the items once it ends.

/** The drop's items (files and folders; text dragged along is none) and how many are folders. */
export function describeDroppedItems(transferData) {
    if (!transferData || !transferData.items) {
        throw new Error('describeDroppedItems requires the drop\'s data');
    }
    let itemCount = 0;
    let folderCount = 0;
    for (const item of transferData.items) {
        if (item.kind !== 'file') continue;
        if (typeof item.webkitGetAsEntry !== 'function') {
            throw new Error('This browser gives no webkitGetAsEntry for a dropped item');
        }
        itemCount += 1;
        const entry = item.webkitGetAsEntry();
        if (entry !== null && entry.isDirectory) folderCount += 1;
    }
    return { folderCount, itemCount };
}

/** The entry of the drop's one item when it is a folder (read during the drop event). */
export function loneDroppedFolderEntry(transferData) {
    const items = [...transferData.items].filter((item) => item.kind === 'file');
    if (items.length !== 1) {
        throw new Error('loneDroppedFolderEntry requires a drop of one item');
    }
    const entry = items[0].webkitGetAsEntry();
    if (entry === null || !entry.isDirectory) {
        throw new Error('The dropped item is not a folder');
    }
    return entry;
}

// A folder entry's children: the browser hands them out in batches, the last one empty.
async function childrenOf(folderEntry) {
    const reader = folderEntry.createReader();
    const children = [];
    for (;;) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (batch.length === 0) return children;
        children.push(...batch);
    }
}

async function collectFiles(entry, prefix, files) {
    if (entry.isFile) {
        const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
        // As the server writes paths (macOS gives names decomposed): the checklist's paths match.
        files.push({ path: `${prefix}${entry.name}`.normalize('NFC'), size: file.size, file });
        return;
    }
    if (!entry.isDirectory) {
        throw new Error(`A dropped entry is neither a file nor a folder: ${entry.name}`);
    }
    for (const child of await childrenOf(entry)) {
        await collectFiles(child, `${prefix}${entry.name}/`, files);
    }
}

/**
 * A dropped folder's files, at any depth: { name, files: [{ path (inside it, with /), size,
 * file }] }, in the order the browser lists them. Nothing is uploaded.
 */
export async function readDroppedFolder(folderEntry) {
    if (!folderEntry || folderEntry.isDirectory !== true) {
        throw new Error('readDroppedFolder requires a folder entry');
    }
    const files = [];
    for (const child of await childrenOf(folderEntry)) {
        await collectFiles(child, '', files);
    }
    return { name: folderEntry.name, files };
}

// The folder the import walkthrough was opened with, kept here (its files can't be one of the
// walkthrough's choices): { id, name, files }, or null.
const droppedState = ApplicationState.createFields('dropped-folders', { folder: null, lastId: 0 });

/** Keep a dropped folder for the walkthrough; its id is the walkthrough's droppedFolderId. */
export function holdDroppedFolder(folder) {
    if (!folder || typeof folder.name !== 'string' || !Array.isArray(folder.files)) {
        throw new Error('holdDroppedFolder requires a read folder');
    }
    const id = droppedState.lastId + 1;
    droppedState.lastId = id;
    droppedState.folder = { id: String(id), name: folder.name, files: folder.files };
    return String(id);
}

/** The dropped folder held under id. */
export function heldDroppedFolder(id) {
    const folder = droppedState.folder;
    if (folder === null || folder.id !== id) {
        throw new Error(`No dropped folder is held as ${id}`);
    }
    return folder;
}
