import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// A URL's .pathname is not a file path on Windows: the pathname of a URL made from the
// module's own URL is "/D:/a/..." there, which path.join turns into "D:\D:\a\..." (CI,
// 2026-10-25: two unit tests found none of their files). fileURLToPath gives the path on
// every system.

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const PATHNAME_OF_MODULE_URL = /import\.meta\.url\s*\)\s*\.pathname/;

function scripts(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return ['node_modules', 'vendor'].includes(entry.name) ? [] : scripts(path);
    return /\.m?js$/.test(entry.name) ? [path] : [];
  });
}

export function usesPathnameAsFilePath(source) {
  return PATHNAME_OF_MODULE_URL.test(source);
}

test('no script takes a file path from a module URL\'s pathname', () => {
  const offenders = ['tests', 'scripts'].flatMap((folder) => scripts(join(ROOT, folder)))
    .filter((path) => usesPathnameAsFilePath(readFileSync(path, 'utf8')))
    .map((path) => relative(ROOT, path));
  assert.deepEqual(offenders, []);
});

test('the check finds the pattern', () => {
  // Built from parts, so this file does not show the pattern it looks for.
  const moduleUrl = ['import', 'meta', 'url'].join('.');
  assert.equal(usesPathnameAsFilePath(`const ROOT = new URL('../../', ${moduleUrl}).pathname;`), true);
  assert.equal(usesPathnameAsFilePath(`const ROOT = fileURLToPath(new URL('../../', ${moduleUrl}));`), false);
});
