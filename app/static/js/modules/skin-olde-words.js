import { ApplicationState } from './application-state.js';
import { NOT_RESPELLED, NOT_VERBS, SPELLING_ENDINGS, THEE_AFTER, TWO_WORD_SWAPS, VERB_SUBJECTS, WORD_SWAPS } from './skin-olde-vocabulary.js';

// The Illuminated skin draws a note's words as old English: "you" as "thou" (docs/ui/skins.md).
// Only the drawing changes. Each swapped word is a span holding the real word, so the real words
// go back before a note is edited or saved. Copying needs nothing: a note's text can be selected
// only while editing, and Copy on a note is built by the server from the saved note.
const OLDE_WORD_CLASS = 'olde-word';
export const INITIAL_HOST_ATTRIBUTE = 'data-initial-host';
const OLDE_WORD_SELECTOR = `.${OLDE_WORD_CLASS}`;
const NOTE_CONTENT_SELECTOR = '.note:not(.editing) > .note-content:not([contenteditable="true"])';
// Where the exact text matters.
const UNTOUCHED_SELECTOR = [
    OLDE_WORD_SELECTOR, 'code', 'pre', 'a', 'button', 'math', 'svg', 'style', 'script', 'input', 'textarea', 'mark',
    '.meta-code', '.meta-json', '.meta-csv', '.meta-diff', '.meta-mermaid', '.meta-mermaid-diagram', '.meta-latex',
    '.meta-copyable', '.meta-credential-value', '.note-reference-block', '.note-backlinks-link',
].join(', ');

