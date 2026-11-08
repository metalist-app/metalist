import { ApplicationState } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { escapeHtml } from '../../html-escape.js';
import { showSearchInputChip } from './search-input-chip-service.js';
import { getActiveReferenceChain, isViewingReferenceSource } from './reference-source-navigation-service.js';
import { showContextMenu } from '../../context-menu/context-menu-service.js';
import { showErrorDialog } from '../../modals/error-dialog.js';
import { isVirtualFoldersShown, rememberVirtualFoldersShown } from './virtual-folders-state.js';
import { isFolderContext, recordFolderContextsFromServer } from './folder-context-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { initVirtualFoldersWidth } from './virtual-folders-width.js';
import { FloatingMessages } from '../../floating-messages.js';

export { isVirtualFoldersShown } from './virtual-folders-state.js';

// Virtual folders, an experiment (docs/ready-to-build/virtual-folders.md): a tag ending in
// `/` is a folder. With the Virtual Folders toggle on, a tree in the left margin lists every
// folder in the vault, each with its subfolders, and no notes (the maintainer, 2026-11-01:
// the column shows them). The tree belongs to folder contexts (docs/ready-to-build/virtual-folders.md, "Folder contexts"):
// open folders tab goes to the folder context used last, close folders tab to the plain search
// used last, and the tree shows in folder contexts only; clicking a folder narrows the one shown
// to that folder and the folders below it (a chip in the search input). The notes column moves right to make room.
// Right-click: New Folder, Rename Folder, Delete Folder; a folder dragged onto another moves
// into it. A renamed, moved or deleted folder changes the tags on the notes.

const FOLDER_MARK = '/';
const TREE_ID = 'virtual-folders';
const ON_CLASS = 'virtual-folders-on';
const TOGGLE_BUTTON_ID = 'virtual-folders-button';
const DRAG_TYPE = 'application/x-metalist-folder';
const DROP_CLASS = 'is-drop-target';
// Dropped on the tree's empty space: to the top.
const TOP = '';
// A New Folder no note carries yet.
const NO_NOTES = 0;
const ONE_NOTE = 1;

const moduleState = ApplicationState.createFields('virtual-folders-service', {
    // The active tab's filter, as the server last sent it: a folder, or '' for none.
    folder: '',
    // Every tab's folder, as the server last sent it (a tab in none is absent): the list of
    // search contexts names a tab narrowed to a folder by it.
    tabFolders: Object.freeze({}),
    // The folders the server last sent, by path.
    folders: Object.freeze([]),
    // How many notes clicking each folder shows, with the folders below it, in the view's
    // search (the maintainer, 2026-11-01); the top's under ''.
    noteCounts: Object.freeze({}),
    // How many each shows with no search: a count the search narrows reads out of it
    // (docs/ready-to-build/folder-counts.md); the top's under ''.
    noteTotals: Object.freeze({}),
    // Whether a view's folders have been read yet: the tree is drawn only from them.
    hasReadFolders: false,
    // The folders the person opened in the tree, by path.
    openPaths: Object.freeze([]),
    // Whether the top, `/`, is open: closed, the tree is one line (the maintainer, 2026-11-01).
    isRootOpen: true,
    // New Folder: held here until a folder is moved into it (no note carries its tag yet).
    newPaths: Object.freeze([]),
    // The folder being dragged ('' when none).
    draggedPath: '',
});

// Wired by the command palette: setFilter(folder) narrows the folder context shown to it ('' for
// `/`); openFoldersTab() and closeFoldersTab() go to the folder context or plain search used last;
// confirm(context) asks (ConfirmationModal); askName(form) asks a name (FolderNameModal);
// askDeleteFolder(form) asks whether to delete a folder, and its notes (DeleteFolderModal);
// afterChange() shows the view again once tags changed; undo() is ⌘Z.
const handlers = ApplicationState.createFields('virtual-folders-handlers', {
    setFilter: null,
    openFoldersTab: null,
    closeFoldersTab: null,
    confirm: null,
    askName: null,
    askDeleteFolder: null,
    afterChange: null,
    undo: null,
});

