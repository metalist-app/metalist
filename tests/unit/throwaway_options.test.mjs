import assert from 'node:assert/strict';
import test from 'node:test';

import {parseThrowawayOptions} from '../../scripts/throwaway-options.mjs';

const NONE = {keep: false, empty: false, development: false, notes: null, files: null, scriptedAi: null};

test('no options means the sample notes and a real AI', () => {
  assert.deepEqual(parseThrowawayOptions([]), NONE);
});

test('the flags and the valued options are read in any order', () => {
  assert.deepEqual(
    parseThrowawayOptions(['--scripted-ai', 'tests/fixtures/scripted-ai/search-view.json', '--keep', '--notes', '100000', '--files', '1200', '--development']),
    {keep: true, empty: false, development: true, notes: 100000, files: 1200, scriptedAi: 'tests/fixtures/scripted-ai/search-view.json'},
  );
});

test('an unknown option, a missing value or a bad count stops the start', () => {
  assert.throws(() => parseThrowawayOptions(['--notes']), /--notes needs a value/);
  assert.throws(() => parseThrowawayOptions(['--notes', '--keep']), /--notes needs a value/);
  assert.throws(() => parseThrowawayOptions(['--notes', '0']), /whole number above 0, got 0/);
  assert.throws(() => parseThrowawayOptions(['--notes', '12k']), /whole number above 0, got 12k/);
  assert.throws(() => parseThrowawayOptions(['--scripted-ai']), /--scripted-ai needs a value/);
  assert.throws(() => parseThrowawayOptions(['--huge']), /Unknown option --huge/);
});

test('options that contradict each other stop the start', () => {
  assert.throws(() => parseThrowawayOptions(['--empty', '--notes', '10']), /--empty cannot be combined/);
  assert.throws(() => parseThrowawayOptions(['--files', '10']), /--files needs --notes/);
});