const WORD_PATTERN = /[A-Za-z]+(?:['\u2019][A-Za-z]+)?/g;
const CURLY_APOSTROPHE = /\u2019/g;
const ONLY_SPACES = /^[ \t]+$/;
const JOINED_BEFORE = /[\w@#/\\.-]$/;
const JOINED_AFTER = /^(?:[\w@/\\]|[.-]\w)/;
const MIN_VERB_LETTERS = 3;
const ALL_CAPITALS_MIN_LETTERS = 2;

const moduleState = ApplicationState.createFields('skin-olde-words', {
    observer: null,
    pendingContents: new Set(),
    isSwapScheduled: false,
});

function inTheCaseOf(original, olde) {
    if (original.length >= ALL_CAPITALS_MIN_LETTERS && original === original.toUpperCase()) {
        return olde.toUpperCase();
    }
    if (original[0] === original[0].toUpperCase()) {
        const firstLetter = olde[0] === "'" ? 1 : 0;
        return olde.slice(0, firstLetter) + olde[firstLetter].toUpperCase() + olde.slice(firstLetter + 1);
    }
    return olde;
}

function verbEnding(verb) {
    const stem = verb.slice(0, -1);
    return stem.endsWith('e') ? `${stem}th` : `${stem}eth`;
}

function oldeSpelling(word) {
    if (NOT_RESPELLED.has(word)) {
        return null;
    }
    for (const { pattern, replacement, minLetters } of SPELLING_ENDINGS) {
        if (word.length >= minLetters && pattern.test(word)) {
            return word.replace(pattern, replacement);
        }
    }
    return null;
}

function oldeWordFor(word, previousWord, mayRespell) {
    if (word === 'you') {
        return THEE_AFTER.has(previousWord) ? 'thee' : 'thou';
    }
    if (WORD_SWAPS.has(word)) {
        return WORD_SWAPS.get(word);
    }
    if (VERB_SUBJECTS.has(previousWord) && word.length >= MIN_VERB_LETTERS && word.endsWith('s') && !word.endsWith('ss') && !NOT_VERBS.has(word)) {
        return verbEnding(word);
    }
    return mayRespell ? oldeSpelling(word) : null;
}

function foldedWord(word) {
    return word.toLowerCase().replace(CURLY_APOSTROPHE, "'");
}

// Plain words only: not iPhone, a@b.com, some/path or the parts of old-fashioned.
function isPlainWord(text, match) {
    const word = match[0];
    const end = match.index + word.length;
    if (JOINED_BEFORE.test(text.slice(0, match.index)) || JOINED_AFTER.test(text.slice(end))) {
        return false;
    }
    return [word[0].toUpperCase() + word.slice(1).toLowerCase(), word.toLowerCase(), word.toUpperCase()].includes(word);
}

// A capital inside a sentence is likely a name, so only its first word may be respelled.
function mayRespellWord(word, wordIndex) {
    if (word === word.toLowerCase()) {
        return true;
    }
    return wordIndex === 0 && word !== word.toUpperCase();
}

// The text in pieces: { text } as written, or { text, original } where a word is swapped.
export function oldeTextParts(text) {
    if (typeof text !== 'string') {
        throw new Error('oldeTextParts requires a string');
    }
    const words = Array.from(text.matchAll(WORD_PATTERN));
    const parts = [];
    let position = 0;
    let previousWord = '';
    let previousEnd = 0;
    for (let index = 0; index < words.length; index += 1) {
        const match = words[index];
        const word = foldedWord(match[0]);
        const next = words[index + 1];
        const isPaired = next !== undefined && isPlainWord(text, match) && isPlainWord(text, next)
            && ONLY_SPACES.test(text.slice(match.index + match[0].length, next.index));
        const pair = isPaired ? `${word} ${foldedWord(next[0])}` : '';
        let original = null;
        let olde = null;
        let endIndex = index;
        if (TWO_WORD_SWAPS.has(pair)) {
            original = text.slice(match.index, next.index + next[0].length);
            olde = TWO_WORD_SWAPS.get(pair);
            endIndex = index + 1;
        } else if (isPlainWord(text, match)) {
            const isRightAfterPrevious = ONLY_SPACES.test(text.slice(previousEnd, match.index));
            const swapped = oldeWordFor(word, isRightAfterPrevious ? previousWord : '', mayRespellWord(match[0], index));
            if (swapped !== null) {
                original = match[0];
                olde = swapped;
            }
        }
        previousWord = foldedWord(words[endIndex][0]);
        previousEnd = words[endIndex].index + words[endIndex][0].length;
        index = endIndex;
        if (original !== null) {
            if (match.index > position) parts.push({ text: text.slice(position, match.index) });
            parts.push({ text: inTheCaseOf(original, olde), original });
            position = match.index + original.length;
        }
    }
    if (position < text.length) parts.push({ text: text.slice(position) });
    return parts;
}

function swappableTextNodes(content) {
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => (node.parentElement.closest(UNTOUCHED_SELECTOR) === null ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });
    const nodes = [];
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
        nodes.push(node);
    }
    return nodes;
}

function oldeWordElement(part) {
    const span = document.createElement('span');
    span.className = OLDE_WORD_CLASS;
    span.dataset.original = part.original;
    span.dataset.olde = part.text;
    span.textContent = part.text;
    return span;
}

function swapWordsIn(content) {
    for (const node of swappableTextNodes(content)) {
        const parts = oldeTextParts(node.nodeValue);
        if (parts.some((part) => 'original' in part)) {
            node.replaceWith(...parts.map((part) => ('original' in part ? oldeWordElement(part) : document.createTextNode(part.text))));
        }
    }
}

// The note's text as it was before the skin touched it: the real words back in place of the spans,
// and no mark on the block that holds the big letter.
export function restoreOldeWords(root) {
    for (const marked of root.querySelectorAll(`[${INITIAL_HOST_ATTRIBUTE}]`)) {
        marked.removeAttribute(INITIAL_HOST_ATTRIBUTE);
    }
    // A template's fragment has no attributes of its own.
    if (typeof root.removeAttribute === 'function') {
        root.removeAttribute(INITIAL_HOST_ATTRIBUTE);
    }
    const spans = Array.from(root.querySelectorAll(OLDE_WORD_SELECTOR));
    for (const span of spans) {
        span.replaceWith(document.createTextNode(span.dataset.original));
    }
    if (spans.length > 0) {
        root.normalize();
    }
}

// The last guard before storage: whatever reached a save, it holds the real words.
export function restoreOldeWordsInHtml(html) {
    if (!html.includes(OLDE_WORD_CLASS) && !html.includes(INITIAL_HOST_ATTRIBUTE)) {
        return html;
    }
    const template = document.createElement('template');
    template.innerHTML = html;
    restoreOldeWords(template.content);
    return template.innerHTML;
}

function notesContainer() {
    const container = document.getElementById('notes-container');
    if (container === null) {
        throw new Error('Old-English words need #notes-container');
    }
    return container;
}

function schedulePendingSwaps() {
    if (moduleState.isSwapScheduled) {
        return;
    }
    moduleState.isSwapScheduled = true;
    requestAnimationFrame(() => {
        moduleState.isSwapScheduled = false;
        if (moduleState.observer === null) {
            return;
        }
        const contents = Array.from(moduleState.pendingContents);
        if (contents.length === 0) {
            return;
        }
        moduleState.pendingContents = new Set();
        for (const content of contents) {
            if (content.isConnected && content.matches(NOTE_CONTENT_SELECTOR)) {
                swapWordsIn(content);
            }
        }
    });
}

function addPendingContent(content) {
    if (!moduleState.pendingContents.has(content)) {
        moduleState.pendingContents.add(content);
    }
}

function noteChangedParts(mutations) {
    for (const mutation of mutations) {
        const element = mutation.target instanceof Element ? mutation.target : mutation.target.parentElement;
        if (element === null) {
            continue;
        }
        const content = element.closest('.note-content');
        if (content !== null) {
            addPendingContent(content);
        }
        for (const added of mutation.addedNodes) {
            if (added instanceof Element) {
                for (const inner of added.querySelectorAll('.note-content')) {
                    addPendingContent(inner);
                }
            }
        }
    }
    schedulePendingSwaps();
}

export function setOldeWordsActive(isActive) {
    if (typeof isActive !== 'boolean') {
        throw new Error('setOldeWordsActive requires a boolean');
    }
    if (isActive === (moduleState.observer !== null)) {
        return;
    }
    const container = notesContainer();
    if (!isActive) {
        moduleState.observer.disconnect();
        moduleState.observer = null;
        restoreOldeWords(container);
        return;
    }
    moduleState.observer = new MutationObserver(noteChangedParts);
    moduleState.observer.observe(container, { childList: true, subtree: true, characterData: true });
    for (const content of container.querySelectorAll(NOTE_CONTENT_SELECTOR)) {
        swapWordsIn(content);
    }
}
