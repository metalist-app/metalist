import { isTextCharacter, normalizeText } from '../../tag-characters.js';
export const MAX_SELECTED_TEXT_TAG_CHARACTERS = 25;

const TAG_CONTAINS_DISALLOWED = new Set([
    ':',
    ',',
    '"',
    '\\',
    '>',
    '<',
    '=',
    '[',
    ']',
    '{',
    '}',
    '(',
    ')',
    '*',
    '|',
    ';',
    '~',
    '`',
]);
const TOKEN_START_DISALLOWED = new Set(['-', '+', '/']);

function buildDefaultTagCandidate(normalizedSelectedText) {
    // A default tag keeps letters in any script (tag-characters.js).
    const spacesJoined = normalizeText(normalizedSelectedText).replace(/\s+/g, '-');
    let candidate = '';
    for (const char of spacesJoined) {
        if (!isTextCharacter(char)) {
            continue;
        }
        if (TAG_CONTAINS_DISALLOWED.has(char)) {
            continue;
        }
        candidate += char;
    }
    while (candidate.length > 0 && TOKEN_START_DISALLOWED.has(candidate[0])) {
        candidate = candidate.slice(1);
    }
    return candidate;
}

export function normalizeSelectedTextForTagAction(selectedText) {
    if (typeof selectedText !== 'string') {
        throw new Error('normalizeSelectedTextForTagAction expects selectedText string');
    }
    if (selectedText.length === 0 || selectedText.length > MAX_SELECTED_TEXT_TAG_CHARACTERS) {
        return null;
    }

    const normalizedSelectedText = selectedText.replace(/\s+/g, ' ').trim();
    if (normalizedSelectedText.length === 0) {
        return null;
    }
    const candidate = buildDefaultTagCandidate(normalizedSelectedText);
    if (candidate.length === 0 || candidate === 'OR') {
        return null;
    }
    return normalizedSelectedText;
}
