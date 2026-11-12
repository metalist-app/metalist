import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

// The red overlay names a fatal error above everything MetaList draws (the maintainer,
// 2026-11-12: an error in the import's Files screen looked like "completely unresponsive";
// the overlay showed, but under the dialog, seen only once it closed). Only the skin's mouse
// pointer, a picture that takes no clicks, is drawn above it.
const CSS_ROOT = 'app/static/css';
const MOUSE_POINTER_SELECTOR = 'html[data-skin="illuminated"] .skin-pointer';

function cssFiles(folder) {
    return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
        const path = join(folder, entry.name);
        if (entry.isDirectory()) return cssFiles(path);
        return entry.name.endsWith('.css') ? [path] : [];
    });
}

// Each rule's selector with its z-index, in every stylesheet.
function zIndexRules() {
    const rules = [];
    for (const path of cssFiles(CSS_ROOT)) {
        const source = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        for (const match of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
            const zIndex = /z-index:\s*(\d+)/.exec(match[2]);
            if (zIndex !== null) rules.push({ path, selector: match[1].trim(), zIndex: Number(zIndex[1]) });
        }
    }
    return rules;
}

test('the fatal error overlay is drawn above every dialog, card and cover', () => {
    const overlaySource = readFileSync('app/static/js/modules/error-overlay.js', 'utf8');
    const overlayZIndex = Number(/FATAL_OVERLAY_Z_INDEX = (\d+)/.exec(overlaySource)[1]);
    const rules = zIndexRules();
    assert.ok(rules.some((rule) => rule.selector === '.modal'), 'the dialog layer is among the rules read');
    const above = rules.filter((rule) => rule.selector !== MOUSE_POINTER_SELECTOR && rule.zIndex >= overlayZIndex);
    assert.deepEqual(above, [], `drawn over the fatal error overlay (${overlayZIndex})`);
});
