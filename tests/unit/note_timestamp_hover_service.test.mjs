import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    formatNoteTimestamp,
    syncNoteTimestampDataset,
} from '../../app/static/js/modules/mode-manager/services/note-timestamp-hover-service.js';

test('formatNoteTimestamp formats an ISO timestamp as local date and time', () => {
    const formatted = formatNoteTimestamp('2026-08-17T19:45:00+00:00', {
        locale: 'en-US',
        timeZone: 'UTC',
    });

    assert.equal(formatted, 'Aug 17, 2026, 7:45 PM');
});

test('formatNoteTimestamp rejects missing and invalid timestamps', () => {
    assert.throws(() => formatNoteTimestamp('', {}), /non-empty ISO timestamp/);
    assert.throws(() => formatNoteTimestamp('not-a-date', {}), /invalid ISO timestamp/);
});

test('syncNoteTimestampDataset stores formatted created and updated values', () => {
    const noteElement = { dataset: {} };
    const formattedInputs = [];
    const formatTimestamp = (timestamp) => {
        formattedInputs.push(timestamp);
        return `formatted:${timestamp}`;
    };

    syncNoteTimestampDataset(
        noteElement,
        {
            createdAt: '2026-08-17T18:00:00+00:00',
            updatedAt: '2026-08-17T19:45:00+00:00',
        },
        formatTimestamp,
    );

    assert.deepEqual(formattedInputs, [
        '2026-08-17T18:00:00+00:00',
        '2026-08-17T19:45:00+00:00',
    ]);
    assert.equal(
        noteElement.dataset.noteCreatedDisplay,
        'formatted:2026-08-17T18:00:00+00:00',
    );
    assert.equal(
        noteElement.dataset.noteUpdatedDisplay,
        'formatted:2026-08-17T19:45:00+00:00',
    );
});

test('syncNoteTimestampDataset requires complete timestamp metadata', () => {
    const noteElement = { dataset: {} };

    assert.throws(
        () => syncNoteTimestampDataset(
            noteElement,
            { createdAt: '2026-08-17T18:00:00+00:00' },
            (timestamp) => timestamp,
        ),
        /updatedAt/,
    );
});

test('timestamps use the context-menu info footer, in the theme colours, instead of a hover preference', () => {
    const cssUrl = new URL('../../app/static/css/main.css', import.meta.url);
    const css = readFileSync(cssUrl, 'utf8');

    assert.doesNotMatch(css, /pref-show-note-timestamps/);
    assert.match(css, /\.context-menu-info\s*\{[\s\S]*?background:\s*var\(--modal-surface-raised\)/);
    assert.match(css, /\.context-menu-info\s*\{[\s\S]*?color:\s*var\(--modal-text\)/);
});
