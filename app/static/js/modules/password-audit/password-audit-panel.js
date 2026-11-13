// Password Audit (docs/ui/password-audit.md; the maintainer, 2026-11-12): a movable
// panel, not a dialog, so the list stays usable behind it. It checks every password when it
// opens and lists them by group, each by its note's first line and tags, never the password.
// Go to opens the top-level note the password is in, as following a link to it does; Replace…
// makes a strong password to change on the site, then saves it, the old one kept in a note under
// it (one undo step, app/usecases/password_audit.py). While it is open it updates itself as notes
// change, here or anywhere else, once the changes settle; the server checks only what is new.
import { NotesAPI } from '../api-client.js';
import { ApplicationState, stateValuesEqual } from '../application-state.js';
import { escapeHtml } from '../html-escape.js';
import { DEFAULT_PASSWORD_CHARSET, DEFAULT_PASSWORD_LENGTH, generateRandomPassword, normalizePasswordCharset } from '../password-generator.js';
import { openReferenceInNewTab } from '../mode-manager/events/keyboard-events.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { onNotesChanged } from '../notes-change-signal.js';
import { WEAK_BELOW_USUAL, WEAK_THRESHOLDS } from './weak-thresholds.js';

const PANEL_ID = 'password-audit-panel';
const GROUPS = [
    ['leaked', 'Leaked'],
    ['reused', 'Reused'],
    ['weak', 'Weak'],
    ['old', 'Old'],
    ['replaced', 'Replaced, to delete'],
];
// A password in a ((…)) region never holds a bracket of any wrapper, so it can't close its region.
const WRAPPER_CHARACTERS = new Set(['(', ')', '[', ']', '{', '}', '<', '>']);
const COPIED_SECONDS = 2;
const MS_PER_SECOND = 1000;
// After the notes change, the panel waits this long for more changes before it updates, so a
// password is checked once typing pauses, not at every save.
const UPDATE_AFTER_CHANGES_SECONDS = 2;
const UPDATE_AFTER_CHANGES_MS = UPDATE_AFTER_CHANGES_SECONDS * MS_PER_SECOND;

const state = ApplicationState.createFields('password-audit-panel', {
    element: null,
    weakBelow: WEAK_BELOW_USUAL,
    checkLeaks: false,
    savePreferences: null,
    onAudited: null,
    result: null,
    // The password being replaced, as { noteId, kind, passwordId }: it is followed while its note
    // changes, and never confused with another password in the same note.
    replacing: null,
    newPassword: '',
    isChecking: false,
    // An update while open: one at a time, and one more when the notes changed meanwhile.
    isUpdating: false,
    updatesAgain: false,
    updateTimer: null,
    stopListening: null,
    drag: null,
});

// ApplicationState refuses a write that changes nothing (opening again on the same threshold):
// write only what differs.
function setField(name, value) {
    if (!stateValuesEqual(state[name], value)) {
        state[name] = value;
    }
}

function newPasswordFor(row) {
    let charset = DEFAULT_PASSWORD_CHARSET;
    if (row.kind === 'region') {
        charset = Array.from(normalizePasswordCharset(DEFAULT_PASSWORD_CHARSET)).filter((character) => !WRAPPER_CHARACTERS.has(character)).join('');
    }
    return generateRandomPassword(DEFAULT_PASSWORD_LENGTH, charset, null);
}

function rowKey(row) {
    return `${row.noteId}:${row.kind}:${row.regionIndex}`;
}

function isReplacing(row) {
    const replacing = state.replacing;
    return replacing !== null && row.noteId === replacing.noteId && row.kind === replacing.kind && row.passwordId === replacing.passwordId;
}

// The row of the password being replaced, where it is now; null once it is gone from its note.
function replacingRow() {
    if (state.result === null) return null;
    const found = state.result.rows.find(isReplacing);
    return found === undefined ? null : found;
}

