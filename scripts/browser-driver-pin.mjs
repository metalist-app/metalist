import {readFileSync} from 'node:fs';
import {join} from 'node:path';

// The browser suites drive Chrome and Firefox with the Puppeteer that package.json pins, the one
// GitHub installs (npm ci). Found 2026-11-15: this checkout held 25.13.0 while GitHub ran 23.11.1,
// so the suites passed here and failed there. A run with another one installed stops at once.
const REPOSITORY = join(import.meta.dirname, '..');

function readJson(path) {
  return JSON.parse(readFileSync(join(REPOSITORY, path), 'utf8'));
}

export function assertInstalledDriverIsPinned() {
  const pinned = readJson('package.json').devDependencies.puppeteer;
  const installed = readJson('node_modules/puppeteer/package.json').version;
  if (installed !== pinned) {
    throw new Error(`node_modules holds Puppeteer ${installed}, package.json pins ${pinned}: run npm ci`);
  }
}
