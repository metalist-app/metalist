import { ApplicationState } from './application-state.js';

// Ye Olde Scrypte's quill and hand are drawn on the page, following the mouse: browsers swap a
// real cursor bigger than 32 px for the regular one near the window's edges. The skin's cursors
// are blank pictures, and which one the browser reports says what to draw; any other cursor (a
// resize arrow, "wait") is the browser's own and nothing is drawn. x and y: the point that clicks.
const POINTER_KINDS = [
    { name: 'quill', marker: 'cursor-blank-quill', x: 0, y: 47 },
    { name: 'hand', marker: 'cursor-blank-hand', x: 1, y: 0 },
];
const POINTER_CLASS = 'skin-pointer';
const MOVE_OPTIONS = { capture: true, passive: true };

const moduleState = ApplicationState.createFields('skin-pointer', {
    element: null,
});

function pointerKindAt(target) {
    if (!(target instanceof Element) || target.tagName === 'IFRAME') {
        return null;
    }
    const cursor = getComputedStyle(target).cursor;
    const kind = POINTER_KINDS.find((candidate) => cursor.includes(candidate.marker));
    return kind === undefined ? null : kind;
}

function showKind(kind) {
    const element = moduleState.element;
    if (kind === null) {
        delete element.dataset.kind;
    } else if (element.dataset.kind !== kind.name) {
        element.dataset.kind = kind.name;
    }
}

function followMouse(event) {
    if (event.pointerType !== 'mouse') {
        showKind(null);
        return;
    }
    const kind = pointerKindAt(event.target);
    showKind(kind);
    if (kind !== null) {
        moduleState.element.style.transform = `translate3d(${event.clientX - kind.x}px, ${event.clientY - kind.y}px, 0)`;
    }
}

function hideOnLeavingThePage() {
    showKind(null);
}

export function setSkinPointerActive(isActive) {
    if (typeof isActive !== 'boolean') {
        throw new Error('setSkinPointerActive requires a boolean');
    }
    if (isActive === (moduleState.element !== null)) {
        return;
    }
    if (!isActive) {
        document.removeEventListener('pointermove', followMouse, MOVE_OPTIONS);
        document.documentElement.removeEventListener('mouseleave', hideOnLeavingThePage);
        moduleState.element.remove();
        moduleState.element = null;
        return;
    }
    const element = document.createElement('div');
    element.className = POINTER_CLASS;
    element.setAttribute('aria-hidden', 'true');
    document.body.append(element);
    moduleState.element = element;
    document.addEventListener('pointermove', followMouse, MOVE_OPTIONS);
    document.documentElement.addEventListener('mouseleave', hideOnLeavingThePage);
}
