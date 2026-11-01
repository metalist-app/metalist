import { ApplicationState } from '../../app/static/js/modules/application-state.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
    isViewModeNoteDisclosureToggle,
    isViewModeNoteLink,
    resolveNonContentNoteSelectionTarget,
    viewModeCalloutTitleAt,
} from '../../app/static/js/modules/mode-manager/services/note-click-target-service.js';

const source = readFileSync(new URL(
    '../../app/static/js/modules/mode-manager/events/mouse-events.js', import.meta.url,
), 'utf8').replace(/^import[\s\S]*?from '[^']+';\s*/gm, '').replace(/^export /gm, '');

function harness(isEditing) {
    class Element {
        localName = 'span';
        closest() { return null; }
        matches() { return false; }
        hasAttribute() { return false; }
    }
    const note = new Element();
    note.dataset = { noteId: 'note-1' };
    note.classList = { contains: (name) => name === 'editing' && isEditing };
    const content = new Element();
    content.closest = (selector) => selector === '.note' ? note : null;
    const anchor = new Element();
    anchor.closest = (selector) => ({ '.note': note, '.note-content': content })[selector] ?? null;
    const label = new Element();
    label.closest = (selector) => ({ 'a[href]': anchor, '.note': note, '.note-content': content })[selector] ?? null;
    const events = [];
    const dependencies = {
        Element, isViewModeNoteDisclosureToggle, isViewModeNoteLink,
        resolveNonContentNoteSelectionTarget, viewModeCalloutTitleAt,
        toggleMarkdownCallout: () => {}, toggleMarkdownFold: () => {},
        ModeContext: { isEditing, currentNoteId: isEditing ? 'note-1' : null, isConnected: true, isLoading: false },
        isContextMenuInteractionTarget: () => false,
        Logger: { logNoop() {}, logDebug() {} },
        performance: { now: () => 100 },
        CommandGate: { run: (name) => events.push(name) },
        SHELL_SELECTOR: '.meta-shell', SHELL_CLOSE_SELECTOR: '.meta-shell-close',
        resolveDiagramTarget: () => null,
    };
    const handlers = new Function('ApplicationState', ...Object.keys(dependencies), `${source}\nreturn {
        handleImmediateMouseDown, handleMoveDragMouseDown, handleClick,
        dragContext: () => moduleState.moveDragContext,
    };`).bind(null, ApplicationState)(...Object.values(dependencies));
    return { handlers, events, label, anchor, event: {
        target: label, clientX: 10, clientY: 10, button: 0, type: 'click',
        composedPath() { return [label, anchor, content, note]; },
        preventDefault() { events.push('prevent-default'); },
        stopPropagation() { events.push('stop-propagation'); },
    } };
}

function disclosureHarness(isEditing) {
    const h = harness(isEditing);
    const note = h.anchor.closest('.note');
    const content = h.anchor.closest('.note-content');
    const details = {
        closest(selector) {
            return ({
                '.note': note,
                '.note-content': content,
                'details.ai-chat-references-disclosure': details,
            })[selector] ?? null;
        },
    };
    const summary = {
        closest(selector) {
            return ({
                '.note': note,
                '.note-content': content,
                'details.ai-chat-references-disclosure': details,
                'summary.ai-chat-references-heading': summary,
            })[selector] ?? null;
        },
    };
    const label = {
        closest(selector) {
            return ({
                '.note': note,
                '.note-content': content,
                'details.ai-chat-references-disclosure': details,
                'summary.ai-chat-references-heading': summary,
            })[selector] ?? null;
        },
    };
    h.event.target = label;
    h.event.composedPath = () => [label, summary, details, content, note];
    return h;
}

test('clicking nested title/domain markup preserves browser navigation and view mode', () => {
    const h = harness(false);
    h.handlers.handleImmediateMouseDown(h.event);
    h.handlers.handleMoveDragMouseDown(h.event);
    h.handlers.handleClick(h.event);
    assert.deepEqual(h.events, []);
    assert.equal(h.handlers.dragContext(), null);
});

