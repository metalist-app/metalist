import { ApplicationState } from '../application-state.js';

// What a problem report knows of the last 10 minutes (docs/ready-to-build/error-reports.md §1):
// inputs, the commands they ran and the requests the page made, in memory only. A reload
// discards it; nothing is written or sent until a report is made.
//
// No text the user typed is kept: letters become x or X and digits 0 as they are typed (the
// server shapes them again), except a LaTeX command after a backslash, which a formula needs.
// A password field records nothing, not even how much was typed.

// 10 minutes (the maintainer, 2026-11-12).
export const RING_WINDOW_MS = 600000;
export const RING_MAX_ENTRIES = 5000;
// Typing in one place with no other input between, within this gap, is one entry.
const TYPING_RUN_GAP_MS = 2000;
// Scrolling and resizing fire continuously: one entry each this often at most.
const CONTINUOUS_INPUT_GAP_MS = 500;
const PASTE_KEEP_CHARACTERS = 2000;
const SPEC_URL = '/static/config/problem-report-spec.json';

const state = ApplicationState.createFields('problem-report-recorder', {
    isInstalled: false,
    syntaxCharacters: '',
    latexCommands: [],
    inputs: [],
    commands: [],
    requests: [],
    lastScrollAt: 0,
    lastResizeAt: 0,
});

function nowMs() {
    return Date.now();
}

function dropOld(entries, now) {
    let firstKept = 0;
    while (firstKept < entries.length && entries[firstKept].at < now - RING_WINDOW_MS) firstKept += 1;
    const overCap = entries.length - firstKept - RING_MAX_ENTRIES;
    if (overCap > 0) firstKept += overCap;
    if (firstKept > 0) entries.splice(0, firstKept);
}

function remember(list, entry) {
    list.push(Object.freeze(entry));
    dropOld(list, entry.at);
}

export function shapeCharacter(character) {
    if (/\p{L}/u.test(character)) return character === character.toLowerCase() ? 'x' : 'X';
    if (/\p{Nd}/u.test(character)) return '0';
    if (/\s/u.test(character) || state.syntaxCharacters.includes(character)) return character;
    return 'x';
}

// Shapes typed text, keeping a LaTeX command MetaList knows after a backslash.
export function shapeTyped(text) {
    const kept = new Set(state.latexCommands);
    return text.replace(/\\([A-Za-z]+)|[\s\S]/gu, (whole, command) => {
        if (command !== undefined) {
            return kept.has(command) ? whole : `\\${[...command].map(shapeCharacter).join('')}`;
        }
        return shapeCharacter(whole);
    });
}

function isEditable(target) {
    if (!(target instanceof Element)) return false;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
    return target.closest('[contenteditable="true"], [contenteditable=""]') !== null;
}

function isPasswordField(target) {
    return target instanceof HTMLInputElement && target.type === 'password';
}

// Report a Problem…'s own box: what is typed there goes into the report as written, so the
// trail does not repeat it.
const REPORT_BOX_SELECTOR = '#problem-report-modal';
// A modifier pressed on its own says nothing: the key it goes with is recorded with it.
const MODIFIER_KEYS = new Set(['Alt', 'Control', 'Meta', 'Shift', 'OS', 'AltGraph']);

function isUnrecordedKey(event) {
    if (MODIFIER_KEYS.has(event.key)) return true;
    return event.target instanceof Element && event.target.closest(REPORT_BOX_SELECTOR) !== null;
}

const NOTE_PARTS = Object.freeze([
    ['.note-collapse-toggle', 'fold-arrow'],
    ['.note-tag-bar', 'tag-bar'],
    ['.note-tags', 'tags'],
    ['.note-backlinks-badge, .note-backlinks-link, .note-proposal-indicator, .note-collapsed-children-indicator, .note-source-arrow', 'badge'],
    ['.note-embed-collapse-toggle, .note-search-embed-result, .note-reference-note', 'embed'],
    ['.note-content', 'content'],
]);

const CONTROLS = Object.freeze([
    ['.command-palette-row', 'palette-row'],
    ['.context-menu-item', 'menu-item'],
    ['#search-input, .search-input', 'search'],
    ['button, [role="button"]', 'button'],
    ['input, textarea, select', 'input'],
    ['a[href]', 'link'],
]);

// Where an input landed: a note and its part, or a kind of control. Never an element's text.
export function describeTarget(target) {
    if (!(target instanceof Element)) return { note: '', part: '', control: 'page' };
    const note = target.closest('.note[data-note-id]');
    if (note instanceof HTMLElement) {
        const own = target.closest('.note[data-note-id]') === note ? target : note;
        for (const [selector, part] of NOTE_PARTS) {
            const holder = own.closest(selector);
            if (holder !== null && note.contains(holder)) return { note: note.dataset.noteId, part, control: '' };
        }
        return { note: note.dataset.noteId, part: 'note', control: '' };
    }
    for (const [selector, control] of CONTROLS) {
        if (target.closest(selector) !== null) return { note: '', part: '', control };
    }
    return { note: '', part: '', control: 'page' };
}

function modifiersOf(event) {
    const mods = [];
    if (event.altKey) mods.push('alt');
    if (event.ctrlKey) mods.push('ctrl');
    if (event.metaKey) mods.push('meta');
    if (event.shiftKey) mods.push('shift');
    return mods;
}

function inputEntry(at, kind, where, fields) {
    return {
        at, kind, note: where.note, part: where.part, control: where.control, command: '',
        code: fields.code, mods: fields.mods, typed: fields.typed,
    };
}

const NO_KEY = Object.freeze({ code: '', mods: [], typed: '' });