/** The palette's ways to filter, open, ask and refresh (set once at startup). */
export function wireVirtualFolders(wiring) {
    for (const name of ['setFilter', 'openFoldersTab', 'closeFoldersTab', 'confirm', 'askName', 'askDeleteFolder', 'afterChange', 'undo']) {
        if (typeof wiring[name] !== 'function') {
            throw new Error(`wireVirtualFolders requires ${name}`);
        }
        handlers[name] = wiring[name];
    }
    initVirtualFoldersWidth();
    // The search contexts are loaded by now: the tree shows from the first view when the folder
    // context does, its button saying so, without waiting for the folders to be read.
    showFolderOfActiveContext();
}

export function activeVirtualFolder() {
    return moduleState.folder;
}

/** The folder a tab is narrowed to, '' for none (the server lists only tabs in a folder). */
export function folderOfTab(tabId) {
    if (typeof tabId !== 'string' || tabId === '') {
        throw new Error('folderOfTab requires a tab id');
    }
    if (!Object.prototype.hasOwnProperty.call(moduleState.tabFolders, tabId)) return '';
    return moduleState.tabFolders[tabId];
}

/** A folder context was just narrowed to folder ('' for none), before the view's refresh reads
 * every tab's folder again (chooseFolder). */
export function recordFolderContextFolder(tabId, folder) {
    if (typeof tabId !== 'string' || tabId === '' || typeof folder !== 'string') {
        throw new Error('recordFolderContextFolder requires the tab and its folder');
    }
    const tabFolders = { ...moduleState.tabFolders };
    if (folder === TOP) delete tabFolders[tabId];
    else tabFolders[tabId] = folder;
    remember('tabFolders', Object.freeze(tabFolders));
}

/** The context shown changed: the tree shows only in folder contexts, and the folder of
 * the one shown in the tree and the chip at once, not one refresh later beside a plain search. */
export function showFolderOfActiveContext() {
    const treeTabId = treeContextTabId();
    rememberVirtualFoldersShown(treeTabId !== '');
    if (treeTabId === '') remember('folder', TOP);
    else remember('folder', folderOfTab(treeTabId));
    render();
}

function remember(field, value) {
    if (JSON.stringify(moduleState[field]) !== JSON.stringify(value)) {
        moduleState[field] = value;
    }
}

/** Read the tree's state for the view shown now and draw it (after every view refresh). A
 * note opened from the tree (a reference view) keeps the folders of the view it came from. */
export async function updateVirtualFolders() {
    if (isViewingReferenceSource()) {
        showFolderOfActiveContext();
        return;
    }
    const answer = await NotesAPI.listVirtualFolders();
    recordFolderContextsFromServer(answer);
    if (typeof answer.folder !== 'string' || !Array.isArray(answer.folders)
        || answer.tabFolders === null || typeof answer.tabFolders !== 'object'
        || Object.values(answer.tabFolders).some((folder) => typeof folder !== 'string')
        || answer.noteCounts === null || typeof answer.noteCounts !== 'object'
        || answer.noteTotals === null || typeof answer.noteTotals !== 'object') {
        throw new Error('Virtual folders answer malformed');
    }
    // A folder newly chosen shows in the tree; a refresh leaves what the person closed closed.
    const isNewlyChosen = answer.folder !== moduleState.folder;
    remember('folder', answer.folder);
    const haveTabFoldersChanged = JSON.stringify(answer.tabFolders) !== JSON.stringify(moduleState.tabFolders);
    remember('tabFolders', Object.freeze({ ...answer.tabFolders }));
    remember('folders', Object.freeze(answer.folders));
    remember('noteCounts', Object.freeze({ ...answer.noteCounts }));
    remember('noteTotals', Object.freeze({ ...answer.noteTotals }));
    remember('hasReadFolders', true);
    // A new folder stays new until something is in it: a note carrying its tag, or a folder below it.
    const known = answer.folders;
    remember('newPaths', Object.freeze(moduleState.newPaths.filter((path) => !known.some((knownPath) => knownPath.startsWith(path)))));
    if (isNewlyChosen && answer.folder.endsWith(FOLDER_MARK)) openTo(answer.folder);
    rememberVirtualFoldersShown(treeContextTabId() !== '');
    render();
    // The list of search contexts names each tab by its folder too (keyboard-events.js listens).
    if (haveTabFoldersChanged) document.dispatchEvent(new CustomEvent('metalist:tab-folders-changed'));
}

