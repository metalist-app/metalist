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
const { insertKindsFor, insertPasswordPlan, insertPlan } = await import('../../app/static/js/modules/mode-manager/services/insert-format-plan.js');

// Insert LaTeX / CSV / Mermaid Diagram (docs/ui/content-formatting.md, "Previews while editing").

test('a kind the whole note already is is not offered', () => {
    assert.deepEqual(insertKindsFor(''), ['latex', 'csv', 'mermaid', 'password']);
    assert.deepEqual(insertKindsFor('@markdown todo'), ['latex', 'csv', 'mermaid', 'password']);
    assert.deepEqual(insertKindsFor('@csv'), ['latex', 'mermaid', 'password']);
    assert.deepEqual(insertKindsFor('@LaTeX'), ['csv', 'mermaid', 'password']);
    assert.deepEqual(insertKindsFor('@mermaid'), ['latex', 'csv', 'password']);
    // A password note is a password already.
    assert.deepEqual(insertKindsFor('@password'), ['latex', 'csv', 'mermaid']);
    // A region of the format is no whole-note tag.
    assert.deepEqual(insertKindsFor('((@csv))'), ['latex', 'csv', 'mermaid', 'password']);
    assert.deepEqual(insertKindsFor('((@password))'), ['latex', 'csv', 'mermaid', 'password']);
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

// Insert Password (docs/ui/content-formatting.md, "A password in a note's text").
const PASSWORD_LENGTH = 16;
// A random source that counts up, so every character of the charset comes out in turn.
function countingRandomValues() {
    let next = 0;
    return (buffer) => {
        for (let index = 0; index < buffer.length; index += 1) {
            buffer[index] = next;
            next += 1;
        }
    };
}

test('a blank note becomes a password note: the password alone, @password added', () => {
    const plan = insertPasswordPlan({ tagBarText: 'bank', contentText: '', isBlank: true, fillRandomValues: countingRandomValues() });
    assert.equal(plan.tagToken, '@password');
    assert.equal(plan.text.length, PASSWORD_LENGTH);
});

test('in a note with text the password is a region in an unused wrapper, its ((@password)) added', () => {
    const plan = insertPasswordPlan({ tagBarText: 'bank', contentText: 'Login for the bank: ', isBlank: false, fillRandomValues: countingRandomValues() });
    assert.equal(plan.tagToken, '{@password}');
    assert.match(plan.text, /^\{[^{}]{16}\}$/);
    // `{` is taken by the text and `[` by the tag bar: the next free wrapper.
    const next = insertPasswordPlan({ tagBarText: '[@red]', contentText: 'a {b}', isBlank: false, fillRandomValues: countingRandomValues() });
    assert.equal(next.tagToken, '(@password)');
    assert.match(next.text, /^\([^()]{16}\)$/);
});

test('a wrapper the tag bar already gives @password is used again, nothing added', () => {
    const plan = insertPasswordPlan({ tagBarText: 'bank ((@password))', contentText: 'PIN ((1234))', isBlank: false, fillRandomValues: countingRandomValues() });
    assert.equal(plan.tagToken, null);
    assert.match(plan.text, /^\(\([^()]{16}\)\)$/);
});

test('a region password never holds its wrapper\'s characters, which would end it early', () => {
    // Many draws over the whole charset: none may hold a ( or ).
    for (let draw = 0; draw < 50; draw += 1) {
        const plan = insertPasswordPlan({ tagBarText: '{@red} [@blue]', contentText: 'x', isBlank: false, fillRandomValues: null });
        assert.equal(plan.tagToken, '(@password)');
        assert.ok(!/[()]/.test(plan.text.slice(1, -1)), plan.text);
    }
});