function replacingHtml(key) {
    let save = '<span class="password-audit-hint">This password is no longer in its note.</span>';
    if (key !== null) {
        save = `
                <span class="password-audit-hint">Change it on the site, then Save.</span>
                <button type="button" class="password-audit-button is-primary" data-audit-save="${escapeHtml(key)}" title="Put it in the note; the old one is kept in a note under it">Save</button>`;
    }
    return `
            <div class="password-audit-replacing">
                <code class="password-audit-new">${escapeHtml(state.newPassword)}</code>
                <button type="button" class="password-audit-button" data-audit-copy>Copy</button>${save}
                <button type="button" class="password-audit-button" data-audit-cancel>Cancel</button>
            </div>`;
}

function summaryText(result) {
    if (result === null) return 'Checking…';
    const parts = GROUPS.filter(([group]) => group !== 'replaced').map(([group, label]) => `${result.summary[group]} ${label.toLowerCase()}`);
    let text = `${result.passwordCount} passwords: ${parts.join(', ')}`;
    if (result.leakCheck === 'unavailable') text += ' (leak check unavailable)';
    return text;
}

// A password in more than one group (reused and weak) shows its replacing once, in the first.
function rowHtml(row, shownReplacing) {
    const key = rowKey(row);
    const tags = row.tags === '' ? '' : `<span class="password-audit-tags">${escapeHtml(row.tags)}</span>`;
    let replace = '';
    if (row.canReplace) {
        replace = `<button type="button" class="password-audit-button" data-audit-replace="${escapeHtml(key)}" title="Make a strong password to change on the site">Replace…</button>`;
    }
    let replacing = '';
    if (isReplacing(row) && !shownReplacing.has(key)) {
        shownReplacing.add(key);
        replacing = replacingHtml(key);
    }
    return `
        <li class="password-audit-row" data-audit-row="${escapeHtml(key)}">
            <div class="password-audit-row-line">
                <span class="password-audit-label" title="${escapeHtml(row.label)}">${escapeHtml(row.label === '' ? '(empty first line)' : row.label)}</span>
                ${tags}
                <span class="password-audit-actions">
                    <button type="button" class="password-audit-button" data-audit-go="${escapeHtml(row.rootNoteId)}" title="Open the note it is in">Go to</button>
                    ${replace}
                </span>
            </div>
            ${replacing}
        </li>`;
}

function groupsHtml(result) {
    if (result === null) return '';
    const shownReplacing = new Set();
    // A password being replaced that left its note (edited or deleted meanwhile): the new one
    // stays to copy, since it may already be in use on the site.
    let gone = '';
    if (state.replacing !== null && replacingRow() === null) {
        gone = replacingHtml(null);
    }
    return gone + GROUPS.map(([group, label]) => {
        const rows = result.rows.filter((row) => row.groups.includes(group));
        if (rows.length === 0) return '';
        return `
            <section class="password-audit-group" data-audit-group="${group}">
                <h4>${escapeHtml(label)} <span class="password-audit-count">${rows.length}</span></h4>
                <ul>${rows.map((row) => rowHtml(row, shownReplacing)).join('')}</ul>
            </section>`;
    }).join('');
}

function thresholdHtml() {
    return WEAK_THRESHOLDS.map((value) => `<button type="button" class="password-audit-segment${state.weakBelow === value ? ' is-chosen' : ''}" data-audit-weak="${value}" aria-pressed="${state.weakBelow === value}">${value}</button>`).join('');
}

const CONTROL_ATTRIBUTES = ['data-audit-go', 'data-audit-replace', 'data-audit-copy', 'data-audit-save', 'data-audit-cancel'];

