import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const MAIN_CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);

// A Markdown task's box takes the place of its bullet, never of its number:
// `1. [ ] Book flights` keeps "1." (bug 2026-10-31: numbered tasks lost their numbers).
test('only a bulleted task hides its marker', async () => {
    const css = (await readFile(MAIN_CSS_URL, 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');
    const hidingRules = [...css.matchAll(/([^{}]+)\{[^}]*list-style:\s*none;[^}]*\}/g)]
        .map((match) => match[1].trim())
        .filter((selector) => selector.includes('meta-markdown-task'));
    assert.deepEqual(hidingRules, ['.meta-markdown ul > li.meta-markdown-task']);
});

// Two lists side by side are two lists in standard Markdown; a gap shows they are (2026-10-31).
test('a list right after another list stands apart from it', async () => {
    const css = (await readFile(MAIN_CSS_URL, 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');
    assert.match(css, /\.meta-markdown :is\(ul, ol\) \+ :is\(ul, ol\) \{\s*margin-top: 1em;\s*\}/);
});
