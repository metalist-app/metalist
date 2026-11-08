import assert from 'node:assert/strict';
import test from 'node:test';

import {
    describeScopeQuestion,
    scopeAnswerValue,
} from '../../app/static/js/modules/ai-chat/bulk-scope-question.js';


const TAGS = {
    kind: 'tag_scope_confirmation',
    root_count: 562,
    batch_count: 4,
    prefix_root_count: 121,
    chooses_focus: true,
    focus: 'both',
};


test('tags over budget offer three choices', () => {
    assert.deepEqual(describeScopeQuestion(TAGS), {
        allLabel: 'Tag all 562',
        prefixLabel: 'Use first 121 only',
        focusDefault: 'both',
    });
});


test('scopes that fit offer no prefix choice', () => {
    assert.equal(
        describeScopeQuestion({ ...TAGS, batch_count: 1, prefix_root_count: 0 }).prefixLabel,
        null,
    );
});


test('answers carry the selected tag focus with the scope choice', () => {
    assert.equal(scopeAnswerValue(TAGS, 'all', 'new'), 'focus_new');
    assert.equal(scopeAnswerValue(TAGS, 'prefix', 'existing'), 'prefix_focus_existing');
    assert.equal(scopeAnswerValue(TAGS, 'cancel', 'new'), 'cancel');
    const fixedFocus = { ...TAGS, chooses_focus: false, focus: 'new' };
    assert.equal(describeScopeQuestion(fixedFocus).focusDefault, null);
    assert.equal(scopeAnswerValue(fixedFocus, 'all', null), 'proceed');
    assert.equal(scopeAnswerValue(fixedFocus, 'prefix', null), 'use_prefix');
});


test('invalid scope questions and answers fail loudly', () => {
    assert.throws(() => describeScopeQuestion({ ...TAGS, kind: 'focus' }), /Unknown bulk question kind/);
    assert.throws(() => describeScopeQuestion({ ...TAGS, focus: 'all' }), /valid focus/);
    assert.throws(() => describeScopeQuestion({ ...TAGS, prefix_root_count: 562 }), /proper leading subset/);
    assert.throws(() => scopeAnswerValue(TAGS, 'all', null), /selected focus/);
    assert.throws(() => scopeAnswerValue({ ...TAGS, chooses_focus: false }, 'all', 'new'), /no focus selector/);
    assert.throws(
        () => scopeAnswerValue({ ...TAGS, prefix_root_count: 0 }, 'prefix', 'new'),
        /offers no prefix/,
    );
});
