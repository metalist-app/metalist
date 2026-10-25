import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

// The AI opens a menu destination for the user and checks it showed by the catalog's CSS
// selector (app/static/config/agent-menu-actions.json). A selector naming an element the app no
// longer builds makes the AI say "The dialog did not open" while it did (2026-10-25: the AI
// tagging dialogs moved off native <dialog>s). Every selector must name an element some
// script or template still builds; the agent-help browser suite then checks each one opens.

const ROOT = new URL('../../', import.meta.url).pathname;
const CATALOG = JSON.parse(readFileSync(join(ROOT, 'app/static/config/agent-menu-actions.json'), 'utf8'));

function sourceFiles(directory, extension) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return entry.name === 'vendor' ? [] : sourceFiles(path, extension);
        return entry.name.endsWith(extension) ? [path] : [];
    });
}

const SOURCE = [
    ...sourceFiles(join(ROOT, 'app/static/js'), '.js'),
    ...sourceFiles(join(ROOT, 'app/templates'), '.html'),
].map((path) => readFileSync(path, 'utf8')).join('\n');

function quoted(text) {
    const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`['"\`]${escaped}['"\`]`);
}

// Why a selector names nothing the app builds, or '' when it names something.
export function selectorProblem(selector, source) {
    const byId = /^#([\w-]+)$/.exec(selector);
    if (byId !== null) {
        return quoted(byId[1]).test(source) ? '' : `no script or template builds an element with id ${byId[1]}`;
    }
    const byAttribute = /^([a-z]+)\[([\w-]+)="([^"]+)"\]$/.exec(selector);
    if (byAttribute !== null) {
        const [, tag, , value] = byAttribute;
        const buildsTag = quoted(tag).test(source) || source.includes(`<${tag}`);
        if (!buildsTag) return `no script or template builds a <${tag}>`;
        return source.includes(value) ? '' : `no script or template uses the value "${value}"`;
    }
    return `the check does not read selectors like ${selector}; use #id`;
}

function selectorsOf(entry) {
    const selectors = [entry.selector];
    if ('alternate_dialog' in entry) selectors.push(entry.alternate_dialog.selector);
    return selectors;
}

test('every agent menu destination names an element the app still builds', () => {
    const problems = CATALOG.flatMap((entry) => selectorsOf(entry)
        .map((selector) => [selector, selectorProblem(selector, SOURCE)])
        .filter(([, problem]) => problem !== '')
        .map(([selector, problem]) => `${entry.id} (${selector}): ${problem}`));
    assert.deepEqual(problems, []);
});

test('the check finds a selector for an element nothing builds', () => {
    const source = "super('memoryUsageModal', 'memory-usage-modal');";
    assert.equal(selectorProblem('#memory-usage-modal', source), '');
    assert.match(selectorProblem('#gone-modal', source), /id gone-modal/);
    assert.match(selectorProblem('dialog[aria-label="AI-proposed tags"]', source), /<dialog>/);
    assert.match(selectorProblem('.some-class', source), /use #id/);
});
