import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// The browser suites drive Chrome and Firefox through Puppeteer. GitHub installs the version
// the lockfile pins (npm ci); this checkout ran whatever its node_modules held. Found
// 2026-11-15: GitHub ran 23.11.1 while every local run used 25.13.0, so main's browser suites
// failed in Firefox on GitHub (23's BiDi refused to continue a request it had not intercepted)
// while passing here, for eleven days. The suites must run the version GitHub runs.

function readJson(path) {
    return JSON.parse(readFileSync(path, 'utf8'));
}

// What is installed is checked where it is used, as the suites start (browser-driver-pin.mjs):
// the JavaScript unit jobs install nothing.
test('the lockfile locks the browser driver package.json pins', () => {
    const pinned = readJson('package.json').devDependencies.puppeteer;
    assert.match(pinned, /^\d+\.\d+\.\d+$/, 'package.json pins an exact Puppeteer version');
    const locked = readJson('package-lock.json').packages['node_modules/puppeteer'].version;
    assert.equal(locked, pinned, 'package-lock.json locks the Puppeteer that package.json pins');
});

test('the release checks drive the browsers with the same Puppeteer as the browser suites', () => {
    const suites = readJson('package.json').devDependencies.puppeteer;
    const release = readJson('scripts/browser-validation/package.json').dependencies['puppeteer-core'];
    assert.equal(release, suites, 'scripts/browser-validation pins the Puppeteer of the browser suites');
});

// A package that needs Puppeteer beside it (a peer dependency) must accept the pinned version:
// GitHub's npm ci refuses the lockfile otherwise, and every job fails before it starts. Found
// 2026-11-15: @mermaid-js/mermaid-cli 11.9.0 wanted Puppeteer ^23; npm 11 here installed 25.13.0
// beside it anyway, npm 10 on GitHub (Node 22) did not.
export function acceptsPuppeteer(range, version) {
    const major = Number(version.split('.')[0]);
    return range.split('||').map((part) => part.trim()).some((part) => {
        const caret = /^\^(\d+)(\.\d+){0,2}$/.exec(part);
        if (caret === null) throw new Error(`A Puppeteer peer range this test cannot read: ${range}`);
        return Number(caret[1]) === major;
    });
}

export function puppeteerPeerProblems(lock, pinned) {
    return Object.entries(lock.packages)
        .filter(([, entry]) => entry.peerDependencies !== undefined && 'puppeteer' in entry.peerDependencies)
        .filter(([, entry]) => !acceptsPuppeteer(entry.peerDependencies.puppeteer, pinned))
        .map(([path, entry]) => `${path} needs Puppeteer ${entry.peerDependencies.puppeteer}, package.json pins ${pinned}`);
}

test('every package that needs Puppeteer beside it accepts the pinned version', () => {
    const pinned = readJson('package.json').devDependencies.puppeteer;
    assert.deepEqual(puppeteerPeerProblems(readJson('package-lock.json'), pinned), []);
});
