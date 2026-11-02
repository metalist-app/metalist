import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);


test('tag bar focus has a persistent cue and an optional one-shot halo', async () => {
    const cssSource = await readFile(CSS_URL, 'utf8');

    assert.match(
        cssSource,
        /\.note-tag-bar:focus-within\s*\{[\s\S]*border-color:[\s\S]*box-shadow:/,
    );
    assert.match(
        cssSource,
        /body\.pref-animated-transitions \.note-tag-bar:focus-within::after\s*\{[\s\S]*animation: note-tag-bar-focus-halo 520ms/,
    );
    assert.match(cssSource, /@keyframes note-tag-bar-focus-halo/);
    assert.match(
        cssSource,
        /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.note-tag-bar:focus-within::after[\s\S]*animation: none;/,
    );
});


test('dark theme tag bar and search shell share a grey control surface that stands out', async () => {
    const cssSource = await readFile(CSS_URL, 'utf8');
    const darkTokens = cssSource.match(/html\[data-theme="dark"\]\s*\{([^}]*)\}/);
    assert.ok(darkTokens, 'expected the dark theme token block');
    const hexToken = (name) => {
        const match = darkTokens[1].match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'));
        assert.ok(match, `expected --${name} in the dark theme tokens`);
        return parseInt(match[1].slice(1, 3), 16);
    };
    const control = hexToken('app-control-surface');
    assert.ok(control - hexToken('app-surface-0') >= 16, 'control surface must stand out from the edited note');
    assert.ok(control - hexToken('app-surface-1') >= 16, 'control surface must stand out from notes');
    assert.ok(control - hexToken('bg-color') >= 24, 'control surface must stand out from the page');

    assert.match(cssSource, /html\[data-theme="dark"\] \.note-tag-bar\s*\{[^}]*background:\s*var\(--app-control-surface\)/);
    assert.match(cssSource, /html\[data-theme="dark"\] \.note-tag-bar-empty-icon-front\s*\{[^}]*fill:\s*var\(--app-control-surface\)/);
    assert.match(cssSource, /html\[data-theme="dark"\] \.controls\s*\{[^}]*background:\s*var\(--app-control-surface\)/);
});