/** The folders tab, or Show/Hide Virtual Folders: close folders tab in a folder context (the
 * tree shown), open folders tab in a plain search (docs/ready-to-build/virtual-folders.md, "Folder contexts"). */
export function toggleFolderContextFromTab() {
    if (isVirtualFoldersShown()) {
        void handlers.closeFoldersTab();
        return;
    }
    void handlers.openFoldersTab();
}

// The context whose folder the tree shows: the folder context shown, or the one a reference view
// shown was opened from; '' in a plain search, and the tree hidden with it.
function treeContextTabId() {
    const activeTabId = ModeContext.activeTabId;
    if (isFolderContext(activeTabId)) return activeTabId;
    if (!isViewingReferenceSource()) return '';
    const originTabId = getActiveReferenceChain()[0].fromTabId;
    if (isFolderContext(originTabId)) return originTabId;
    return '';
}

// A folder and every folder above it open, so a filtered folder shows in the tree.
function openTo(path) {
    if (!moduleState.isRootOpen) remember('isRootOpen', true);
    const open = new Set(moduleState.openPaths);
    for (const ancestor of ancestorsOf(path)) open.add(ancestor);
    open.add(path);
    remember('openPaths', Object.freeze([...open].sort()));
}

function ancestorsOf(path) {
    const parts = path.split(FOLDER_MARK).filter((part) => part !== '');
    return parts.slice(0, -1).map((_, index) => `${parts.slice(0, index + 1).join(FOLDER_MARK)}${FOLDER_MARK}`);
}

function toggleOpen(path) {
    const open = new Set(moduleState.openPaths);
    if (open.has(path)) open.delete(path);
    else open.add(path);
    remember('openPaths', Object.freeze([...open].sort()));
    render();
}

// The folders as a tree: a parent exists when a folder below it does (Projects/ for
// Projects/Client-A/). Each node: { path, name, children (paths) }.
function buildTree(folders) {
    const nodes = new Map();
    const ensure = (path) => {
        if (!nodes.has(path)) {
            nodes.set(path, { path, name: nameOf(path), children: new Set() });
        }
        return nodes.get(path);
    };
    for (const path of [...folders, ...moduleState.newPaths]) {
        ensure(path);
        let child = path;
        for (const ancestor of ancestorsOf(path).reverse()) {
            ensure(ancestor).children.add(child);
            child = ancestor;
        }
    }
    const tops = [...nodes.keys()].filter((path) => ancestorsOf(path).length === 0);
    return { nodes, tops: sortedByName(tops, nodes) };
}

function nameOf(path) {
    const parts = path.split(FOLDER_MARK).filter((part) => part !== '');
    return parts[parts.length - 1];
}

// The folder holding path ('' at the top).
function parentOf(path) {
    const ancestors = ancestorsOf(path);
    if (ancestors.length === 0) return TOP;
    return ancestors[ancestors.length - 1];
}

function sortedByName(paths, nodes) {
    return [...paths].sort((left, right) => nodes.get(left).name.localeCompare(nodes.get(right).name, undefined, { sensitivity: 'base' }));
}

