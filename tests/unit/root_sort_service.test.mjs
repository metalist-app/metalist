import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ROOT_SORT_MODES,
    buildRootDateSeparatorPlan,
    getRootSortModeIndicatorLabel,
    getRootSortModeChipLabel,
    isRootReorderLocked,
    rootNoteCreationBlockMessage,
} from '../../app/static/js/modules/mode-manager/services/root-sort-service.js';

test('isRootReorderLocked locks every non-normal sort mode', () => {
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.NORMAL), false);
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.CREATED), true);
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.UPDATED), true);
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.ALPHABETICAL), true);
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.CONTENT_VOLUME), true);
});

test('buildRootDateSeparatorPlan emits one separator per day bucket transition', () => {
    const plan = buildRootDateSeparatorPlan(
        ['root-a', 'root-b', 'root-c', 'root-d'],
        {
            'root-a': { key: '2026-04-19', label: '2026/04/19 - Sunday' },
            'root-b': { key: '2026-04-19', label: '2026/04/19 - Sunday' },
            'root-c': { key: '2026-04-18', label: '2026/04/18 - Saturday' },
            'root-d': { key: '2026-04-17', label: '2026/04/17 - Friday' },
        },
        '',
    );

    assert.deepEqual(plan, [
        { rootId: 'root-a', bucketKey: '2026-04-19', label: '2026/04/19 - Sunday' },
        { rootId: 'root-c', bucketKey: '2026-04-18', label: '2026/04/18 - Saturday' },
        { rootId: 'root-d', bucketKey: '2026-04-17', label: '2026/04/17 - Friday' },
    ]);
});

test('getRootSortModeIndicatorLabel returns dismissible pill text for sorted modes', () => {
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.NORMAL), '');
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.CREATED), 'Sorted by datetime created');
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.UPDATED), 'Sorted by datetime last updated');
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.ALPHABETICAL), 'Sorted alphabetically');
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.CONTENT_VOLUME), 'Sorted by content volume');
});

test('the text order and the File size order have chips of their own', () => {
    assert.equal(getRootSortModeChipLabel(ROOT_SORT_MODES.CONTENT_VOLUME), 'Length');
    assert.equal(getRootSortModeChipLabel(`${ROOT_SORT_MODES.CONTENT_VOLUME}-reversed`), 'Length \u2191');
    assert.equal(getRootSortModeChipLabel(ROOT_SORT_MODES.FILE_SIZE), 'File size');
    assert.equal(getRootSortModeChipLabel(`${ROOT_SORT_MODES.FILE_SIZE}-reversed`), 'File size \u2191');
    assert.equal(getRootSortModeIndicatorLabel(ROOT_SORT_MODES.FILE_SIZE), 'Sorted by file size, largest first');
    assert.equal(isRootReorderLocked(ROOT_SORT_MODES.FILE_SIZE), true);
    assert.match(rootNoteCreationBlockMessage(ROOT_SORT_MODES.FILE_SIZE, 'top'), /sort order/);
});

test('buildRootDateSeparatorPlan continues the day bucket from above the loaded band', () => {
    const buckets = {
        'root-b': { key: '2026-04-19', label: '2026/04/19 - Sunday' },
        'root-c': { key: '2026-04-18', label: '2026/04/18 - Saturday' },
    };
    const plan = buildRootDateSeparatorPlan(['root-b', 'root-c'], buckets, '2026-04-19');

    assert.deepEqual(plan.map((entry) => entry.rootId), ['root-c']);
    assert.deepEqual(buildRootDateSeparatorPlan(['root-b'], buckets, '2026-04-20').map((entry) => entry.rootId), ['root-b']);
});

test('rootNoteCreationBlockMessage allows new root notes only where they land in view', () => {
    const allowed = (mode, placement) => rootNoteCreationBlockMessage(mode, placement) === null;
    assert.equal(allowed(ROOT_SORT_MODES.NORMAL, 'top'), true);
    assert.equal(allowed(ROOT_SORT_MODES.NORMAL, 'below'), true);
    // Newest-first date sorts put a new note at the top, never below a root.
    for (const mode of [ROOT_SORT_MODES.CREATED, ROOT_SORT_MODES.UPDATED]) {
        assert.equal(allowed(mode, 'top'), true, mode);
        assert.equal(allowed(mode, 'below'), false, mode);
    }
    // An empty note sorts far away in these.
    for (const mode of [ROOT_SORT_MODES.ALPHABETICAL, ROOT_SORT_MODES.CONTENT_VOLUME]) {
        assert.equal(allowed(mode, 'top'), false, mode);
        assert.equal(allowed(mode, 'below'), false, mode);
    }
    assert.match(rootNoteCreationBlockMessage(ROOT_SORT_MODES.CONTENT_VOLUME, 'top'), /sort order/);
    assert.match(rootNoteCreationBlockMessage(ROOT_SORT_MODES.CREATED, 'below'), /sort order/);
    assert.throws(() => rootNoteCreationBlockMessage(ROOT_SORT_MODES.NORMAL, 'child'), /placement/);
});
