import assert from 'node:assert/strict';
import test from 'node:test';

import {
    searchTermsOf,
    withSearchTerm,
    withoutSearchTerm,
} from '../../app/static/js/modules/phone/phone-search-terms.js';

// The phone shows a search's terms as pills, each removable with one tap
// (docs/ready-to-build/phone-prototype.md, §2).

test('a search splits into its terms, exclusions and quoted phrases kept whole', () => {
    assert.deepEqual(searchTermsOf('upcoming -journal "spaced repetition" -"old idea"  recipes'), [
        { text: 'upcoming', isExclusion: false },
        { text: '-journal', isExclusion: true },
        { text: '"spaced repetition"', isExclusion: false },
        { text: '-"old idea"', isExclusion: true },
        { text: 'recipes', isExclusion: false },
    ]);
    assert.deepEqual(searchTermsOf('   '), []);
});

test('removing a term leaves the others as they were', () => {
    assert.equal(withoutSearchTerm('upcoming -journal "spaced repetition"', 1), 'upcoming "spaced repetition"');
    assert.equal(withoutSearchTerm('ramen', 0), '');
    assert.throws(() => withoutSearchTerm('ramen', 1), /no term 1/);
});

test('narrowing by a tag adds it once', () => {
    assert.equal(withSearchTerm('upcoming', 'recipes'), 'upcoming recipes');
    assert.equal(withSearchTerm('upcoming recipes', 'recipes'), 'upcoming recipes');
    assert.equal(withSearchTerm('', 'recipes'), 'recipes');
});
