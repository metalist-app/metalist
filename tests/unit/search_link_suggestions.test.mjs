import assert from 'node:assert/strict';
import test from 'node:test';

import { searchesToOffer } from '../../app/static/js/modules/mode-manager/services/search-link-suggestions.js';
import { chosenSearchLinkText } from '../../app/static/js/modules/mode-manager/services/reference-text.js';

const contexts = [
    { tabId: 'recipes', search: 'recipes', isSearch: true },
    { tabId: 'work', search: 'work -archive', isSearch: true },
    { tabId: 'folder', search: 'work', isSearch: false },
    { tabId: 'blank', search: '', isSearch: true },
    { tabId: 'brackets', search: 'work [draft]', isSearch: true },
    { tabId: 'again', search: 'work -archive', isSearch: true },
    { tabId: 'workout', search: 'Workout', isSearch: true },
];

test('typed text offers the search contexts whose search holds it, the current one first', () => {
    assert.deepEqual(searchesToOffer({ query: 'wo', contexts, activeTabId: 'workout', isEmbed: false }), ['Workout', 'work -archive']);
    assert.deepEqual(searchesToOffer({ query: 'search:rec', contexts, activeTabId: 'work', isEmbed: false }), ['recipes']);
});

test('nothing typed offers the current search context alone', () => {
    assert.deepEqual(searchesToOffer({ query: '', contexts, activeTabId: 'work', isEmbed: false }), ['work -archive']);
    // A folder context, a blank search and one with brackets are never offered.
    for (const activeTabId of ['folder', 'blank', 'brackets']) {
        assert.deepEqual(searchesToOffer({ query: '', contexts, activeTabId, isEmbed: false }), []);
    }
});

test('after ![[ the same searches are offered: an embedded search shows the results', () => {
    assert.deepEqual(searchesToOffer({ query: 'wo', contexts, activeTabId: 'work', isEmbed: true }), ['work -archive', 'Workout']);
});

test('choosing a search writes its link, its closing brackets once', () => {
    assert.equal(chosenSearchLinkText('work -archive', ' and more'), '[[search:work -archive]]');
    assert.equal(chosenSearchLinkText('work -archive', ']] and more'), '[[search:work -archive');
    assert.equal(chosenSearchLinkText('work -archive', '|Current work]]'), '[[search:work -archive');
});
