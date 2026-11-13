import assert from 'node:assert/strict';
import test from 'node:test';

import { problemReportFileName } from '../../app/static/js/modules/problem-reports/report-file-names.js';

// Every report file is named one way, by the local date and time it was saved: one report, or a
// bundle of kept ones with the plural (the maintainer, 2026-11-12: three ways had grown, two in
// UTC, so his dad's 6:52 PM export said 02-52).
const SAVED_AT = new Date(2026, 10, 12, 18, 52, 9);

test('a report file is named by the local date and time it was saved', () => {
    assert.equal(problemReportFileName({ isBundle: false, savedAt: SAVED_AT }), 'metalist-problem-report-2026-11-12 18-52-09');
});

test('a bundle of kept reports takes the plural, and the same date and time', () => {
    assert.equal(problemReportFileName({ isBundle: true, savedAt: SAVED_AT }), 'metalist-problem-reports-2026-11-12 18-52-09');
});

test('single digits are padded, so names sort by time', () => {
    assert.equal(problemReportFileName({ isBundle: false, savedAt: new Date(2027, 0, 3, 4, 5, 6) }), 'metalist-problem-report-2027-01-03 04-05-06');
});
