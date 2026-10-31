import { foldTagCase, isTextCharacter, normalizeText } from '../../tag-characters.js';
import {
    VALUE_ESCAPE, VALUE_QUOTE, findOutsideValues, isQuoted, opensValue, quotedValueEnd, tokenEnd,
} from '../../quoted-values.js';
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

const TAG_WRAPPER_OPENERS = new Set(['[', '{', '(']);
const TAG_WRAPPER_PAIRS = new Map([
    ['[', ']'],
    ['{', '}'],
    ['(', ')'],
]);
const TAG_WRAPPER_CHARS = new Set(['[', ']', '{', '}', '(', ')']);
// A tag may be wrapped at most three levels deep: [tag], [[tag]], [[[tag]]].
export const MAX_WRAPPER_DEPTH = 3;
// Each wrapper level contributes one opener and one closer.
const WRAPPER_ENDS_PER_LEVEL = 2;
export const COMMENT_OPEN = '/*';
export const COMMENT_CLOSE = '*/';
const SCOPED_RENDERER_TAGS = new Set(['@markdown', '@latex', '@json', '@csv', '@shell', '@chess', '@diff', '@mermaid']);
// @code=<language> (any name the server's highlighter knows; app/services/code_rendering.py).
const CODE_RENDERER_TAG_RE = /^@code=[a-z0-9][a-z0-9+#._-]*$/;

function isRendererTag(folded) {
    if (SCOPED_RENDERER_TAGS.has(folded)) {
        return true;
    }
    return CODE_RENDERER_TAG_RE.test(folded);
}
const KNOWN_META_TAGS = new Set([
    '@footnote', '@monospace', '@heading', '@red', '@green', '@blue', '@grey', '@gray',
    '@highlight', '@bold', '@italic', '@strikethrough', '@serif', '@copyable',
    '@bullets', '@numbered', '@username', '@password', '@email',
    '@todo', '@done', '@markdown', '@ai', '@latex', '@shell', '@json', '@csv', '@chess', '@diff', '@mermaid',
    '@stats',
]);
// @sum=, @avg=, @min=, @max=, @count= and a property name (app/services/subtree_stats.py);
// bare (`@sum`: every number property) or with = while being typed.
const SUMMARY_TAG_RE = /^@(?:sum|avg|min|max|count)(?:=(?:\p{L}[^\s=:]*)?)?$/u;
// @datetime=2026-10-24 or @datetime=2026-10-24T08:30, the date a note belongs to
// (app/services/note_datetime.py). Its value keeps its colon, unlike other @ tags.
const DATETIME_TAG_PREFIX = '@datetime=';
const DATETIME_VALUE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:t(\d{2}):(\d{2}))?$/i;
const DATETIME_NEEDS_DATE_MESSAGE = '@datetime needs a date: YYYY-MM-DD or YYYY-MM-DDTHH:MM';
const LAST_HOUR = 23;
const LAST_MINUTE = 59;
// Date counts months from 0.
const DATE_MONTH_OFFSET = 1;

function isDatetimeToken(token) {
    return token.toLowerCase().startsWith(DATETIME_TAG_PREFIX);
}

// Whether a @datetime token's value is a real day, and a real time when it has one.
function isValidDatetimeToken(token) {
    const parts = DATETIME_VALUE_RE.exec(token.slice(DATETIME_TAG_PREFIX.length));
    if (parts === null) {
        return false;
    }
    const [, yearText, monthText, dayText, hourText, minuteText] = parts;
    const year = Number(yearText);
    const monthIndex = Number(monthText) - DATE_MONTH_OFFSET;
    const day = Number(dayText);
    const calendarDay = new Date(year, monthIndex, day);
    if (calendarDay.getFullYear() !== year || calendarDay.getMonth() !== monthIndex || calendarDay.getDate() !== day) {
        return false;
    }
    if (hourText === undefined) {
        return true;
    }
    return Number(hourText) <= LAST_HOUR && Number(minuteText) <= LAST_MINUTE;
}

function isSupportedMetaTag(term) {
    if (typeof term !== 'string') {
        throw new Error('isSupportedMetaTag requires string');
    }
    if (!term.startsWith('@')) {
        return true;
    }
    const folded = term.toLowerCase();
    if (KNOWN_META_TAGS.has(folded)) {
        return true;
    }
    if (CODE_RENDERER_TAG_RE.test(folded)) {
        return true;
    }
    if (SUMMARY_TAG_RE.test(folded)) {
        return true;
    }
    return /^@size=(?:\d+(?:\.\d*)?|\.\d+)$/.test(folded)
        && /[1-9]/.test(folded.slice('@size='.length));
}

function isWhitespace(char) {
    return typeof char === 'string' && char.length === 1 && /\s/.test(char);
}

