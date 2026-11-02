import { ApplicationState } from '../../application-state.js';

// The virtual folders tree's width (the maintainer, 2026-11-02): dragged at the panel's right
// edge, as the AI chat's at its left (.ai-chat-resizer); ← and → by 24px, Home the least, End
// the most. At least 160px; at most what leaves the notes 480px, beside the chat too. Kept in
// this browser, as whether the tree shows is (virtual-folders-service.js). The width also moves
// the line where the tree, the notes and the chat stop fitting: there the tree hides
// (virtual-folders-crowded, main.css).

const WIDTH_KEY = 'metalist.virtual_folders.width';
const LEAST_WIDTH_PX = 160;
const KEY_STEP_PX = 24;
// What the notes keep beside the tree (as beside the chat: --ai-chat-min-notes-width), and the
// chat's least width (the clamp in --ai-chat-effective-width).
const NOTES_LEAST_PX = 480;
const CHAT_LEAST_PX = 280;
const RESIZER_CLASS = 'virtual-folders-resizer';
const RESIZING_CLASS = 'virtual-folders-resizing';
const CROWDED_CLASS = 'virtual-folders-crowded';
const CHAT_SHOWN_CLASS = 'pref-show-ai-chat';
const WIDTH_PROPERTY = '--virtual-folders-width';
const PIXELS = 'px';
const PRIMARY_BUTTON = 0;

const moduleState = ApplicationState.createFields('virtual-folders-width', {
    // The width chosen (stored, or the stylesheet's at first), before the window's limits.
    chosenWidth: 0,
    resizer: null,
});

function remember(field, value) {
    if (moduleState[field] !== value) moduleState[field] = value;
}

// A length the stylesheet gives in pixels (--side-rail-edge, --virtual-folders-gap).
function stylePixels(name) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (!raw.endsWith(PIXELS)) {
        throw new Error(`${name} must be set in pixels, got ${raw}`);
    }
    return Number.parseFloat(raw);
}

function isChatShown() {
    return document.body.classList.contains(CHAT_SHOWN_CLASS);
}

// The widest the tree can be: the notes keep 480px, beside the chat at its least (the chat
// narrows first as the tree widens: main.css, --ai-chat-effective-width beside the tree).
function mostWidth() {
    const room = document.documentElement.clientWidth - stylePixels('--side-rail-edge') - stylePixels('--virtual-folders-gap');
    const chat = isChatShown() ? CHAT_LEAST_PX : 0;
    return Math.max(LEAST_WIDTH_PX, Math.floor(room - NOTES_LEAST_PX - chat));
}

function withinLimits(width) {
    return Math.min(Math.max(Math.round(width), LEAST_WIDTH_PX), mostWidth());
}

function appliedWidth() {
    return stylePixels(WIDTH_PROPERTY);
}

/** Whether the tree at its chosen width, 480px of notes and the chat's least fit in the page (the
 * window less any scrollbar): where not, the tree hides (a narrower window doesn't squeeze the
 * tree first: the line is the width's). */
export function syncVirtualFoldersRoom() {
    const needed = stylePixels('--side-rail-edge') + moduleState.chosenWidth + stylePixels('--virtual-folders-gap')
        + NOTES_LEAST_PX + CHAT_LEAST_PX;
    const isCrowded = isChatShown() && document.documentElement.clientWidth < needed;
    if (document.body.classList.contains(CROWDED_CLASS) !== isCrowded) {
        document.body.classList.toggle(CROWDED_CLASS, isCrowded);
    }
}

function apply(width) {
    document.documentElement.style.setProperty(WIDTH_PROPERTY, `${width}${PIXELS}`);
    const resizer = moduleState.resizer;
    resizer.setAttribute('aria-valuenow', String(width));
    resizer.setAttribute('aria-valuemin', String(LEAST_WIDTH_PX));
    resizer.setAttribute('aria-valuemax', String(mostWidth()));
    syncVirtualFoldersRoom();
}

// A width the person set: shown, and kept unless it is the one kept already.
function choose(width) {
    const chosen = withinLimits(width);
    remember('chosenWidth', chosen);
    apply(chosen);
    if (window.localStorage.getItem(WIDTH_KEY) !== String(chosen)) {
        window.localStorage.setItem(WIDTH_KEY, String(chosen));
    }
}

function onPointerMove(event) {
    const width = withinLimits(event.clientX - stylePixels('--side-rail-edge'));
    remember('chosenWidth', width);
    apply(width);
}

function onPointerUp() {
    document.body.classList.remove(RESIZING_CLASS);
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onPointerUp);
    choose(moduleState.chosenWidth);
}

function onPointerDown(event) {
    if (event.button !== PRIMARY_BUTTON) return;
    event.preventDefault();
    document.body.classList.add(RESIZING_CLASS);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
}

function onKeyDown(event) {
    const current = appliedWidth();
    const widthByKey = {
        ArrowRight: current + KEY_STEP_PX, ArrowLeft: current - KEY_STEP_PX, Home: LEAST_WIDTH_PX, End: mostWidth(),
    };
    if (!Object.hasOwn(widthByKey, event.key)) return;
    event.preventDefault();
    choose(widthByKey[event.key]);
}

// The window changed: the chosen width again, within the new limits (not kept: widening the
// window again gives it back).
function onWindowResize() {
    apply(withinLimits(moduleState.chosenWidth));
}

/** Once at startup: the handle, and the width kept, within this window's limits. */
export function initVirtualFoldersWidth() {
    if (moduleState.resizer !== null) {
        throw new Error('initVirtualFoldersWidth runs once');
    }
    const resizer = document.createElement('div');
    resizer.className = RESIZER_CLASS;
    resizer.setAttribute('role', 'separator');
    resizer.setAttribute('aria-label', 'Resize virtual folders');
    resizer.setAttribute('aria-orientation', 'vertical');
    resizer.tabIndex = 0;
    resizer.addEventListener('pointerdown', onPointerDown);
    resizer.addEventListener('keydown', onKeyDown);
    document.body.appendChild(resizer);
    remember('resizer', resizer);
    const stored = window.localStorage.getItem(WIDTH_KEY);
    let chosen = appliedWidth();
    if (stored !== null) chosen = Number(stored);
    if (!Number.isFinite(chosen)) {
        throw new Error(`Stored virtual folders width is not a number: ${stored}`);
    }
    remember('chosenWidth', chosen);
    apply(withinLimits(chosen));
    window.addEventListener('resize', onWindowResize);
    document.addEventListener('metalist:ai-chat-visibility-changed', syncVirtualFoldersRoom);
}
