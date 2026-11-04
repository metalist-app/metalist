import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { actionRowHtml } from '../../modals/action-row.js';

// Dropped text files (docs/ready-to-build/files-shown-not-copied.md §5; the maintainer,
// 2026-11-03): a note with each one's text (the default, focused) or a file's card, one
// question for all dropped together. Shaped as the bookmarks drop's question
// (bookmarks-drop-choice-modal-service.js).

const MODAL_NAME = 'textDropChoiceModal';
const MODAL_ID = 'text-drop-choice-modal';
export const AS_NOTE = 'note';
export const AS_FILE = 'file';
// How many dropped files' names the question lists before "and N more".
const NAMES_LISTED = 3;

const moduleState = ApplicationState.createFields('text-drop-choice-modal-service', {
    activeDialog: null,
});

function ensureModalElement() {
    let modalElement = document.getElementById(MODAL_ID);
    if (modalElement instanceof HTMLElement) {
        return modalElement;
    }
    modalElement = document.createElement('div');
    modalElement.id = MODAL_ID;
    modalElement.className = 'modal text-drop-choice-modal';
    modalElement.style.display = 'none';
    modalElement.innerHTML = `
        <div class="modal-content text-drop-choice-modal-content">
            <button type="button" class="modal-close-button" aria-label="Close" title="Close (Esc)">×</button>
            <h2 class="text-drop-choice-title"></h2>
            <p class="text-drop-choice-files"></p>
            ${actionRowHtml({
                alternative: { id: 'text-drop-choice-file', label: 'File', disabled: false, attributes: [] },
                cancel: { id: 'text-drop-choice-cancel', label: 'Cancel', disabled: false, attributes: [] },
                main: {
                    id: 'text-drop-choice-note', label: 'Note', disabled: false, attributes: [],
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
        throw new Error(`Text drop choice ${selector} missing`);
    }
    return element;
}

// "notes.txt", "a.txt, b.md", "a.txt, b.txt, c.txt and 2 more".
function namesText(fileNames) {
    const listed = fileNames.slice(0, NAMES_LISTED).join(', ');
    const more = fileNames.length - NAMES_LISTED;
    if (more <= 0) return listed;
    return `${listed} and ${more} more`;
}

/** AS_NOTE, AS_FILE, or null when cancelled, for the dropped text files named. */
export function promptForTextDropChoice(fileNames) {
    if (!Array.isArray(fileNames) || fileNames.length === 0 || !fileNames.every((name) => typeof name === 'string' && name !== '')) {
        throw new Error('promptForTextDropChoice requires the files\' names');
    }
    if (moduleState.activeDialog !== null) {
        throw new Error('Text drop choice is already open');
    }
    if (ModeContext.modalStack.length > 0) {
        throw new Error('Cannot open the text drop choice while another modal is open');
    }
    const modalElement = ensureModalElement();
    requireElement(modalElement, '.text-drop-choice-title', HTMLElement).textContent = fileNames.length === 1 ? 'Text file' : `${fileNames.length} text files`;
    requireElement(modalElement, '.text-drop-choice-files', HTMLElement).textContent = namesText(fileNames);
    const noteButton = requireElement(modalElement, '#text-drop-choice-note', HTMLButtonElement);
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
                throw new Error('Text drop choice click missing target');
            }
            if (event.target === modalElement) {
                finish(null);
            } else if (event.target.closest('#text-drop-choice-note')) {
                finish(AS_NOTE);
            } else if (event.target.closest('#text-drop-choice-file')) {
                finish(AS_FILE);
            } else if (event.target.closest('#text-drop-choice-cancel') || event.target.closest('.modal-close-button')) {
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
            // Enter on a focused button presses it; elsewhere it makes the note, the default.
            if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement)) {
                event.preventDefault();
                event.stopPropagation();
                finish(AS_NOTE);
            }
        };
        moduleState.activeDialog = { resolve };
        modalElement.addEventListener('click', handleClick);
        document.addEventListener('keydown', handleKeyDown, { capture: true });
        window.setTimeout(() => {
            noteButton.focus();
        }, 0);
    });
}
