import assert from 'node:assert/strict';
import test from 'node:test';

import { searchContextForDigitKey } from '../../app/static/js/modules/mode-manager/services/search-context-digit-service.js';

// The number keys switch search contexts while nothing is typed (the maintainer, 2026-11-21).
// Journal, Recipes and Work are listed 1 to 3; Journal is the one shown.
const LISTED = ['journal', 'recipes', 'work'];

function chosen(overrides) {
    return searchContextForDigitKey({
        key: '2', hasModifier: false, isMenuOpen: false, listedTabIds: LISTED, shownTabId: 'journal', ...overrides,
    });
}

test('a digit chooses the search context the list gives that number', () => {
    assert.equal(chosen({ key: '2' }), 'recipes');
    assert.equal(chosen({ key: '3' }), 'work');
    assert.equal(chosen({ key: '1', shownTabId: 'work' }), 'journal');
});

test('nine contexts are reached, each by its own digit', () => {
    const nine = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'];
    assert.deepEqual(
        ['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((key) => chosen({ key, listedTabIds: nine, shownTabId: 'j' })),
        ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'],
    );
});

test('a digit with no such context chooses nothing', () => {
    assert.equal(chosen({ key: '7' }), '');
    assert.equal(chosen({ key: '4' }), '');
});

test('the digit of the context already shown chooses nothing', () => {
    assert.equal(chosen({ key: '1' }), '');
});

test('zero, letters and other keys choose nothing', () => {
    for (const key of ['0', 'a', 'Enter', ' ', '10', '!', 'F2']) {
        assert.equal(chosen({ key }), '', key);
    }
});

test('a digit with a key held, or with a menu open, chooses nothing', () => {
    assert.equal(chosen({ hasModifier: true }), '');
    assert.equal(chosen({ isMenuOpen: true }), '');
});