function folderHtml(path, tree, depth) {
    const node = tree.nodes.get(path);
    const isOpen = moduleState.openPaths.includes(path);
    const isFiltered = moduleState.folder === path;
    const isNew = moduleState.newPaths.includes(path);
    const children = sortedByName(node.children, tree.nodes);
    // An innermost folder has nothing to open.
    const isInnermost = children.length === 0;
    let body = '';
    if (isOpen && !isInnermost) {
        body = children.map((child) => folderHtml(child, tree, depth + 1)).join('');
    }
    return `
        <div class="virtual-folder${isFiltered ? ' is-filtered' : ''}${isNew ? ' is-new' : ''}${!isNew && isUnmatched(path) ? ' is-unmatched' : ''}">
            <button type="button" class="virtual-folder-row interactive" data-virtual-folder="${escapeHtml(path)}" draggable="${!isNew}"
                style="--virtual-folder-depth:${depth}"${isInnermost ? '' : ` aria-expanded="${isOpen}"`} title="${escapeHtml(path)}">
                ${isInnermost
                    ? '<span class="virtual-folder-arrow" aria-hidden="true"></span>'
                    : `<span class="virtual-folder-arrow" data-virtual-folder-arrow aria-hidden="true">${isOpen ? '▾' : '▸'}</span>`}
                <span class="virtual-folder-icon" aria-hidden="true"></span>
                <span class="virtual-folder-name">${escapeHtml(node.name)}</span>
                ${isNew ? countHtml(NO_NOTES, NO_NOTES) : countHtml(noteCountOf(path), noteTotalOf(path))}
            </button>
            ${body}
        </div>`;
}

function noteCountOf(path) {
    if (!Object.prototype.hasOwnProperty.call(moduleState.noteCounts, path)) {
        throw new Error(`No note count for the folder ${path}`);
    }
    return moduleState.noteCounts[path];
}

function noteTotalOf(path) {
    if (!Object.prototype.hasOwnProperty.call(moduleState.noteTotals, path)) {
        throw new Error(`No note total for the folder ${path}`);
    }
    return moduleState.noteTotals[path];
}

// Holding notes, none of which this search shows: dimmed, never hidden (folder-counts.md §3).
function isUnmatched(path) {
    return noteCountOf(path) === NO_NOTES && noteTotalOf(path) > NO_NOTES;
}

function notesWord(count) {
    return `${count.toLocaleString()} ${count === ONE_NOTE ? 'note' : 'notes'}`;
}

// The notes clicking a folder shows, out of all it holds when the search narrows it, so a count
// of none doesn't read as an empty folder (the maintainer, 2026-11-02: "(0/17)"); its tooltip
// says it in words.
function countHtml(count, total) {
    if (count === total) {
        return `<span class="virtual-folder-count" title="${escapeHtml(notesWord(total))}">(${total.toLocaleString()})</span>`;
    }
    const verb = total === ONE_NOTE ? 'matches' : 'match';
    const words = `${count.toLocaleString()} of ${notesWord(total)} ${verb} this search`;
    return `<span class="virtual-folder-count" title="${escapeHtml(words)}">(${count.toLocaleString()}/${total.toLocaleString()})</span>`;
}

// The top, `/`, over every folder (the maintainer, 2026-11-01): clicking it opens the folder
// context with no folder, every note. It looks chosen while that shows.
function rootHtml(built) {
    const isChosen = isFolderContext(ModeContext.activeTabId) && moduleState.folder === TOP && !isViewingReferenceSource();
    const isOpen = moduleState.isRootOpen;
    return `
        <div class="virtual-folder${isChosen ? ' is-filtered' : ''}${isUnmatched(TOP) ? ' is-unmatched' : ''}">
            <button type="button" class="virtual-folder-row interactive" data-virtual-folder-root
                style="--virtual-folder-depth:0" aria-expanded="${isOpen}" title="Every folder: show every note">
                <span class="virtual-folder-arrow" data-virtual-folder-arrow aria-hidden="true">${isOpen ? '▾' : '▸'}</span>
                <span class="virtual-folder-icon" aria-hidden="true"></span>
                <span class="virtual-folder-name">/</span>
                ${countHtml(noteCountOf(TOP), noteTotalOf(TOP))}
            </button>
            ${isOpen ? built.tops.map((path) => folderHtml(path, built, 1)).join('') : ''}
        </div>`;
}

