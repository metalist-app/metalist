import assert from 'node:assert/strict';
import test from 'node:test';

import {
    opensValue,
    quotedValueEnd,
    splitTokens,
    tokenEnd,
    unquoteValue,
} from '../../app/static/js/modules/quoted-values.js';
import {
    analyzeTagBarInput,
    enforceTagBarInput,
    enforceTagBarInputForEditing,
    findTagAtIndexInTagBar,
    splitTagsForDisplay,
} from '../../app/static/js/modules/mode-manager/services/tag-syntax-service.js';
import {
    analyzeSearchQueryInput,
    findUnfillableSearchTerm,
} from '../../app/static/js/modules/mode-manager/services/search-syntax-service.js';
import { scanTopLevelTagTokens } from '../../app/static/js/modules/mode-manager/services/add-style-service.js';
import { searchTermsOf } from '../../app/static/js/modules/phone/phone-search-terms.js';

// Quoted tag values (docs/design/tag-properties.md, Quoted values), as the browser reads them.

test('a quote straight after an operator opens a value, anywhere else nothing', () => {
    assert.equal(opensValue('author="x"', 7), true);
    assert.equal(opensValue('year>"1960"', 5), true);
    assert.equal(opensValue('author "x"', 7), false);
    assert.equal(opensValue("author='Brien", 7), false);
    assert.equal(opensValue('"x"', 0), false);
});

test('a quoted value runs to its closing quote, past escaped quotes, or to the end when open', () => {
    const text = 'title="The \\"Best\\" Book" next';
    assert.deepEqual({ ...quotedValueEnd(text, 6) }, { end: 25, isClosed: true });
    assert.deepEqual({ ...quotedValueEnd('author="Ursula Le', 7) }, { end: 17, isClosed: false });
});

test('tokens keep a quoted value whole with its spaces', () => {
    assert.deepEqual(splitTokens('author="Ursula Le Guin" book:title="Dune: Messiah" sf'),
        ['author="Ursula Le Guin"', 'book:title="Dune: Messiah"', 'sf']);
    assert.deepEqual(splitTokens('author "Ursula Le Guin"'), ['author', '"Ursula', 'Le', 'Guin"']);
    assert.deepEqual(splitTokens("author=O'Brien x"), ["author=O'Brien", 'x']);
    assert.equal(tokenEnd('a="b c', 0), 6);
});

test('a value is read without its quotes and escapes', () => {
    assert.equal(unquoteValue('"The \\"Best\\" Book"'), 'The "Best" Book');
    assert.equal(unquoteValue('"a\\\\b"'), 'a\\b');
    assert.equal(unquoteValue('"Ursula Le'), 'Ursula Le');
    assert.equal(unquoteValue("O'Brien"), "O'Brien");
});

test('the tag bar keeps a quoted value as one tag', () => {
    for (const tags of [
        'author="Ursula Le Guin"',
        'book:title="A Wizard of Earthsea"',
        'book:title="Dune: Messiah":year=1969',
        'title="The \\"Best\\" Book"',
        "author=O'Brien",
    ]) {
        assert.equal(enforceTagBarInput(tags), tags, tags);
        assert.deepEqual(splitTagsForDisplay(tags).map((part) => part.text), [tags], tags);
        assert.equal(analyzeTagBarInput(tags).isValid, true, tags);
        assert.equal(analyzeTagBarInput(tags).sanitizedText, tags, tags);
    }
});

test('the tag bar closes an open value when the user moves on, and removes an empty one', () => {
    assert.equal(enforceTagBarInputForEditing('author="Ursula Le'), 'author="Ursula Le');
    assert.equal(enforceTagBarInput('author="Ursula Le'), 'author="Ursula Le"');
    assert.equal(enforceTagBarInput('author="'), 'author');
    assert.equal(enforceTagBarInput('author=""'), 'author');
});

