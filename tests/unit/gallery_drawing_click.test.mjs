import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// resolveDiagramTarget alone: the module it lives in needs the whole app.
const source = readFileSync(new URL('../../app/static/js/modules/excalidraw/excalidraw-actions.js', import.meta.url), 'utf8');
const start = source.indexOf('export function resolveDiagramTarget');
const end = source.indexOf('\n}\n', start) + '\n}\n'.length;

class FakeElement {
    constructor(classes, parent, dataset) {
        this.classList = { contains: (name) => classes.includes(name) };
        this.parent = parent;
        this.dataset = dataset;
        this.classes = classes;
    }

    // The few selectors resolveDiagramTarget and the gallery ask for.
    matches(selector) {
        const rules = {
            '.note-file-excalidraw-embed[data-file-ref-id]': () => this.classes.includes('note-file-excalidraw-embed') && 'fileRefId' in this.dataset,
            '.note-reference-block[data-ref-host-note-id]': () => this.classes.includes('note-reference-block') && 'refHostNoteId' in this.dataset,
            '.meta-gallery-tile': () => this.classes.includes('meta-gallery-tile'),
        };
        assert.ok(selector in rules, `unexpected selector ${selector}`);
        return rules[selector]();
    }

    closest(selector) {
        for (let element = this; element !== null; element = element.parent) {
            if (element.matches(selector)) return element;
        }
        return null;
    }
}

const resolveDiagramTarget = new Function('Element', 'HTMLElement', `${source.slice(start, end).replace('export ', '')}\nreturn resolveDiagramTarget;`)(FakeElement, FakeElement);

function drawingIn(container) {
    const embed = new FakeElement(['note-file-excalidraw-embed'], container, { fileRefId: 'drawing' });
    return new FakeElement(['note-file-excalidraw-preview'], embed, {});
}

test('a drawing in a gallery tile belongs to the tile: its click shows it full screen', () => {
    const tile = new FakeElement(['note-file-reference-link', 'meta-gallery-tile'], new FakeElement(['note-content'], null, {}), {});
    assert.equal(resolveDiagramTarget(drawingIn(tile)), null);
});

test('a drawing embedded in a note is that note\'s diagram, to edit', () => {
    const block = new FakeElement(['note-reference-block'], null, { refHostNoteId: 'host' });
    assert.deepEqual(resolveDiagramTarget(drawingIn(block)), { fileId: 'drawing', hostNoteId: 'host' });
});
