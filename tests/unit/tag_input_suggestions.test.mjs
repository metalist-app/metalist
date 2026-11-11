import assert from 'node:assert/strict';
import test from 'node:test';
import { isTagText, tagsToOffer } from '../../app/static/js/modules/tag-input-offer.js';

const ranked = ['security-questions', 'question', 'quote', '@quote', 'Questions', 'QQQ'];

test('tags starting with the letters come first, each in the ranked order', () => {
    assert.deepEqual(tagsToOffer('q', ranked, []), ['question', 'quote', 'Questions', 'QQQ', 'security-questions']);
});

test('tags already chosen and built-in tags are left out, whatever their case', () => {
    assert.deepEqual(tagsToOffer('q', ranked, ['QUESTION', 'qqq']), ['quote', 'Questions', 'security-questions']);
});

test('nothing is offered for a phrase, a space or nothing typed', () => {
    for (const typed of ['"a phr', "'a", 'two words', '', '   ']) {
        assert.deepEqual(tagsToOffer(typed, ranked, []), [], typed);
        assert.equal(isTagText(typed), false, typed);
    }
    assert.equal(isTagText(' qu '), true);
});

test('at most eight are offered', () => {
    const many = Array.from({ length: 20 }, (unused, index) => `tag-${index}`);
    assert.equal(tagsToOffer('tag', many, []).length, 8);
});
