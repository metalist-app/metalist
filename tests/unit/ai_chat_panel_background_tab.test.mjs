import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { calculateAiChatPanelWidth } from '../../app/static/js/modules/ai-chat/ai-chat-panel-service.js';

// A tab loaded while it is in the background has no width yet: describing the chat's width
// handle then failed the start ("calculateAiChatPanelWidth requires positive viewportWidth",
// 2026-11-14, a tab reloaded behind another; several tabs on one sign-in make that common). It
// waits for the window's first width instead (the resize that brings it).
// Read with \n line ends: a Windows checkout writes \r\n.
const source = readFileSync(new URL('../../app/static/js/modules/ai-chat/ai-chat-panel-controller.js', import.meta.url), 'utf8')
    .replaceAll('\r\n', '\n');
const start = source.indexOf('    _syncResizerAria() {');
const end = source.indexOf('\n    }\n', start) + '\n    }\n'.length;
assert.ok(start >= 0 && end > start, '_syncResizerAria is in the controller');
const body = source.slice(start + '    _syncResizerAria() {'.length, end - '\n    }\n'.length);
const DEFAULT_PANEL_WIDTH_DIVISOR = 3;

function controllerIn(windowWidth) {
    const described = [];
    const controller = {
        _elements: { panel: { getBoundingClientRect: () => ({ width: 0 }) } },
        _setResizerAria: (width) => described.push(width),
    };
    const sync = new Function(
        'window', 'calculateAiChatPanelWidth', 'DEFAULT_PANEL_WIDTH_DIVISOR', body,
    );
    return { run: () => sync.call(controller, { innerWidth: windowWidth }, calculateAiChatPanelWidth, DEFAULT_PANEL_WIDTH_DIVISOR), described };
}

test('a tab with no width yet starts without describing the chat width', () => {
    const backgroundTab = controllerIn(0);
    assert.doesNotThrow(backgroundTab.run);
    assert.deepEqual(backgroundTab.described, []);
});

test('a tab with a width describes it', () => {
    const shownTab = controllerIn(1200);
    shownTab.run();
    assert.equal(shownTab.described.length, 1);
    assert.ok(shownTab.described[0] > 0);
});
