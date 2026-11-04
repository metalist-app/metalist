// A password's eye (docs/ui/content-formatting.md, @password; the maintainer, 2026-11-03): it
// shows the value until the next thing the user does: the eye again, a click anywhere else, any
// key, leaving the window. Clicking a value copies it (mouse-events.js); copy buttons were tried
// on every value and dropped (2026-11-04): clicking the value is what the maintainer wants.
//
// The eye is added here, in MetaList's page and its floating windows, never by the server:
// exports and prints have none, and the AI sees none.

import { ApplicationState } from '../../application-state.js';

// What the server shows for a password (content_formatting.py, CREDENTIAL_MASK).
const CREDENTIAL_MASK_LENGTH = 8;
export const CREDENTIAL_MASK = '•'.repeat(CREDENTIAL_MASK_LENGTH);
const HIDDEN_PASSWORD_LABEL = 'Hidden password';

const PASSWORD_VALUE_SELECTOR = '.meta-credential-password .meta-credential-value';
export const VALUE_BUTTONS_SELECTOR = '.meta-value-buttons';
const VALUE_BUTTON_SELECTOR = '.meta-value-button';
const SHOWN_CLASS = 'meta-credential-shown';
// A password's value in MetaList: monospaced, its eye right after it, where it shifts while the
// password shows (the maintainer, 2026-11-04: next to the dots, which row an eye is on takes no
// looking; a fixed space and a column at the row's edge were tried before).
const PASSWORD_VALUE_CLASS = 'meta-credential-monospace';
// Its row says so itself: main.css avoids :has() in notes (it crashed Chrome folding a tall note).
const WITH_EYE_ROW_CLASS = 'meta-credential-with-eye';
const EYE_SELECTOR = '[data-value-action="show"]';
const FLOATING_WINDOW_SELECTOR = '.floating-note-window';
// Rendered notes being edited hold the editor, not values to decorate.
const EDITING_SELECTOR = '.note.editing, [contenteditable="true"]';

const EYE_ICON = '<svg class="meta-value-button-icon meta-value-button-eye-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    + '<path fill="currentColor" d="M12 5C6.5 5 2.7 9.3 1.5 12c1.2 2.7 5 7 10.5 7s9.3-4.3 10.5-7C21.3 9.3 17.5 5 12 5Zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9Zm0-7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z"/></svg>'
    + '<svg class="meta-value-button-icon meta-value-button-eye-off-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    + '<path fill="currentColor" d="M2.3 3.7 3.7 2.3l18 18-1.4 1.4-3.4-3.4A11.4 11.4 0 0 1 12 19C6.5 19 2.7 14.7 1.5 12a13 13 0 0 1 4.1-5L2.3 3.7ZM12 5c5.5 0 9.3 4.3 10.5 7a13.2 13.2 0 0 1-3.3 4.4l-3-3A4.5 4.5 0 0 0 10.6 7.8L8.5 5.6C9.6 5.2 10.8 5 12 5Zm-4.4 5 1.6 1.6a2.5 2.5 0 0 0 3.2 3.2l1.6 1.6A4.5 4.5 0 0 1 7.6 10Z"/></svg>';

const moduleState = ApplicationState.createFields('value-buttons-service', {
    // The rows whose password is shown, by where they are (rowKey), kept while the view redraws
    // under it: in memory only, never saved. Anything the user does next hides them.
    shownRows: Object.freeze([]),
});

// Where a value is: the note, embed and link ids around it, out through a floating window.
function rowKey(element) {
    const parts = [];
    let node = element;
    while (node) {
        for (let current = node; current; current = current.parentElement) {
            const { noteId, embedNoteId, refNoteId, refOccurrence, floatingNoteId } = current.dataset;
            for (const part of [noteId, embedNoteId, refNoteId, refOccurrence, floatingNoteId]) {
                if (part !== undefined) parts.push(part);
            }
        }
        const root = node.getRootNode();
        node = root instanceof ShadowRoot ? root.host : null;
    }
    return parts.join('/');
}

function makeButton({ action, label, iconHtml }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'meta-value-button';
    button.dataset.valueAction = action;
    button.setAttribute('aria-label', label);
    button.title = label;
    button.innerHTML = iconHtml;
    return button;
}

function makeEyeButtons() {
    const buttons = document.createElement('span');
    buttons.className = 'meta-value-buttons';
    buttons.contentEditable = 'false';
    const eye = makeButton({ action: 'show', label: 'Show password', iconHtml: EYE_ICON });
    eye.setAttribute('aria-pressed', 'false');
    buttons.append(eye);
    return buttons;
}