function requireTree() {
    let tree = document.getElementById(TREE_ID);
    if (tree === null) {
        tree = document.createElement('nav');
        tree.id = TREE_ID;
        tree.className = 'virtual-folders';
        tree.setAttribute('aria-label', 'Virtual folders');
        tree.addEventListener('click', onTreeClick);
        tree.addEventListener('dragstart', onDragStart);
        tree.addEventListener('dragover', onDragOver);
        tree.addEventListener('dragleave', clearDropTarget);
        tree.addEventListener('drop', onDrop);
        tree.addEventListener('dragend', onDragEnd);
        document.body.appendChild(tree);
    }
    return tree;
}

function onTreeClick(event) {
    // The top: every note again.
    if (event.target.closest('[data-virtual-folder-root]') !== null) {
        // Its arrow opens or closes every folder at once.
        if (event.target.closest('[data-virtual-folder-arrow]') !== null) {
            remember('isRootOpen', !moduleState.isRootOpen);
            render();
            return;
        }
        // The folder context with no folder, every note; shown already, nothing changes.
        if (isFolderContext(ModeContext.activeTabId) && moduleState.folder === TOP && !isViewingReferenceSource()) return;
        void handlers.setFilter(TOP);
        return;
    }
    const row = event.target.closest('[data-virtual-folder]');
    if (row === null) return;
    const path = row.dataset.virtualFolder;
    // The arrow opens or closes; the name narrows the view to the folder (and opens it).
    if (event.target.closest('[data-virtual-folder-arrow]') !== null) {
        toggleOpen(path);
        return;
    }
    // The chosen folder clicked again: no folder, as `/` (the maintainer, 2026-11-01).
    if (moduleState.folder === path && !isViewingReferenceSource()) {
        void handlers.setFilter(TOP);
        return;
    }
    if (!moduleState.openPaths.includes(path)) toggleOpen(path);
    // Clicked from a reference view: it closes first, and the folder context comes from where it came from.
    void handlers.setFilter(path);
}

// --- Dragging a folder onto another --------------------------------------------------------

function onDragStart(event) {
    const row = event.target.closest('[data-virtual-folder]');
    if (row === null || row.getAttribute('draggable') !== 'true') return;
    remember('draggedPath', row.dataset.virtualFolder);
    event.dataTransfer.setData(DRAG_TYPE, row.dataset.virtualFolder);
    event.dataTransfer.effectAllowed = 'move';
}

// Where a dragged folder would go: the folder under the pointer, or the top over empty space;
// '' (none) for itself, a folder below it, or the folder it is in already.
function dropTargetOf(event) {
    const dragged = moduleState.draggedPath;
    if (dragged === '') return null;
    const target = folderDropAt(event.target);
    if (target.into.startsWith(dragged) || target.into === parentOf(dragged)) return null;
    return target;
}

// The folder under the pointer and the row it highlights: a folder's own row; the top over `/`
// (its row) or over the tree's empty space (the tree itself).
function folderDropAt(pointerTarget) {
    const folderRow = pointerTarget.closest('[data-virtual-folder]');
    if (folderRow !== null) return { into: folderRow.dataset.virtualFolder, row: folderRow };
    const rootRow = pointerTarget.closest('[data-virtual-folder-root]');
    if (rootRow !== null) return { into: TOP, row: rootRow };
    return { into: TOP, row: requireTree() };
}

function clearDropTarget() {
    for (const marked of document.querySelectorAll(`#${TREE_ID} .${DROP_CLASS}`)) marked.classList.remove(DROP_CLASS);
}

function onDragOver(event) {
    // Files or a folder from the desktop: the folder they would go into (the top over empty space).
    if (moduleState.draggedPath === '' && event.dataTransfer.types.includes('Files')) {
        clearDropTarget();
        const into = virtualFolderAt(event.target);
        const row = into === TOP
            ? document.querySelector(`#${TREE_ID} [data-virtual-folder-root]`)
            : event.target.closest('[data-virtual-folder]');
        row.classList.add(DROP_CLASS);
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        return;
    }
    const target = dropTargetOf(event);
    clearDropTarget();
    if (target === null) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    target.row.classList.add(DROP_CLASS);
}

