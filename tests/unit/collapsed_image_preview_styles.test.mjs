import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';


const css = readFileSync(new URL('../../app/static/css/main.css', import.meta.url), 'utf8');


function declarationsFor(selector) {
    const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`));
    assert.ok(match, `Missing CSS rule for ${selector}`);
    return match[1];
}


test('collapsed image previews contain the complete image instead of cropping it', () => {
    const declarations = declarationsFor('.note.collapsed:not(.editing) .note-content img:not(:where(.note-reference-note.note-embed-block, .note-reference-note.note-embed-block *, .meta-gallery *))');

    assert.match(declarations, /height:\s*4\.5em\s*!important/);
    assert.match(declarations, /width:\s*7\.5em\s*!important/);
    assert.match(declarations, /object-fit:\s*contain\s*!important/);
});


test('gallery pictures fill their square, cropped about the middle, folded or not', () => {
    const declarations = declarationsFor('.note-file-reference-link.meta-gallery-tile .meta-gallery-picture :is(.note-file-image-preview, .note-file-excalidraw-preview, .meta-gallery-written-image)');

    assert.match(declarations, /width:\s*100%/);
    assert.match(declarations, /height:\s*100%/);
    assert.match(declarations, /object-fit:\s*cover/);
});
