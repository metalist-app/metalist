// A note's fold arrow (▾/▸) sits on the baseline of the note's first line of text,
// as a bullet sits on its line, so it is level with that line at any size: a
// heading, the top-level note sizes, a line that wraps, the line being edited
// (agreed 2026-10-26, docs/ui/controls.md). A first line that is not text (a
// picture, a formula, a diagram, a table, code) keeps the arrow at the note's
// top, where the stylesheet puts it. Notes in embeds follow the same rule.
//
// The baseline is read from the first letter's box and its font's metrics, never
// by adding anything to the text: the note being edited is never touched. The
// arrows are placed before the browser paints, so none shows in its old place.
//
// Downloaded exports inline this file as it is (html_export.py): it imports nothing.

// The arrows of notes in the list (and in full screen and floating windows) and of notes in embeds.
const ARROW_SELECTOR = '.note > .note-collapse-toggle, .note-embed-body > .note-embed-collapse-toggle';
// What a first line can be instead of text; the arrow stays at the note's top for these.
const NOT_TEXT_SELECTOR = [
    'img', 'video', 'canvas', 'table', 'pre', '.meta-latex', '.meta-mermaid-diagram', 'pre.meta-mermaid-source',
    '.note-file-image-embed', '.note-file-excalidraw-embed', 'math[display="block"]',
].join(', ');
// The arrow's own line (main.css): its glyph sits on the baseline of a line this tall.
const ARROW_LINE_HEIGHT_PX = 27;
const HALF = 2;
// A change inside a note realigns that note's arrows; a change elsewhere, all of them.
const NOTE_SELECTOR = '.note';

