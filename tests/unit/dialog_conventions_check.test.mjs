import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import test from 'node:test';

// The dialog conventions, kept (docs/ui/modals.md, "Errors and status", agreed
// 2026-10-25 as step 6):
// - every dialog's button row comes from the shared row (modals/action-row.js), so order,
//   labels, Enter and the narrow-screen stacking stay the same everywhere;
// - no dialog writes an error line into its own layout: refused actions open the error dialog
//   (modals/error-dialog.js), what is wrong while typing floats under its field
//   (modals/field-message.js), and news floats in the corner (floating-messages.js).

const ROOT = new URL('../../', import.meta.url).pathname;
const MODULES = join(ROOT, 'app/static/js/modules');
const SHARED_ROW = 'app/static/js/modules/modals/action-row.js';

const CHECKS = [
    {
        kind: 'button row',
        instead: 'use actionRowHtml (modals/action-row.js)',
        patterns: [
            /class="[^"]*(?<![\w-])(?:form|dialog)-actions(?![\w-])/,
            /className\s*=\s*['"`][^'"`]*(?<![\w-])(?:form|dialog)-actions(?![\w-])/,
        ],
    },
    {
        kind: 'error line',
        instead: 'open the error dialog (showErrorDialog), float a field message (setFieldMessage) or a corner card (ErrorHandler)',
        patterns: [
            /(?<![\w-])error-message(?![\w-])/,
            /role="alert"|setAttribute\('role', 'alert'\)/,
            /data-error(?![\w-])/,
            /class(?:Name)?\s*=\s*['"`][^'"`]*\w-error(?![\w-])/,
        ],
    },
];

// Each exception: where, which kind, how many lines, and why. A new line of that kind in that
// file fails the check like any other.
const EXCEPTIONS = [
    { file: 'app/static/js/modules/modals/memory-usage-modal.js', kind: 'button row', count: 1,
        reason: 'Copy and Refresh are tools of a read-only dialog, not its answer' },
    { file: 'app/static/js/modules/modals/random-password-modal.js', kind: 'button row', count: 1,
        reason: 'Regenerate is a tool of the generator, not the dialog\'s answer' },
    { file: 'app/static/js/modules/modals/backup-settings-modal.js', kind: 'button row', count: 1,
        reason: 'Choose Folder… and Clear are tools of the folder field' },
    { file: 'app/static/js/modules/modals/search-suggestion-statistics-modal.js', kind: 'button row', count: 1,
        reason: 'Reset Activity… opens the dialog\'s own confirmation, which uses the shared row' },
    { file: 'app/static/js/modules/ai-chat/confirmation-card.js', kind: 'button row', count: 1,
        reason: 'AI chat content: a confirmation inside the conversation' },
    { file: 'app/static/js/modules/ai-chat/confirmation-card.js', kind: 'error line', count: 1,
        reason: 'AI chat content: a confirmation inside the conversation' },
    { file: 'app/static/js/modules/ai-chat/ai-chat-panel-controller.js', kind: 'error line', count: 1,
        reason: 'AI chat content: a message in the conversation' },
    { file: 'app/static/js/modules/ai-chat/ai-agent-debug-view.js', kind: 'error line', count: 1,
        reason: 'a developer view of the AI\'s steps' },
    { file: 'app/static/js/modules/mode-manager/services/shell-output-service.js', kind: 'error line', count: 1,
        reason: 'a shell command\'s output, written into the note' },
    { file: 'app/static/js/modules/ai-chat/bulk-proposal-ui.js', kind: 'button row', count: 1,
        reason: 'AI chat content: a tagging or summary operation inside the conversation' },
    { file: 'app/static/js/modules/ai-chat/bulk-proposal-ui.js', kind: 'error line', count: 3,
        reason: 'AI chat content: a tagging or summary operation inside the conversation' },
];

function sourceFiles(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return sourceFiles(path);
        return entry.name.endsWith('.js') ? [path] : [];
    });
}

// Every line that breaks a convention: { file, line, kind, instead, text }.
export function findDialogConventionViolations(files) {
    const violations = [];
    for (const { path, source } of files) {
        if (path === SHARED_ROW) continue;
        source.split('\n').forEach((text, index) => {
            for (const check of CHECKS) {
                if (check.patterns.some((pattern) => pattern.test(text))) {
                    violations.push({ file: path, line: index + 1, kind: check.kind, instead: check.instead, text: text.trim() });
                }
            }
        });
    }
    return violations;
}

// The violations no exception covers, and the exceptions whose count is off.
function unexcused(violations) {
    const problems = [];
    for (const exception of EXCEPTIONS) {
        const found = violations.filter((violation) => violation.file === exception.file && violation.kind === exception.kind);
        if (found.length !== exception.count) {
            problems.push(`${exception.file}: ${found.length} ${exception.kind}(s) where the exception allows ${exception.count} (${exception.reason})`
                + found.map((violation) => `\n    ${violation.line}: ${violation.text}`).join(''));
        }
    }
    const excused = (violation) => EXCEPTIONS.some((exception) => exception.file === violation.file && exception.kind === violation.kind);
    for (const violation of violations.filter((candidate) => !excused(candidate))) {
        problems.push(`${violation.file}:${violation.line}: a ${violation.kind} written by the dialog itself; ${violation.instead}\n    ${violation.text}`);
    }
    return problems;
}

test('no dialog writes its own button row or error line', () => {
    const files = sourceFiles(MODULES).map((path) => ({ path: relative(ROOT, path), source: readFileSync(path, 'utf8') }));
    assert.deepEqual(unexcused(findDialogConventionViolations(files)), []);
});

test('the check fails on a dialog that writes its own row and error line', () => {
    const wrong = {
        path: 'app/static/js/modules/modals/wrong-modal.js',
        source: [
            "const html = `<div class=\"form-actions\"><button>Save</button></div>",
            '<p class="error-message">${error}</p>`;',
            "row.className = 'dialog-actions';",
            "line.setAttribute('role', 'alert');",
            '<p class="settings-key-error">${keyError}</p>',
        ].join('\n'),
    };
    const found = findDialogConventionViolations([wrong]).map((violation) => [violation.line, violation.kind]);
    assert.deepEqual(found, [[1, 'button row'], [2, 'error line'], [3, 'button row'], [4, 'error line'], [5, 'error line']]);
    assert.equal(unexcused(findDialogConventionViolations([wrong])).length, found.length + EXCEPTIONS.length,
        'every line fails, and every exception, found nowhere here, is off');
});

test('the shared row itself may write the row', () => {
    const shared = { path: SHARED_ROW, source: 'return `<div class="form-actions dialog-actions">`;' };
    assert.deepEqual(findDialogConventionViolations([shared]), []);
});
