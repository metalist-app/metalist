/**
 * Which characters tags and searches keep, and how tags compare ignoring case
 * (docs/ui/tag-bar.md, Whitespace + Tokens; the server's app/services/tag_characters.py).
 *
 * Tags may use letters in any script. Text is kept in one Unicode form (NFC); control
 * characters and invisible ones (zero-width spaces, direction marks) are dropped; and case is
 * folded exactly as the server's str.casefold folds it, from the same data
 * (tag-characters-data.js, generated from app/static/config/tag-characters.json).
 */

import { TAG_CHARACTER_DATA } from './tag-characters-data.js';

// The data writes code points in hexadecimal.
const HEXADECIMAL = 16;
const NORMAL_FORM = 'NFC';
const CONTROL_CHARACTER_RE = /^\p{Cc}$/u;
// Loops that step through a string one UTF-16 unit at a time see an emoji as two halves.
const SURROGATE_HALF_RE = /^\p{Cs}$/u;

function characterOf(code) {
    return String.fromCodePoint(Number.parseInt(code, HEXADECIMAL));
}

const INVISIBLE_CHARACTERS = new Set(TAG_CHARACTER_DATA.invisible.map(characterOf));
const CASEFOLD_EXCEPTIONS = new Map(
    Object.entries(TAG_CHARACTER_DATA.casefoldExceptions).map(([code, folded]) => [characterOf(code), folded]),
);

/** Text in the one form tags and searches use: lone surrogate halves replaced, then NFC. */
export function normalizeText(text) {
    if (typeof text !== 'string') {
        throw new Error('normalizeText expects a string');
    }
    return text.toWellFormed().normalize(NORMAL_FORM);
}

/**
 * Whether a tag, a tag comment or a search may keep this character: any character but a
 * control character or an invisible one. Spaces count (callers split tags on them). Takes
 * one character, or one half of a pair from text normalizeText has made well formed.
 */
export function isTextCharacter(char) {
    if (typeof char !== 'string' || char.length === 0 || [...char].length !== 1) {
        throw new Error('isTextCharacter expects one character');
    }
    if (SURROGATE_HALF_RE.test(char)) {
        return true;
    }
    if (INVISIBLE_CHARACTERS.has(char)) {
        return false;
    }
    return !CONTROL_CHARACTER_RE.test(char);
}

/** A tag's text with its case folded as the server folds it (Python's str.casefold). */
export function foldTagCase(text) {
    if (typeof text !== 'string') {
        throw new Error('foldTagCase expects a string');
    }
    let folded = '';
    for (const char of text) {
        if (CASEFOLD_EXCEPTIONS.has(char)) {
            folded += CASEFOLD_EXCEPTIONS.get(char);
            continue;
        }
        // One character at a time, so a final sigma folds to σ as casefold folds it.
        folded += char.toLowerCase();
    }
    return folded;
}
