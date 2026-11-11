import { NotesAPI } from './api-client.js';
import { escapeHtml } from './html-escape.js';
import { isTagText, tagsToOffer } from './tag-input-offer.js';

// A field that asks for a tag offers the tags in use as you type (docs/ui/modals.md, "Fields that
// take a tag"): what to offer is in tag-input-offer.js.
const LIST_CLASS = 'tag-input-suggestions';
const ITEM_CLASS = 'tag-input-suggestion';
const SELECTED_CLASS = 'is-selected';
const LIST_GAP_PX = 4;
const NONE_SELECTED = -1;
const KEYS_FIRST = { capture: true };
const NO_ACTIVITY_WINDOWS = [];

// options.chosenTags(): the tags already in the list; options.onPick(tag): what picking one does.
export function attachTagSuggestions(input, options) {
    if (!(input instanceof HTMLInputElement) || input.parentElement === null) {
        throw new Error('attachTagSuggestions requires an input in the page');
    }
    if (typeof options.chosenTags !== 'function' || typeof options.onPick !== 'function') {
        throw new Error('attachTagSuggestions requires chosenTags and onPick');
    }
    // The list floats over the page, so a dialog's scrolling area doesn't cut it off; it exists
    // only while open.
    const list = document.createElement('div');
    list.className = LIST_CLASS;
    list.setAttribute('role', 'listbox');
    input.setAttribute('aria-autocomplete', 'list');
    const shown = { tags: [], selected: NONE_SELECTED, request: 0 };

    // While the list is open its keys come first, before the dialog's or the page's.
    const onKey = (event) => {
        if (event.target !== input) {
            return;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const step = event.key === 'ArrowDown' ? 1 : -1;
            shown.selected = (shown.selected + step + shown.tags.length + 1) % (shown.tags.length + 1);
            if (shown.selected === shown.tags.length) {
                shown.selected = NONE_SELECTED;
            }
            render();
            return;
        }
        if (event.key === 'Enter' && shown.selected !== NONE_SELECTED) {
            event.preventDefault();
            event.stopPropagation();
            pick(shown.tags[shown.selected]);
            return;
        }
        // Escape closes the list, not the dialog.
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            close();
        }
    };
    const close = () => {
        window.removeEventListener('keydown', onKey, KEYS_FIRST);
        shown.tags = [];
        shown.selected = NONE_SELECTED;
        window.removeEventListener('scroll', place, KEYS_FIRST);
        window.removeEventListener('resize', place);
        list.innerHTML = '';
        list.remove();
    };
    // Under the field, or above it when the window has more room there.
    const place = () => {
        if (!input.isConnected) {
            close();
            return;
        }
        const field = input.getBoundingClientRect();
        list.style.left = `${field.left}px`;
        list.style.width = `${field.width}px`;
        const height = list.offsetHeight;
        const roomBelow = window.innerHeight - field.bottom - LIST_GAP_PX;
        const roomAbove = field.top - LIST_GAP_PX;
        const isAbove = height > roomBelow && roomAbove > roomBelow;
        list.style.top = `${isAbove ? field.top - LIST_GAP_PX - height : field.bottom + LIST_GAP_PX}px`;
    };
    const render = () => {
        if (shown.tags.length === 0) {
            close();
            return;
        }
        list.innerHTML = shown.tags.map((tag, index) => (
            `<div class="${ITEM_CLASS}${index === shown.selected ? ` ${SELECTED_CLASS}` : ''}" role="option" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</div>`
        )).join('');
        if (!list.isConnected) {
            document.body.append(list);
            window.addEventListener('scroll', place, KEYS_FIRST);
            window.addEventListener('resize', place);
        }
        place();
        window.addEventListener('keydown', onKey, KEYS_FIRST);
    };
    const pick = (tag) => {
        close();
        options.onPick(tag);
    };
    const refresh = async () => {
        shown.request += 1;
        const request = shown.request;
        if (!isTagText(input.value)) {
            close();
            return;
        }
        // No recent-activity slots: what you searched for lately says nothing about this field.
        const response = await NotesAPI.fetchSearchSuggestions(input.value.trim(), NO_ACTIVITY_WINDOWS);
        if (!Array.isArray(response.suggestions)) {
            throw new Error('Search suggestions response requires suggestions array');
        }
        if (request !== shown.request) {
            return;
        }
        shown.tags = tagsToOffer(input.value, response.suggestions, options.chosenTags());
        shown.selected = NONE_SELECTED;
        render();
    };

    input.addEventListener('input', () => {
        void refresh();
    });
    input.addEventListener('blur', close);
    // Pressing a suggestion keeps the field focused, so it isn't closed before the click.
    list.addEventListener('mousedown', (event) => event.preventDefault());
    list.addEventListener('click', (event) => {
        const item = event.target instanceof Element ? event.target.closest(`.${ITEM_CLASS}`) : null;
        if (item !== null) {
            pick(item.dataset.tag);
        }
    });
}
