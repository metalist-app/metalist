import { escapeHtml } from '../html-escape.js';

// Every dialog's action row (docs/ready-to-build/dialog-and-menu-conventions.md, rules 1-7):
// a rare alternative at the far left, then Cancel or Back, then the main action rightmost.
// On a narrow screen the row stacks with the main action on top (main.css, .dialog-actions).
// A destructive main action is red, Enter never presses it and its view starts on Cancel
// (BaseModal); another main action may be the dialog's Enter action.

const ATTRIBUTE_NAME = /^[a-z][a-z0-9-]*$/u;
const BUTTON_TYPES = new Set(['button', 'submit']);

function attributesHtml(spec, extraNames) {
    if (typeof spec.label !== 'string' || spec.label.trim() === '') {
        throw new Error('An action row button needs a label');
    }
    if (spec.id !== null && (typeof spec.id !== 'string' || spec.id === '')) {
        throw new Error('An action row button id must be null or a non-empty string');
    }
    if (typeof spec.disabled !== 'boolean') {
        throw new Error(`Action row button ${spec.label} needs a boolean disabled`);
    }
    if (!Array.isArray(spec.attributes)) {
        throw new Error(`Action row button ${spec.label} needs an attributes list`);
    }
    const names = [...extraNames, ...spec.attributes];
    for (const name of names) {
        if (typeof name !== 'string' || !ATTRIBUTE_NAME.test(name)) {
            throw new Error(`Action row attribute must be a plain name, not ${name}`);
        }
    }
    const parts = [];
    if (spec.id !== null) {
        parts.push(`id="${escapeHtml(spec.id)}"`);
    }
    parts.push(...names);
    if (spec.disabled) {
        parts.push('disabled');
    }
    return parts.join(' ');
}

function buttonHtml(type, className, spec, extraNames) {
    return `<button type="${type}" class="${className}" ${attributesHtml(spec, extraNames)}>${escapeHtml(spec.label)}</button>`;
}

/**
 * The row's HTML. Each button is { id (or null), label, disabled, attributes (plain
 * attribute names such as data-password-submit) }; `main` adds isDestructive, isEnterAction
 * and type ('button' or 'submit'); `alternative` may be null, and `cancel` too in a dialog
 * that its × alone closes (Reminders). `rowClass` adds the dialog's own layout class (or is '').
 */
export function actionRowHtml({ alternative, cancel, main, rowClass }) {
    if (typeof rowClass !== 'string') {
        throw new Error('actionRowHtml needs a rowClass string');
    }
    if (typeof main.isDestructive !== 'boolean' || typeof main.isEnterAction !== 'boolean') {
        throw new Error(`Main action ${main.label} needs boolean isDestructive and isEnterAction`);
    }
    if (main.isDestructive && main.isEnterAction) {
        throw new Error(`Enter never presses a destructive action: ${main.label}`);
    }
    if (!BUTTON_TYPES.has(main.type)) {
        throw new Error(`Main action ${main.label} type must be button or submit`);
    }
    const buttons = [];
    if (alternative !== null) {
        buttons.push(buttonHtml('button', 'secondary-btn dialog-actions-alternative', alternative, []));
    }
    if (cancel !== null) {
        buttons.push(buttonHtml('button', 'secondary-btn', cancel, ['data-modal-safe-focus']));
    } else if (main.isDestructive) {
        throw new Error(`A destructive action needs Cancel beside it: ${main.label}`);
    }
    let mainClass = 'primary-btn';
    const mainRole = [];
    if (main.isDestructive) {
        mainClass = 'danger-btn';
        mainRole.push('data-modal-destructive');
    } else if (main.isEnterAction) {
        mainRole.push('data-modal-enter-action');
    }
    buttons.push(buttonHtml(main.type, mainClass, main, mainRole));
    const classes = ['form-actions', 'dialog-actions'];
    if (rowClass !== '') {
        classes.push(rowClass);
    }
    return `<div class="${escapeHtml(classes.join(' '))}">${buttons.join('')}</div>`;
}
