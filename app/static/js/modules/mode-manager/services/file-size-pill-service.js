// The File size order shows what it sorts by (docs/ui/command-palette.md, Sort Order): each
// note's total beside it, and each file's size on its card. The card's size is drawn from an
// attribute, so it is no text of the note: find and copy never see it.

import { ApplicationState } from '../../application-state.js';
import { formatByteSize } from '../../byte-sizes.js';

const TOTAL_CLASS = 'note-file-total';
const CARD_HEADER_SELECTOR = '.note-file-reference-header';
const CARD_SIZE_ATTRIBUTE = 'data-file-size';
const TOTALS_IN_NOTE_CLASS = 'file-totals-in-note';
// .note-file-total's distance from its note.
const TOTAL_MARGIN_PX = 8;
const moduleState = ApplicationState.createFields('file-size-pill-service', {
    marginObserver: null,
});

function removePills(notesContainer) {
    for (const total of notesContainer.querySelectorAll(`.${TOTAL_CLASS}`)) {
        total.remove();
    }
    for (const header of notesContainer.querySelectorAll(`[${CARD_SIZE_ATTRIBUTE}]`)) {
        header.removeAttribute(CARD_SIZE_ATTRIBUTE);
    }
}

function createTotalPill(sizeBytes) {
    const pill = document.createElement('div');
    pill.className = TOTAL_CLASS;
    const size = document.createElement('span');
    size.textContent = formatByteSize(sizeBytes);
    size.title = 'Total size of this note\'s files';
    pill.append(size);
    return pill;
}

// A total sits in the margin to its note's right when it fits before the controls there; a
// panel or a narrow window takes that margin, and the totals move inside their notes. Measured,
// because how much margin is left depends on the window and on both panels' dragged widths.
function placeTotals() {
    const notesContainer = document.getElementById('notes-container');
    const totals = Array.from(notesContainer.querySelectorAll(`.${TOTAL_CLASS} > span`));
    if (totals.length === 0) {
        return;
    }
    const controls = document.querySelector('.global-controls');
    if (!controls) {
        throw new Error('.global-controls not found');
    }
    const widest = Math.max(...totals.map((total) => total.getBoundingClientRect().width));
    const marginEnd = notesContainer.getBoundingClientRect().right + TOTAL_MARGIN_PX + widest;
    notesContainer.classList.toggle(TOTALS_IN_NOTE_CLASS, marginEnd > controls.getBoundingClientRect().left);
}

function keepTotalsPlaced(notesContainer) {
    if (moduleState.marginObserver === null) {
        // In the next frame: moving the totals changes the layout this observer is reporting.
        const observer = new ResizeObserver(() => requestAnimationFrame(placeTotals));
        observer.observe(document.documentElement);
        observer.observe(notesContainer);
        moduleState.marginObserver = observer;
    }
    placeTotals();
}

export function rebuildFileSizePills(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') {
        throw new Error('rebuildFileSizePills requires snapshot object');
    }
    const fileSizes = snapshot.fileSizes;
    if (!fileSizes || typeof fileSizes.rootTotals !== 'object' || typeof fileSizes.files !== 'object') {
        throw new Error('Snapshot missing fileSizes');
    }
    const notesContainer = document.getElementById('notes-container');
    if (!notesContainer) {
        throw new Error('notes-container not found');
    }
    removePills(notesContainer);
    for (const [rootId, sizeBytes] of Object.entries(fileSizes.rootTotals)) {
        const rootElement = notesContainer.querySelector(`.note[data-note-id="${rootId}"]`);
        if (!(rootElement instanceof HTMLElement)) {
            throw new Error(`Visible root note element missing for its file size: ${rootId}`);
        }
        rootElement.prepend(createTotalPill(sizeBytes));
    }
    for (const card of notesContainer.querySelectorAll('[data-file-ref-id]')) {
        const header = card.querySelector(CARD_HEADER_SELECTOR);
        if (header !== null && Object.hasOwn(fileSizes.files, card.dataset.fileRefId)) {
            header.setAttribute(CARD_SIZE_ATTRIBUTE, formatByteSize(fileSizes.files[card.dataset.fileRefId]));
        }
    }
    keepTotalsPlaced(notesContainer);
}
