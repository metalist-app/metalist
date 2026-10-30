import { chooseStyleScope, scanTopLevelTagTokens } from './add-style-service.js';

// What Insert LaTeX, Insert CSV and Insert Mermaid Diagram type, and which tag they add
// (insert-format-service.js types it): no page needed, so it is tested on its own.

export const INSERT_KINDS = Object.freeze({
    latex: Object.freeze({ tag: '@latex', label: 'LaTeX' }),
    csv: Object.freeze({ tag: '@csv', label: 'CSV' }),
    mermaid: Object.freeze({ tag: '@mermaid', label: 'Mermaid Diagram' }),
});
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
    if (!Object.hasOwn(INSERT_KINDS, kind)) {
        throw new Error(`Not a kind to insert: ${kind}`);
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
