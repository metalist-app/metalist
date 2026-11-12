import { CONFIG } from '../config.js';
import { HTTP_STATUS } from '../http-status.js';
import { ServerInputRejectedError } from '../expected-errors.js';
import { buildSessionHeaders } from '../session-auth.js';
import { ModeContextInstance as ModeContext } from '../mode-manager/mode-context.js';
import { recordedTrail } from './input-recorder.js';

// Makes a problem report (docs/ready-to-build/error-reports.md): the page sends its draft (the
// trail, where it is, the error), and MetaList's server, which holds the notes, fills them in,
// redacts, checks and keeps it, then answers the report to be saved as a file.

const MAX_NOTES = 200;
const MAX_FRAMES = 50;
const MADE_BY_OVERLAY = 'overlay';
const MADE_BY_USER = 'user';
const PREFERENCE_CLASS_PREFIX = 'pref-';
// 2026-11-12T10:31:05.123: to the millisecond, so two files never share a name.
const FILE_STAMP_LENGTH = 23;
const JSON_INDENT = 2;
const SAFE_FILE = /^[A-Za-z0-9_./-]+\.js$/;
const SAFE_FUNCTION = /^[A-Za-z0-9_$.<>]{1,80}$/;
// A stack line in Chrome (`at fn (http://host/static/js/modules/x.js:205:12)`) or Firefox
// (`fn@http://host/static/js/modules/x.js:205:12`).
const STACK_LINE = /^\s*(?:at\s+)?(?:(?<fn>[^\s(@]+)\s*[(@])?\s*[a-z]+:\/\/[^/]+\/static\/js\/(?<file>[^:)]+):(?<line>\d+)(?::\d+)?\)?\s*$/;

export const NO_ERROR = Object.freeze({ className: '', message: '', stack: '' });

// The code's own frames from a stack: script and line, and the function when it has a plain name.
export function stackFrames(stack) {
    const frames = [];
    for (const line of stack.split('\n')) {
        const match = STACK_LINE.exec(line);
        if (match === null || !SAFE_FILE.test(match.groups.file)) continue;
        const name = match.groups.fn;
        const fn = name !== undefined && SAFE_FUNCTION.test(name) ? ` ${name}` : '';
        frames.push(`${match.groups.file}:${match.groups.line}${fn}`);
        if (frames.length === MAX_FRAMES) break;
    }
    return frames;
}

function isLoggedIn() {
    return document.body.dataset.appReady === 'true';
}

// The notes the trail touched, the note being edited, and the parents above them.
function involvedNoteIds(trail, editingNote) {
    const ids = new Set(trail.inputs.map((entry) => entry.note).filter((id) => id !== ''));
    if (editingNote !== '') ids.add(editingNote);
    for (const id of [...ids]) {
        let element = document.querySelector(`.note[data-note-id="${CSS.escape(id)}"]`);
        while (element instanceof HTMLElement && element.dataset.parentId) {
            ids.add(element.dataset.parentId);
            element = document.querySelector(`.note[data-note-id="${CSS.escape(element.dataset.parentId)}"]`);
        }
    }
    return [...ids].slice(0, MAX_NOTES);
}

const NO_SKIN = '';

// The skin chosen (theme-choices.js), or none.
function skinOf(root) {
    if (!Object.hasOwn(root.dataset, 'skin')) return NO_SKIN;
    return root.dataset.skin;
}

// How big the view was: the notes in the list, those on screen, and how far it was scrolled.
function viewSize() {
    const notes = [...document.querySelectorAll('.note[data-note-id]')];
    const onScreen = notes.filter((note) => {
        const box = note.getBoundingClientRect();
        return box.height > 0 && box.bottom > 0 && box.top < window.innerHeight;
    });
    return { notesInList: notes.length, notesOnScreen: onScreen.length, scrollY: Math.max(window.scrollY, 0) };
}

export function pageDraft({ madeBy, description, error }) {
    const trail = recordedTrail();
    const loggedIn = isLoggedIn();
    const editingNote = loggedIn && ModeContext.isEditing ? ModeContext.currentNoteId : '';
    const root = document.documentElement;
    return {
        madeBy,
        description,
        error: { className: error.className, message: error.message, frames: stackFrames(error.stack) },
        window: { w: window.innerWidth, h: window.innerHeight },
        view: viewSize(),
        theme: root.dataset.theme === 'dark' ? 'dark' : 'light',
        skin: skinOf(root),
        preferences: [...document.body.classList].filter((name) => name.startsWith(PREFERENCE_CLASS_PREFIX)),
        editingNote,
        search: loggedIn ? ModeContext.getExecutedSearchQuery(ModeContext.activeTabId) : '',
        noteIds: loggedIn ? involvedNoteIds(trail, editingNote) : [],
        inputs: trail.inputs,
        commands: trail.commands,
        requests: trail.requests,
    };
}

async function answerOf(response) {
    const body = await response.json();
    if (response.status === HTTP_STATUS.BAD_REQUEST && body.inputRejected === true) {
        throw new ServerInputRejectedError(body.detail);
    }
    if (!response.ok) {
        throw new Error(`Problem report failed: ${response.status} ${response.statusText}`);
    }
    return body;
}

// Sends the draft; a report made logged in is kept, one from the login page is not.
export async function makeReport(draft) {
    const loggedIn = isLoggedIn();
    const url = loggedIn ? CONFIG.API.PROBLEM_REPORTS.MAKE : CONFIG.API.PROBLEM_REPORTS.MAKE_UNSAVED;
    const headers = loggedIn ? buildSessionHeaders(true) : { 'Content-Type': 'application/json' };
    const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(draft) });
    const answer = await answerOf(response);
    // A kept report is named by its id; one from the login page, kept nowhere, by the time.
    const name = loggedIn ? answer.reportId : fileStamp();
    return { report: answer.report, name };
}

export async function keptReports() {
    const response = await fetch(CONFIG.API.PROBLEM_REPORTS.LIST, { headers: buildSessionHeaders(false) });
    return (await answerOf(response)).reports;
}

export async function exportKeptReports(reportIds) {
    const response = await fetch(CONFIG.API.PROBLEM_REPORTS.EXPORT, {
        method: 'POST', headers: buildSessionHeaders(true), body: JSON.stringify({ reportIds }),
    });
    return (await answerOf(response)).reports;
}

function fileStamp() {
    return new Date().toISOString().slice(0, FILE_STAMP_LENGTH).replace(/[:.T]/g, '-');
}

// Saves as the browser saves a download (export-service.js does the same).
export function saveAsFile(content, fileName) {
    const blob = new Blob([`${JSON.stringify(content, null, JSON_INDENT)}\n`], { type: 'application/json' });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = `${fileName}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

export async function exportOverlayReport(error) {
    const { report, name } = await makeReport(pageDraft({ madeBy: MADE_BY_OVERLAY, description: '', error }));
    saveAsFile(report, `metalist-problem-report-${name}`);
}

export async function exportUserReport(description) {
    const { report, name } = await makeReport(pageDraft({ madeBy: MADE_BY_USER, description, error: NO_ERROR }));
    saveAsFile(report, `metalist-problem-report-${name}`);
}

export function exportedReportsFileName() {
    return `metalist-problem-reports-${fileStamp()}`;
}
