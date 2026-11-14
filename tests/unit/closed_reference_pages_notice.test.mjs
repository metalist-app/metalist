import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// When the browser takes its tabs again after the server closed reference pages whose notes were
// deleted (ui-actions.js, hasNewlyClosedReferencePages; docs/ready-to-build/reference-cards.md §2
// rule 10). Run as written, with its state given.
const source = readFileSync(new URL('../../app/static/js/modules/mode-manager/actions/ui-actions.js', import.meta.url), 'utf8');
const start = source.indexOf('function hasNewlyClosedReferencePages(snapshot)');
const end = source.indexOf('\n}\n', start) + 2;
assert.ok(start >= 0 && end > start, 'hasNewlyClosedReferencePages is in ui-actions.js');
const functionSource = source.slice(start, end);

function harness() {
    const NOT_YET_SEEN = -1;
    const moduleState = { pagesClosedAtVersion: NOT_YET_SEEN };
    const decide = new Function('moduleState', 'NOT_YET_SEEN', `${functionSource}\nreturn hasNewlyClosedReferencePages;`)(
        moduleState, NOT_YET_SEEN,
    );
    return (closedAt) => {
        const snapshot = { notes: {} };
        if (closedAt !== undefined) snapshot.pagesClosedAtVersion = closedAt;
        return decide(snapshot);
    };
}

test('the tabs are taken again only when pages closed since the last view', () => {
    const viewSays = harness();
    assert.equal(viewSays(4), false, 'the first view: the tabs just loaded are the server\'s');
    assert.equal(viewSays(4), false, 'nothing closed since');
    assert.equal(viewSays(9), true, 'pages closed with their notes');
    assert.equal(viewSays(2), false, 'a server started again counts afresh');
    assert.equal(viewSays(5), true);
});

test('a view from a server that does not say so closes nothing and does not fail', () => {
    // A page loaded with newer code than the server running (an upgrade under way, or MetaList
    // not restarted yet) met "notes.view snapshot requires pagesClosedAtVersion" (2026-11-14).
    const viewSays = harness();
    assert.equal(viewSays(undefined), false);
    assert.equal(viewSays(3), false, 'its first count is where it starts');
    assert.equal(viewSays(undefined), false);
});
