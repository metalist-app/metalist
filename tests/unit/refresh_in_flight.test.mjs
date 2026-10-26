import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// A refresh asked for while a view request is in flight waits its turn, then runs
// (docs/ui/state-handling.md, "Refreshes in flight"). Dropping it crashed switching notes and
// left deleted notes on screen (2026-10-26). Only the infinite-scroll poll may skip a round,
// and only by asking isViewRequestInFlight itself; scripts/browser-refresh-in-flight-regressions.mjs
// checks the behaviour.

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const MODULES = join(ROOT, 'app/static/js/modules');
const UI_ACTIONS = 'app/static/js/modules/mode-manager/actions/ui-actions.js';
const POLL = 'app/static/js/modules/mode-manager/services/infinite-scroll-service.js';

function sourceFiles(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return entry.name === 'vendor' ? [] : sourceFiles(path);
        return entry.name.endsWith('.js') ? [path] : [];
    });
}

const SOURCES = sourceFiles(MODULES).map((path) => ({
    path: relative(ROOT, path).split(sep).join('/'),
    source: readFileSync(path, 'utf8'),
}));

test('only the infinite-scroll poll asks whether a view request is in flight', () => {
    const askers = SOURCES.filter(({ path, source }) => path !== UI_ACTIONS && source.includes('isViewRequestInFlight'))
        .map(({ path }) => path);
    assert.deepEqual(askers, [POLL]);
});

test('no caller asks for the old requireExecution option', () => {
    const callers = SOURCES.filter(({ path, source }) => path !== UI_ACTIONS && /requireExecution/.test(source))
        .map(({ path }) => path);
    assert.deepEqual(callers, []);
});

test('a refresh in flight is waited for, never answered with nothing', () => {
    const uiActions = SOURCES.find(({ path }) => path === UI_ACTIONS).source;
    const start = uiActions.indexOf('export async function actionRefreshAndMaybeSelect');
    const inFlight = uiActions.indexOf('if (moduleState.viewRequestInFlight) {', start);
    assert(start >= 0 && inFlight > start, 'the refresh checks for a request in flight');
    const branch = uiActions.slice(inFlight, uiActions.indexOf('}', inFlight));
    assert.match(branch, /await waitForViewRequestIdle\(\);/);
    assert.doesNotMatch(branch, /return/);
});