function enforceTagTokenInternal(rawToken, allowTrailingAssignmentSeparator) {
    if (typeof rawToken !== 'string') {
        throw new Error('enforceTagTokenInternal expects a string');
    }
    if (typeof allowTrailingAssignmentSeparator !== 'boolean') {
        throw new Error('enforceTagTokenInternal expects allowTrailingAssignmentSeparator boolean');
    }

    let token = rawToken;
    while (token.length > 0 && TOKEN_START_DISALLOWED.has(token[0])) {
        token = token.slice(1);
    }

    const assignmentSeparatorCount = Array.from(token).filter((char) => char === '=').length;
    const assignmentSeparatorIndex = token.indexOf('=');
    const canPreserveAssignmentSeparator = (
        assignmentSeparatorCount === 1
        && assignmentSeparatorIndex > 0
        && (
            assignmentSeparatorIndex < token.length - 1
            || (allowTrailingAssignmentSeparator && assignmentSeparatorIndex === token.length - 1)
        )
    );
    let out = '';
    for (const char of token) {
        if (!isTextCharacter(char)) {
            continue;
        }
        if (char === '=' && canPreserveAssignmentSeparator) {
            out += char;
            continue;
        }
        if (TAG_CONTAINS_DISALLOWED.has(char)) {
            continue;
        }
        out += char;
    }
    return out;
}

function enforceTagToken(rawToken) {
    return enforceTagTokenInternal(rawToken, false);
}

// A quoted value as the tag bar keeps it (docs/design/tag-properties.md, Quoted values):
// any text character inside the quotes, other whitespace as a space, escapes as typed,
// nothing after the closing quote. An open value stays open; closeValue closes it.
function enforceQuotedValue(rawValue) {
    if (!isQuoted(rawValue)) {
        throw new Error('enforceQuotedValue expects a quoted value');
    }
    // Read as the value of a=, so quotedValueEnd finds where it closes.
    const text = `${PROPERTY_ASSIGNMENT}${rawValue}`;
    const { end } = quotedValueEnd(text, PROPERTY_ASSIGNMENT.length);
    let out = '';
    for (const char of text.slice(PROPERTY_ASSIGNMENT.length, end)) {
        if (isWhitespace(char)) {
            out += ' ';
            continue;
        }
        if (isTextCharacter(char)) {
            out += char;
        }
    }
    return out;
}

// A quoted value once the user moves on: an open one closed (a backslash typed last left
// out), an empty one ('"' or '""') removed.
function closeValue(value) {
    if (!isQuoted(value)) {
        return value;
    }
    const text = `${PROPERTY_ASSIGNMENT}${value}`;
    let closed = value;
    if (!quotedValueEnd(text, PROPERTY_ASSIGNMENT.length).isClosed) {
        let open = value;
        let trailingEscapes = 0;
        while (trailingEscapes < open.length - 1 && open[open.length - 1 - trailingEscapes] === VALUE_ESCAPE) {
            trailingEscapes += 1;
        }
        if (trailingEscapes % 2 === 1) {
            open = open.slice(0, -1);
        }
        closed = `${open}${VALUE_QUOTE}`;
    }
    if (closed === `${VALUE_QUOTE}${VALUE_QUOTE}`) {
        return '';
    }
    return closed;
}

// A value as the tag bar keeps it: quoted, or the characters a bare value keeps.
function enforceValue(rawValue) {
    if (isQuoted(rawValue)) {
        return enforceQuotedValue(rawValue);
    }
    return keepAllowedChars(rawValue, { allowsColon: true });
}

// A top-level tag (not inside a scope), whose value may be quoted: author="Ursula Le Guin".
// While its value is still being typed ({ isTypingValue }) an open quote stays open.
function enforceValuedTagToken(rawToken, options) {
    if (options === null || typeof options !== 'object' || typeof options.isTypingValue !== 'boolean') {
        throw new Error('enforceValuedTagToken requires { isTypingValue } boolean');
    }
    const assignmentIndex = rawToken.indexOf(PROPERTY_ASSIGNMENT);
    const isQuotedValue = !rawToken.startsWith('@') && assignmentIndex > 0
        && opensValue(rawToken, assignmentIndex + 1);
    if (!isQuotedValue) {
        return enforceTagTokenInternal(rawToken, options.isTypingValue);
    }
    const name = enforceTagTokenInternal(rawToken.slice(0, assignmentIndex), false);
    let value = enforceQuotedValue(rawToken.slice(assignmentIndex + 1));
    if (!options.isTypingValue) {
        value = closeValue(value);
    }
    if (name.length === 0 || value.length === 0) {
        return name;
    }
    return `${name}${PROPERTY_ASSIGNMENT}${value}`;
}

// Tag properties (docs/design/tag-properties.md): jogging:miles=3:duration=30. The tag is
// everything before the first colon. After it, a colon followed by a letter starts the
// next property and any other colon belongs to the value (start=10:30pm). Meta tags and
// tags inside scopes have no properties: their colons are removed as before.
const PROPERTY_SEPARATOR = ':';
const PROPERTY_ASSIGNMENT = '=';
// A property's name starts with a letter, in any script (Größe, 時間).
const PROPERTY_NAME_START_RE = /^\p{L}$/u;

const PROPERTY_SEPARATORS = new Set([PROPERTY_SEPARATOR]);

// The colon that ends the tag, outside any quoted value (author="a:b" has none), or -1.
function propertySeparatorIndex(token) {
    return findOutsideValues(token, PROPERTY_SEPARATORS, 0);
}

