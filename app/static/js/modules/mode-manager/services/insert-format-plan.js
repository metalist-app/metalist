import { chooseStyleScope, scanTopLevelTagTokens } from './add-style-service.js';
import { DEFAULT_PASSWORD_CHARSET, DEFAULT_PASSWORD_LENGTH, generateRandomPassword, normalizePasswordCharset } from '../../password-generator.js';

// What Insert LaTeX, Insert CSV, Insert Mermaid Diagram and Insert Password type, and which
// tag they add (insert-format-service.js types it): no page needed, so it is tested on its own.

export const PASSWORD_KIND = 'password';
export const INSERT_KINDS = Object.freeze({
    latex: Object.freeze({ tag: '@latex', label: 'LaTeX' }),
    csv: Object.freeze({ tag: '@csv', label: 'CSV' }),
    mermaid: Object.freeze({ tag: '@mermaid', label: 'Mermaid Diagram' }),
    [PASSWORD_KIND]: Object.freeze({ tag: '@password', label: 'Password' }),
});
const PASSWORD_TAG = INSERT_KINDS[PASSWORD_KIND].tag;
const MARKDOWN_TAG = '@markdown';
const TAG_SPELLINGS = Object.freeze({ '@latex': '@LaTeX', '@csv': '@csv', '@mermaid': '@mermaid' });
const MATH_DELIMITER = '$$';
const FENCE = '```';
// A new diagram starts as a flowchart, ready for its first node.
const DIAGRAM_START = 'flowchart LR\n';
const LINE_BREAK = '\n';
const WRAPPED_TAG_RE = /^(?<open>[{[(]{1,3})\s*(?<tag>@[^\s{}[\]()]+)\s*(?<close>[}\])]{1,3})$/;

function globalTags(tagBarText) {
    return new Set(scanTopLevelTagTokens(tagBarText).map((token) => token.toLowerCase()));
}

// The kinds the menu and the palette offer for a note with these tags.
export function insertKindsFor(tagBarText) {
    const tags = globalTags(tagBarText);
    return Object.keys(INSERT_KINDS).filter((kind) => !tags.has(INSERT_KINDS[kind].tag));
}

// The wrapper the tag bar already gives the format (`(((@LaTeX)))`), or null.
function existingWrapper(tagBarText, tag) {
    for (const token of scanTopLevelTagTokens(tagBarText)) {
        const match = WRAPPED_TAG_RE.exec(token);
        if (match === null || match.groups.tag.toLowerCase() !== tag) continue;
        if (match.groups.open.length !== match.groups.close.length) continue;
        return { tagToken: token, open: match.groups.open, close: match.groups.close };
    }
    return null;
}

// What to type and which tag (or none) to add, for `kind` in a note with these tags and text.
export function insertPlan({ kind, tagBarText, contentText, hasSelection }) {
    if (!Object.hasOwn(INSERT_KINDS, kind) || kind === PASSWORD_KIND) {
        throw new Error(`Not a kind to insert as a region to type in: ${kind}`);
    }
    const { tag } = INSERT_KINDS[kind];
    const isMarkdown = globalTags(tagBarText).has(MARKDOWN_TAG);
    if (isMarkdown && kind === 'latex') {
        return { open: MATH_DELIMITER, close: MATH_DELIMITER, start: '', tagToken: null, isBlock: false };
    }
    if (isMarkdown && kind === 'mermaid') {
        return { open: `${FENCE}mermaid${LINE_BREAK}`, close: `${LINE_BREAK}${FENCE}`, start: hasSelection ? '' : DIAGRAM_START, tagToken: null, isBlock: true };
    }
    const existing = existingWrapper(tagBarText, tag);
    let start = '';
    if (kind === 'mermaid' && !hasSelection) start = DIAGRAM_START;
    if (existing !== null) {
        return { open: existing.open, close: existing.close, start, tagToken: null, isBlock: false };
    }
    const scope = chooseStyleScope(contentText, tagBarText);
    return {
        open: scope.openToken, close: scope.closeToken, start,
        tagToken: `${scope.openToken}${TAG_SPELLINGS[tag]}${scope.closeToken}`, isBlock: false,
    };
}

// Insert Password (docs/ui/content-formatting.md, "A password in a note's text"): a new
// password, as the password generator makes one by default, typed where the right-click (or
// caret) was. A note with nothing in it becomes a password note (@password); otherwise the
// password is a region of its own, in a wrapper the tag bar already gives @password or else
// one nothing in the note uses, its `((@password))` added. A region's password leaves out its
// wrapper's characters, which would end the region early. The selection, if any, is replaced,
// as typing replaces it.
export function insertPasswordPlan({ tagBarText, contentText, isBlank, fillRandomValues }) {
    if (typeof tagBarText !== 'string' || typeof contentText !== 'string' || typeof isBlank !== 'boolean') {
        throw new Error('insertPasswordPlan needs the tag bar, the text and whether the note is blank');
    }
    if (isBlank) {
        return { text: generateRandomPassword(DEFAULT_PASSWORD_LENGTH, DEFAULT_PASSWORD_CHARSET, fillRandomValues), tagToken: PASSWORD_TAG };
    }
    const existing = existingWrapper(tagBarText, PASSWORD_TAG);
    let open = null;
    let close = null;
    let tagToken = null;
    if (existing !== null) {
        open = existing.open;
        close = existing.close;
    } else {
        const scope = chooseStyleScope(contentText, tagBarText);
        open = scope.openToken;
        close = scope.closeToken;
        tagToken = `${open}${PASSWORD_TAG}${close}`;
    }
    const wrapperCharacters = new Set([...open, ...close]);
    const charset = Array.from(normalizePasswordCharset(DEFAULT_PASSWORD_CHARSET)).filter((character) => !wrapperCharacters.has(character)).join('');
    const password = generateRandomPassword(DEFAULT_PASSWORD_LENGTH, charset, fillRandomValues);
    return { text: `${open}${password}${close}`, tagToken };
}
