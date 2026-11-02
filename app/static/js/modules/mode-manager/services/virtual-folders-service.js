import { ApplicationState } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { escapeHtml } from '../../html-escape.js';
import { showSearchInputChip } from './search-input-chip-service.js';
import { isViewingReferenceSource } from './reference-source-navigation-service.js';
import { showContextMenu } from '../../context-menu/context-menu-service.js';
import { showErrorDialog } from '../../modals/error-dialog.js';
import { isVirtualFoldersShown, rememberVirtualFoldersShown } from './virtual-folders-state.js';
import { initVirtualFoldersWidth } from './virtual-folders-width.js';

export { isVirtualFoldersShown } from './virtual-folders-state.js';

// Virtual folders, an experiment (docs/ready-to-build/virtual-folders.md): a tag ending in
// `/` is a folder. With the Virtual Folders toggle on, a tree in the left margin lists every
// folder in the vault, each with its subfolders, and no notes (the maintainer, 2026-11-01:
// the column shows them); clicking a folder narrows the view to it and the folders below it
// (a chip in the search input). The notes column moves right to make room. Right-click: New
// Folder, Rename Folder, Delete Folder; a folder dragged onto another moves into it. The
// server keeps the filters in its memory only (app/services/virtual_folders.py); a renamed,
// moved or deleted folder changes the tags on the notes.

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

const moduleState = ApplicationState.createFields('virtual-folders-service', {
    // The active tab's filter, as the server last sent it: a folder, or '' for none.
    folder: '',
    // The folders the server last sent, by path.
    folders: Object.freeze([]),
    // How many notes clicking each folder shows, with the folders below it, in the view's
    // search (the maintainer, 2026-11-01); the top's under ''.
    noteCounts: Object.freeze({}),
    // Whether a view's folders have been read yet: the tree is drawn only from them.
    hasReadFolders: false,
    // The folders the person opened in the tree, by path.
    openPaths: Object.freeze([]),
    // Whether the top, `/`, is open: closed, the tree is one line (the maintainer, 2026-11-01).
    isRootOpen: true,
    // Whether `/` was clicked to show every note: only then does it look chosen (the
    // maintainer, 2026-11-01: a folder clicked again shows every note with nothing chosen).
    isRootClicked: false,
    // New Folder: held here until a folder is moved into it (no note carries its tag yet).
    newPaths: Object.freeze([]),
    // The folder being dragged ('' when none).
    draggedPath: '',
});

// Wired by the command palette: setFilter(folder) narrows the view to it;
// confirm(context) asks (ConfirmationModal); askName(form) asks a name (FolderNameModal);
// askDeleteFolder(form) asks whether to delete a folder, and its notes (DeleteFolderModal);
// afterChange() shows the view again once tags changed.
const handlers = ApplicationState.createFields('virtual-folders-handlers', {
    setFilter: null,
    confirm: null,
    askName: null,
    askDeleteFolder: null,
    afterChange: null,
});

/** The palette's ways to filter, open, ask and refresh (set once at startup). */
export function wireVirtualFolders(wiring) {
    for (const name of ['setFilter', 'confirm', 'askName', 'askDeleteFolder', 'afterChange']) {
        if (typeof wiring[name] !== 'function') {
            throw new Error(`wireVirtualFolders requires ${name}`);
        }
        handlers[name] = wiring[name];
    }
    rememberVirtualFoldersShown(window.localStorage.getItem(SHOWN_KEY) === SHOWN);
    initVirtualFoldersWidth();
    // The first view's folders can be read before this runs, the tree drawn hidden: drawn again
    // with the remembered choice, so it shows and its button says so without waiting for a
    // refresh. Read after, they draw it themselves.
    if (moduleState.hasReadFolders) render();
}

export function activeVirtualFolder() {
    return moduleState.folder;
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
        render();
        return;
    }
    const answer = await NotesAPI.listVirtualFolders();
    if (typeof answer.folder !== 'string' || !Array.isArray(answer.folders)
        || answer.noteCounts === null || typeof answer.noteCounts !== 'object') {
        throw new Error('Virtual folders answer malformed');
    }
    // A folder newly chosen shows in the tree; a refresh leaves what the person closed closed.
    const isNewlyChosen = answer.folder !== moduleState.folder;
    remember('folder', answer.folder);
    remember('folders', Object.freeze(answer.folders));
    remember('noteCounts', Object.freeze({ ...answer.noteCounts }));
    remember('hasReadFolders', true);
    // A new folder stays new until something is in it: a note carrying its tag, or a folder below it.
    const known = answer.folders;
    remember('newPaths', Object.freeze(moduleState.newPaths.filter((path) => !known.some((knownPath) => knownPath.startsWith(path)))));
    if (isNewlyChosen && answer.folder.endsWith(FOLDER_MARK)) openTo(answer.folder);
    render();
}

