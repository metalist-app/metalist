import { ApplicationState } from '../../application-state.js';

// An embedded search's ▾/▸ folds it to its heading (docs/ready-to-build/search-links.md §11). The
// fold is a deliberate choice, kept in the vault's preferences by note and search, as a gallery's
// outline is (gallery-view-service.js), so a reload or another device shows it the same.
const FOLDED_PREFERENCE = 'pref.folded_search_embeds';
const FOLDED_CLASS = 'note-search-embed-folded';
const EMBEDS = '#notes-container .note-search-embed:not(.note-search-embed-nested)';
// A search can't hold |: it ends a search link's search.
const KEY_SEPARATOR = '|';

const moduleState = ApplicationState.createFields('search-embed', {
    foldedKeys: [],
    observer: null,
    isMarkScheduled: false,
});

function foldKey(embed) {
    const note = embed.closest('.note[data-note-id]');
    if (note === null) {
        throw new Error('An embedded search must be in a note');
    }
    return `${note.dataset.noteId}${KEY_SEPARATOR}${embed.dataset.searchQuery}`;
}

function markFolds() {
    const folded = new Set(moduleState.foldedKeys);
    for (const embed of document.querySelectorAll(EMBEDS)) {
        const isFolded = folded.has(foldKey(embed));
        if (embed.classList.contains(FOLDED_CLASS) !== isFolded) {
            embed.classList.toggle(FOLDED_CLASS, isFolded);
        }
        const toggle = embed.querySelector(':scope > .note-search-embed-toggle');
        const expanded = String(!isFolded);
        if (toggle !== null && toggle.getAttribute('aria-expanded') !== expanded) {
            toggle.setAttribute('aria-expanded', expanded);
        }
    }
}

function markSoon() {
    if (moduleState.isMarkScheduled) {
        return;
    }
    moduleState.isMarkScheduled = true;
    requestAnimationFrame(() => {
        moduleState.isMarkScheduled = false;
        markFolds();
    });
}

// The saved folds, each time the preferences are applied (command-palette-controller.js).
export function receiveFoldedSearchEmbeds(savedText) {
    const keys = JSON.parse(savedText);
    if (!Array.isArray(keys) || keys.some((key) => typeof key !== 'string')) {
        throw new Error(`${FOLDED_PREFERENCE} must be a list of folds`);
    }
    if (JSON.stringify(keys) !== JSON.stringify(moduleState.foldedKeys)) {
        moduleState.foldedKeys = keys;
    }
    if (moduleState.observer === null) {
        const container = document.getElementById('notes-container');
        if (container === null) {
            throw new Error('Embedded searches need #notes-container');
        }
        moduleState.observer = new MutationObserver(markSoon);
        moduleState.observer.observe(container, { childList: true, subtree: true });
    }
    markFolds();
}

// Its ▾/▸ pressed: folded or open again, at once, then kept.
export async function toggleSearchEmbedFold(toggle) {
    const embed = toggle.closest('.note-search-embed');
    if (embed === null) {
        throw new Error('A fold arrow must be in an embedded search');
    }
    const key = foldKey(embed);
    const keys = moduleState.foldedKeys.includes(key)
        ? moduleState.foldedKeys.filter((folded) => folded !== key)
        : [...moduleState.foldedKeys, key];
    moduleState.foldedKeys = keys;
    markFolds();
    const { CommandPalette } = await import('../../command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(FOLDED_PREFERENCE, JSON.stringify(keys));
}
