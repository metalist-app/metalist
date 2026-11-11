import assert from 'node:assert/strict';
import test from 'node:test';

import {
    appStateForView,
    fittedView,
    savedViewOf,
    viewOfAppState,
    viewsDiffer,
    withSavedView,
} from '../../app/static/js/modules/excalidraw/excalidraw-scene.js';

// A diagram editor 1000 by 600 pixels.
const WIDTH = 1000;
const HEIGHT = 600;

function rectangle(x, y, width, height) {
    return { type: 'rectangle', x, y, width, height, isDeleted: false };
}

test('a view is the scene point in the middle of the editor and the zoom', () => {
    // Scrolled so scene point (0, 0) is at the top-left, at 200%: the middle is (250, 150).
    const view = viewOfAppState({ scrollX: 0, scrollY: 0, zoom: { value: 2 }, width: WIDTH, height: HEIGHT });
    assert.deepEqual(view, { centerX: 250, centerY: 150, zoom: 2 });
});

test('a view puts its middle in the middle of any editor size (case 5)', () => {
    const view = { centerX: 250, centerY: 150, zoom: 2 };
    assert.deepEqual(appStateForView(view, WIDTH, HEIGHT), { scrollX: 0, scrollY: 0, zoom: { value: 2 } });
    const narrow = appStateForView(view, 500, 300);
    assert.deepEqual(viewOfAppState({ ...narrow, width: 500, height: 300 }), view);
});

test('a view saved in the drawing file is read back, beside the scene (case 2)', () => {
    const text = JSON.stringify({ type: 'excalidraw', elements: [], appState: {}, files: {} });
    const view = { centerX: 12.5, centerY: -40, zoom: 0.75 };
    assert.deepEqual(savedViewOf(JSON.parse(withSavedView(text, view))), view);
    assert.equal(savedViewOf(JSON.parse(text)), null);
});

test('a broken view in a file from elsewhere counts as none', () => {
    const scene = { type: 'excalidraw', elements: [], metalistView: { centerX: 'left', centerY: 0, zoom: 1 } };
    assert.equal(savedViewOf(scene), null);
    assert.equal(savedViewOf({ ...scene, metalistView: { centerX: 0, centerY: 0, zoom: 0 } }), null);
});

test('a first open fits the whole drawing, never above 100% (case 1)', () => {
    // 3000 wide: it fits by width, with a margin.
    const wide = fittedView([rectangle(0, 0, 3000, 400)], WIDTH, HEIGHT);
    assert.equal(wide.centerX, 1500);
    assert.equal(wide.centerY, 200);
    assert.ok(wide.zoom < WIDTH / 3000 && wide.zoom > 0.25, `zoom ${wide.zoom}`);
    // A small drawing stays at 100%.
    assert.deepEqual(fittedView([rectangle(10, 10, 100, 50)], WIDTH, HEIGHT), { centerX: 60, centerY: 35, zoom: 1 });
    // Lines and arrows count by their points; deleted elements do not count.
    const arrow = { type: 'arrow', x: 100, y: 100, width: 200, height: 0, points: [[0, 0], [-200, 0]], isDeleted: false };
    assert.deepEqual(fittedView([arrow, { ...rectangle(5000, 5000, 10, 10), isDeleted: true }], WIDTH, HEIGHT), { centerX: 0, centerY: 100, zoom: 1 });
    assert.equal(fittedView([], WIDTH, HEIGHT), null);
});

test('a view moved less than a scene unit or 1% of zoom is the same view', () => {
    const view = { centerX: 100, centerY: 100, zoom: 1 };
    assert.equal(viewsDiffer(view, { centerX: 100.3, centerY: 99.8, zoom: 1.004 }), false);
    assert.equal(viewsDiffer(view, { centerX: 140, centerY: 100, zoom: 1 }), true);
    assert.equal(viewsDiffer(view, { centerX: 100, centerY: 100, zoom: 1.5 }), true);
});