function setPasswordShown(value, eye, shown) {
    value.classList.toggle(SHOWN_CLASS, shown);
    eye.setAttribute('aria-pressed', String(shown));
    const label = shown ? 'Hide password' : 'Show password';
    eye.setAttribute('aria-label', label);
    eye.title = label;
    if (shown) {
        value.textContent = value.dataset.copyValue;
        value.removeAttribute('role');
        value.removeAttribute('aria-label');
        return;
    }
    value.textContent = CREDENTIAL_MASK;
    value.setAttribute('role', 'img');
    value.setAttribute('aria-label', HIDDEN_PASSWORD_LABEL);
}

function decoratePassword(value) {
    if (value.closest(EDITING_SELECTOR) || value.hasAttribute('data-redacted')) return;
    const next = value.nextElementSibling;
    if (next && next.matches(VALUE_BUTTONS_SELECTOR)) return;
    if (typeof value.dataset.copyValue !== 'string') {
        throw new Error('Credential value missing data-copy-value attribute');
    }
    const buttons = makeEyeButtons();
    value.classList.add(PASSWORD_VALUE_CLASS);
    value.closest('.meta-credential').classList.add(WITH_EYE_ROW_CLASS);
    value.after(buttons);
    if (moduleState.shownRows.includes(rowKey(value))) {
        setPasswordShown(value, buttons.querySelector(EYE_SELECTOR), true);
    }
}

export function decorateValueButtons(root) {
    if (root.matches?.(PASSWORD_VALUE_SELECTOR)) decoratePassword(root);
    for (const value of root.querySelectorAll(PASSWORD_VALUE_SELECTOR)) decoratePassword(value);
}

// Notes are drawn and redrawn all the time (views, embeds, saves): every drawn value is
// decorated as it arrives, in the page and in each floating window's own tree.
export function observeValueButtons(root) {
    decorateValueButtons(root);
    new MutationObserver(records => {
        for (const record of records) {
            for (const added of record.addedNodes) {
                if (added instanceof Element && !added.matches(VALUE_BUTTONS_SELECTOR)) decorateValueButtons(added);
            }
        }
    }).observe(root, { childList: true, subtree: true });
}

function hideShownPasswords() {
    if (moduleState.shownRows.length === 0) return;
    moduleState.shownRows = Object.freeze([]);
    const floatingTrees = [...document.querySelectorAll(FLOATING_WINDOW_SELECTOR)].map(windowElement => windowElement.shadowRoot);
    for (const root of [document, ...floatingTrees]) {
        for (const value of root.querySelectorAll(`.${SHOWN_CLASS}`)) {
            setPasswordShown(value, value.nextElementSibling.querySelector(EYE_SELECTOR), false);
        }
    }
}

// The eye an event is on, in a floating window's own tree too; null for anything else.
function eyeOf(event) {
    const target = event.composedPath()[0];
    if (!(target instanceof Element)) return null;
    return target.closest(EYE_SELECTOR);
}

// A press anywhere hides a shown password, but on an eye, whose click shows or hides (and hides
// any other). It hides once the press is over and its click has run: hidden at once, the row
// would shrink and move what the press is on (the value it copies, the rest of a link) from
// under the pointer.
function hideOnPointerUp(event) {
    if (eyeOf(event) !== null) return;
    window.setTimeout(hideShownPasswords);
}

// Any key hides it (Escape too), but Enter or Space pressing an eye, which toggles itself.
function hideOnKeyDown(event) {
    if ((event.key === 'Enter' || event.key === ' ') && eyeOf(event) !== null) return;
    hideShownPasswords();
}

export function startValueButtons() {
    observeValueButtons(document.body);
    document.addEventListener('pointerup', hideOnPointerUp, { capture: true });
    document.addEventListener('keydown', hideOnKeyDown, { capture: true });
    // Clicking into another app or window is clicking elsewhere too.
    window.addEventListener('blur', hideShownPasswords);
}

// A click on a password's eye: true when it was one (the click is then used up). target: the
// element clicked, inside a floating window's own tree too.
export function handleValueButtonClick(event, target) {
    if (!(target instanceof Element)) return false;
    const button = target.closest(VALUE_BUTTON_SELECTOR);
    if (!button) return false;
    event.preventDefault();
    event.stopPropagation();
    if (button.dataset.valueAction !== 'show') throw new Error(`Unknown value button: ${button.dataset.valueAction}`);
    const value = button.closest(VALUE_BUTTONS_SELECTOR).previousElementSibling;
    if (!value?.matches(PASSWORD_VALUE_SELECTOR)) throw new Error('Show button without a password');
    const key = rowKey(value);
    const shown = !moduleState.shownRows.includes(key);
    // One shown at a time: an eye pressed by its key leaves no other shown either.
    hideShownPasswords();
    if (shown) moduleState.shownRows = Object.freeze([key]);
    setPasswordShown(value, button, shown);
    return true;
}