function hasPropertySyntax(token) {
    return propertySeparatorIndex(token) > 0 && !token.startsWith('@');
}

/** The tag a token names: jogging for jogging:miles=3, the token itself otherwise. */
export function tagPartOfToken(token) {
    if (typeof token !== 'string') {
        throw new Error('tagPartOfToken expects a string');
    }
    if (!hasPropertySyntax(token)) {
        return token;
    }
    return token.slice(0, propertySeparatorIndex(token));
}

// The tag's name without a value: jogging for jogging=3 and for jogging:miles=3.
function tagNameOfToken(token) {
    return tagPartOfToken(token).split(PROPERTY_ASSIGNMENT)[0];
}

// The text after the tag, split where a colon is followed by a letter (or ends it); a
// quoted value is kept whole (title="Dune: Messiah").
function splitPropertySegments(text) {
    const segments = [];
    let current = '';
    for (let index = 0; index < text.length; index += 1) {
        if (opensValue(text, index)) {
            const { end } = quotedValueEnd(text, index);
            current += text.slice(index, end);
            index = end - 1;
            continue;
        }
        const char = text[index];
        const isLast = index === text.length - 1;
        if (char === PROPERTY_SEPARATOR && (isLast || PROPERTY_NAME_START_RE.test(text[index + 1]))) {
            segments.push(current);
            current = '';
            continue;
        }
        current += char;
    }
    segments.push(current);
    return segments;
}

// The characters a property's name or value keeps ({ allowsColon }: a value's can hold a colon).
function keepAllowedChars(text, options) {
    if (options === null || typeof options !== 'object' || typeof options.allowsColon !== 'boolean') {
        throw new Error('keepAllowedChars requires { allowsColon } boolean');
    }
    const allowsColon = options.allowsColon;
    let out = '';
    for (const char of text) {
        if (!isTextCharacter(char)) {
            continue;
        }
        if (char === PROPERTY_SEPARATOR && allowsColon) {
            out += char;
            continue;
        }
        if (TAG_CONTAINS_DISALLOWED.has(char)) {
            continue;
        }
        out += char;
    }
    return out;
}

// One property: a name starting with a letter, then = and its value (null before the =).
function enforcePropertySegment(segment) {
    let start = 0;
    while (start < segment.length && !PROPERTY_NAME_START_RE.test(segment[start])) {
        start += 1;
    }
    const text = segment.slice(start);
    const assignmentIndex = text.indexOf(PROPERTY_ASSIGNMENT);
    if (assignmentIndex === -1) {
        return { name: keepAllowedChars(text, { allowsColon: false }), value: null };
    }
    return {
        name: keepAllowedChars(text.slice(0, assignmentIndex), { allowsColon: false }),
        value: enforceValue(text.slice(assignmentIndex + 1)),
    };
}

// While typing ({ isEditing: true }) properties stay as typed, unfinished ones too;
// otherwise a property without a value, and a repeated one, are removed.
function enforcePropertyTagToken(rawToken, options) {
    if (options === null || typeof options !== 'object' || typeof options.isEditing !== 'boolean') {
        throw new Error('enforcePropertyTagToken requires { isEditing } boolean');
    }
    const colonIndex = propertySeparatorIndex(rawToken);
    const tag = enforceTagTokenInternal(rawToken.slice(0, colonIndex), false);
    if (tag.length === 0 || tag.startsWith('@')) {
        return enforceTagTokenInternal(rawToken, false);
    }
    const segments = splitPropertySegments(rawToken.slice(colonIndex + 1)).map(enforcePropertySegment);
    if (options.isEditing) {
        const typed = segments
            .filter((segment, index) => segment.name.length > 0 || index === segments.length - 1)
            .map((segment) => (segment.value === null || segment.name.length === 0
                ? segment.name
                : `${segment.name}${PROPERTY_ASSIGNMENT}${segment.value}`));
        return `${tag}${PROPERTY_SEPARATOR}${typed.join(PROPERTY_SEPARATOR)}`;
    }
    const seenNames = new Set();
    const kept = [];
    for (const typedSegment of segments) {
        const segment = typedSegment.value === null
            ? typedSegment
            : { name: typedSegment.name, value: closeValue(typedSegment.value) };
        const isComplete = segment.name.length > 0 && segment.value !== null && segment.value.length > 0;
        if (!isComplete || seenNames.has(foldTagCase(segment.name))) {
            continue;
        }
        seenNames.add(foldTagCase(segment.name));
        kept.push(`${segment.name}${PROPERTY_ASSIGNMENT}${segment.value}`);
    }
    if (kept.length === 0) {
        return tag;
    }
    return `${tag}${PROPERTY_SEPARATOR}${kept.join(PROPERTY_SEPARATOR)}`;
}

