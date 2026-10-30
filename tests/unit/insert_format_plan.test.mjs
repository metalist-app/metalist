import assert from 'node:assert/strict';
import test from 'node:test';

// The module reads MetaList's mode state, which keeps its client id in browser storage.
function memoryStorage() {
    const entries = new Map();
    return {
        getItem: (key) => (entries.has(key) ? entries.get(key) : null),
        setItem: (key, value) => entries.set(key, String(value)),
        removeItem: (key) => entries.delete(key),
        clear: () => entries.clear(),
    };
}
globalThis.sessionStorage = memoryStorage();
globalThis.localStorage = memoryStorage();
const { insertKindsFor, insertPlan } = await import('../../app/static/js/modules/mode-manager/services/insert-format-plan.js');

// Insert LaTeX / CSV / Mermaid Diagram (docs/ui/content-formatting.md, "Previews while editing").

test('a kind the whole note already is is not offered', () => {
    assert.deepEqual(insertKindsFor(''), ['latex', 'csv', 'mermaid']);
    assert.deepEqual(insertKindsFor('@markdown todo'), ['latex', 'csv', 'mermaid']);
    assert.deepEqual(insertKindsFor('@csv'), ['latex', 'mermaid']);
    assert.deepEqual(insertKindsFor('@LaTeX'), ['csv', 'mermaid']);
    assert.deepEqual(insertKindsFor('@mermaid'), ['latex', 'csv']);
    // A region of the format is no whole-note tag.
    assert.deepEqual(insertKindsFor('((@csv))'), ['latex', 'csv', 'mermaid']);
});

test('in a Markdown note a formula is $$…$$ and a diagram a fence, with no tag added', () => {
    assert.deepEqual(insertPlan({ kind: 'latex', tagBarText: '@markdown', contentText: 'x', hasSelection: false }),
        { open: '$$', close: '$$', start: '', tagToken: null, isBlock: false });
    assert.deepEqual(insertPlan({ kind: 'mermaid', tagBarText: '@markdown', contentText: 'x', hasSelection: false }),
        { open: '```mermaid\n', close: '\n```', start: 'flowchart LR\n', tagToken: null, isBlock: true });
    // Selected text is the diagram: no starting line.
    assert.equal(insertPlan({ kind: 'mermaid', tagBarText: '@markdown', contentText: 'x', hasSelection: true }).start, '');
});

test('elsewhere a region uses a wrapper nothing in the note uses, its tag added', () => {
    assert.deepEqual(insertPlan({ kind: 'latex', tagBarText: '', contentText: 'Plain note', hasSelection: false }),
        { open: '{', close: '}', start: '', tagToken: '{@LaTeX}', isBlock: false });
    // `{` and `[` are taken: the next free wrapper.
    assert.deepEqual(insertPlan({ kind: 'csv', tagBarText: '{@red}', contentText: 'a [b] {c}', hasSelection: false }),
        { open: '(', close: ')', start: '', tagToken: '(@csv)', isBlock: false });
    // CSV is a region in a Markdown note too.
    assert.equal(insertPlan({ kind: 'csv', tagBarText: '@markdown', contentText: 'x', hasSelection: false }).tagToken, '{@csv}');
    assert.equal(insertPlan({ kind: 'mermaid', tagBarText: '', contentText: 'x', hasSelection: false }).start, 'flowchart LR\n');
});

test('a wrapper the tag bar already gives the format is used again', () => {
    assert.deepEqual(insertPlan({ kind: 'latex', tagBarText: 'maths (((@LaTeX)))', contentText: '(((x)))', hasSelection: true }),
        { open: '(((', close: ')))', start: '', tagToken: null, isBlock: false });
});
