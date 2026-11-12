import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';
import test from 'node:test';

import {
    DEFAULT_PASSPHRASE_WORD_COUNT,
    MAX_PASSPHRASE_WORD_COUNT,
    WORDLIST_SIZE,
    generatePassphrase,
    parseWordlist,
    suggestPassphrase,
} from '../../app/static/js/modules/passphrase.js';
import { PASSWORD_MAX_LENGTH } from '../../app/static/js/modules/password-policy.js';

// docs/security/README.md, "Password Requirements": suggestions are five words of EFF's long
// wordlist, drawn without bias, and always pass the vault password rule.
const require = createRequire(import.meta.url);
const vendoredZxcvbn = require('../../app/static/js/vendor/zxcvbn-4.4.2.js');
const WORDS = parseWordlist(readFileSync(new URL('../../app/static/js/vendor/eff-large-wordlist-2016-07-18.txt', import.meta.url), 'utf8'));
const fillRandomValues = (buffer) => webcrypto.getRandomValues(buffer);
// 10,000 all scored 4 when measured (2026-10-29, both zxcvbns); 1,000 keeps the suite quick.
const SUGGESTIONS = 1000;
const VERY_STRONG = 4;
// Draws for the evenness check, and how far above its expected count (about 6.4) a word may
// come up: about seven standard deviations, so a fair draw never trips it.
const EVENNESS_DRAWS = 50000;
const EVENNESS_SLACK = 7;

test('the bundled wordlist holds 7,776 distinct lowercase words', () => {
    assert.equal(WORDS.length, WORDLIST_SIZE);
    assert.deepEqual([WORDS[0], WORDS[WORDS.length - 1]], ['abacus', 'zoom']);
});

test('1,000 suggestions are list words that score 4', () => {
    // A few list words hold a hyphen (drop-down): their halves count as list words too.
    const parts = new Set(WORDS.flatMap((word) => word.split('-')));
    for (let index = 0; index < SUGGESTIONS; index += 1) {
        let score = null;
        const scoring = (password, userInputs) => {
            score = vendoredZxcvbn(password, userInputs).score;
            return { score };
        };
        const suggestion = suggestPassphrase(WORDS, scoring, fillRandomValues);
        assert.equal(score, VERY_STRONG, suggestion);
        assert.ok(suggestion.length <= PASSWORD_MAX_LENGTH, suggestion);
        assert.ok(suggestion.split('-').every((part) => parts.has(part)), suggestion);
    }
});

// A passphrase is read back word by word by splitting at hyphens, so a hyphenated list word
// (drop-down, felt-tip, t-shirt, yo-yo) comes back as its halves: down and shirt are list
// words too, and yo-yo gives yo twice, so they came up about twice as often and tripped the
// check now and then (macOS CI, 2026-11-12). Their halves are left out of the count.
const HYPHENATED_WORD_HALVES = new Set(WORDS.filter((word) => word.includes('-')).flatMap((word) => word.split('-')));

test('every word comes up about equally often', () => {
    const counts = new Map();
    const draws = EVENNESS_DRAWS / DEFAULT_PASSPHRASE_WORD_COUNT;
    for (let index = 0; index < draws; index += 1) {
        for (const word of generatePassphrase(WORDS, DEFAULT_PASSPHRASE_WORD_COUNT, fillRandomValues).split('-')) {
            if (HYPHENATED_WORD_HALVES.has(word)) continue;
            counts.set(word, (counts.get(word) ?? 0) + 1);
        }
    }
    const expected = EVENNESS_DRAWS / WORDLIST_SIZE;
    const most = Math.max(...counts.values());
    assert.ok(most < expected + EVENNESS_SLACK * Math.sqrt(expected), `a word came up ${most} times; about ${expected} expected`);
});

test('a passphrase takes the word count asked for, up to what fits a vault password', () => {
    const fixed = (buffer) => buffer.fill(0);
    assert.equal(generatePassphrase(WORDS, 3, fixed), 'abacus-abacus-abacus');
    assert.throws(() => generatePassphrase(WORDS, MAX_PASSPHRASE_WORD_COUNT + 1, fixed), /wordCount must be from 1 through 7/);
});

test('a suggestion below the rule is drawn again', () => {
    let draws = 0;
    const weakThenStrong = () => {
        draws += 1;
        return { score: draws === 1 ? 3 : 4 };
    };
    suggestPassphrase(WORDS, weakThenStrong, fillRandomValues);
    assert.equal(draws, 2);
});