function enforceWrappedTagTokenInternal(
    rawToken,
    preserveTrailingSpaceWhenUnclosed,
    allowTrailingAssignmentSeparator,
) {
    if (typeof rawToken !== 'string') {
        throw new Error('enforceWrappedTagToken expects a string');
    }
    if (typeof preserveTrailingSpaceWhenUnclosed !== 'boolean') {
        throw new Error('enforceWrappedTagTokenInternal expects preserveTrailingSpaceWhenUnclosed boolean');
    }
    if (typeof allowTrailingAssignmentSeparator !== 'boolean') {
        throw new Error('enforceWrappedTagTokenInternal expects allowTrailingAssignmentSeparator boolean');
    }

    if (rawToken.length === 0) {
        return '';
    }

    const opener = rawToken[0];
    if (!TAG_WRAPPER_OPENERS.has(opener)) {
        if (isDatetimeToken(rawToken)) {
            const name = rawToken.slice(0, DATETIME_TAG_PREFIX.length);
            return `${name}${keepAllowedChars(rawToken.slice(DATETIME_TAG_PREFIX.length), { allowsColon: true })}`;
        }
        if (hasPropertySyntax(rawToken)) {
            // Only the editing path keeps trailing spaces: it is the one typing.
            return enforcePropertyTagToken(rawToken, { isEditing: preserveTrailingSpaceWhenUnclosed });
        }
        return enforceValuedTagToken(rawToken, { isTypingValue: allowTrailingAssignmentSeparator });
    }

    const closer = TAG_WRAPPER_PAIRS.get(opener);
    if (typeof closer !== 'string') {
        throw new Error(`Unknown tag wrapper opener: ${opener}`);
    }

    let openerCount = 0;
    while (openerCount < rawToken.length && rawToken[openerCount] === opener && openerCount < MAX_WRAPPER_DEPTH) {
        openerCount += 1;
    }

    let remainder = rawToken.slice(openerCount);

    const remainderHadTrailingWhitespace = /\s$/.test(remainder);

    while (remainder.length > 0 && TAG_WRAPPER_CHARS.has(remainder[remainder.length - 1]) && remainder[remainder.length - 1] !== closer) {
        remainder = remainder.slice(0, -1);
    }

    let closerCount = 0;
    while (closerCount < openerCount && remainder.endsWith(closer)) {
        closerCount += 1;
        remainder = remainder.slice(0, -1);
    }

    const wrapperIsUnclosed = closerCount < openerCount;
    const rawInnerParts = remainder.split(/\s+/).filter((part) => part.length > 0);
    const innerParts = rawInnerParts
        .map((part, partIndex) => enforceTagTokenInternal(
            part,
            allowTrailingAssignmentSeparator
                && wrapperIsUnclosed
                && !remainderHadTrailingWhitespace
                && partIndex === rawInnerParts.length - 1,
        ))
        .filter((part) => part.length > 0);
    let sanitizedInner = innerParts.join(' ');
    if (preserveTrailingSpaceWhenUnclosed && wrapperIsUnclosed && remainderHadTrailingWhitespace && sanitizedInner.length > 0) {
        sanitizedInner += ' ';
    }
    if (sanitizedInner.length === 0) {
        if (openerCount > closerCount) {
            return opener.repeat(openerCount);
        }
        return '';
    }

    const prefix = opener.repeat(openerCount);
    const suffix = closer.repeat(closerCount);
    return `${prefix}${sanitizedInner}${suffix}`;
}

function enforceWrappedTagToken(rawToken) {
    return enforceWrappedTagTokenInternal(rawToken, false, false);
}

function enforceWrappedTagTokenForEditing(rawToken, allowTrailingAssignmentSeparator) {
    return enforceWrappedTagTokenInternal(rawToken, true, allowTrailingAssignmentSeparator);
}

function analyzeUnclosedWrapperTokenInfo(token) {
    if (typeof token !== 'string') {
        throw new Error('analyzeUnclosedWrapperTokenInfo expects a string');
    }

    if (token.length === 0) {
        return null;
    }

    const opener = token[0];
    if (!TAG_WRAPPER_OPENERS.has(opener)) {
        return null;
    }

    const closer = TAG_WRAPPER_PAIRS.get(opener);
    if (typeof closer !== 'string') {
        throw new Error(`Unknown tag wrapper opener: ${opener}`);
    }

    let openerCount = 0;
    while (openerCount < token.length && token[openerCount] === opener && openerCount < MAX_WRAPPER_DEPTH) {
        openerCount += 1;
    }

    let closerCount = 0;
    while (
        closerCount < token.length
        && token[token.length - 1 - closerCount] === closer
        && closerCount < openerCount
    ) {
        closerCount += 1;
    }

    if (closerCount >= openerCount) {
        return null;
    }

    const inner = token.slice(openerCount, token.length - closerCount);
    const innerParts = inner
        .split(/\s+/)
        .map((part) => enforceTagToken(part))
        .filter((part) => part.length > 0);
    const shouldWarn = innerParts.length > 0 && /\s/.test(inner.trimStart());

    return {
        missingSuffix: closer.repeat(openerCount - closerCount),
        shouldWarn,
        inner,
        depth: openerCount,
    };
}

