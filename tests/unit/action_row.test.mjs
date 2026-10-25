import assert from 'node:assert/strict';
import test from 'node:test';

import { actionRowHtml } from '../../app/static/js/modules/modals/action-row.js';

// The shared button row (docs/ready-to-build/dialog-and-menu-conventions.md): Cancel alone
// while a dialog loads or only stops what runs.

const CANCEL = { id: 'loading-cancel', label: 'Cancel', disabled: false, attributes: [] };

test('a row may hold Cancel alone, with no main action', () => {
    assert.equal(
        actionRowHtml({ alternative: null, cancel: CANCEL, main: null, rowClass: '' }),
        '<div class="form-actions dialog-actions"><button type="button" class="secondary-btn" id="loading-cancel" data-modal-safe-focus>Cancel</button></div>',
    );
});

test('a row without a main action needs Cancel, and nothing beside it', () => {
    assert.throws(() => actionRowHtml({ alternative: null, cancel: null, main: null, rowClass: '' }), /Cancel alone/);
    assert.throws(() => actionRowHtml({ alternative: CANCEL, cancel: CANCEL, main: null, rowClass: '' }), /Cancel alone/);
});
