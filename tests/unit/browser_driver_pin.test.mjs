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

test('the installed browser driver is the one package.json and its lockfile pin', () => {
    const pinned = readJson('package.json').devDependencies.puppeteer;
    assert.match(pinned, /^\d+\.\d+\.\d+$/, 'package.json pins an exact Puppeteer version');
    const locked = readJson('package-lock.json').packages['node_modules/puppeteer'].version;
    assert.equal(locked, pinned, 'package-lock.json locks the Puppeteer that package.json pins');
    const installed = readJson('node_modules/puppeteer/package.json').version;
    assert.equal(installed, pinned, `node_modules holds Puppeteer ${installed}, package.json pins ${pinned}: run npm ci`);
});

test('the release checks drive the browsers with the same Puppeteer as the browser suites', () => {
    const suites = readJson('package.json').devDependencies.puppeteer;
    const release = readJson('scripts/browser-validation/package.json').dependencies['puppeteer-core'];
    assert.equal(release, suites, 'scripts/browser-validation pins the Puppeteer of the browser suites');
});