function enforceTagBarInputInternal(rawInput, options) {
    if (typeof rawInput !== 'string') {
        throw new Error('enforceTagBarInputInternal expects a string');
    }

    const allowTrailingCommentStart = Boolean(options && options.allowTrailingCommentStart);
    // One Unicode form, so tags that look the same are the same (tag-characters.js).
    const text = normalizeText(rawInput);

    let output = '';
    let currentToken = '';
    let inComment = false;
    let wrapper = null;

    const flushToken = ({ isFinal }) => {
        if (currentToken.length === 0) {
            return;
        }

        if (allowTrailingCommentStart && currentToken === '/') {
            output += currentToken;
        } else {
            if (allowTrailingCommentStart) {
                output += enforceWrappedTagTokenForEditing(currentToken, isFinal);
            } else {
                output += enforceWrappedTagToken(currentToken);
            }
        }
        currentToken = '';
    };

    for (let index = 0; index < text.length; index += 1) {
        const char = text[index];
        const nextChar = index + 1 < text.length ? text[index + 1] : '';

        if (!inComment && char === '/' && nextChar === '*') {
            flushToken({ isFinal: false });
            output += '/*';
            inComment = true;
            index += 1;
            continue;
        }

        if (inComment) {
            if (char === '*' && nextChar === '/') {
                output += '*/';
                inComment = false;
                index += 1;
                continue;
            }
            if (!isTextCharacter(char)) {
                continue;
            }
            output += char;
            continue;
        }

        if (!wrapper && currentToken.length === 0 && TAG_WRAPPER_OPENERS.has(char)) {
            const opener = char;
            const closer = TAG_WRAPPER_PAIRS.get(opener);
            if (typeof closer !== 'string') {
                throw new Error(`Unknown tag wrapper opener: ${opener}`);
            }
            let openerCount = 0;
            while (openerCount < text.length - index && text[index + openerCount] === opener && openerCount < MAX_WRAPPER_DEPTH) {
                openerCount += 1;
            }
            wrapper = { opener, closer, openerCount };
            currentToken += opener.repeat(openerCount);
            index += openerCount - 1;
            continue;
        }

        // A quoted value keeps its spaces, and a /* inside it is text.
        if (!wrapper && opensValue(text, index) && currentToken.endsWith(PROPERTY_ASSIGNMENT)) {
            const { end } = quotedValueEnd(text, index);
            currentToken += text.slice(index, end);
            index = end - 1;
            continue;
        }

        if (isWhitespace(char) && !wrapper) {
            flushToken({ isFinal: false });
            if (output.length > 0 && output[output.length - 1] !== ' ') {
                output += ' ';
            }
            continue;
        }

        currentToken += char;

        if (wrapper && currentToken.endsWith(wrapper.closer.repeat(wrapper.openerCount))) {
            wrapper = null;
        }
    }

    flushToken({ isFinal: true });
    return output;
}

export function enforceTagBarInput(rawInput) {
    return enforceTagBarInputInternal(rawInput, { allowTrailingCommentStart: false });
}

export function enforceTagBarInputForEditing(rawInput) {
    return enforceTagBarInputInternal(rawInput, { allowTrailingCommentStart: true });
}

function scanTagBarSegments(rawInput) {
    if (typeof rawInput !== 'string') {
        throw new Error('scanTagBarSegments expects a string');
    }

    const segments = [];
    let currentToken = '';
    let index = 0;
    let wrapper = null;
    while (index < rawInput.length) {
        if (rawInput.startsWith(COMMENT_OPEN, index)) {
            if (currentToken.length > 0) {
                segments.push({ type: 'token', text: currentToken });
                currentToken = '';
            }

            const closeIndex = rawInput.indexOf(COMMENT_CLOSE, index + COMMENT_OPEN.length);
            if (closeIndex === -1) {
                return { segments, unclosedCommentText: rawInput.slice(index) };
            }

            segments.push({ type: 'comment', text: rawInput.slice(index, closeIndex + COMMENT_CLOSE.length) });
            index = closeIndex + COMMENT_CLOSE.length;
            continue;
        }

        const char = rawInput[index];
        if (!wrapper && currentToken.length === 0 && TAG_WRAPPER_OPENERS.has(char)) {
            const opener = char;
            const closer = TAG_WRAPPER_PAIRS.get(opener);
            if (typeof closer !== 'string') {
                throw new Error(`Unknown tag wrapper opener: ${opener}`);
            }
            let openerCount = 0;
            while (openerCount < rawInput.length - index && rawInput[index + openerCount] === opener && openerCount < MAX_WRAPPER_DEPTH) {
                openerCount += 1;
            }
            wrapper = { opener, closer, openerCount };
            currentToken += opener.repeat(openerCount);
            index += openerCount;
            continue;
        }

        if (!wrapper && currentToken.length > 0 && opensValue(rawInput, index)) {
            const { end } = quotedValueEnd(rawInput, index);
            currentToken += rawInput.slice(index, end);
            index = end;
            continue;
        }

        if (isWhitespace(char) && !wrapper) {
            if (currentToken.length > 0) {
                segments.push({ type: 'token', text: currentToken });
                currentToken = '';
            }
            index += 1;
            continue;
        }

        currentToken += char;
        index += 1;

        if (wrapper && currentToken.endsWith(wrapper.closer.repeat(wrapper.openerCount))) {
            wrapper = null;
        }
    }

    if (currentToken.length > 0) {
        segments.push({ type: 'token', text: currentToken });
    }

    return { segments, unclosedCommentText: null };
}