function onDragEnd() {
    clearDropTarget();
    remember('draggedPath', '');
}

async function onDrop(event) {
    const target = dropTargetOf(event);
    const dragged = moduleState.draggedPath;
    onDragEnd();
    if (target === null) return;
    event.preventDefault();
    await moveFolder(dragged, target.into);
}

// --- Dragging a note from the column onto a folder ------------------------------------------
// (docs/ready-to-build/virtual-folders.md §4). The column's own drag (mouse-events.js)
// asks here once the pointer is over the tree: there it is a drop into the folder under the
// pointer, or the top for no folder.

const MOVED_CARD_KEY = 'virtual-folders.moved';
const ONLY_ROOT_NOTES_TEXT = 'Only top-level notes can go in a folder.';

// The folder tags written in a note's tag bar (the column keeps it on the note's element).
function folderTagsOfNote(noteElement) {
    const tags = noteElement.dataset.noteTags;
    if (typeof tags !== 'string') {
        throw new Error('A dragged note has no tags on its element');
    }
    return tags.split(/\s+/).filter((tag) => tag.endsWith(FOLDER_MARK));
}

/**
 * What a note dragged from the column would do at pointerTarget: null when the pointer is not
 * over the tree (an ordinary note drag); over it, { folder, row, isChild } with folder the
 * folder it would go into ('' the top) or null when the drop would do nothing: a child (it
 * inherits its parent's folder), or the folder the note is in already.
 */
export function noteDropAt(pointerTarget, noteElement) {
    if (!(pointerTarget instanceof Element) || pointerTarget.closest(`#${TREE_ID}`) === null) return null;
    const isChild = noteElement.parentElement.closest('.note') !== null;
    if (isChild) return { folder: null, row: null, isChild };
    const current = folderTagsOfNote(noteElement);
    const folderRow = pointerTarget.closest('[data-virtual-folder]');
    if (folderRow === null) {
        // The top: `/` or the tree's empty space; `/`'s row is highlighted.
        if (current.length === 0) return { folder: null, row: null, isChild };
        return { folder: TOP, row: document.querySelector(`#${TREE_ID} [data-virtual-folder-root]`), isChild };
    }
    const into = folderRow.dataset.virtualFolder;
    if (current.length === 1 && current[0] === into) return { folder: null, row: null, isChild };
    return { folder: into, row: folderRow, isChild };
}

/** The virtual folder a drop from the desktop landed on: its path, '' for the top (`/` or the
 * tree's empty space), null when it landed outside the tree. */
export function virtualFolderAt(target) {
    if (!(target instanceof Element) || target.closest(`#${TREE_ID}`) === null) return null;
    const folderRow = target.closest('[data-virtual-folder]');
    if (folderRow === null) return TOP;
    return folderRow.dataset.virtualFolder;
}

/** Highlight the folder a note would be dropped into (null: none). */
export function showNoteDropTarget(row) {
    clearDropTarget();
    if (row !== null) row.classList.add(DROP_CLASS);
}

/** A note dropped on the tree: into the folder, or why not. One undo step; the message offers Undo. */
export async function dropNoteOnFolder(noteId, drop) {
    clearDropTarget();
    if (drop.isChild) {
        FloatingMessages.show({ text: ONLY_ROOT_NOTES_TEXT, type: 'info', detail: '', isClosable: false, isLasting: false, key: null, action: null });
        return;
    }
    if (drop.folder === null) return;
    await NotesAPI.fileNoteInVirtualFolder(noteId, drop.folder);
    await handlers.afterChange();
    showMovedMessage(drop.folder === TOP ? 'Moved out of every folder' : `Moved to ${drop.folder}`);
}

