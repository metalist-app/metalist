// Copy and show buttons on copyable values (docs/ui/content-formatting.md, @password and
// @copyable; the maintainer, 2026-11-03). Every @copyable, @username and @password value gets a
// clipboard button that copies it; a password also gets an eye that shows its value until the
// next thing the user does: the eye again, a click anywhere else, any key, leaving the window.
// Clicking the value itself copies nothing: it does what a click anywhere else in the note does.
// Before, a click on the value copied it, and nothing on screen said so.
//
// The buttons are added here, in MetaList's page and its floating windows, never by the server:
// exports and prints keep their own click to copy (html_export.py), and the AI sees no buttons.

import { copyTextToClipboard, normalizeCopyableText } from '../events/mouse-events.js';
import * as Logger from '../mode-logger.js';
import { ApplicationState } from '../../application-state.js';

// What the server shows for a password (content_formatting.py, CREDENTIAL_MASK).
const CREDENTIAL_MASK_LENGTH = 8;
export const CREDENTIAL_MASK = '•'.repeat(CREDENTIAL_MASK_LENGTH);
const HIDDEN_PASSWORD_LABEL = 'Hidden password';

const CREDENTIAL_VALUE_SELECTOR = '.meta-credential-value';
const COPYABLE_SELECTOR = '.meta-copyable';
export const VALUE_BUTTONS_SELECTOR = '.meta-value-buttons';
const VALUE_BUTTON_SELECTOR = '.meta-value-button';
const COPIED_CLASS = 'meta-value-button-copied';
const SHOWN_CLASS = 'meta-credential-shown';
// A password's value in MetaList: a space as wide for every password, so showing one moves
// nothing after it and its width says nothing of its length (main.css).
const PASSWORD_SLOT_CLASS = 'meta-credential-slot';
const EYE_SELECTOR = '[data-value-action="show"]';
const FLOATING_WINDOW_SELECTOR = '.floating-note-window';
// Rendered notes being edited hold the editor, not values to decorate.
const EDITING_SELECTOR = '.note.editing, [contenteditable="true"]';

const COPY_ICON = '<svg class="meta-value-button-icon meta-value-button-copy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    + '<path fill="currentColor" d="M16 1H6a2 2 0 0 0-2 2v12h2V3h10V1Zm3 4H10a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16h-9V7h9v14Z"/></svg>'
    + '<svg class="meta-value-button-icon meta-value-button-check-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    + '<path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2Z"/></svg>';
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

function makeButtons({ copyLabel, withEye }) {
    const buttons = document.createElement('span');
    buttons.className = 'meta-value-buttons';
    buttons.contentEditable = 'false';
    if (withEye) {
        const eye = makeButton({ action: 'show', label: 'Show password', iconHtml: EYE_ICON });
        eye.setAttribute('aria-pressed', 'false');
        buttons.append(eye);
    }
    buttons.append(makeButton({ action: 'copy', label: copyLabel, iconHtml: COPY_ICON }));
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

function decorateCredential(value) {
    if (value.closest(EDITING_SELECTOR) || value.hasAttribute('data-redacted')) return;
    const next = value.nextElementSibling;
    if (next && next.matches(VALUE_BUTTONS_SELECTOR)) return;
    if (typeof value.dataset.copyValue !== 'string') {
        throw new Error('Credential value missing data-copy-value attribute');
    }
    const isPassword = value.closest('.meta-credential-password') !== null;
    const buttons = makeButtons({ copyLabel: isPassword ? 'Copy password' : 'Copy username', withEye: isPassword });
    if (isPassword) value.classList.add(PASSWORD_SLOT_CLASS);
    value.after(buttons);
    if (isPassword && moduleState.shownRows.includes(rowKey(value))) {
        setPasswordShown(value, buttons.querySelector('[data-value-action="show"]'), true);
    }
}

function decorateCopyable(copyable) {
    // A copyable password or username has its row's buttons.
    if (copyable.matches(CREDENTIAL_VALUE_SELECTOR) || copyable.closest(EDITING_SELECTOR)) return;
    const last = copyable.lastElementChild;
    if (last && last.matches(VALUE_BUTTONS_SELECTOR)) return;
    const buttons = makeButtons({ copyLabel: 'Copy', withEye: false });
    // A ((…)) region inside a line keeps its button right after it. A whole note's sits at its
    // top right: after the text of a one-line note (its box is as wide as its text), at the
    // corner of several lines, as on a code block.
    const isRegionInLine = copyable.tagName === 'SPAN' && copyable.classList.contains('meta-scope');
    buttons.classList.add(isRegionInLine ? 'meta-value-buttons-inline' : 'meta-value-buttons-corner');
    copyable.append(buttons);
}

export function decorateValueButtons(root) {
    if (root.matches?.(CREDENTIAL_VALUE_SELECTOR)) decorateCredential(root);
    if (root.matches?.(COPYABLE_SELECTOR)) decorateCopyable(root);
    for (const value of root.querySelectorAll(CREDENTIAL_VALUE_SELECTOR)) decorateCredential(value);
    for (const copyable of root.querySelectorAll(COPYABLE_SELECTOR)) decorateCopyable(copyable);
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

function copiedValue(button) {
    const row = button.closest('.meta-credential');
    if (row) {
        const value = row.querySelector(CREDENTIAL_VALUE_SELECTOR);
        if (typeof value?.dataset.copyValue !== 'string') throw new Error('Copy button without a credential value');
        return value.dataset.copyValue;
    }
    const copyable = button.closest(COPYABLE_SELECTOR);
    if (!copyable) throw new Error('Copy button outside a copyable value');
    if (typeof copyable.dataset.copyValue === 'string') return normalizeCopyableText(copyable.dataset.copyValue);
    return normalizeCopyableText(copyable.textContent);
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
// would shrink and move what the press is on (its copy button, the rest of a link) from under
// the pointer.
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

// A click on a copy or show button: true when it was one (the click is then used up). target:
// the element clicked, inside a floating window's own tree too.
export function handleValueButtonClick(event, target) {
    if (!(target instanceof Element)) return false;
    const button = target.closest(VALUE_BUTTON_SELECTOR);
    if (!button) return false;
    event.preventDefault();
    event.stopPropagation();
    if (button.dataset.valueAction === 'show') {
        const value = button.closest(VALUE_BUTTONS_SELECTOR).previousElementSibling;
        if (!value?.matches(CREDENTIAL_VALUE_SELECTOR)) throw new Error('Show button without a password');
        const key = rowKey(value);
        const shown = !moduleState.shownRows.includes(key);
        // One shown at a time: an eye pressed by its key leaves no other shown either.
        hideShownPasswords();
        if (shown) moduleState.shownRows = Object.freeze([key]);
        setPasswordShown(value, button, shown);
        return true;
    }
    const isCredential = button.closest('.meta-credential') !== null;
    void copyTextToClipboard(copiedValue(button), button, COPIED_CLASS);
    // A credential's copy says nothing of the value, not even its length.
    Logger.logAction(isCredential ? 'credential.copy' : 'copyable.copy', {});
    return true;
}