function scanTagBarTokensWithPositions(rawInput) {
    const tokens = [];
    const commentRanges = [];
    let index = 0;

    while (index < rawInput.length) {
        while (index < rawInput.length && isWhitespace(rawInput[index])) {
            index += 1;
        }
        if (index >= rawInput.length) {
            break;
        }

        if (rawInput.startsWith(COMMENT_OPEN, index)) {
            const end = rawInput.indexOf(COMMENT_CLOSE, index + COMMENT_OPEN.length);
            if (end === -1) {
                break;
            }
            commentRanges.push({ start: index, end: end + COMMENT_CLOSE.length });
            index = end + COMMENT_CLOSE.length;
            continue;
        }

        const start = index;
        const opener = rawInput[index];
        if (TAG_WRAPPER_OPENERS.has(opener)) {
            let openerCount = 1;
            while (index + openerCount < rawInput.length && rawInput[index + openerCount] === opener && openerCount < MAX_WRAPPER_DEPTH) {
                openerCount += 1;
            }
            if (openerCount <= MAX_WRAPPER_DEPTH) {
                const closer = TAG_WRAPPER_PAIRS.get(opener);
                if (typeof closer !== 'string') {
                    throw new Error(`Unknown tag wrapper opener: ${opener}`);
                }
                const needle = closer.repeat(openerCount);
                const closeAt = rawInput.indexOf(needle, index + openerCount);
                if (closeAt !== -1) {
                    index = closeAt + openerCount;
                } else {
                    index = rawInput.length;
                }
                tokens.push({ text: rawInput.slice(start, index), start, end: index });
                continue;
            }
        }

        index = tokenEnd(rawInput, index);
        tokens.push({ text: rawInput.slice(start, index), start, end: index });
    }

    return { tokens, commentRanges };
}

function unwrapWrapperToken(token) {
    if (!token) {
        return null;
    }

    const opener = token[0];
    if (!TAG_WRAPPER_OPENERS.has(opener)) {
        return null;
    }

    let openerCount = 1;
    while (openerCount < token.length && token[openerCount] === opener) {
        openerCount += 1;
    }
    if (openerCount > MAX_WRAPPER_DEPTH) {
        return null;
    }

    const closer = TAG_WRAPPER_PAIRS.get(opener);
    if (typeof closer !== 'string') {
        throw new Error(`Unknown tag wrapper opener: ${opener}`);
    }

    if (token.length < openerCount * WRAPPER_ENDS_PER_LEVEL) {
        return null;
    }

    if (!token.endsWith(closer.repeat(openerCount))) {
        return null;
    }

    let closerCount = 0;
    while (closerCount < token.length && token[token.length - 1 - closerCount] === closer) {
        closerCount += 1;
    }
    if (closerCount !== openerCount) {
        return null;
    }

    const inner = token.slice(openerCount, token.length - openerCount);
    if (!inner) {
        return null;
    }

    return { inner, depth: openerCount };
}

