import assert from 'node:assert/strict';
import test from 'node:test';

import { analyzeSearchQueryInput, enforceSearchQueryInputForEditing, findUnfillableSearchTerm } from '../../app/static/js/modules/mode-manager/services/search-syntax-service.js';

// A star in a search's tag term stands for any letters (docs/ui/search-semantics.md, Wildcards;
// the maintainer, 2026-11-21): the search box keeps it, and no new note is added under it.

test('the search box keeps a star in a tag term', () => {
    for (const typed of ['*burger*', 'burger*', '*burger', 'che*ger', '-*burger*', 'lunch *burger* -soup*']) {
        assert.equal(analyzeSearchQueryInput(typed).sanitizedText, typed, typed);
    }
});

test('stars side by side are one', () => {
    assert.equal(analyzeSearchQueryInput('**burger***').sanitizedText, '*burger*');
});

// "I literally cannot type * into search" (the maintainer, 2026-11-21): a star alone was dropped
// as it was typed, so *burger* could not be begun.
test('a wildcard can be typed one key at a time: a star alone stays in the box and searches nothing', () => {
    let box = '';
    for (const key of '*burger*') {
        box = enforceSearchQueryInputForEditing(box + key);
    }
    assert.equal(box, '*burger*');
    const alone = analyzeSearchQueryInput('lunch *');
    assert.deepEqual({box: alone.enforcedText, searched: alone.sanitizedText, isComplete: alone.isComplete},
        {box: 'lunch *', searched: 'lunch', isComplete: false});
    assert.equal(enforceSearchQueryInputForEditing('-*'), '-*');
    assert.equal(analyzeSearchQueryInput('***').sanitizedText, '');
    assert.equal(findUnfillableSearchTerm('lunch *'), null);
});

test('a comment term is still a comment', () => {
    assert.equal(analyzeSearchQueryInput('/*help*/ burger').sanitizedText, '/*help*/ burger');
    assert.equal(findUnfillableSearchTerm('/*help*/ burger'), null);
});

test('a search with a wildcard takes no new note at its top, unless the wildcard is excluded', () => {
    assert.equal(findUnfillableSearchTerm('*burger*'), '*burger*');
    assert.equal(findUnfillableSearchTerm('lunch burger*'), 'burger*');
    assert.equal(findUnfillableSearchTerm('lunch -*burger*'), null);
    assert.equal(findUnfillableSearchTerm('lunch burger'), null);
});
