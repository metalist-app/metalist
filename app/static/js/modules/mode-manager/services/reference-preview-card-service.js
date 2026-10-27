import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { hydrateImageFilePreviews } from './file-image-preview-service.js';
import { hydrateExcalidrawPreviews } from '../../excalidraw/excalidraw-preview-service.js';
import { hydrateRemoteImageProxies } from './remote-image-proxy-service.js';
import { queueMermaidDiagramRendering } from './mermaid-render-service.js';
import { serverRenderedHtml } from '../../server-rendered-html.js';

// A reference's preview card (docs/ui/references.md, "Preview"): the top of the
// note it names as the list draws it (Markdown, headings, colours, checkboxes,
// pictures; passwords hidden), cut at the card's height with a fade. One card
// shows at a time, for the `[[` suggestion list's highlighted note or for a link
// the pointer rests on. It floats and takes no pointer: nothing under it moves.
// Its note is drawn inside a shadow root with the list's stylesheet, as a
// floating window's is, so the list's rules for notes don't reach the card.

const STYLESHEETS = ['/static/css/main.css', '/static/css/reference-preview.css'];
// What asks for the card: only that asker hides it.
export const PREVIEW_OWNERS = Object.freeze({ suggestions: 'suggestions', hover: 'hover' });

const moduleState = ApplicationState.createFields('reference-preview-card-service', {
    card: null,
    clip: null,
    tree: null,
    stylesLoaded: null,
    owner: null,
    noteId: null,
    place: null,
    serial: 0,
});

function setState(field, value) {
    if (!stateValuesEqual(moduleState[field], value)) moduleState[field] = value;
}

// Places the card and fades its bottom when the note goes on past it.
function layOut() {
    const { card, clip, tree, place } = moduleState;
    if (card === null || card.hidden || place === null) return;
    clip.classList.toggle('is-cut', tree.offsetHeight > clip.clientHeight);
    place(card);
}

function createCard() {
    const card = document.createElement('div');
    card.className = 'reference-preview';
    card.setAttribute('aria-hidden', 'true');
    card.hidden = true;
    const shadow = card.attachShadow({ mode: 'open' });
    const loads = STYLESHEETS.map((href) => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        shadow.appendChild(link);
        return new Promise((resolve, reject) => {
            link.addEventListener('load', resolve, { once: true });
            link.addEventListener('error', () => reject(new Error(`Preview card stylesheet failed to load: ${href}`)), { once: true });
        });
    });
    const clip = document.createElement('div');
    clip.className = 'reference-preview-clip';
    const tree = document.createElement('div');
    tree.className = 'reference-preview-tree';
    clip.appendChild(tree);
    shadow.appendChild(clip);
    document.body.appendChild(card);
    // Pictures and diagrams arrive after the card shows: it is placed again as it grows.
    new ResizeObserver(layOut).observe(tree);
    setState('card', card);
    setState('clip', clip);
    setState('tree', tree);
    setState('stylesLoaded', Promise.all(loads));
}

function fill(tree, html) {
    tree.innerHTML = serverRenderedHtml(html);
    for (const editable of tree.querySelectorAll('[contenteditable]')) editable.setAttribute('contenteditable', 'false');
    for (const control of tree.querySelectorAll('button, input, textarea, select')) control.setAttribute('disabled', '');
    hydrateImageFilePreviews(tree);
    void hydrateExcalidrawPreviews(tree);
    hydrateRemoteImageProxies(tree);
    void queueMermaidDiagramRendering(tree);
}

// Shows `noteId`'s card for `owner`, placed by `place(card)`; replaces any card
// showing. A note that is not there (deleted, or a file's UUID) shows none.
export async function showReferencePreview(noteId, place, owner) {
    if (typeof noteId !== 'string' || noteId === '' || typeof place !== 'function' || !Object.hasOwn(PREVIEW_OWNERS, owner)) {
        throw new Error('showReferencePreview requires a note id, a place function and an owner');
    }
    if (moduleState.card === null) createCard();
    const serial = moduleState.serial + 1;
    setState('serial', serial);
    setState('owner', owner);
    setState('noteId', noteId);
    setState('place', place);
    const preview = await NotesAPI.getReferencePreview(noteId);
    await moduleState.stylesLoaded;
    // Hidden, or replaced by another card, while it loaded.
    if (moduleState.serial !== serial) return;
    if (preview.status !== 'ready') {
        hideReferencePreview(owner);
        return;
    }
    fill(moduleState.tree, preview.html);
    moduleState.card.dataset.previewNoteId = noteId;
    moduleState.card.style.left = '0px';
    moduleState.card.style.top = '0px';
    moduleState.card.hidden = false;
    layOut();
}

// Hides the card if `owner` showed it (a hover never hides the list's card).
export function hideReferencePreview(owner) {
    if (!Object.hasOwn(PREVIEW_OWNERS, owner)) {
        throw new Error(`Unknown preview owner: ${owner}`);
    }
    if (moduleState.owner !== owner) return;
    setState('serial', moduleState.serial + 1);
    setState('owner', null);
    setState('noteId', null);
    setState('place', null);
    if (moduleState.card !== null) moduleState.card.hidden = true;
}

// Places the card again where its owner wants it now (the list moved with a scroll).
export function placeReferencePreview() {
    layOut();
}
