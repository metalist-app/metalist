import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Button labels say what happens, in Title Case, never OK, Yes, Submit or Confirm
// (docs/ui/modals.md, "Dialog and menu conventions", rules 2 and 3; agreed 2026-10-24).
// The order of each row is checked in the browser (scripts/browser-dialog-button-regressions.mjs).

function source(path) {
    return readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
}

const RENAMED = [
    ['app/static/js/modules/command-palette/command-palette-controller.js', "'Remove all'", "'Remove All'"],
    ['app/static/js/modules/command-palette/command-palette-controller.js', "'Trim files'", "'Trim Files'"],
    ['app/static/js/modules/modals/search-suggestion-statistics-modal.js', "'Reset activity'", "'Reset Activity'"],
    ['app/static/js/modules/excalidraw/excalidraw-editor-service.js', 'Discard changes', 'Discard Changes'],
    ['app/static/js/modules/modals/version-info-modal.js', 'Check again', 'Check Again'],
    ['app/static/js/modules/modals/reminder-modal.js', 'Got it', 'Dismiss'],
    ['app/static/js/modules/modals/reminder-modal.js', "'Save changes'", "'Save Changes'"],
    ['app/static/js/modules/modals/reminder-modal.js', "'Add reminder'", "'Add Reminder'"],
    ['app/static/js/modules/modals/reminder-modal.js', 'Clear form', 'Clear Form'],
    ['app/static/js/modules/modals/delete-namespace-modal.js', 'Delete vault</button>', 'Delete Vault'],
    ['app/static/js/modules/modals/backup-restore-modal.js', 'Confirm Restore', 'Restore Backup'],
    ['app/static/js/modules/modals/backup-restore-modal.js', 'Confirm Import', 'Import Backup'],
    ['app/static/js/modules/modals/backup-restore-modal.js', 'Restore Selected Backup', "'Continue'"],
    ['app/static/js/modules/modals/ai-agent-settings-modal.js', 'Save key', 'Save Key'],
    ['app/static/js/modules/modals/ontology-modal.js', "confirmLabel: 'Delete tag'", "confirmLabel: 'Delete Tag'"],
    ['app/static/js/modules/modals/ontology-modal.js', 'Delete tag…', 'Delete Tag…'],
    ['app/static/js/modules/ai-chat/confirmation-card.js', "'Yes'", "'Apply'"],
    ['app/static/js/modules/ai-chat/proposal-menu.js', '>Close</button>', "label: 'Cancel'"],
    ['app/templates/index.html', '>OK</button>', '>Log In</button>'],
];

for (const [path, before, after] of RENAMED) {
    test(`${path} says ${after}, not ${before}`, () => {
        const text = source(path);
        assert.equal(text.includes(before), false, `${before} is still in ${path}`);
        assert.equal(text.includes(after), true, `${after} is missing from ${path}`);
    });
}

test('Back Up Now says it is backing up while the backup runs', () => {
    const text = source('app/static/js/modules/modals/backup-settings-modal.js');
    assert.equal(text.includes("'Backing Up…'"), true);
    assert.equal(/run-btn[^\n]*Saving\.\.\./u.test(text), false, 'the run button still says Saving...');
});