// Whether the tree shows, remembered by this browser (the maintainer, 2026-11-01: the choice
// stays across logins). Not a vault preference: a MetaList that doesn't know a stored
// preference refuses to load them, so dropping the experiment would leave a vault older
// MetaLists can't open.
const SHOWN_KEY = 'metalist.virtual_folders.shown';
const SHOWN = 'true';
const HIDDEN = 'false';

/** The toggle: show or hide the tree. An import shows it too. */
export function setVirtualFoldersShown(isShown) {
    window.localStorage.setItem(SHOWN_KEY, isShown ? SHOWN : HIDDEN);
    rememberVirtualFoldersShown(isShown);
    render();
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
        <div class="virtual-folder${isFiltered ? ' is-filtered' : ''}${isNew ? ' is-new' : ''}">
            <button type="button" class="virtual-folder-row interactive" data-virtual-folder="${escapeHtml(path)}" draggable="${!isNew}"
                style="--virtual-folder-depth:${depth}"${isInnermost ? '' : ` aria-expanded="${isOpen}"`} title="${escapeHtml(path)}">
                ${isInnermost
                    ? '<span class="virtual-folder-arrow" aria-hidden="true"></span>'
                    : `<span class="virtual-folder-arrow" data-virtual-folder-arrow aria-hidden="true">${isOpen ? '▾' : '▸'}</span>`}
                <span class="virtual-folder-icon" aria-hidden="true"></span>
                <span class="virtual-folder-name">${escapeHtml(node.name)}</span>
                ${countHtml(isNew ? NO_NOTES : noteCountOf(path))}
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

function countHtml(count) {
    return `<span class="virtual-folder-count">(${count})</span>`;
}

// The top, `/`, over every folder (the maintainer, 2026-11-01): clicking it shows every note
// again, whatever folder the view was narrowed to. It looks chosen only once clicked
// (isRootClicked), while no folder is.
function rootHtml(built) {
    const isChosen = moduleState.isRootClicked && moduleState.folder === TOP;
    const isOpen = moduleState.isRootOpen;
    return `
        <div class="virtual-folder${isChosen ? ' is-filtered' : ''}">
            <button type="button" class="virtual-folder-row interactive" data-virtual-folder-root
                style="--virtual-folder-depth:0" aria-expanded="${isOpen}" title="Every folder: show every note">
                <span class="virtual-folder-arrow" data-virtual-folder-arrow aria-hidden="true">${isOpen ? '▾' : '▸'}</span>
                <span class="virtual-folder-icon" aria-hidden="true"></span>
                <span class="virtual-folder-name">/</span>
                ${countHtml(noteCountOf(TOP))}
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
        // Chosen already, clicked again: it looks unchosen, as a folder does (the maintainer,
        // 2026-11-01); the view shows every note either way.
        const isChosenAgain = moduleState.isRootClicked && moduleState.folder === TOP && !isViewingReferenceSource();
        remember('isRootClicked', !isChosenAgain);
        render();
        if (moduleState.folder !== '' || isViewingReferenceSource()) void handlers.setFilter('');
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
    remember('isRootClicked', false);
    if (moduleState.folder === path && !isViewingReferenceSource()) {
        void handlers.setFilter(TOP);
        return;
    }
    if (!moduleState.openPaths.includes(path)) toggleOpen(path);
    // Clicked from a reference view: back to the folders' view, narrowed to this one.
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
    // The top (`/` or the tree's empty space), or the folder under the pointer.
    const folderRow = event.target.closest('[data-virtual-folder]');
    const row = folderRow === null ? event.target.closest('[data-virtual-folder-root]') : folderRow;
    const into = folderRow === null ? TOP : folderRow.dataset.virtualFolder;
    if (into.startsWith(dragged) || into === parentOf(dragged)) return null;
    return { into, row };
}

function clearDropTarget() {
    for (const marked of document.querySelectorAll(`#${TREE_ID} .${DROP_CLASS}`)) marked.classList.remove(DROP_CLASS);
}

function onDragOver(event) {
    const target = dropTargetOf(event);
    clearDropTarget();
    if (target === null) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    (target.row === null ? requireTree() : target.row).classList.add(DROP_CLASS);
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
    if (isVirtualFoldersShown()) {
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
    button.onclick = () => setVirtualFoldersShown(!isVirtualFoldersShown());
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
