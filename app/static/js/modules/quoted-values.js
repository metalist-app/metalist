// Quoted tag values (docs/design/tag-properties.md, Quoted values; decided 2026-10-30), as
// app/services/quoted_values.py reads them on the server.
//
// A value may be quoted to hold spaces and any other character: author="Ursula Le Guin",
// book:title="Dune: Messiah". A double quote straight after an operator (=, and in a search
// also <, >, <= or >=) opens the value, which runs to the closing quote; inside it \" is a
// quote and \\ a backslash. A quote anywhere else opens nothing.

export const VALUE_QUOTE = '"';
export const VALUE_ESCAPE = '\\';
// A quote straight after one of these opens a value.
const VALUE_OPERATOR_CHARACTERS = new Set(['=', '<', '>']);

function isWhitespace(char) {
    return /\s/.test(char);
}

/** Whether the character at index is a quote that opens a value. */
export function opensValue(text, index) {
    if (typeof text !== 'string') {
        throw new Error('opensValue expects a string');
    }
    return index > 0 && index < text.length && text[index] === VALUE_QUOTE
        && VALUE_OPERATOR_CHARACTERS.has(text[index - 1]);
}

/**
 * Where the quoted value opened at quoteIndex ends: { end } just past its closing quote,
 * or the end of the text when it is still open ({ isClosed: false }).
 */
export function quotedValueEnd(text, quoteIndex) {
    if (!opensValue(text, quoteIndex)) {
        throw new Error(`no value opens at ${quoteIndex} in ${text}`);
    }
    let index = quoteIndex + 1;
    while (index < text.length) {
        const char = text[index];
        if (char === VALUE_ESCAPE) {
            index += VALUE_ESCAPE.length + 1;
            continue;
        }
        if (char === VALUE_QUOTE) {
            return Object.freeze({ end: index + 1, isClosed: true });
        }
        index += 1;
    }
    return Object.freeze({ end: text.length, isClosed: false });
}

/** Where the token starting at start ends: at whitespace outside a quoted value, or the end. */
export function tokenEnd(text, start) {
    let index = start;
    while (index < text.length && !isWhitespace(text[index])) {
        if (opensValue(text, index)) {
            index = quotedValueEnd(text, index).end;
            continue;
        }
        index += 1;
    }
    return index;
}

/** Text split on whitespace, each quoted value kept whole with its spaces. */
export function splitTokens(text) {
    if (typeof text !== 'string') {
        throw new Error('splitTokens expects a string');
    }
    const tokens = [];
    let index = 0;
    while (index < text.length) {
        if (isWhitespace(text[index])) {
            index += 1;
            continue;
        }
        const end = tokenEnd(text, index);
        tokens.push(text.slice(index, end));
        index = end;
    }
    return tokens;
}

/** The first index at or after start holding one of chars outside a quoted value, or -1. */
export function findOutsideValues(text, chars, start) {
    let index = start;
    while (index < text.length) {
        if (opensValue(text, index)) {
            index = quotedValueEnd(text, index).end;
            continue;
        }
        if (chars.has(text[index])) {
            return index;
        }
        index += 1;
    }
    return -1;
}

/** Whether a value as written starts with its quote. */
export function isQuoted(value) {
    return value.startsWith(VALUE_QUOTE);
}

/** A value's text: a quoted value's quotes and escapes removed, any other value as written. */
export function unquoteValue(value) {
    if (typeof value !== 'string') {
        throw new Error('unquoteValue expects a string');
    }
    if (!isQuoted(value)) {
        return value;
    }
    let out = '';
    let index = VALUE_QUOTE.length;
    while (index < value.length) {
        const char = value[index];
        if (char === VALUE_ESCAPE && index + 1 < value.length) {
            out += value[index + 1];
            index += VALUE_ESCAPE.length + 1;
            continue;
        }
        if (char === VALUE_QUOTE) {
            break;
        }
        out += char;
        index += 1;
    }
    return out;
}
