// The number keys 1 to 9 switch to the search context the list numbers that way (the
// maintainer, 2026-11-21), only while nothing is being typed: the caller has ruled out a note
// being edited, the search box, any other field, and an open dialog.

const DIGIT_KEY_RE = /^[1-9]$/;

/**
 * The search context a key press chooses: '' when the key is no digit from 1 to 9, a key is
 * held with it (⌘3 is the browser's own), a menu is open, the list has no context of that
 * number, or the context is the one already shown.
 */
export function searchContextForDigitKey({ key, hasModifier, isMenuOpen, listedTabIds, shownTabId }) {
    if (typeof key !== 'string' || typeof hasModifier !== 'boolean' || typeof isMenuOpen !== 'boolean'
        || !Array.isArray(listedTabIds) || typeof shownTabId !== 'string') {
        throw new Error('searchContextForDigitKey requires the key, its modifiers, the menu state, the listed contexts and the one shown');
    }
    if (!DIGIT_KEY_RE.test(key) || hasModifier || isMenuOpen) return '';
    const place = Number(key) - 1;
    if (place >= listedTabIds.length) return '';
    const tabId = listedTabIds[place];
    if (tabId === shownTabId) return '';
    return tabId;
}
