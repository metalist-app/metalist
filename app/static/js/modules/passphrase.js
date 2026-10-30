import { ApplicationState } from './application-state.js';
import { pickRandomIndexes } from './password-generator.js';
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_ZXCVBN_SCORE } from './password-policy.js';

// Passphrases of random words (docs/security/README.md, "Password Requirements"): EFF's
// long wordlist, bundled with MetaList (docs/security/vendor-manifest.json), so nothing is
// fetched from elsewhere. Each word is about 12.9 bits; five are about 64.6.
const WORDLIST_URL = '/static/js/vendor/eff-large-wordlist-2016-07-18.txt';
export const WORDLIST_SIZE = 7776;
export const DEFAULT_PASSPHRASE_WORD_COUNT = 5;
const WORD_SEPARATOR = '-';
// Each line is five dice digits, a tab and the word.
const WORDLIST_LINE_RE = /^[1-6]{5}\t([a-z-]+)$/;
const LONGEST_WORD_LENGTH = 9;
// As many words as always fit a vault password, separators included.
export const MAX_PASSPHRASE_WORD_COUNT = Math.floor(
    (PASSWORD_MAX_LENGTH + WORD_SEPARATOR.length) / (LONGEST_WORD_LENGTH + WORD_SEPARATOR.length),
);
// A suggestion scoring below the rule is drawn again. Five words score 4 every time in
// 10,000 tries (measured 2026-10-29; tests/unit/passphrase.test.mjs keeps 1,000), so this many
// misses is a bug.
const MAX_SUGGESTION_DRAWS = 20;

const moduleState = ApplicationState.createFields('passphrase', {
    wordsPromise: null,
});

export function parseWordlist(text) {
    if (typeof text !== 'string') {
        throw new Error('parseWordlist requires the wordlist text');
    }
    const words = text.split('\n').filter((line) => line !== '').map((line) => {
        const match = WORDLIST_LINE_RE.exec(line);
        if (match === null) {
            throw new Error(`Wordlist line is not dice digits, a tab and a word: ${line}`);
        }
        return match[1];
    });
    if (words.length !== WORDLIST_SIZE || new Set(words).size !== WORDLIST_SIZE) {
        throw new Error(`Wordlist must hold ${WORDLIST_SIZE} distinct words`);
    }
    if (words.some((word) => word.length > LONGEST_WORD_LENGTH)) {
        throw new Error(`Wordlist words must be at most ${LONGEST_WORD_LENGTH} letters`);
    }
    return Object.freeze(words);
}

export function loadPassphraseWords() {
    if (moduleState.wordsPromise === null) {
        moduleState.wordsPromise = fetch(WORDLIST_URL).then((response) => {
            if (!response.ok) {
                throw new Error(`The passphrase wordlist did not load (${response.status})`);
            }
            return response.text();
        }).then(parseWordlist);
    }
    return moduleState.wordsPromise;
}

export function generatePassphrase(words, wordCount, fillRandomValues) {
    if (!Array.isArray(words) || words.length !== WORDLIST_SIZE) {
        throw new Error('generatePassphrase requires the wordlist');
    }
    if (!Number.isInteger(wordCount) || wordCount <= 0 || wordCount > MAX_PASSPHRASE_WORD_COUNT) {
        throw new Error(`wordCount must be from 1 through ${MAX_PASSPHRASE_WORD_COUNT}`);
    }
    return pickRandomIndexes(wordCount, words.length, fillRandomValues).map((index) => words[index]).join(WORD_SEPARATOR);
}

// Five words that pass the vault password rule, scored by the same zxcvbn the form uses.
export function suggestPassphrase(words, estimator, fillRandomValues) {
    if (typeof estimator !== 'function') {
        throw new Error('suggestPassphrase requires the strength estimator');
    }
    for (let draw = 0; draw < MAX_SUGGESTION_DRAWS; draw += 1) {
        const passphrase = generatePassphrase(words, DEFAULT_PASSPHRASE_WORD_COUNT, fillRandomValues);
        if (estimator(passphrase, ['metalist']).score >= PASSWORD_MIN_ZXCVBN_SCORE) {
            return passphrase;
        }
    }
    throw new Error(`No passphrase passed the strength rule in ${MAX_SUGGESTION_DRAWS} draws`);
}
