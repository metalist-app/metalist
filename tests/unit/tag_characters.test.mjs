import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { foldTagCase, isTextCharacter, normalizeText } from '../../app/static/js/modules/tag-characters.js';
import { normalizeTagBarInput } from '../../app/static/js/modules/mode-manager/services/tag-syntax-service.js';
import { analyzeSearchQueryInput } from '../../app/static/js/modules/mode-manager/services/search-syntax-service.js';
import { normalizeSelectedTextForTagAction } from '../../app/static/js/modules/mode-manager/services/selected-text-tag-service.js';

// Tags and searches in any script (docs/ui/tag-bar.md, Whitespace + Tokens; decided
// 2026-10-30). The browser folds case as the server's str.casefold does: from the shared
// table, else toLowerCase one character at a time. test_tag_characters.py keeps the table
// and this lowercase fixture in step with Python.

const LOWERCASE = JSON.parse(readFileSync(new URL('./fixtures/unicode-lowercase.json', import.meta.url), 'utf8')).lowercase;
const LAST_CODE_POINT = 0x10FFFF;
const FIRST_SURROGATE = 0xD800;
const LAST_SURROGATE = 0xDFFF;
const HEXADECIMAL = 16;
const MIN_HEX_DIGITS = 4;

test('the browser lowercases every character as Python does', () => {
    const differing = [];
    for (let codePoint = 0; codePoint <= LAST_CODE_POINT; codePoint += 1) {
        if (codePoint >= FIRST_SURROGATE && codePoint <= LAST_SURROGATE) continue;
        const character = String.fromCodePoint(codePoint);
        const key = codePoint.toString(HEXADECIMAL).toUpperCase().padStart(MIN_HEX_DIGITS, '0');
        const expected = Object.hasOwn(LOWERCASE, key) ? LOWERCASE[key] : character;
        if (character.toLowerCase() !== expected) differing.push(key);
    }
    assert.deepEqual(differing, []);
});

test('tag case folds as casefold does', () => {
    assert.equal(foldTagCase('Straße'), foldTagCase('STRASSE'));
    assert.equal(foldTagCase('ΣΑΣ'), 'σασ', 'a final sigma folds to σ');
    assert.equal(foldTagCase('CAFÉ'), 'café');
});

test('text characters: any script and emoji, no control or invisible characters', () => {
    for (const kept of ['é', '日', '🏃', ' ', '‍', '‌']) assert.equal(isTextCharacter(kept), true, kept);
    for (const dropped of ['​', '‏', '﻿', '­', '\u0007']) assert.equal(isTextCharacter(dropped), false, dropped);
    assert.equal(normalizeText('Café'), 'Café');
});

test('the tag bar keeps tags in any script, in one form', () => {
    assert.equal(normalizeTagBarInput('Café 日記 🏃'), 'Café 日記 🏃');
    assert.equal(normalizeTagBarInput('Café'), 'Café');
    assert.equal(normalizeTagBarInput('fo​o ba‏r'), 'foo bar');
    assert.equal(normalizeTagBarInput('one two'), 'one two');
    assert.equal(normalizeTagBarInput('👨‍👩‍👧'), '👨‍👩‍👧');
    assert.equal(normalizeTagBarInput('Lauf:Größe=5 日記:時間=3'), 'Lauf:Größe=5 日記:時間=3');
    assert.equal(normalizeTagBarInput('x /*naïve 日記*/'), 'x /*naïve 日記*/');
});

test('a search keeps quoted text, tags and property names in any script', () => {
    assert.equal(analyzeSearchQueryInput('"naïve" café').enforcedText, '"naïve" café');
    assert.equal(analyzeSearchQueryInput('日記:時間>2').enforcedText, '日記:時間>2');
    assert.equal(analyzeSearchQueryInput('Lauf:Größe>3').enforcedText, 'Lauf:Größe>3');
});

test('selected text in any script can become a tag', () => {
    // Before, a selection with no ASCII letters left no tag, so the action was not offered.
    assert.equal(normalizeSelectedTextForTagAction('日記'), '日記');
    assert.equal(normalizeSelectedTextForTagAction('\u200b'), null);
});
