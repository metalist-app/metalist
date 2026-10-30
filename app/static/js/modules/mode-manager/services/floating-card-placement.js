// Where a floating card goes (the paste card, the `[[` list, a preview while editing): just
// below its anchor, or above it when it would run past the window's bottom; kept inside
// the window either way. No page needed, so it is tested on its own.

const CARD_GAP_PX = 6;
// The room kept between a card and the window's edges.
export const VIEWPORT_MARGIN_PX = 8;

export function placePasteFormatOffer({ anchor, width, height, viewportWidth, viewportHeight }) {
    let left = Math.min(anchor.left, viewportWidth - width - VIEWPORT_MARGIN_PX);
    left = Math.max(VIEWPORT_MARGIN_PX, left);
    let top = anchor.bottom + CARD_GAP_PX;
    if (top + height > viewportHeight - VIEWPORT_MARGIN_PX) {
        top = Math.max(VIEWPORT_MARGIN_PX, anchor.top - height - CARD_GAP_PX);
    }
    return { left: Math.round(left), top: Math.round(top) };
}
