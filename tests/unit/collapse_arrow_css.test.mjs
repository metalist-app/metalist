import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const MAIN_CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);

test('collapse arrow uses a larger glyph and centered hit area', async () => {
    const cssSource = await readFile(MAIN_CSS_URL, 'utf8');

    assert.match(
        cssSource,
        /\.note-collapse-toggle\s*\{[^}]*top:\s*3px;[^}]*left:\s*-29px;[^}]*width:\s*27px;[^}]*height:\s*27px;[^}]*font-size:\s*23px;/s,
    );
});

test('root collapse arrow hangs inside the minimum visible page gutter', async () => {
    const cssSource = await readFile(MAIN_CSS_URL, 'utf8');

    assert.match(
        cssSource,
        /--app-min-visible-gutter:\s*calc\(var\(--side-rail-edge\) \+ var\(--floating-button-size\) \+ 8px\);/,
    );
    assert.match(
        cssSource,
        /padding-inline:\s*clamp\(\s*calc\(var\(--app-min-visible-gutter\) - var\(--app-page-padding\)\)/s,
    );
    assert.match(cssSource, /\.note-collapse-toggle\s*\{[^}]*position:\s*absolute;[^}]*left:\s*-29px;/s);
});