// Where focus is among the rows' buttons, so drawing them again (an update) leaves it there.
function focusedControlSelector(groups) {
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement) || !groups.contains(focused)) return null;
    const attribute = CONTROL_ATTRIBUTES.find((name) => focused.hasAttribute(name));
    if (attribute === undefined) return null;
    // The form for a password gone from its note sits outside every group and row.
    const parts = [];
    const section = focused.closest('[data-audit-group]');
    if (section !== null) parts.push(`[data-audit-group="${CSS.escape(section.dataset.auditGroup)}"]`);
    const row = focused.closest('[data-audit-row]');
    if (row !== null) parts.push(`[data-audit-row="${CSS.escape(row.dataset.auditRow)}"]`);
    parts.push(`[${attribute}]`);
    return parts.join(' ');
}

function render() {
    const panel = state.element;
    panel.querySelector('.password-audit-summary').textContent = summaryText(state.result);
    panel.querySelector('.password-audit-threshold').innerHTML = thresholdHtml();
    panel.querySelector('.password-audit-leaks input').checked = state.checkLeaks;
    const groups = panel.querySelector('.password-audit-groups');
    const focusedSelector = focusedControlSelector(groups);
    groups.innerHTML = groupsHtml(state.result);
    if (focusedSelector === null) return;
    const control = groups.querySelector(focusedSelector);
    if (control === null) {
        // Gone with its row: focus stays in the panel, so Escape still closes it.
        panel.focus({ preventScroll: true });
        return;
    }
    control.focus({ preventScroll: true });
}

const GROUP_ORDER = GROUPS.map(([group]) => group);

// A row's groups with one changed (added or left out), kept in the panel's order.
function withGroup(groups, group, isIn) {
    const others = groups.filter((each) => each !== group);
    const next = isIn ? [...others, group] : others;
    return GROUP_ORDER.filter((each) => next.includes(each));
}

// The results with weak worked out again from each password's score, which the audit already
// has: switching between 3 and 4 asks the server nothing, leaks least of all (the maintainer,
// 2026-11-12). A kept old password is never weak.
function regroupedByWeakness(result, weakBelow) {
    const rows = result.rows.map((row) => ({
        ...row,
        groups: row.groups.includes('replaced') ? row.groups : withGroup(row.groups, 'weak', row.score < weakBelow),
    }));
    const weak = rows.filter((row) => row.groups.includes('weak')).length;
    return { ...result, rows, summary: { ...result.summary, weak } };
}

// The results with the leak check turned off: its group goes, nothing is asked.
function withoutLeaks(result) {
    const rows = result.rows.map((row) => ({ ...row, groups: withGroup(row.groups, 'leaked', false) }));
    return { ...result, rows, leakCheck: 'off', summary: { ...result.summary, leaked: 0 } };
}

// The passwords still to fix: leaked, reused or weak (old ones are only a hint), each once.
const ISSUE_GROUPS = ['leaked', 'reused', 'weak'];

function openIssues(result) {
    return result.rows.filter((row) => row.groups.some((group) => ISSUE_GROUPS.includes(group))).length;
}

function findRow(key) {
    return state.result.rows.find((row) => rowKey(row) === key);
}

// An answer as the panel shows it now: the threshold or the leak check may have changed while it
// was asked for.
function asShownNow(result) {
    const regrouped = regroupedByWeakness(result, state.weakBelow);
    return state.checkLeaks ? regrouped : withoutLeaks(regrouped);
}

// fresh: the panel opening, everything checked again. Turning the leak check on asks again
// without forgetting the scores. Either way the panel says Checking… meanwhile.
async function check({ fresh }) {
    if (state.isChecking) return;
    setField('isChecking', true);
    setField('result', null);
    if (fresh) setField('replacing', null);
    render();
    // A failed check is a red error (fail loud); the panel says Checking… until it is closed.
    const answer = await NotesAPI.passwordAudit(state.weakBelow, state.checkLeaks, fresh);
    setField('isChecking', false);
    if (state.element === null) return;
    setField('result', asShownNow(answer));
    await state.onAudited(openIssues(state.result));
    render();
    // The notes may have changed while it was asked.
    if (state.updatesAgain) await update();
}

