// Error dialogs (docs/ui/modals.md, "Errors"): an action the user took that did not happen is
// told in a small dialog over the one they were in, never written into that dialog's layout.
// - The dialog underneath stays open with everything entered, and nothing in it moves.
// - One error dialog lists every problem; it has no button: ×, Escape or a click outside
//   closes it.
// - Closing it puts focus back in the first field at fault; each field at fault keeps a red
//   outline (no size changes) until its value changes.

import { ApplicationState } from '../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-manager/mode-context.js';
import { FieldInputRejected } from '../expected-errors.js';

const MODAL_NAME = 'errorDialog';
const ELEMENT_ID = 'error-dialog';
const FIELD_AT_FAULT_CLASS = 'field-at-fault';

const errorDialogState = ApplicationState.createFields('error-dialog', {
    // { element, problems, resolve, close, returnFocus } while one shows.
    active: null,
});

function validateProblems(problems) {
    if (!Array.isArray(problems) || problems.length === 0) {
        throw new Error('An error dialog needs at least one problem');
    }
    for (const problem of problems) {
        if (problem === null || typeof problem !== 'object') {
            throw new Error('An error dialog problem must be an object');
        }
        if (typeof problem.text !== 'string' || problem.text.length === 0) {
            throw new Error('An error dialog problem needs text');
        }
        if (problem.fieldId !== null && (typeof problem.fieldId !== 'string' || problem.fieldId.length === 0)) {
            throw new Error('An error dialog problem names its field by id, or null');
        }
    }
}

function buildElement(problems) {
    const layer = document.createElement('div');
    layer.id = ELEMENT_ID;
    layer.className = 'modal error-dialog-layer';
    const dialog = document.createElement('div');
    dialog.className = 'modal-content error-dialog';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'error-dialog-text');
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'modal-close-button';
    close.setAttribute('aria-label', 'Close');
    close.title = 'Close (Esc)';
    close.textContent = '×';
    dialog.appendChild(close);
    const text = document.createElement(problems.length === 1 ? 'p' : 'ul');
    text.id = 'error-dialog-text';
    text.className = 'error-dialog-text';
    // Plain text: a message can quote what the user typed.
    if (problems.length === 1) {
        text.textContent = problems[0].text;
    } else {
        for (const problem of problems) {
            const item = document.createElement('li');
            item.textContent = problem.text;
            text.appendChild(item);
        }
    }
    dialog.appendChild(text);
    layer.appendChild(dialog);
    return { layer, dialog, close };
}

// The red outline stays until the field's value changes.
function markFieldAtFault(field) {
    field.classList.add(FIELD_AT_FAULT_CLASS);
    const clear = () => {
        field.classList.remove(FIELD_AT_FAULT_CLASS);
        field.removeEventListener('input', clear);
        field.removeEventListener('change', clear);
    };
    field.addEventListener('input', clear);
    field.addEventListener('change', clear);
}

function closeErrorDialog() {
    const active = errorDialogState.active;
    if (active === null) {
        throw new Error('No error dialog is open');
    }
    window.removeEventListener('keydown', handleKeyDown, true);
    document.removeEventListener('focusin', keepFocusInside, true);
    active.element.remove();
    ModeContext.removeModal(MODAL_NAME);
    errorDialogState.active = null;
    const fields = active.problems
        .filter((problem) => problem.fieldId !== null)
        .map((problem) => document.getElementById(problem.fieldId));
    for (const field of fields) {
        if (!(field instanceof HTMLElement)) {
            throw new Error('A field at fault is missing from the dialog underneath');
        }
        markFieldAtFault(field);
    }
    if (fields.length > 0) {
        fields[0].focus();
    } else if (active.returnFocus instanceof HTMLElement && active.returnFocus.isConnected) {
        // Nothing at fault: focus goes back where it was.
        active.returnFocus.focus();
    }
    active.resolve();
}

// Keys belong to the error dialog while it shows: Escape closes it, Tab stays on its ×, and
// nothing reaches the dialog underneath.
function handleKeyDown(event) {
    const active = errorDialogState.active;
    if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeErrorDialog();
        return;
    }
    if (event.key === 'Tab') {
        event.preventDefault();
        active.close.focus();
    }
    event.stopPropagation();
}

// Focus stays in the error dialog while it shows, even when the dialog underneath moves
// focus after a render of its own.
function keepFocusInside(event) {
    const active = errorDialogState.active;
    if (!active.element.contains(event.target)) {
        active.close.focus();
    }
}

export function isErrorDialogOpen() {
    return errorDialogState.active !== null;
}

// problems: [{ text, fieldId }], fieldId null when no one field is at fault. Resolves when
// the dialog closes.
export function showErrorDialog(problems) {
    validateProblems(problems);
    if (errorDialogState.active !== null) {
        throw new Error('An error dialog is already open');
    }
    const { layer, dialog, close } = buildElement(problems);
    return new Promise((resolve) => {
        errorDialogState.active = { element: layer, problems, resolve, close, returnFocus: document.activeElement };
        ModeContext.pushModal(MODAL_NAME);
        close.addEventListener('click', () => closeErrorDialog());
        layer.addEventListener('click', (event) => {
            if (!dialog.contains(event.target)) {
                closeErrorDialog();
            }
        });
        window.addEventListener('keydown', handleKeyDown, true);
        document.addEventListener('focusin', keepFocusInside, true);
        document.body.appendChild(layer);
        layer.style.display = 'block';
        close.focus();
    });
}

// A lasting problem's dialog (floating-messages.js): it closes when the problem ends, so the
// caller gets a function that closes it, if it still shows.
export function showErrorDialogClosedBy(problems) {
    const done = showErrorDialog(problems);
    const element = errorDialogState.active.element;
    return {
        done,
        close: () => {
            if (errorDialogState.active !== null && errorDialogState.active.element === element) {
                closeErrorDialog();
            }
        },
    };
}

// A dialog that could not open has nothing to offer: the error dialog says why, and closing it
// runs closeDialog. Opening is not held up while it shows, so what opened the dialog (the AI's
// menu request, a palette command) learns at once that it did not open.
export function showOpenFailure(error, closeDialog) {
    if (typeof closeDialog !== 'function') {
        throw new Error('showOpenFailure requires the function that closes the dialog');
    }
    void showErrorDialogFor(error, null).then(closeDialog);
}

// The field a refusal names, or null.
export function failureFieldId(error) {
    if (error instanceof FieldInputRejected) {
        return error.fieldId;
    }
    return null;
}

// The message of a refused or failed action (expected-errors.js lets only those through).
export function showErrorDialogFor(error, fieldId) {
    if (!(error instanceof Error) || error.message.length === 0) {
        throw new Error('showErrorDialogFor requires an error with a message');
    }
    return showErrorDialog([{ text: error.message, fieldId }]);
}