function onKeyDown(event) {
    if (isPasswordField(event.target) || isUnrecordedKey(event)) return;
    const at = nowMs();
    const where = describeTarget(event.target);
    const isPrintable = event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (isPrintable && isEditable(event.target)) {
        const last = state.inputs[state.inputs.length - 1];
        const shaped = shapeTyped(event.key);
        if (last !== undefined && last.kind === 'type' && last.note === where.note && last.control === where.control
            && at - last.at < TYPING_RUN_GAP_MS) {
            state.inputs.splice(state.inputs.length - 1, 1, Object.freeze({ ...last, at, typed: last.typed + shaped }));
            return;
        }
        remember(state.inputs, inputEntry(at, 'type', where, { code: '', mods: [], typed: shaped }));
        return;
    }
    remember(state.inputs, inputEntry(at, 'key', where, { code: event.code, mods: modifiersOf(event), typed: '' }));
}

function onPointer(kind) {
    return (event) => {
        remember(state.inputs, inputEntry(nowMs(), kind, describeTarget(event.target), {
            code: '', mods: modifiersOf(event), typed: '',
        }));
    };
}

function onPaste(event) {
    if (isPasswordField(event.target)) return;
    if (event.target instanceof Element && event.target.closest(REPORT_BOX_SELECTOR) !== null) return;
    const text = event.clipboardData.getData('text/plain');
    remember(state.inputs, inputEntry(nowMs(), 'paste', describeTarget(event.target), {
        code: '', mods: [], typed: shapeTyped(text.slice(0, PASTE_KEEP_CHARACTERS)),
    }));
}

function onDrop(event) {
    remember(state.inputs, inputEntry(nowMs(), 'drop', describeTarget(event.target), NO_KEY));
}

function onScroll(event) {
    const at = nowMs();
    if (at - state.lastScrollAt < CONTINUOUS_INPUT_GAP_MS) return;
    state.lastScrollAt = at;
    remember(state.inputs, inputEntry(at, 'scroll', describeTarget(event.target), NO_KEY));
}

function onResize() {
    const at = nowMs();
    if (at - state.lastResizeAt < CONTINUOUS_INPUT_GAP_MS) return;
    state.lastResizeAt = at;
    remember(state.inputs, inputEntry(at, 'resize', { note: '', part: '', control: 'page' }, NO_KEY));
}

function onVisibility() {
    remember(state.inputs, inputEntry(nowMs(), 'visibility', { note: '', part: '', control: 'page' }, NO_KEY));
}

// A command CommandGate ran (command-gate-service.js): its label, how long, how it ended.
export function recordCommand(label, ms, outcome) {
    remember(state.commands, { at: nowMs(), label, ms, outcome });
}

const REQUEST_ID_HEADER = 'X-Request-Id';
const NO_REQUEST_ID = '';

// The server names every request it answers; one refused before its request log (an unknown
// host) has no id.
function requestIdOf(response) {
    if (!response.headers.has(REQUEST_ID_HEADER)) return NO_REQUEST_ID;
    return response.headers.get(REQUEST_ID_HEADER);
}

function wrapFetch() {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (resource, init) => {
        const startedAt = nowMs();
        const url = new URL(resource instanceof Request ? resource.url : String(resource), window.location.href);
        let method = 'GET';
        if (resource instanceof Request) method = resource.method;
        if (init !== undefined && init !== null && typeof init.method === 'string') method = init.method;
        const isOwn = url.origin === window.location.origin;
        const response = await originalFetch(resource, init);
        if (isOwn) {
            remember(state.requests, {
                at: startedAt, method: method.toUpperCase(), path: url.pathname, status: response.status,
                ms: nowMs() - startedAt, requestId: requestIdOf(response),
            });
        }
        return response;
    };
}

async function loadSpec() {
    const response = await fetch(SPEC_URL);
    if (!response.ok) throw new Error(`Problem report spec failed to load (${response.status})`);
    const spec = await response.json();
    state.syntaxCharacters = spec.syntaxCharacters;
    state.latexCommands = spec.latexCommands;
}

// Installed first thing (main.js), in the capture phase on window, so it sees every input
// before any handler stops it; it changes nothing about how the page answers them.
export function installInputRecorder() {
    if (state.isInstalled) return;
    state.isInstalled = true;
    const capture = { capture: true, passive: true };
    window.addEventListener('keydown', onKeyDown, capture);
    window.addEventListener('click', onPointer('click'), capture);
    window.addEventListener('dblclick', onPointer('dblclick'), capture);
    window.addEventListener('contextmenu', onPointer('contextmenu'), capture);
    window.addEventListener('paste', onPaste, capture);
    window.addEventListener('drop', onDrop, capture);
    window.addEventListener('scroll', onScroll, capture);
    window.addEventListener('resize', onResize, { passive: true });
    document.addEventListener('visibilitychange', onVisibility, { passive: true });
    wrapFetch();
    void loadSpec();
}

// The last 10 minutes, each entry's time made relative to the oldest kept (ms).
export function recordedTrail() {
    const now = nowMs();
    for (const list of [state.inputs, state.commands, state.requests]) dropOld(list, now);
    // A request is kept when it answers but timed from when it was sent, so the oldest moment
    // is looked for in every entry, not only each list's first.
    const times = [state.inputs, state.commands, state.requests].flatMap((list) => list.map((entry) => entry.at));
    const origin = Math.min(now, ...times);
    const relative = (entry) => {
        const { at, ...rest } = entry;
        return { t: at - origin, ...rest };
    };
    return {
        inputs: state.inputs.map(relative),
        commands: state.commands.map(relative),
        requests: state.requests.map(relative),
    };
}