function fontOf(element) {
    const style = getComputedStyle(element);
    return `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
}

function isShown(element) {
    return element.getClientRects().length > 0;
}

// The text the arrow folds: the note's content (the one shown, where an export holds
// a folded and an unfolded copy), or an embedded note's.
function contentOf(arrow) {
    const owner = arrow.parentElement;
    const selector = owner.classList.contains('note-embed-body') ? ':scope > .note-embed-content' : ':scope > .note-content';
    return [...owner.querySelectorAll(selector)].find(isShown);
}

// The first letter of the first line: a text node outside anything that is not text.
function firstText(content) {
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
        acceptNode: (text) => {
            const parent = text.parentElement;
            if (!/\S/.test(text.data) || !isShown(parent)) return NodeFilter.FILTER_REJECT;
            const notText = parent.closest(NOT_TEXT_SELECTOR);
            if (notText !== null && content.contains(notText)) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    return walker.nextNode();
}

// An empty first line's baseline: a hidden line of one letter, in the content's font,
// laid where the content's first line starts, outside the notes (the content is not touched).
function emptyLineBaseline(content) {
    const style = getComputedStyle(content);
    const box = content.getBoundingClientRect();
    const line = document.createElement('div');
    line.setAttribute('aria-hidden', 'true');
    line.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;margin:0;padding:0;border:0;white-space:pre';
    for (const property of ['fontStyle', 'fontWeight', 'fontSize', 'fontFamily', 'lineHeight', 'letterSpacing']) {
        line.style[property] = style[property];
    }
    line.style.left = `${box.left}px`;
    line.style.top = `${box.top + content.clientTop + parseFloat(style.paddingTop)}px`;
    const marker = document.createElement('span');
    marker.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
    line.append(marker, 'x');
    document.body.appendChild(line);
    const baseline = marker.getBoundingClientRect().bottom;
    line.remove();
    return baseline;
}

// Measures and places arrows. It keeps the font metrics it has read, which only
// depend on the fonts, so each aligner (the list, a window, an export) has its own.
function createFoldArrowAligner() {
    const metricsByFont = new Map();
    const measuring = { context: null };

    // The ascent and descent of a font's text box, as the browser lays its text out.
    function fontMetrics(font) {
        if (metricsByFont.has(font)) return metricsByFont.get(font);
        if (measuring.context === null) measuring.context = document.createElement('canvas').getContext('2d');
        measuring.context.font = font;
        const measured = measuring.context.measureText('x');
        const metrics = { ascent: measured.fontBoundingBoxAscent, descent: measured.fontBoundingBoxDescent };
        if (!Number.isFinite(metrics.ascent) || !Number.isFinite(metrics.descent)) {
            throw new Error(`No font metrics for ${font}`);
        }
        metricsByFont.set(font, metrics);
        return metrics;
    }

    // The baseline of the content's first line of text, or null when its first line is not text.
    function firstLineBaseline(content) {
        const text = firstText(content);
        const notText = [...content.querySelectorAll(NOT_TEXT_SELECTOR)].find(isShown);
        if (text === null) {
            if (notText !== undefined) return null;
            return emptyLineBaseline(content);
        }
        const range = document.createRange();
        const start = text.data.search(/\S/);
        range.setStart(text, start);
        range.setEnd(text, start + 1);
        const letter = range.getClientRects()[0];
        // Something that is not text on a line above the text's: that is the first line.
        if (notText !== undefined && (notText.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
            && notText.getBoundingClientRect().bottom <= letter.top) {
            return null;
        }
        return letter.bottom - fontMetrics(fontOf(text.parentElement)).descent;
    }

    // Where the arrow's top goes for its glyph to sit on the first line's baseline;
    // null keeps the stylesheet's place.
    function arrowTop(arrow) {
        const content = contentOf(arrow);
        if (content === undefined) return null;
        const baseline = firstLineBaseline(content);
        if (baseline === null) return null;
        const owner = arrow.offsetParent;
        const { ascent, descent } = fontMetrics(fontOf(arrow));
        const glyphBaseline = (ARROW_LINE_HEIGHT_PX - ascent - descent) / HALF + ascent;
        return baseline - (owner.getBoundingClientRect().top + owner.clientTop) - glyphBaseline;
    }

    function place(arrow, top) {
        if (top === null) {
            if (arrow.style.top !== '') arrow.style.top = '';
            return;
        }
        const value = `${top}px`;
        if (arrow.style.top !== value) arrow.style.top = value;
    }

    // Every arrow shown in `scopes`: all are measured first, then all are placed, so
    // the page is laid out once.
    function align(scopes) {
        const arrows = [];
        for (const scope of scopes) {
            if (scope.matches(ARROW_SELECTOR)) arrows.push(scope);
            arrows.push(...scope.querySelectorAll(ARROW_SELECTOR));
        }
        const shown = [...new Set(arrows)].filter(isShown);
        const tops = shown.map(arrowTop);
        shown.forEach((arrow, index) => place(arrow, tops[index]));
    }

    // The notes a change touched: the note around each changed node and every note
    // added, or everything when the change is outside any note.
    function scopesOf(records, root) {
        const scopes = new Set();
        for (const record of records) {
            const target = record.target instanceof Element ? record.target : record.target.parentElement;
            const note = target === null ? null : target.closest(NOTE_SELECTOR);
            if (note === null || !root.contains(note)) return [root];
            scopes.add(note);
            for (const added of record.addedNodes) {
                if (added instanceof Element) scopes.add(added);
            }
        }
        return [...scopes];
    }

    // Aligns the arrows in `root` now and whenever it changes: its size (text loaded,
    // a note folded, the note size or the window changed, a font arrived) or what it
    // holds (a note added or rendered again, typing).
    function watch(root) {
        new ResizeObserver(() => align([root])).observe(root);
        new MutationObserver((records) => align(scopesOf(records, root)))
            .observe(root, { childList: true, subtree: true, characterData: true });
        void document.fonts.ready.then(() => align([root]));
        align([root]);
    }

    return { watch };
}

// Keeps the fold arrows in `root` on their notes' first lines.
export function watchFoldArrows(root) {
    if (!(root instanceof HTMLElement)) {
        throw new Error('watchFoldArrows requires an element');
    }
    createFoldArrowAligner().watch(root);
}