// The notes changed while the panel is open: the answer is asked for again, the server checking
// only what is new, and the panel drawn again in place, no Checking…, nothing highlighted.
async function update() {
    if (state.element === null || state.result === null) return;
    if (state.isChecking || state.isUpdating) {
        setField('updatesAgain', true);
        return;
    }
    setField('updatesAgain', false);
    setField('isUpdating', true);
    const answer = await NotesAPI.passwordAudit(state.weakBelow, state.checkLeaks, false);
    setField('isUpdating', false);
    if (state.element === null) return;
    const before = openIssues(state.result);
    setField('result', asShownNow(answer));
    render();
    const after = openIssues(state.result);
    if (after !== before) await state.onAudited(after);
    if (state.updatesAgain) await update();
}

function updateSoon() {
    if (state.updateTimer !== null) window.clearTimeout(state.updateTimer);
    setField('updateTimer', window.setTimeout(() => {
        setField('updateTimer', null);
        void update();
    }, UPDATE_AFTER_CHANGES_MS));
}

async function onClick(event) {
    const target = event.target instanceof Element ? event.target.closest('button, input') : null;
    if (target === null) return;
    if (target.matches('[data-audit-close]')) {
        closePasswordAudit();
        return;
    }
    if (target.matches('[data-audit-weak]')) {
        const value = Number(target.dataset.auditWeak);
        if (value === state.weakBelow) return;
        setField('weakBelow', value);
        await state.savePreferences({ weakBelow: state.weakBelow, checkLeaks: state.checkLeaks });
        if (state.result !== null) {
            setField('result', regroupedByWeakness(state.result, state.weakBelow));
            render();
            // What still needs attention changed with the threshold.
            await state.onAudited(openIssues(state.result));
        }
        return;
    }
    // The password's top-level note, opened as following a link to it opens it: a Source note
    // view with a way back (the maintainer, 2026-11-12). The panel stays where it is.
    if (target.matches('[data-audit-go]')) {
        const rootNoteId = target.dataset.auditGo;
        await CommandGate.run('passwordAudit.go_to', async () => {
            await openReferenceInNewTab(rootNoteId);
        });
        return;
    }
    if (target.matches('[data-audit-replace]')) {
        const row = findRow(target.dataset.auditReplace);
        setField('replacing', { noteId: row.noteId, kind: row.kind, passwordId: row.passwordId });
        setField('newPassword', newPasswordFor(row));
        render();
        return;
    }
    if (target.matches('[data-audit-cancel]')) {
        setField('replacing', null);
        setField('newPassword', '');
        render();
        return;
    }
    if (target.matches('[data-audit-copy]')) {
        await navigator.clipboard.writeText(state.newPassword);
        target.textContent = 'Copied';
        window.setTimeout(() => { target.textContent = 'Copy'; }, COPIED_SECONDS * MS_PER_SECOND);
        return;
    }
    if (target.matches('[data-audit-save]')) {
        target.disabled = true;
        // Where the password is now: the note may have changed since the last update.
        await update();
        const row = replacingRow();
        if (row === null) return;  // Gone from its note: the panel says so, the new one stays to copy.
        await NotesAPI.replacePassword(row, state.newPassword);
        setField('replacing', null);
        setField('newPassword', '');
        await update();
    }
}

async function onChange(event) {
    if (!(event.target instanceof HTMLInputElement) || !event.target.matches('[data-audit-leaks]')) return;
    setField('checkLeaks', event.target.checked);
    await state.savePreferences({ weakBelow: state.weakBelow, checkLeaks: state.checkLeaks });
    // Only turning the leak check on asks anything; turning it off just drops its group.
    if (!state.checkLeaks && state.result !== null) {
        setField('result', withoutLeaks(state.result));
        render();
        return;
    }
    await check({ fresh: false });
}

