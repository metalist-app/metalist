import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { actionRowHtml } from '../../modals/action-row.js';

// A dropped bookmarks export (docs/ready-to-build/bookmark-import.md §5; the maintainer,
// 2026-11-02): import the bookmarks (the default) or keep the file as a file, wherever it is
// dropped. As the image drop's choice (image-file-insert-choice-modal-service.js) asks.

const MODAL_NAME = 'bookmarksDropChoiceModal';
const MODAL_ID = 'bookmarks-drop-choice-modal';
export const IMPORT_BOOKMARKS = 'import';
export const KEEP_AS_FILE = 'keep';

const moduleState = ApplicationState.createFields('bookmarks-drop-choice-modal-service', {
    activeDialog: null,
});

function ensureModalElement() {
    let modalElement = document.getElementById(MODAL_ID);
    if (modalElement instanceof HTMLElement) {
        return modalElement;
    }
    modalElement = document.createElement('div');
    modalElement.id = MODAL_ID;
    modalElement.className = 'modal bookmarks-drop-choice-modal';
    modalElement.style.display = 'none';
    modalElement.innerHTML = `
        <div class="modal-content bookmarks-drop-choice-modal-content">
            <button type="button" class="modal-close-button" aria-label="Close" title="Close (Esc)">×</button>
            <h2>Bookmarks file</h2>
            <p class="bookmarks-drop-choice-file"></p>
            ${actionRowHtml({
                alternative: { id: 'bookmarks-drop-choice-keep', label: 'Keep as File', disabled: false, attributes: [] },
                cancel: { id: 'bookmarks-drop-choice-cancel', label: 'Cancel', disabled: false, attributes: [] },
                main: {
                    id: 'bookmarks-drop-choice-import', label: 'Import Bookmarks', disabled: false, attributes: [],
                    isDestructive: false, isEnterAction: false, type: 'button',
                },
                rowClass: '',
            })}
        </div>
    `;
    document.body.appendChild(modalElement);
    return modalElement;
}

function requireElement(modalElement, selector, type) {
    const element = modalElement.querySelector(selector);
    if (!(element instanceof type)) {
        throw new Error(`Bookmarks drop choice ${selector} missing`);
    }
    return element;
}

/** IMPORT_BOOKMARKS, KEEP_AS_FILE, or null when cancelled. */
export function promptForBookmarksDropChoice(fileName) {
    if (typeof fileName !== 'string' || fileName === '') {
        throw new Error('promptForBookmarksDropChoice requires the file\'s name');
    }
    if (moduleState.activeDialog !== null) {
        throw new Error('Bookmarks drop choice is already open');
    }
    if (ModeContext.modalStack.length > 0) {
        throw new Error('Cannot open the bookmarks drop choice while another modal is open');
    }
    const modalElement = ensureModalElement();
    requireElement(modalElement, '.bookmarks-drop-choice-file', HTMLElement).textContent = fileName;
    const importButton = requireElement(modalElement, '#bookmarks-drop-choice-import', HTMLButtonElement);
    modalElement.style.display = 'block';
    ModeContext.pushModal(MODAL_NAME);

    return new Promise((resolve) => {
        const finish = (value) => {
            if (moduleState.activeDialog === null) {
                return;
            }
            modalElement.removeEventListener('click', handleClick);
            document.removeEventListener('keydown', handleKeyDown, { capture: true });
            modalElement.style.display = 'none';
            ModeContext.removeModal(MODAL_NAME);
            moduleState.activeDialog = null;
            resolve(value);
        };
        const handleClick = (event) => {
            if (!(event.target instanceof Element)) {
                throw new Error('Bookmarks drop choice click missing target');
            }
            if (event.target === modalElement) {
                finish(null);
            } else if (event.target.closest('#bookmarks-drop-choice-import')) {
                finish(IMPORT_BOOKMARKS);
            } else if (event.target.closest('#bookmarks-drop-choice-keep')) {
                finish(KEEP_AS_FILE);
            } else if (event.target.closest('#bookmarks-drop-choice-cancel') || event.target.closest('.modal-close-button')) {
                finish(null);
            }
        };
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                finish(null);
                return;
            }
            // Enter on a focused button presses it; elsewhere it imports, the default.
            if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement)) {
                event.preventDefault();
                event.stopPropagation();
                finish(IMPORT_BOOKMARKS);
            }
        };
        moduleState.activeDialog = { resolve };
        modalElement.addEventListener('click', handleClick);
        document.addEventListener('keydown', handleKeyDown, { capture: true });
        window.setTimeout(() => {
            importButton.focus();
        }, 0);
    });
}