/** A note just made at the top (files dropped on a folder) put in exactly that folder ('' none). */
export async function fileNewNoteInFolder(noteId, folder) {
    const noteElement = document.querySelector(`#notes-container .note[data-note-id="${noteId}"]`);
    if (!(noteElement instanceof HTMLElement)) {
        throw new Error(`The note made for the dropped files is not shown: ${noteId}`);
    }
    const current = folderTagsOfNote(noteElement);
    // Made in that folder's view, it is there already.
    const isThereAlready = folder === TOP ? current.length === 0 : current.length === 1 && current[0] === folder;
    if (!isThereAlready) await NotesAPI.fileNoteInVirtualFolder(noteId, folder);
    await handlers.afterChange();
}

// The message stays until the next thing the person does, so its Undo never undoes anything else.
function showMovedMessage(text) {
    FloatingMessages.end(MOVED_CARD_KEY);
    const closeOnNextAction = (event) => {
        if (event.target instanceof Element && event.target.closest('.floating-message-action') !== null) return;
        document.removeEventListener('keydown', closeOnNextAction, true);
        document.removeEventListener('mousedown', closeOnNextAction, true);
        FloatingMessages.end(MOVED_CARD_KEY);
    };
    FloatingMessages.show({
        text, type: 'success', detail: '', isClosable: false, isLasting: false, key: MOVED_CARD_KEY,
        action: {
            label: 'Undo',
            onSelect: () => {
                document.removeEventListener('keydown', closeOnNextAction, true);
                document.removeEventListener('mousedown', closeOnNextAction, true);
                void handlers.undo();
            },
        },
    });
    document.addEventListener('keydown', closeOnNextAction, true);
    document.addEventListener('mousedown', closeOnNextAction, true);
}

// --- Changing folders -----------------------------------------------------------------------

function knownPaths() {
    return new Set([...moduleState.folders.map((folder) => folder.path), ...moduleState.newPaths]);
}

async function moveFolder(folder, into) {
    const newPath = `${into}${nameOf(folder)}${FOLDER_MARK}`;
    if (knownPaths().has(newPath) && !(await confirmMerge(folder, newPath))) return;
    await NotesAPI.moveVirtualFolder(folder, into);
    openTo(newPath);
    await handlers.afterChange();
}

async function confirmMerge(folder, newPath) {
    return handlers.confirm({
        eyebrow: 'Virtual folders', title: `Merge into ${newPath}?`,
        description: `${newPath} exists already: ${folder} and everything in it join it.`,
        confirmLabel: 'Merge', isDangerous: false,
    });
}

// A name typed for a folder: one level, so no `/` in it.
async function askFolderName(form) {
    const name = await handlers.askName(form);
    if (name === null) return null;
    if (name.includes(FOLDER_MARK)) {
        await showErrorDialog([{ text: 'A folder\'s name can\'t hold a /. Make the folder inside another instead.', fieldId: null }]);
        return null;
    }
    return name;
}

async function newFolder(parent) {
    const name = await askFolderName({ title: 'New Folder', name: '', actionLabel: 'Create' });
    if (name === null) return;
    const path = `${parent}${name}${FOLDER_MARK}`;
    if (knownPaths().has(path)) {
        await showErrorDialog([{ text: `${path} exists already.`, fieldId: null }]);
        return;
    }
    remember('newPaths', Object.freeze([...moduleState.newPaths, path]));
    openTo(path);
    render();
}

async function renameFolder(path) {
    const name = await askFolderName({ title: 'Rename Folder', name: nameOf(path), actionLabel: 'Rename' });
    if (name === null) return;
    const newPath = `${parentOf(path)}${name}${FOLDER_MARK}`;
    if (moduleState.newPaths.includes(path)) {
        remember('newPaths', Object.freeze(moduleState.newPaths.map((known) => (known === path ? newPath : known))));
        render();
        return;
    }
    if (knownPaths().has(newPath) && !(await confirmMerge(path, newPath))) return;
    await NotesAPI.renameVirtualFolder(path, newPath);
    openTo(newPath);
    await handlers.afterChange();
}