// Dragged by its title bar; it stays where it is put while open.
function onPointerDown(event) {
    if (!(event.target instanceof Element) || event.target.closest('button') !== null) return;
    const box = state.element.getBoundingClientRect();
    setField('drag', { dx: event.clientX - box.left, dy: event.clientY - box.top });
    event.currentTarget.setPointerCapture(event.pointerId);
}

function onPointerMove(event) {
    if (state.drag === null) return;
    const panel = state.element;
    const left = Math.min(Math.max(event.clientX - state.drag.dx, 0), window.innerWidth - panel.offsetWidth);
    const top = Math.min(Math.max(event.clientY - state.drag.dy, 0), window.innerHeight - panel.offsetHeight);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.right = 'auto';
}

function onPointerUp() {
    setField('drag', null);
}

function onKeyDown(event) {
    if (event.key === 'Escape') {
        event.stopPropagation();
        closePasswordAudit();
    }
}

function build() {
    const panel = document.createElement('section');
    panel.id = PANEL_ID;
    panel.className = 'password-audit-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Password Audit');
    panel.tabIndex = -1;
    panel.innerHTML = `
        <header class="password-audit-header">
            <h3>Password Audit</h3>
            <button type="button" class="password-audit-close" data-audit-close aria-label="Close" title="Close">×</button>
        </header>
        <div class="password-audit-controls">
            <span class="password-audit-threshold-label" title="zxcvbn scores a password 0 (very weak) to 4 (very strong)">Weak below</span>
            <span class="password-audit-threshold" role="group" aria-label="Weak below"></span>
            <label class="password-audit-leaks" title="Asks Have I Been Pwned whether a password has leaked. Only the first 5 characters of each password's SHA-1 hash are sent, never the password.">
                <input type="checkbox" data-audit-leaks> Check leaks
            </label>
        </div>
        <p class="password-audit-summary" aria-live="polite"></p>
        <div class="password-audit-groups"></div>`;
    panel.addEventListener('click', (event) => { void onClick(event); });
    panel.addEventListener('change', (event) => { void onChange(event); });
    panel.addEventListener('keydown', onKeyDown);
    const header = panel.querySelector('.password-audit-header');
    header.addEventListener('pointerdown', onPointerDown);
    header.addEventListener('pointermove', onPointerMove);
    header.addEventListener('pointerup', onPointerUp);
    return panel;
}

// weakBelow and checkLeaks as saved for this vault; savePreferences(next) keeps a change;
// onAudited(openIssues) follows each audit that runs: the reminder's clock restarts, sooner while
// passwords are still leaked, reused or weak.
export async function openPasswordAudit({ weakBelow, checkLeaks, savePreferences, onAudited }) {
    if (!WEAK_THRESHOLDS.includes(weakBelow) || typeof checkLeaks !== 'boolean' || typeof savePreferences !== 'function'
        || typeof onAudited !== 'function') {
        throw new Error('openPasswordAudit requires the saved threshold, the leak check, a way to save them and what follows an audit');
    }
    setField('weakBelow', weakBelow);
    setField('checkLeaks', checkLeaks);
    setField('savePreferences', savePreferences);
    setField('onAudited', onAudited);
    if (state.element === null) {
        setField('element', build());
        document.body.appendChild(state.element);
    }
    if (state.stopListening === null) {
        setField('stopListening', onNotesChanged(updateSoon));
    }
    state.element.focus({ preventScroll: true });
    await check({ fresh: true });
}

export function closePasswordAudit() {
    if (state.element === null) return;
    state.stopListening();
    setField('stopListening', null);
    if (state.updateTimer !== null) {
        window.clearTimeout(state.updateTimer);
        setField('updateTimer', null);
    }
    setField('updatesAgain', false);
    state.element.remove();
    setField('element', null);
    setField('result', null);
    setField('replacing', null);
    setField('newPassword', '');
}

export function isPasswordAuditOpen() {
    return state.element !== null;
}