export function analyzeTagBarInput(rawInput) {
    if (typeof rawInput !== 'string') {
        throw new Error('analyzeTagBarInput expects a string');
    }

    const enforcedText = enforceTagBarInput(rawInput);
    const { segments, unclosedCommentText } = scanTagBarSegments(enforcedText);


    let unclosedWrapperSuffix = null;
    // Keep the typed trailing space for warning timing; persisted tokens still
    // use the strict enforcement and sanitization path below.
    const editingSegments = scanTagBarSegments(enforceTagBarInputForEditing(rawInput)).segments;
    for (const segment of editingSegments) {
        if (segment.type !== 'token') {
            continue;
        }
        const wrapperInfo = analyzeUnclosedWrapperTokenInfo(segment.text);
        if (wrapperInfo && wrapperInfo.shouldWarn) {
            unclosedWrapperSuffix = wrapperInfo.missingSuffix;
            break;
        }
    }
    let hasReservedOrTag = false;
    // A note has each tag once when one of its tokens has properties: jogging beside
    // jogging:miles=3 is refused. By tag name (lowercase), whether its token has them.
    const tagNamesWithProperties = new Map();
    let refusedTagName = null;
    let hasDatetime = false;
    let hasInvalidDatetime = false;

    const sanitizedSegments = [];
    const normalizedSegments = [];
    let globalRenderer = null;
    for (const segment of segments) {
        normalizedSegments.push(segment.text);
        let sanitizedToken = segment.text;
        if (segment.type === 'token') {
            const wrapperInfo = analyzeUnclosedWrapperTokenInfo(segment.text);
            if (wrapperInfo) {
                continue;
            }
            const closedWrapperInfo = unwrapWrapperToken(segment.text);
            const tagTerms = closedWrapperInfo
                ? closedWrapperInfo.inner.split(/\s+/).filter(Boolean)
                : [segment.text];
            if (tagTerms.includes('OR')) {
                hasReservedOrTag = true;
                continue;
            }
            if (closedWrapperInfo) {
                let scopedRenderer = null;
                const retainedTerms = tagTerms.filter((term) => {
                    if (!isSupportedMetaTag(term)) {
                        return false;
                    }
                    const renderer = term.toLowerCase();
                    if (!isRendererTag(renderer)) {
                        return true;
                    }
                    if (scopedRenderer !== null && scopedRenderer !== renderer) {
                        return false;
                    }
                    scopedRenderer = renderer;
                    return true;
                });
                if (retainedTerms.length === 0) {
                    continue;
                }
                const opener = segment.text[0];
                const prefix = opener.repeat(closedWrapperInfo.depth);
                const suffix = TAG_WRAPPER_PAIRS.get(opener).repeat(closedWrapperInfo.depth);
                sanitizedToken = `${prefix}${retainedTerms.join(' ')}${suffix}`;
            } else if (isDatetimeToken(segment.text)) {
                // One date per note, and only a real one.
                if (!isValidDatetimeToken(segment.text)) {
                    hasInvalidDatetime = true;
                    continue;
                }
                if (hasDatetime) {
                    if (refusedTagName === null) {
                        refusedTagName = '@datetime';
                    }
                    continue;
                }
                hasDatetime = true;
            } else if (!isSupportedMetaTag(segment.text)) {
                continue;
            } else if (!segment.text.startsWith('@')) {
                const name = tagNameOfToken(segment.text);
                const key = foldTagCase(name);
                const hasProperties = hasPropertySyntax(segment.text);
                if (tagNamesWithProperties.has(key) && (hasProperties || tagNamesWithProperties.get(key))) {
                    if (refusedTagName === null) {
                        refusedTagName = name;
                    }
                    continue;
                }
                tagNamesWithProperties.set(key, hasProperties);
            } else {
                const renderer = segment.text.toLowerCase();
                if (isRendererTag(renderer)) {
                    if (globalRenderer !== null && globalRenderer !== renderer) {
                        continue;
                    }
                    globalRenderer = renderer;
                }
            }
        }
        sanitizedSegments.push(sanitizedToken);
    }

    const sanitizedText = sanitizedSegments.join(' ').trim();

    if (unclosedCommentText) {
        normalizedSegments.push(unclosedCommentText);
    }
    const normalizedText = normalizedSegments.join(' ').trim();

    const shouldWarnUnclosedComment = Boolean(unclosedCommentText) && unclosedCommentText.length > COMMENT_OPEN.length;

    const errorMessage = shouldWarnUnclosedComment
        ? 'Close comment with */'
        : (hasReservedOrTag ? 'OR is reserved for search' : null);
    let reminderMessage = '';
    if (unclosedWrapperSuffix) {
        reminderMessage = `Close scope with ${unclosedWrapperSuffix}`;
    } else if (refusedTagName !== null) {
        reminderMessage = `${refusedTagName} is already on this note`;
    } else if (hasInvalidDatetime) {
        reminderMessage = DATETIME_NEEDS_DATE_MESSAGE;
    }

    return {
        isValid: errorMessage === null,
        errorMessage,
        reminderMessage,
        sanitizedText,
        normalizedText,
    };
}

// Saved tag-bar text as display pieces: plain tags, @meta tags, bracketed scopes
// (kept whole, including their inner spaces) and /* comments */.
export function splitTagsForDisplay(tags) {
    if (typeof tags !== 'string') {
        throw new Error('splitTagsForDisplay expects a string');
    }
    const { segments, unclosedCommentText } = scanTagBarSegments(tags);
    const pieces = segments.map((segment) => {
        if (segment.type === 'comment') {
            return { kind: 'comment', text: segment.text };
        }
        if (segment.type !== 'token') {
            throw new Error(`Unknown tag bar segment type: ${segment.type}`);
        }
        if (TAG_WRAPPER_OPENERS.has(segment.text[0])) {
            return { kind: 'scope', text: segment.text };
        }
        if (segment.text.startsWith('@')) {
            return { kind: 'meta', text: segment.text };
        }
        return { kind: 'tag', text: segment.text };
    });
    if (unclosedCommentText) {
        pieces.push({ kind: 'comment', text: unclosedCommentText });
    }
    return pieces;
}

export function normalizeTagBarInput(rawInput) {
    if (typeof rawInput !== 'string') {
        throw new Error('normalizeTagBarInput expects a string');
    }

    return analyzeTagBarInput(rawInput).normalizedText;
}

