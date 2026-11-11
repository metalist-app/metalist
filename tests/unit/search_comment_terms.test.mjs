import assert from 'node:assert/strict';
import test from 'node:test';

import { analyzeSearchQueryInput, findSearchTagAtIndex } from '../../app/static/js/modules/mode-manager/services/search-syntax-service.js';

// `/*help*/` in the search box is a tag bar's comment, kept whole with its spaces
// (app/services/search_query.py, comment terms; docs/ui/search-semantics.md, Comment Terms).

test('a comment term is kept as typed and searched whole', () => {
    const typed = analyzeSearchQueryInput('/*help me*/ Bookmarks/ -/*later*/');
    assert.equal(typed.enforcedText, '/*help me*/ Bookmarks/ -/*later*/');
    assert.equal(typed.sanitizedText, '/*help me*/ Bookmarks/ -/*later*/');
    assert.equal(typed.isComplete, true);
    assert.equal(typed.warningMessage, null);
});

test('a comment still being typed searches as if closed, as an open quote does', () => {
    const typing = analyzeSearchQueryInput('work /*hel');
    assert.equal(typing.enforcedText, 'work /*hel');
    assert.equal(typing.sanitizedText, 'work /*hel*/');
    assert.equal(typing.closedText, 'work /*hel*/');
    assert.equal(typing.endsInOpenQuote, true);
    assert.equal(typing.warningMessage, null);
    assert.equal(analyzeSearchQueryInput('/*help ').enforcedText, '/*help ');
    assert.equal(analyzeSearchQueryInput('/*').sanitizedText, '');
    // Typed a character at a time: the `/` stays until its `*` comes.
    for (const step of ['/', 'work /', '-/']) {
        assert.equal(analyzeSearchQueryInput(step).enforcedText, step, step);
    }
    assert.equal(analyzeSearchQueryInput('/x').enforcedText, 'x');
});

test('an empty comment says how to fix it', () => {
    const empty = analyzeSearchQueryInput('/* */ work');
    assert.equal(empty.isComplete, false);
    assert.match(empty.warningMessage, /between \/\* and \*\//);
});

test('the cursor in a comment is in no tag', () => {
    assert.equal(findSearchTagAtIndex('/*help*/ work', 3), null);
    assert.equal(findSearchTagAtIndex('/*help*/ work', 11).tag, 'work');
});