test('link guard distinguishes view links from editor links and non-link content', () => {
    assert.equal(isViewModeNoteLink(harness(false).label), true);
    assert.equal(isViewModeNoteLink(harness(true).label), false);
    assert.equal(isViewModeNoteLink({ closest: () => null }), false);
    assert.equal(isViewModeNoteLink(null), false);
});

test('References disclosure toggles in view mode without selecting or dragging its note', () => {
    const h = disclosureHarness(false);
    h.handlers.handleImmediateMouseDown(h.event);
    h.handlers.handleMoveDragMouseDown(h.event);
    h.handlers.handleClick(h.event);

    assert.deepEqual(h.events, []);
    assert.equal(h.handlers.dragContext(), null);
});

test('References disclosure guard applies only outside edit mode', () => {
    assert.equal(isViewModeNoteDisclosureToggle(disclosureHarness(false).event.target), true);
    assert.equal(isViewModeNoteDisclosureToggle(disclosureHarness(true).event.target), false);
});

// A folding Markdown callout's title (docs/ui/content-formatting.md, Callouts).
const CALLOUT_FOLD = 'meta-markdown-callout-fold';
function calloutHarness({ noteClasses, isOpen, inEmbed, foldClass }) {
    const h = harness(noteClasses.includes('editing'));
    const note = { dataset: { noteId: 'note-1' }, classList: { contains: (name) => noteClasses.includes(name) } };
    const content = { closest: (selector) => selector === '.note' ? note : null };
    const fold = {
        open: isOpen, dataset: { calloutIndex: '2', foldIndex: '3' },
        classList: { contains: (name) => name === foldClass },
        matches: (selector) => selector.split(', ').includes(`details.${foldClass}`),
    };
    const embed = inEmbed ? {} : null;
    const summary = {
        parentElement: fold,
        closest: (selector) => ({ summary, '.note': note, '.note-content': content, '.note-embed-node': embed })[selector] ?? null,
    };
    const title = { closest: (selector) => selector === 'summary' ? summary : summary.closest(selector) };
    h.event.target = title;
    h.event.composedPath = () => [title, summary, fold, content, note];
    return h;
}

test('a callout title folds and saves without selecting, editing or dragging its note', () => {
    const h = calloutHarness({ noteClasses: [], isOpen: false, inEmbed: false, foldClass: CALLOUT_FOLD });
    h.handlers.handleImmediateMouseDown(h.event);
    h.handlers.handleMoveDragMouseDown(h.event);
    h.handlers.handleClick(h.event);
    assert.deepEqual(h.events, ['mouse.toggle_markdown_callout']);
    assert.equal(h.handlers.dragContext(), null);
});

test('a callout title in an embed folds there only; in a locked note nothing changes', () => {
    const embedded = calloutHarness({ noteClasses: [], isOpen: true, inEmbed: true, foldClass: CALLOUT_FOLD });
    embedded.handlers.handleClick(embedded.event);
    assert.deepEqual(embedded.events, []);
    const locked = calloutHarness({ noteClasses: ['locked'], isOpen: true, inEmbed: false, foldClass: CALLOUT_FOLD });
    locked.handlers.handleClick(locked.event);
    assert.deepEqual(locked.events, ['prevent-default']);
});

test('a callout title is a plain click while editing or collapsed', () => {
    for (const noteClasses of [['editing'], ['collapsed']]) {
        const h = calloutHarness({ noteClasses, isOpen: false, inEmbed: false, foldClass: CALLOUT_FOLD });
        assert.equal(viewModeCalloutTitleAt(h.event.target), null, noteClasses[0]);
        assert.equal(isViewModeNoteDisclosureToggle(h.event.target), false, noteClasses[0]);
    }
});

test('a <details> fold written in HTML folds and saves like a callout', () => {
    const h = calloutHarness({ noteClasses: [], isOpen: false, inEmbed: false, foldClass: 'meta-markdown-html-fold' });
    h.handlers.handleImmediateMouseDown(h.event);
    h.handlers.handleMoveDragMouseDown(h.event);
    h.handlers.handleClick(h.event);
    assert.deepEqual(h.events, ['mouse.toggle_markdown_fold']);
});