export function parseTagBarSuggestionContext(rawInput, cursorIndex) {
    if (typeof rawInput !== 'string') {
        throw new Error('parseTagBarSuggestionContext expects a string');
    }
    if (!Number.isInteger(cursorIndex)) {
        throw new Error('parseTagBarSuggestionContext expects cursorIndex integer');
    }
    if (cursorIndex < 0 || cursorIndex > rawInput.length) {
        throw new Error('parseTagBarSuggestionContext cursorIndex out of bounds');
    }

    const analysis = analyzeTagBarInput(rawInput);
    if (!analysis.isValid) {
        return null;
    }

    const { tokens, commentRanges } = scanTagBarTokensWithPositions(rawInput);
    for (const range of commentRanges) {
        if (cursorIndex >= range.start && cursorIndex < range.end) {
            return null;
        }
    }

    const atoms = [];
    for (const token of tokens) {
        let wrapperInfo = unwrapWrapperToken(token.text);
        if (wrapperInfo === null) {
            wrapperInfo = analyzeUnclosedWrapperTokenInfo(token.text);
        }
        if (wrapperInfo) {
            const inner = wrapperInfo.inner;
            let innerIndex = 0;
            while (innerIndex < inner.length) {
                while (innerIndex < inner.length && isWhitespace(inner[innerIndex])) {
                    innerIndex += 1;
                }
                if (innerIndex >= inner.length) {
                    break;
                }
                const start = innerIndex;
                while (innerIndex < inner.length && !isWhitespace(inner[innerIndex])) {
                    innerIndex += 1;
                }
                const text = inner.slice(start, innerIndex);
                if (text.length > 0) {
                    const absoluteStart = token.start + wrapperInfo.depth + start;
                    const absoluteEnd = token.start + wrapperInfo.depth + innerIndex;
                    atoms.push({ text, start: absoluteStart, end: absoluteEnd });
                }
            }
            continue;
        }
        if (token.text.length > 0) {
            atoms.push({ text: token.text, start: token.start, end: token.end });
        }
    }

    let currentAtom = null;
    for (const atom of atoms) {
        if (cursorIndex >= atom.start && cursorIndex <= atom.end) {
            currentAtom = atom;
            break;
        }
    }
    // Typing a property (after jogging:): the server suggests its names and units from
    // the token typed so far, replacing it whole.
    const isTypingProperty = Boolean(currentAtom) && hasPropertySyntax(currentAtom.text)
        && cursorIndex > currentAtom.start + propertySeparatorIndex(currentAtom.text);

    // A tag with properties counts as its tag: jogging:miles=3 is jogging.
    const explicitTags = [];
    for (const atom of atoms) {
        if (atom.text.length > 0) {
            explicitTags.push(tagPartOfToken(atom.text));
        }
    }

    const anchors = [];
    for (const atom of atoms) {
        if (currentAtom && atom === currentAtom) {
            continue;
        }
        if (atom.text.length > 0) {
            anchors.push(tagPartOfToken(atom.text));
        }
    }

    let prefix = '';
    let replaceStart = cursorIndex;
    let replaceEnd = cursorIndex;
    if (currentAtom) {
        prefix = rawInput.slice(currentAtom.start, cursorIndex);
        replaceStart = currentAtom.start;
        replaceEnd = cursorIndex;
    }

    return {
        anchors,
        explicitTags,
        prefix,
        replaceStart,
        replaceEnd,
        isTypingProperty,
    };
}

export function findTagAtIndexInTagBar(rawInput, cursorIndex) {
    if (typeof rawInput !== 'string') {
        throw new Error('findTagAtIndexInTagBar expects a string');
    }
    if (!Number.isInteger(cursorIndex)) {
        throw new Error('findTagAtIndexInTagBar expects cursorIndex integer');
    }
    if (cursorIndex < 0 || cursorIndex > rawInput.length) {
        throw new Error('findTagAtIndexInTagBar cursorIndex out of bounds');
    }

    const analysis = analyzeTagBarInput(rawInput);
    if (!analysis.isValid) {
        return null;
    }

    const { tokens, commentRanges } = scanTagBarTokensWithPositions(rawInput);
    for (const range of commentRanges) {
        if (cursorIndex >= range.start && cursorIndex < range.end) {
            return null;
        }
    }

    const atoms = [];
    for (const token of tokens) {
        const wrapperInfo = unwrapWrapperToken(token.text);
        if (wrapperInfo) {
            const inner = wrapperInfo.inner;
            let innerIndex = 0;
            while (innerIndex < inner.length) {
                while (innerIndex < inner.length && isWhitespace(inner[innerIndex])) {
                    innerIndex += 1;
                }
                if (innerIndex >= inner.length) {
                    break;
                }
                const start = innerIndex;
                while (innerIndex < inner.length && !isWhitespace(inner[innerIndex])) {
                    innerIndex += 1;
                }
                const text = inner.slice(start, innerIndex);
                const enforced = enforceTagToken(text);
                if (enforced.length > 0) {
                    const absoluteStart = token.start + wrapperInfo.depth + start;
                    const absoluteEnd = token.start + wrapperInfo.depth + innerIndex;
                    atoms.push({ text: enforced, start: absoluteStart, end: absoluteEnd });
                }
            }
            continue;
        }

        // Anywhere on jogging:miles=3 is the tag jogging.
        const enforced = enforceValuedTagToken(tagPartOfToken(token.text), { isTypingValue: false });
        if (enforced.length > 0) {
            atoms.push({ text: enforced, start: token.start, end: token.end });
        }
    }

    for (const atom of atoms) {
        if (cursorIndex >= atom.start && cursorIndex <= atom.end) {
            return atom;
        }
    }

    return null;
}
