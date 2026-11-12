// A tag dialog's suggestion list (Add or Remove Tag, Prioritize Tag) ends inside the window and
// scrolls within itself: reaching past the window's bottom, it made the dialog layer scroll and,
// where scrollbars take room, the dialog move (docs/ui/interaction-principles.md; the maintainer,
// 2026-11-11). Tests: scripts/browser-tag-dialog-list-regressions.mjs.

// Room left between the list and the window's bottom edge.
const WINDOW_MARGIN_PX = 12;
// The least it is given, in a window shorter than the dialog: a few rows, the dialog layer
// scrolling to them as it already scrolls to the rest of the dialog.
const MIN_LIST_HEIGHT_PX = 120;

export function fitSuggestionList(list) {
    if (!(list instanceof HTMLElement)) {
        throw new Error('fitSuggestionList requires the list element');
    }
    const room = window.innerHeight - list.getBoundingClientRect().top - WINDOW_MARGIN_PX;
    list.style.maxHeight = `${Math.max(room, MIN_LIST_HEIGHT_PX)}px`;
    keepSelectedRowInView(list);
}

// The highlighted row scrolled into the list's view, the list alone: scrollIntoView could
// scroll the dialog layer too.
function keepSelectedRowInView(list) {
    const selected = list.querySelector('.is-selected');
    if (selected === null) return;
    // The list's inside, within its padding; scrolled by whole pixels, so a row a fraction past
    // it scrolls the whole of that fraction.
    const listBox = list.getBoundingClientRect();
    const style = getComputedStyle(list);
    const insideTop = listBox.top + list.clientTop + parseFloat(style.paddingTop);
    const insideBottom = listBox.top + list.clientTop + list.clientHeight - parseFloat(style.paddingBottom);
    const rowBox = selected.getBoundingClientRect();
    if (rowBox.bottom > insideBottom) {
        list.scrollTop += Math.ceil(rowBox.bottom - insideBottom);
    } else if (rowBox.top < insideTop) {
        list.scrollTop -= Math.ceil(insideTop - rowBox.top);
    }
}
