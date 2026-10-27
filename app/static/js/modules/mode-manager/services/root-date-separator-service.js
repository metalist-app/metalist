import { buildRootDateSeparatorPlan, isRootDateBucketSortMode, normalizeRootSortMode } from './root-sort-service.js';

const SEPARATOR_SELECTOR = '.root-date-separator';

function createSeparatorElement({ bucketKey, label }) {
    const element = document.createElement('div');
    element.className = 'root-date-separator';
    element.dataset.bucketKey = bucketKey;
    element.textContent = label;
    return element;
}

export function rebuildRootDateSeparators(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') {
        throw new Error('rebuildRootDateSeparators requires snapshot object');
    }

    const notesContainer = document.getElementById('notes-container');
    if (!notesContainer) {
        throw new Error('notes-container not found');
    }

    for (const existing of Array.from(notesContainer.querySelectorAll(SEPARATOR_SELECTOR))) {
        existing.remove();
    }

    const sortMode = normalizeRootSortMode(snapshot.sortMode);
    if (!isRootDateBucketSortMode(sortMode)) {
        return;
    }

    const rootIds = snapshot.rootIds;
    const rootSortBuckets = snapshot.rootSortBuckets;
    const plan = buildRootDateSeparatorPlan(rootIds, rootSortBuckets, snapshot.rootSortKeyBeforeWindow);
    for (const entry of plan) {
        const rootElement = document.querySelector(`.note[data-note-id="${entry.rootId}"]`);
        if (!(rootElement instanceof HTMLElement)) {
            throw new Error(`Visible root note element missing for separator: ${entry.rootId}`);
        }
        if (rootElement.parentElement !== notesContainer) {
            throw new Error(`Root note ${entry.rootId} is not a direct child of notes-container`);
        }
        notesContainer.insertBefore(createSeparatorElement(entry), rootElement);
    }
}
