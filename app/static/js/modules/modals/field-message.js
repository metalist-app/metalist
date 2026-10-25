// Field messages (docs/ui/modals.md, "Messages under a field"): what is wrong with a
// field's value floats just under that field, over what is below it. Nothing moves, focus
// stays where it is, and the message leaves once the value is fine. Errors are red,
// warnings amber. Typing never opens a dialog; this is what typing gets instead.

const KINDS = new Set(['error', 'warning']);
const ANCHOR_CLASS = 'field-message-anchor';
// The space between a field and its message.
const FIELD_MESSAGE_GAP_PX = 4;

function messageId(field) {
    if (!(field instanceof HTMLElement) || field.id === '') {
        throw new Error('A field message needs a field with an id');
    }
    return `${field.id}-message`;
}

function removeFieldMessage(field) {
    const existing = document.getElementById(messageId(field));
    if (existing !== null) {
        existing.remove();
        field.removeAttribute('aria-describedby');
    }
}

// The field's nearest container that draws a box (a label shown as display: contents draws
// none), which the message is placed in, so it scrolls with the field.
function boxedContainer(field) {
    let container = field.parentElement;
    while (container instanceof HTMLElement && getComputedStyle(container).display === 'contents') {
        container = container.parentElement;
    }
    if (!(container instanceof HTMLElement)) {
        throw new Error('A field message needs the field inside an element');
    }
    return container;
}

// text '' takes the message away.
export function setFieldMessage(field, text, kind) {
    if (typeof text !== 'string') {
        throw new Error('A field message needs text (empty for none)');
    }
    if (!KINDS.has(kind)) {
        throw new Error(`Unknown field message kind: ${kind}`);
    }
    if (text === '') {
        removeFieldMessage(field);
        return;
    }
    const anchor = boxedContainer(field);
    // Positioned against the field's own container, so it scrolls with the dialog.
    anchor.classList.add(ANCHOR_CLASS);
    let message = document.getElementById(messageId(field));
    if (message === null) {
        message = document.createElement('div');
        message.id = messageId(field);
        message.className = 'field-message';
        message.setAttribute('role', 'status');
        anchor.appendChild(message);
        field.setAttribute('aria-describedby', message.id);
    }
    message.dataset.kind = kind;
    message.textContent = text;
    // Placed from where it lands at 0, 0, to the fraction of a pixel, so it sits exactly
    // under the field whatever its container's borders and scrolling.
    message.style.top = '0px';
    message.style.left = '0px';
    const origin = message.getBoundingClientRect();
    const fieldBox = field.getBoundingClientRect();
    message.style.top = `${fieldBox.bottom + FIELD_MESSAGE_GAP_PX - origin.top}px`;
    message.style.left = `${fieldBox.left - origin.left}px`;
    message.style.minWidth = `${fieldBox.width}px`;
}
