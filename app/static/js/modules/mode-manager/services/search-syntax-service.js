import { foldTagCase, isTextCharacter, normalizeText } from '../../tag-characters.js';
import { VALUE_QUOTE, opensValue } from '../../quoted-values.js';
const TAG_CONTAINS_DISALLOWED = new Set([
    ':',
    '"',
    '\\',
    '>',
    '<',
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
// A tag's name and value: @code=python (app/services/search_index.py TAG_VALUE_SEPARATOR).
const TAG_VALUE_SEPARATOR = '=';
// Same wording as the server's rejection (app/services/search_query.py).
const SPACED_PREFIX_WARNING = 'In a search, + or - must be directly followed by the tag or quoted text, with no space (for example -tag)';

const QUOTE_CHARS = new Set(['"', "'" ]);
// `/*help*/`: a tag bar's comment (app/services/search_query.py, comment terms). No tag starts with /.
const COMMENT_OPEN = '/*';
const COMMENT_CLOSE = '*/';
const NOT_FOUND = -1;
const EMPTY_COMMENT_WARNING = 'Put the comment\'s words between /* and */ (for example /*help*/)';

/**
 * A comment term from index (at its `/*`): to the next `*` + `/`, spaces kept; one not yet
 * closed reaches the end of the query. Its text as typed, its words, where the next term starts,
 * and whether it is closed.
 */
function readCommentTerm(rawInput, startIndex) {
    const innerStart = startIndex + COMMENT_OPEN.length;
    const closeAt = rawInput.indexOf(COMMENT_CLOSE, innerStart);
    const isClosed = closeAt !== NOT_FOUND;
    let innerEnd = rawInput.length;
    let nextIndex = rawInput.length;
    if (isClosed) {
        innerEnd = closeAt;
        nextIndex = closeAt + COMMENT_CLOSE.length;
    }
    return {
        typed: rawInput.slice(startIndex, nextIndex),
        words: rawInput.slice(innerStart, innerEnd).replace(/\s+/g, ' ').trim(),
        nextIndex,
        isClosed,
    };
}
const OR_OPERATOR = 'OR';
// jogging:miles=MAX: the notes with the largest value, no value to give a new one.
const EXTREME_VALUES = new Set(['MAX', 'MIN']);
// A backslash and the character it escapes.
const ESCAPE_SEQUENCE_LENGTH = 2;
function isWhitespace(char) {
    return typeof char === 'string' && char.length === 1 && /\s/.test(char);
}

function enforceTagToken(rawToken) {
    if (typeof rawToken !== 'string') {
        throw new Error('enforceTagToken expects a string');
    }

    let token = rawToken;
    while (token.length > 0 && TOKEN_START_DISALLOWED.has(token[0])) {
        token = token.slice(1);
    }

    // One = joins a tag's name and value (@code=python), as in the tag bar; it is
    // never the first character, and any further = is dropped.
    let output = '';
    let hasValueSeparator = false;
    for (const char of token) {
        if (!isTextCharacter(char)) {
            continue;
        }
        if (char === TAG_VALUE_SEPARATOR) {
            if (output !== '' && !hasValueSeparator) {
                output += char;
                hasValueSeparator = true;
            }
            continue;
        }
        if (TAG_CONTAINS_DISALLOWED.has(char)) {
            continue;
        }
        output += char;
    }

    return output;
}

// Property terms (docs/design/tag-properties.md): jogging:miles>2, jogging:miles?,
// jogging:miles, date>=2024-01 (app/services/tag_properties.py parse_property_term).
const PROPERTY_SEPARATOR = ':';
const PROPERTY_TERM_MARKS = new Set([PROPERTY_SEPARATOR, '<', '>', '?']);
// A property's name starts with a letter, in any script.
// A value: bare, or quoted (masked to "v" before these are tested).
const TERM_TAG_PATTERN = '[^:=<>?@"][^:=<>?"]*';
// A colon followed by a letter starts the chain's next condition, so no value holds one.
const TERM_VALUE_PATTERN = '(?:"v"|(?:[^<>?=":]|:(?!\\p{L}))+)';
const PROPERTY_CONDITION_PATTERN = `\\p{L}[^:=<>?"]*(?:(?:>=|<=|>|<|=)${TERM_VALUE_PATTERN})?`;
// One condition, or a chain whose conditions one tag meets (jogging:miles>2:duration<40;
// decided 2026-10-31); ? only alone.
const NAMED_PROPERTY_TERM_RE = new RegExp(
    `^${TERM_TAG_PATTERN}(?::\\p{L}[^:=<>?"]*\\?|(?::${PROPERTY_CONDITION_PATTERN})+)$`, 'u',
);
const IMPLICIT_PROPERTY_TERM_RE = new RegExp(`^${TERM_TAG_PATTERN}(?:>=|<=|>|<)${TERM_VALUE_PATTERN}$`, 'u');
// A property on any tag (:version, :version=0.24.5, :version>0.24, :foo="bar":baz>3;
// app/services/tag_properties.py parse_tagless_property_term). Never with ?: on any tag it
// matches too much.
const TAGLESS_PROPERTY_TERM_RE = new RegExp(`^(?::${PROPERTY_CONDITION_PATTERN})+$`, 'u');
// Where a chain's next condition starts: a colon followed by a letter.
const CHAIN_SEPARATOR_RE = /:(?=\p{L})/u;
const CHAIN_TERM_EXAMPLE = 'jogging:miles>2:duration<40';
const UNQUOTED_OPERATOR_PROBLEM = 'Quote a value holding <, >, ? or = (for example book:title="a=b")';
const TAGLESS_PROPERTY_TERM_EXAMPLE = ':version=0.24';
const TRAILING_OPERATOR_RE = /(>=|<=|>|<|=)$/;
const PROPERTY_NAME_NOT_A_LETTER_RE = /^[^:]+:\P{L}/u;
const PROPERTY_TERM_EXAMPLE = 'jogging:miles>2';
// The stats tags' figures (@sum:calories>2000; app/services/tag_properties.py
// parse_stats_term): only these @ words take a property, and only in a search.
const STATS_TERM_START_RE = /^(@(?:sum|avg|min|max|count))[:<>?]/i;
const STATS_TERM_RE = /^@(?:sum|avg|min|max|count):\p{L}[^:=<>?]*(?:(?:>=|<=|>|<|=)[^<>?=]+)?$/iu;
const STATS_TERM_EXAMPLE_PROPERTY = 'calories>2000';

// Quoted values (docs/design/tag-properties.md, Quoted values): a quote straight after
// = < > opens a value, author="Ursula Le Guin" (quoted-values.js). Checked with each
// quoted value masked as MASKED_VALUE, so the patterns above see one plain character.
const MASKED_VALUE = 'v';
const EMPTY_QUOTED_VALUE_RE = /(>=|<=|>|<|=)""$/;
// author="Le Guin": the tag's own value, matched as quoted text (tag_properties.py).
const QUOTED_VALUE_TERM_RE = /^[^:=<>?@][^:=<>?]*="v"$/u;
const QUOTED_VALUE_START_RE = /^[^:=<>?@"][^:=<>?"]*="/u;

// A term with each closed quoted value's text masked; an open one is closed first.
function maskQuotedValues(term) {
    let out = '';
    let index = 0;
    while (index < term.length) {
        if (!opensValue(term, index)) {
            out += term[index];
            index += 1;
            continue;
        }
        const { normalizedInner, nextIndex } = readQuotedInner(term, index + 1, VALUE_QUOTE);
        out += normalizedInner.length > 0 ? `${VALUE_QUOTE}${MASKED_VALUE}${VALUE_QUOTE}` : `${VALUE_QUOTE}${VALUE_QUOTE}`;
        index = nextIndex;
    }
    return out;
}

function isPropertyTerm(token) {
    if (STATS_TERM_START_RE.test(token) || token.startsWith(PROPERTY_SEPARATOR)) {
        return true;
    }
    if (token.startsWith('@')) {
        return false;
    }
    if (QUOTED_VALUE_START_RE.test(token)) {
        return true;
    }
    const masked = maskQuotedValues(token);
    if (masked.indexOf(PROPERTY_SEPARATOR) > 0) {
        return true;
    }
    return /[<>]/.test(masked);
}

// A property term's characters: a tag's, plus : < > ? (and = in any number: an
// extra one is explained, not dropped, so the term never changes meaning silently).
// A quoted value keeps every text character.
function enforcePropertyTerm(rawToken) {
    let output = '';
    let index = 0;
    while (index < rawToken.length) {
        if (opensValue(rawToken, index)) {
            const { normalizedInner, closed, nextIndex } = readQuotedInner(rawToken, index + 1, VALUE_QUOTE);
            output += `${VALUE_QUOTE}${normalizedInner}${closed ? VALUE_QUOTE : ''}`;
            index = nextIndex;
            continue;
        }
        const char = rawToken[index];
        index += 1;
        if (!isTextCharacter(char)) {
            continue;
        }
        if (char === TAG_VALUE_SEPARATOR || PROPERTY_TERM_MARKS.has(char) || !TAG_CONTAINS_DISALLOWED.has(char)) {
            output += char;
        }
    }
    return output;
}

/** What is unfinished or wrong in a property term, or '' when it can run. */
function describePropertyTermProblem(typedTerm) {
    if (typedTerm.split(/[:<>=]/)[0] === OR_OPERATOR) {
        return 'OR is reserved and cannot be used as a tag';
    }
    const term = maskQuotedValues(typedTerm);
    const emptyValue = EMPTY_QUOTED_VALUE_RE.exec(term);
    if (emptyValue) {
        return `Write a value after ${emptyValue[1]}`;
    }
    const statsStart = STATS_TERM_START_RE.exec(term);
    if (!statsStart && !(term.startsWith(PROPERTY_SEPARATOR) && term.endsWith('?'))) {
        const chainProblem = describeChainProblem(term);
        if (chainProblem !== '') {
            return chainProblem;
        }
    }
    if ([NAMED_PROPERTY_TERM_RE, IMPLICIT_PROPERTY_TERM_RE, STATS_TERM_RE, TAGLESS_PROPERTY_TERM_RE, QUOTED_VALUE_TERM_RE].some((re) => re.test(term))) {
        return '';
    }
    if (term.startsWith(PROPERTY_SEPARATOR)) {
        return describeTaglessPropertyTermProblem(term);
    }
    if (statsStart) {
        const statsTag = statsStart[1].toLowerCase();
        const statsExample = `${statsTag}:${STATS_TERM_EXAMPLE_PROPERTY}`;
        if (!term.startsWith(`${statsStart[1]}${PROPERTY_SEPARATOR}`)) {
            return `Name the property after ${statsTag} (for example ${statsExample})`;
        }
        if (term.endsWith('?')) {
            return `${statsTag} always has a figure; compare it (for example ${statsExample})`;
        }
        if (term.slice(statsStart[1].length + PROPERTY_SEPARATOR.length).split(CHAIN_SEPARATOR_RE).length > 1) {
            return `Compare one figure per term (for example ${statsExample} ${statsTag}:fat<30)`;
        }
    }
    if (term.endsWith(PROPERTY_SEPARATOR)) {
        return `Name a property after the colon (for example ${PROPERTY_TERM_EXAMPLE})`;
    }
    if (PROPERTY_NAME_NOT_A_LETTER_RE.test(term)) {
        return `A property name starts with a letter (for example ${PROPERTY_TERM_EXAMPLE})`;
    }
    const trailingOperator = TRAILING_OPERATOR_RE.exec(term);
    if (trailingOperator) {
        return `Write a value after ${trailingOperator[1]}`;
    }
    return UNQUOTED_OPERATOR_PROBLEM;
}

// Same wording as the server (app/services/tag_properties.py _chain_problem): ?, MAX and
// MIN go in terms of their own, and a chain names each property once. term is masked.
function describeChainProblem(term) {
    const separatorIndex = term.indexOf(PROPERTY_SEPARATOR);
    if (separatorIndex === -1) {
        return '';
    }
    const isTagless = separatorIndex === 0;
    const segments = term.slice(separatorIndex + PROPERTY_SEPARATOR.length).split(CHAIN_SEPARATOR_RE);
    if (segments.length === 1) {
        // One property: no chain.
        return '';
    }
    const exampleTag = isTagless ? '' : 'jogging';
    const names = segments.map((segment) => foldTagCase(segment.split(/[<>=?]/)[0]));
    if (new Set(names).size !== names.length) {
        return `Name each property once in a search term (for example ${CHAIN_TERM_EXAMPLE})`;
    }
    for (const segment of segments) {
        const name = segment.split(/[<>=?]/)[0];
        if (segment.endsWith('?')) {
            return `Search a missing property in a term of its own (for example ${exampleTag}:miles>2 ${exampleTag}:${name}?)`;
        }
        const extreme = /=(MAX|MIN)$/.exec(segment);
        if (extreme) {
            return `${extreme[1]} goes in a term of its own (for example ${exampleTag}:${name}=${extreme[1]})`;
        }
    }
    return '';
}

// Same wording as the server (app/services/tag_properties.py parse_tagless_property_term).
function describeTaglessPropertyTermProblem(term) {
    if (term.endsWith('?')) {
        return 'A search for a missing property needs its tag (for example jogging:miles?)';
    }
    if (term === PROPERTY_SEPARATOR) {
        return `Name a property after the colon (for example ${TAGLESS_PROPERTY_TERM_EXAMPLE})`;
    }
    if (!/^:\p{L}/u.test(term)) {
        return `A property name starts with a letter (for example ${PROPERTY_TERM_EXAMPLE})`;
    }
    const trailingOperator = TRAILING_OPERATOR_RE.exec(term);
    if (trailingOperator) {
        return `Write a value after ${trailingOperator[1]}`;
    }
    return UNQUOTED_OPERATOR_PROBLEM;
}

function readQuotedInner(rawInput, startIndex, quoteChar) {
    if (typeof rawInput !== 'string') {
        throw new Error('readQuotedInner expects rawInput string');
    }
    if (!Number.isInteger(startIndex) || startIndex < 0) {
        throw new Error('readQuotedInner expects startIndex integer');
    }
    if (quoteChar !== '"' && quoteChar !== "'") {
        throw new Error('readQuotedInner expects quoteChar to be " or \'');
    }

    let index = startIndex;
    let normalizedInner = '';
    let closed = false;
    // A backslash typed last, its escape not yet finished.
    let endsInUnfinishedEscape = false;

    while (index < rawInput.length) {
        const char = rawInput[index];

        if (char === quoteChar) {
            closed = true;
            index += 1;
            break;
        }

        if (char === '\\') {
            if (index + 1 < rawInput.length) {
                const nextChar = rawInput[index + 1];
                if (nextChar === quoteChar || nextChar === '\\') {
                    normalizedInner += `\\${nextChar}`;
                    index += ESCAPE_SEQUENCE_LENGTH;
                    continue;
                }
            }

            if (isTextCharacter(char)) {
                normalizedInner += char;
            }
            index += 1;
            endsInUnfinishedEscape = index === rawInput.length;
            continue;
        }

        if (isTextCharacter(char)) {
            normalizedInner += char;
        }
        index += 1;
    }

    return { normalizedInner, closed, nextIndex: index, endsInUnfinishedEscape };
}

/**
 * An open quote reaches the end of the query, so only the last term can be one.
 * It searches as if closed (docs/ui/search-syntax.md, Completeness): its text as
 * typed, trailing space included, without an unfinished escape. '' when that
 * leaves no text.
 */
function closeOpenQuoteTerm(opening, inner, quoteChar, endsInUnfinishedEscape) {
    let text = inner;
    if (endsInUnfinishedEscape) {
        text = text.slice(0, -1);
    }
    if (text === '') {
        return '';
    }
    return `${opening}${text}${quoteChar}`;
}

/**
 * A tag or property term from index: to the next space outside a quoted value. Its
 * text, where the next term starts, and whether it ends in a value quote still open.
 */
function readTermToken(rawInput, startIndex) {
    let index = startIndex;
    let text = '';
    let endsInOpenValue = false;
    let endsInUnfinishedEscape = false;
    while (index < rawInput.length && !isWhitespace(rawInput[index])) {
        if (text.length > 0 && opensValue(rawInput, index)) {
            const quoted = readQuotedInner(rawInput, index + 1, VALUE_QUOTE);
            text += rawInput.slice(index, quoted.nextIndex);
            index = quoted.nextIndex;
            endsInOpenValue = !quoted.closed;
            endsInUnfinishedEscape = quoted.endsInUnfinishedEscape;
            continue;
        }
        text += rawInput[index];
        index += 1;
    }
    return { text, nextIndex: index, endsInOpenValue, endsInUnfinishedEscape };
}

/** A term ending in an open value quote, closed: '' when the value has nothing in it yet. */
function closeOpenValueTerm(term, endsInUnfinishedEscape) {
    let text = term;
    if (endsInUnfinishedEscape) {
        text = text.slice(0, -1);
    }
    if (text.endsWith(VALUE_QUOTE) && opensValue(text, text.length - 1)) {
        return '';
    }
    return `${text}${VALUE_QUOTE}`;
}

export function analyzeSearchQueryInput(typedInput) {
    if (typeof typedInput !== 'string') {
        throw new Error('analyzeSearchQueryInput expects a string');
    }
    // One Unicode form, so a search matches tags that look the same (tag-characters.js).
    const rawInput = normalizeText(typedInput);

    const normalizedTerms = [];
    const sanitizedTerms = [];
    // The terms with an open last quote closed: what the field holds once the
    // user moves on, and what runs while the quote is still open.
    const closedTerms = [];
    let endsInOpenQuote = false;

    const hasTrailingWhitespace = rawInput.length > 0 && isWhitespace(rawInput[rawInput.length - 1]);

    let isComplete = true;
    let warningMessage = null;
    let currentClauseTermCount = 0;
    let endsWithOrOperator = false;
    // A prefix followed by a space ("- tag"): invalid. The term after it is
    // explained and left out of the searched text, so it never runs with the
    // opposite meaning ("tag"). A lone prefix at the end is still being typed.
    let spacedPrefixPending = false;

    let index = 0;
    while (index < rawInput.length) {
        while (index < rawInput.length && isWhitespace(rawInput[index])) {
            index += 1;
        }
        if (index >= rawInput.length) {
            break;
        }

        let prefix = '';
        const firstChar = rawInput[index];
        if (firstChar === '+' || firstChar === '-') {
            prefix = firstChar;
            index += 1;
            if (index >= rawInput.length || isWhitespace(rawInput[index])) {
                normalizedTerms.push(prefix);
                closedTerms.push(prefix);
                isComplete = false;
                spacedPrefixPending = true;
                continue;
            }
        }
        // This term follows a prefix and a space: keep it as typed, explain,
        // and do not search for it.
        if (spacedPrefixPending) {
            spacedPrefixPending = false;
            if (!warningMessage) {
                warningMessage = SPACED_PREFIX_WARNING;
            }
            const termStart = index;
            const isQuoted = QUOTE_CHARS.has(rawInput[index]);
            let closedTerm = '';
            if (isQuoted) {
                const quoteChar = rawInput[index];
                const { closed, nextIndex, endsInUnfinishedEscape } = readQuotedInner(rawInput, index + 1, quoteChar);
                index = nextIndex;
                closedTerm = rawInput.slice(termStart, index);
                if (!closed) {
                    endsInOpenQuote = true;
                    closedTerm = closeOpenQuoteTerm(quoteChar, rawInput.slice(termStart + 1, index), quoteChar, endsInUnfinishedEscape);
                }
            } else {
                const termToken = readTermToken(rawInput, index);
                index = termToken.nextIndex;
                closedTerm = rawInput.slice(termStart, index);
                if (termToken.endsInOpenValue) {
                    endsInOpenQuote = true;
                    closedTerm = closeOpenValueTerm(closedTerm, termToken.endsInUnfinishedEscape);
                }
            }
            normalizedTerms.push(rawInput.slice(termStart, index));
            if (closedTerm !== '') {
                closedTerms.push(closedTerm);
            }
            continue;
        }

        // A `/` last of all may become a comment (`/*`): kept as typed, nothing searched yet.
        if (rawInput.slice(index) === COMMENT_OPEN[0]) {
            normalizedTerms.push(`${prefix}${COMMENT_OPEN[0]}`);
            closedTerms.push(`${prefix}${COMMENT_OPEN[0]}`);
            isComplete = false;
            index = rawInput.length;
            continue;
        }
        if (rawInput.startsWith(COMMENT_OPEN, index)) {
            // `+` is a tag-term modifier only. Drop it for a comment.
            if (prefix === '+') prefix = '';
            const comment = readCommentTerm(rawInput, index);
            index = comment.nextIndex;
            normalizedTerms.push(`${prefix}${comment.typed}`);
            if (!comment.isClosed) endsInOpenQuote = true;
            if (comment.words === '') {
                isComplete = false;
                if (comment.isClosed) closedTerms.push(`${prefix}${comment.typed}`);
                if (comment.isClosed && !warningMessage) warningMessage = EMPTY_COMMENT_WARNING;
                continue;
            }
            // Searched as if closed while still being typed, as an open quote is.
            const closedComment = `${prefix}${COMMENT_OPEN}${comment.words}${COMMENT_CLOSE}`;
            closedTerms.push(closedComment);
            sanitizedTerms.push(closedComment);
            currentClauseTermCount += 1;
            endsWithOrOperator = false;
            continue;
        }

        const nextChar = rawInput[index];
        const isQuoteStart = QUOTE_CHARS.has(nextChar);
        if (isQuoteStart && prefix === '+') {
            // `+` is a tag-term modifier only. Drop it for quoted text.
            prefix = '';
        }

        if (isQuoteStart && (prefix === '' || prefix === '-')) {
            const quoteChar = nextChar;
            index += 1;
            const { normalizedInner, closed, nextIndex, endsInUnfinishedEscape } = readQuotedInner(rawInput, index, quoteChar);
            index = nextIndex;

            const normalized = `${prefix}${quoteChar}${normalizedInner}`;

            if (!closed) {
                normalizedTerms.push(normalized);
                endsInOpenQuote = true;
                const closedOpenTerm = closeOpenQuoteTerm(`${prefix}${quoteChar}`, normalizedInner, quoteChar, endsInUnfinishedEscape);
                if (closedOpenTerm === '') {
                    // A quote with nothing typed in it yet: nothing to search, and nothing to warn about.
                    isComplete = false;
                    continue;
                }
                closedTerms.push(closedOpenTerm);
                sanitizedTerms.push(closedOpenTerm);
                currentClauseTermCount += 1;
                endsWithOrOperator = false;
                continue;
            }

            const closedToken = `${normalized}${quoteChar}`;
            normalizedTerms.push(closedToken);
            closedTerms.push(closedToken);

            if (normalizedInner.length === 0) {
                isComplete = false;
                if (!warningMessage) {
                    warningMessage = 'Enter text inside quotes';
                }
                continue;
            }

            sanitizedTerms.push(closedToken);
            currentClauseTermCount += 1;
            endsWithOrOperator = false;
            continue;
        }

        const termToken = readTermToken(rawInput, index);
        const rawToken = termToken.text;
        index = termToken.nextIndex;
        if (termToken.endsInOpenValue) {
            // author="Ursula Le: searched as if closed, as an open text quote is; with
            // nothing in it yet (author=") it is still being typed.
            endsInOpenQuote = true;
            const unprefixed = rawToken.replace(/^[+-]+/, '');
            const openTerm = `${prefix}${enforcePropertyTerm(unprefixed)}`;
            normalizedTerms.push(openTerm);
            const closedOpenTerm = closeOpenValueTerm(openTerm, termToken.endsInUnfinishedEscape);
            if (closedOpenTerm === '') {
                isComplete = false;
                continue;
            }
            closedTerms.push(closedOpenTerm);
            if (describePropertyTermProblem(closedOpenTerm.slice(prefix.length)) !== '') {
                isComplete = false;
                continue;
            }
            sanitizedTerms.push(closedOpenTerm);
            currentClauseTermCount += 1;
            endsWithOrOperator = false;
            continue;
        }

        if (rawToken === OR_OPERATOR) {
            normalizedTerms.push(`${prefix}${OR_OPERATOR}`);
            closedTerms.push(`${prefix}${OR_OPERATOR}`);
            if (prefix !== '') {
                isComplete = false;
                if (!warningMessage) {
                    warningMessage = 'OR is reserved and cannot be used as a tag';
                }
                endsWithOrOperator = false;
                continue;
            }
            if (currentClauseTermCount === 0) {
                isComplete = false;
                if (!warningMessage) {
                    warningMessage = 'OR requires a term before it';
                }
                endsWithOrOperator = true;
                continue;
            }
            sanitizedTerms.push(OR_OPERATOR);
            currentClauseTermCount = 0;
            endsWithOrOperator = true;
            continue;
        }

        const unprefixedToken = rawToken.replace(/^[+-]+/, '');
        if (isPropertyTerm(unprefixedToken)) {
            const term = `${prefix}${enforcePropertyTerm(unprefixedToken)}`;
            normalizedTerms.push(term);
            closedTerms.push(term);
            const problem = describePropertyTermProblem(term.slice(prefix.length));
            if (problem !== '') {
                // Still being typed until a space follows it: then say how to finish it.
                // OR is reserved at once, as a tag OR is.
                isComplete = false;
                let isFinished = hasTrailingWhitespace;
                if (index < rawInput.length) {
                    isFinished = true;
                }
                if (problem.startsWith(OR_OPERATOR)) {
                    isFinished = true;
                }
                if (isFinished && !warningMessage) {
                    warningMessage = problem;
                }
                continue;
            }
            sanitizedTerms.push(term);
            currentClauseTermCount += 1;
            endsWithOrOperator = false;
            continue;
        }

        const enforcedToken = enforceTagToken(rawToken);
        if (enforcedToken.length === 0) {
            if (prefix) {
                normalizedTerms.push(prefix);
                closedTerms.push(prefix);
                isComplete = false;
            }
            continue;
        }
        if (enforcedToken === OR_OPERATOR) {
            normalizedTerms.push(OR_OPERATOR);
            closedTerms.push(OR_OPERATOR);
            isComplete = false;
            if (!warningMessage) {
                warningMessage = 'OR is reserved and cannot be used as a tag';
            }
            endsWithOrOperator = false;
            continue;
        }

        const normalizedTag = `${prefix}${enforcedToken}`;
        normalizedTerms.push(normalizedTag);
        closedTerms.push(normalizedTag);
        sanitizedTerms.push(normalizedTag);
        currentClauseTermCount += 1;
        endsWithOrOperator = false;
    }

    if (endsWithOrOperator) {
        isComplete = false;
        if (!warningMessage) {
            warningMessage = 'OR requires a term after it';
        }
        while (sanitizedTerms[sanitizedTerms.length - 1] === OR_OPERATOR) {
            sanitizedTerms.pop();
        }
    }

    // Terms carry no outer spaces, except an open last quote's own text (a trailing
    // space there marks a word edge), which is kept.
    const normalizedText = normalizedTerms.join(' ');
    const sanitizedText = sanitizedTerms.join(' ');
    const closedText = closedTerms.join(' ');

    let enforcedText = normalizedText;
    if (hasTrailingWhitespace && normalizedText.length > 0 && !endsInOpenQuote) {
        enforcedText = `${normalizedText} `;
    }

    return {
        normalizedText,
        enforcedText,
        sanitizedText,
        closedText,
        endsInOpenQuote,
        isComplete,
        warningMessage,
    };
}

// A property term a new note can be given (app/usecases/search_context_tags.py): its tag
// and exact values, jogging:miles=3, jogging:miles=3:duration=30 or book:author="Le Guin"
// (masked), or a tag's own quoted value, author="Le Guin".
const FILLABLE_PROPERTY_TERM_RE = new RegExp(
    `^${TERM_TAG_PATTERN}(?:=${TERM_VALUE_PATTERN}|(?::\\p{L}[^:=<>?"]*=${TERM_VALUE_PATTERN})+)$`, 'u',
);

/**
 * The first property term in a search's first clause that a note added in the search
 * cannot be given (jogging:miles>3, :foo="ba", jogging:miles?, MAX, @sum:calories>2000),
 * or null. A note added there would not match its own search, so none is added (agreed
 * 2026-10-31). Excluded terms never block: a new note has no values.
 */
export function findUnfillableSearchTerm(searchQuery) {
    if (typeof searchQuery !== 'string') {
        throw new Error('findUnfillableSearchTerm expects a string');
    }
    const runnable = analyzeSearchQueryInput(searchQuery).sanitizedText;
    let index = 0;
    while (index < runnable.length) {
        if (isWhitespace(runnable[index])) {
            index += 1;
            continue;
        }
        const prefix = runnable[index] === '-' || runnable[index] === '+' ? runnable[index] : '';
        const bodyStart = index + prefix.length;
        if (QUOTE_CHARS.has(runnable[bodyStart])) {
            index = readQuotedInner(runnable, bodyStart + 1, runnable[bodyStart]).nextIndex;
            continue;
        }
        const { text, nextIndex } = readTermToken(runnable, bodyStart);
        index = nextIndex;
        if (text === OR_OPERATOR) {
            return null;
        }
        if (prefix === '-' || !isPropertyTerm(text)) {
            continue;
        }
        const masked = maskQuotedValues(text);
        const value = masked.slice(masked.lastIndexOf('=') + 1);
        if (!FILLABLE_PROPERTY_TERM_RE.test(masked) || EXTREME_VALUES.has(value)) {
            return text;
        }
    }
    return null;
}

/**
 * The quote mark of the quoted phrase the cursor is inside (" or '), or '' when
 * the cursor is outside quoted text. Inside a phrase a paste is text as copied,
 * not dictation (docs/ui/dictation-paste.md).
 */
export function findOpenQuoteAtIndex(rawInput, cursorIndex) {
    if (typeof rawInput !== 'string') {
        throw new Error('findOpenQuoteAtIndex expects a string');
    }
    if (!Number.isInteger(cursorIndex) || cursorIndex < 0 || cursorIndex > rawInput.length) {
        throw new Error('findOpenQuoteAtIndex expects a cursor index within the input');
    }
    const before = rawInput.slice(0, cursorIndex);
    let index = 0;
    while (index < before.length) {
        if (isWhitespace(before[index])) {
            index += 1;
            continue;
        }
        if (before[index] === '+' || before[index] === '-') {
            index += 1;
        }
        if (index < before.length && QUOTE_CHARS.has(before[index])) {
            const quoteChar = before[index];
            const { closed, nextIndex } = readQuotedInner(before, index + 1, quoteChar);
            if (!closed) {
                return quoteChar;
            }
            index = nextIndex;
            continue;
        }
        const termToken = readTermToken(before, index);
        if (termToken.endsInOpenValue) {
            return VALUE_QUOTE;
        }
        index = termToken.nextIndex;
    }
    return '';
}

/** Pasted text for inside a quoted phrase: one line, its quote marks and backslashes escaped. */
export function quotePastedSearchText(pastedText, quoteChar) {
    if (typeof pastedText !== 'string') {
        throw new Error('quotePastedSearchText expects the pasted text');
    }
    if (!QUOTE_CHARS.has(quoteChar)) {
        throw new Error('quotePastedSearchText expects " or \'');
    }
    return pastedText
        .replace(/[\r\n]+/g, ' ')
        .replaceAll('\\', '\\\\')
        .replaceAll(quoteChar, `\\${quoteChar}`);
}

export function enforceSearchQueryInputForEditing(rawInput) {
    return analyzeSearchQueryInput(rawInput).enforcedText;
}

export function findSearchTagAtIndex(rawInput, cursorIndex) {
    if (typeof rawInput !== 'string') {
        throw new Error('findSearchTagAtIndex expects a string');
    }
    if (!Number.isInteger(cursorIndex)) {
        throw new Error('findSearchTagAtIndex expects cursorIndex integer');
    }
    if (cursorIndex < 0 || cursorIndex > rawInput.length) {
        throw new Error('findSearchTagAtIndex cursorIndex out of bounds');
    }

    let index = 0;
    while (index < rawInput.length) {
        while (index < rawInput.length && isWhitespace(rawInput[index])) {
            index += 1;
        }
        if (index >= rawInput.length) {
            break;
        }

        const tokenStart = index;
        let prefix = null;
        const firstChar = rawInput[index];
        if (firstChar === '+' || firstChar === '-') {
            prefix = firstChar;
            index += 1;
            if (index >= rawInput.length || isWhitespace(rawInput[index])) {
                continue;
            }
        }

        // A comment is no tag.
        if (rawInput.startsWith(COMMENT_OPEN, index)) {
            index = readCommentTerm(rawInput, index).nextIndex;
            continue;
        }

        const nextChar = rawInput[index];
        const isQuoteStart = QUOTE_CHARS.has(nextChar);
        if (isQuoteStart) {
            if (prefix === '+') {
                prefix = null;
            }
            if (prefix === null || prefix === '-') {
                const quoteChar = nextChar;
                index += 1;
                const { nextIndex } = readQuotedInner(rawInput, index, quoteChar);
                index = nextIndex;
                continue;
            }
        }

        index = readTermToken(rawInput, index).nextIndex;
        const tokenEnd = index;
        if (cursorIndex >= tokenStart && cursorIndex <= tokenEnd) {
            let tokenText = rawInput.slice(tokenStart, tokenEnd);
            if (prefix) {
                tokenText = tokenText.slice(1);
            }
            // A property term is about its tag: jogging:miles>2 is jogging.
            if (isPropertyTerm(tokenText)) {
                tokenText = tokenText.split(/[:<>=]/)[0];
            }
            const enforced = enforceTagToken(tokenText);
            if (enforced === OR_OPERATOR) {
                return null;
            }
            if (enforced.length > 0) {
                return {
                    tag: enforced,
                    start: tokenStart,
                    end: tokenEnd,
                    prefix,
                };
            }
            return null;
        }
    }

    return null;
}