test('a tag and a quoted text are two things when a space parts them', () => {
    assert.notDeepEqual(splitTagsForDisplay('author "Ursula Le Guin"').map((part) => part.text), ['author "Ursula Le Guin"']);
});

test('anywhere on a quoted value is its tag', () => {
    const tags = 'sf book:title="A Wizard of Earthsea" x';
    const atom = findTagAtIndexInTagBar(tags, tags.indexOf('Wizard'));
    assert.equal(atom.text, 'book');
    assert.equal(tags.slice(atom.start, atom.end), 'book:title="A Wizard of Earthsea"');
});

test('a search with a quoted value is complete and searches as typed while the quote is open', () => {
    for (const query of ['author="Ursula Le Guin"', ':foo="ba"', 'book:title="Dune: Messiah"', 'author>"M"',
        'title="The \\"Best\\" Book"', "author=O'Brien"]) {
        const analysis = analyzeSearchQueryInput(query);
        assert.equal(analysis.isComplete, true, query);
        assert.equal(analysis.warningMessage, null, query);
    }
    const open = analyzeSearchQueryInput('author="Ursula Le');
    assert.equal(open.isComplete, true);
    assert.equal(open.closedText, 'author="Ursula Le"');
    assert.equal(analyzeSearchQueryInput('author="').closedText, '');
});

test('a new note cannot be added in a search no new note matches', () => {
    for (const [query, term] of [
        ['jogging:miles>3', 'jogging:miles>3'],
        ['sample jogging:miles>=3', 'jogging:miles>=3'],
        [':foo="ba"', ':foo="ba"'],
        ['jogging:miles?', 'jogging:miles?'],
        ['jogging:miles', 'jogging:miles'],
        ['jogging:miles=MAX', 'jogging:miles=MAX'],
        ['@sum:calories>2000', '@sum:calories>2000'],
        // A chain is filled only when every condition names a value.
        ['jogging:miles=3:duration>30', 'jogging:miles=3:duration>30'],
        ['jogging:miles=3:duration', 'jogging:miles=3:duration'],
        [':foo="bar":baz=3', ':foo="bar":baz=3'],
    ]) {
        assert.equal(findUnfillableSearchTerm(query), term, query);
    }
    for (const query of ['', 'jogging', 'jogging:miles=3', 'book:author="Le Guin"', 'author="Le Guin"',
        '-jogging:miles>3', 'sample OR jogging:miles>3', 'author "Ursula Le Guin"',
        'jogging:miles=3:duration=30', 'book:title="Dune":year=1965', 'run:start=10:30pm:miles=3']) {
        assert.equal(findUnfillableSearchTerm(query), null, query);
    }
});

test('style and phone readers keep a quoted value whole', () => {
    assert.deepEqual(scanTopLevelTagTokens('author="Ursula Le Guin" [x]'), ['author="Ursula Le Guin"', '[x]']);
    assert.deepEqual(searchTermsOf('sf author="Le Guin" -x').map((term) => term.text), ['sf', 'author="Le Guin"', '-x']);
});

test('closing a property value keeps escaped backslashes and drops one left escaping the end', () => {
    assert.equal(enforceTagBarInput('jogging:note="a\\'), 'jogging:note="a"');
    assert.equal(enforceTagBarInput('jogging:note="a\\\\'), 'jogging:note="a\\\\"');
    assert.equal(enforceTagBarInput('jogging:note="a\\\\\\'), 'jogging:note="a\\\\"');
    assert.equal(enforceTagBarInput('jogging:note="\\'), 'jogging');
});

test('a property without a value, or named twice, is removed once the user moves on', () => {
    assert.equal(enforceTagBarInput('jogging:miles:note="x"'), 'jogging:note="x"');
    assert.equal(enforceTagBarInput('jogging:miles=3:miles=4'), 'jogging:miles=3');
    assert.equal(enforceTagBarInput('jogging:=3'), 'jogging');
});
