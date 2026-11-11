import { ApplicationState } from './application-state.js';

// Ye Olde Scrypte's quill and hand are drawn on the page, following the mouse: browsers swap a
// real cursor bigger than 32 px for the regular one near the window's edges. The skin's cursors
// are blank pictures, and which one the browser reports says what to draw; any other cursor (a
// resize arrow, "wait") is the browser's own and nothing is drawn. x and y: the point that clicks.
// The quill's tip, at the bottom left of its 48 px picture.
const QUILL_TIP_Y = 47;
const POINTER_KINDS = [
    { name: 'quill', marker: 'cursor-blank-quill', x: 0, y: QUILL_TIP_Y },
    { name: 'hand', marker: 'cursor-blank-hand', x: 1, y: 0 },
];
const POINTER_CLASS = 'skin-pointer';
const MOVE_OPTIONS = { capture: true, passive: true };

const moduleState = ApplicationState.createFields('skin-pointer', {
    element: null,
    observer: null,
    isLookScheduled: false,
    lastPoint: null,
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
    const point = moduleState.lastPoint;
    // A move to the same point (browsers send them) is no change to record.
    if (point === null || point.x !== event.clientX || point.y !== event.clientY) {
        moduleState.lastPoint = { x: event.clientX, y: event.clientY };
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

// The page changed under a still mouse (editing ended, a menu closed): look again at once.
function lookAgain() {
    moduleState.isLookScheduled = false;
    const point = moduleState.lastPoint;
    if (moduleState.element === null || point === null) {
        return;
    }
    const kind = pointerKindAt(document.elementFromPoint(point.x, point.y));
    showKind(kind);
    if (kind !== null) {
        moduleState.element.style.transform = `translate3d(${point.x - kind.x}px, ${point.y - kind.y}px, 0)`;
    }
}

function lookAgainSoon(records) {
    // Its own moves are not a change to look at.
    if (moduleState.isLookScheduled || records.every((record) => record.target === moduleState.element)) {
        return;
    }
    moduleState.isLookScheduled = true;
    requestAnimationFrame(lookAgain);
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
        moduleState.observer.disconnect();
        moduleState.observer = null;
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
    moduleState.observer = new MutationObserver(lookAgainSoon);
    moduleState.observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style'] });
}
