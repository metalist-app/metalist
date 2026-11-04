import assert from 'node:assert/strict';
import test from 'node:test';

// The module reads MetaList's mode state, which keeps its client id in browser storage.
function memoryStorage() {
    const entries = new Map();
    return {
        getItem: (key) => (entries.has(key) ? entries.get(key) : null),
        setItem: (key, value) => entries.set(key, String(value)),
        removeItem: (key) => entries.delete(key),
        clear: () => entries.clear(),
    };
}
globalThis.sessionStorage = memoryStorage();
globalThis.localStorage = memoryStorage();
const { contentMaxHeight, placePasteFormatOffer } = await import('../../app/static/js/modules/mode-manager/services/floating-card-placement.js');

// The card for a guessed paste format sits just below where the paste ended,
// or above it near the window's bottom, always inside the window.
const viewport = { viewportWidth: 1000, viewportHeight: 800 };

test('the card opens just below the end of the paste', () => {
    const anchor = { left: 120, top: 300, bottom: 320 };
    assert.deepEqual(placePasteFormatOffer({ anchor, width: 260, height: 40, ...viewport }), { left: 120, top: 326, maxHeight: 466 });
});

test('near the bottom of the window the card opens above the paste instead', () => {
    const anchor = { left: 120, top: 760, bottom: 780 };
    assert.deepEqual(placePasteFormatOffer({ anchor, width: 260, height: 40, ...viewport }), { left: 120, top: 714, maxHeight: 746 });
});

test('a card taller than the room on either side is cut to the larger room, never over the paste', () => {
    // Firefox drew the CSV card with its preview 163 px tall in a 260 px window, its paste's
    // last line at 135 to 159: it was pushed up to the top and covered that line (CI, 2026-11-04).
    const anchor = { left: 120, top: 135, bottom: 159 };
    const placed = placePasteFormatOffer({ anchor, width: 260, height: 163, viewportWidth: 1000, viewportHeight: 260 });
    assert.deepEqual(placed, { left: 120, top: 8, maxHeight: 121 });
    assert.ok(placed.top + placed.maxHeight <= anchor.top, 'the card ends above the paste');
});

test('the card is given the room on its side', () => {
    const below = placePasteFormatOffer({ anchor: { left: 120, top: 300, bottom: 320 }, width: 260, height: 40, ...viewport });
    assert.equal(below.maxHeight, 800 - 8 - 326);
    const above = placePasteFormatOffer({ anchor: { left: 120, top: 760, bottom: 780 }, width: 260, height: 40, ...viewport });
    assert.equal(above.maxHeight, 760 - 6 - 8);
});

test('the card stays inside the window at its edges', () => {
    const atRightEdge = { left: 950, top: 300, bottom: 320 };
    assert.equal(placePasteFormatOffer({ anchor: atRightEdge, width: 260, height: 40, ...viewport }).left, 1000 - 260 - 8);
    const tooTallAbove = { left: 10, top: 20, bottom: 790 };
    assert.equal(placePasteFormatOffer({ anchor: tooTallAbove, width: 260, height: 40, ...viewport }).top, 8);
});

test("a card's max-height leaves room for its padding and border", () => {
    const style = { paddingTop: '6px', paddingBottom: '6px', borderTopWidth: '1px', borderBottomWidth: '1px' };
    assert.equal(contentMaxHeight(121, style), 107);
    assert.equal(contentMaxHeight(10, style), 0);
});