async function deleteFolder(path) {
    if (moduleState.newPaths.includes(path)) {
        remember('newPaths', Object.freeze(moduleState.newPaths.filter((known) => known !== path)));
        render();
        return;
    }
    const counted = await NotesAPI.countVirtualFolderNotes(path);
    if (!Number.isInteger(counted.noteCount)) {
        throw new Error('Counting a folder\'s notes answered without a count');
    }
    const choice = await handlers.askDeleteFolder({ path, noteCount: counted.noteCount });
    if (choice === null) return;
    const expectedNoteCount = choice.deleteNotes ? counted.noteCount : NO_NOTES;
    await NotesAPI.deleteVirtualFolder(path, choice.deleteNotes, expectedNoteCount);
    await handlers.afterChange();
}

/** Right-click in the tree: on a folder, New Folder Inside, Rename and Delete; elsewhere, New Folder. */
export function showVirtualFoldersMenu(event) {
    const row = event.target.closest('[data-virtual-folder]');
    const position = { x: event.clientX, y: event.clientY };
    if (row === null) {
        showContextMenu({
            items: [{ id: 'virtual-folder-new', label: 'New Folder…', icon: 'folder', enabled: true, onSelect: () => void newFolder(TOP) }],
            position, onClose: null,
        });
        return;
    }
    const path = row.dataset.virtualFolder;
    showContextMenu({
        items: [
            { id: 'virtual-folder-new-inside', label: 'New Folder Inside…', icon: 'folder', enabled: true, onSelect: () => void newFolder(path) },
            { id: 'virtual-folder-rename', label: 'Rename Folder…', enabled: true, onSelect: () => void renameFolder(path) },
            { id: 'virtual-folder-delete', label: 'Delete Folder…', enabled: true, separated: true, onSelect: () => void deleteFolder(path) },
        ],
        position, onClose: null,
    });
}

function render() {
    const tree = requireTree();
    // The column moves whenever the toggle is on, so a search never shifts it; the tree shows
    // then too, empty or not, so a first folder can be made in it (right-click).
    document.body.classList.toggle(ON_CLASS, isVirtualFoldersShown());
    tree.hidden = !isVirtualFoldersShown();
    renderToggleButton();
    // Drawn from the folders the server sent; until the first are read, the panel waits empty.
    if (isVirtualFoldersShown() && moduleState.hasReadFolders) {
        const built = buildTree(moduleState.folders);
        tree.innerHTML = `<div class="virtual-folders-title">Virtual Folders</div>${rootHtml(built)}`;
    } else {
        tree.innerHTML = '';
    }
    updateVirtualFolderIndicator();
}

// The button at the top left (the maintainer, 2026-11-02): a click shows or hides the tree, as
// View > Show > Virtual Folders and the command palette do; it looks the same either way, its
// tooltip saying what a click does.
function renderToggleButton() {
    const button = document.getElementById(TOGGLE_BUTTON_ID);
    if (!(button instanceof HTMLButtonElement)) {
        throw new Error('virtual-folders-button element missing');
    }
    const label = isVirtualFoldersShown() ? 'Hide virtual folders' : 'Show virtual folders';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-pressed', String(isVirtualFoldersShown()));
    // A press keeps the caret in the note being edited: with no folder context shown, editing goes on.
    button.onmousedown = (event) => event.preventDefault();
    button.onclick = () => toggleFolderContextFromTab();
}

/** The chip in the search input: shown while the active tab is narrowed to a folder. */
export function updateVirtualFolderIndicator() {
    const indicator = document.getElementById('virtual-folder-indicator');
    const label = document.getElementById('virtual-folder-indicator-label');
    if (!(indicator instanceof HTMLElement) || !(label instanceof HTMLElement)) {
        throw new Error('virtual-folder-indicator element missing');
    }
    if (moduleState.folder === '') {
        showSearchInputChip(indicator, { isShown: false });
        return;
    }
    label.textContent = moduleState.folder;
    label.title = `Notes in ${moduleState.folder}`;
    showSearchInputChip(indicator, { isShown: true });
}
