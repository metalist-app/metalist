// Where a floating card goes (the paste card, the `[[` list, a preview while editing): just
// below its anchor, or above it when it would run past the window's bottom; kept inside
// the window either way, and never over its anchor: a card too tall for either side goes on
// the side with more room, and maxHeight is that room, for the card to be cut to. No page
// needed, so it is tested on its own.

const CARD_GAP_PX = 6;
// The room kept between a card and the window's edges.
export const VIEWPORT_MARGIN_PX = 8;

// A card's max-height for the room it has: CSS max-height leaves out padding and border.
// style: the card's computed style.
export function contentMaxHeight(room, style) {
    const chrome = ['paddingTop', 'paddingBottom', 'borderTopWidth', 'borderBottomWidth']
        .reduce((total, side) => total + Number.parseFloat(style[side]), 0);
    return Math.max(0, room - chrome);
}

export function placePasteFormatOffer({ anchor, width, height, viewportWidth, viewportHeight }) {
    let left = Math.min(anchor.left, viewportWidth - width - VIEWPORT_MARGIN_PX);
    left = Math.max(VIEWPORT_MARGIN_PX, left);
    const below = anchor.bottom + CARD_GAP_PX;
    const roomBelow = Math.max(0, Math.floor(viewportHeight - VIEWPORT_MARGIN_PX - below));
    const roomAbove = Math.max(0, Math.floor(anchor.top - CARD_GAP_PX - VIEWPORT_MARGIN_PX));
    let isBelow = roomBelow >= roomAbove;
    if (height <= roomBelow) isBelow = true;
    else if (height <= roomAbove) isBelow = false;
    if (isBelow) return { left: Math.round(left), top: Math.round(below), maxHeight: roomBelow };
    const shownHeight = Math.min(height, roomAbove);
    return { left: Math.round(left), top: Math.round(anchor.top - CARD_GAP_PX - shownHeight), maxHeight: roomAbove };
}
