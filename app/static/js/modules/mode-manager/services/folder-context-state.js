import { ApplicationState } from '../../application-state.js';

// Folder contexts (docs/ready-to-build/virtual-folders.md, "Folder contexts"): the search contexts with the tree and
// a folder chosen in them; the others are plain searches. Open folders tab goes to the folder
// context used last, close folders tab to the plain search used last. The server keeps both with
// the search contexts (tab_state.py: folderContexts, recentTabs); every tab-state answer carries
// them, the tree's answer the folder contexts. Apart, so the list of search contexts and the
// tab-state service can read them without the tree's dependencies.

const NOT_RECENT = -1;

const moduleState = ApplicationState.createFields('folder-context-state', {
    folderTabIds: Object.freeze([]),
    // Every tab, the most recently shown first.
    recentTabIds: Object.freeze([]),
});

function requireTabIds(value, name) {
    if (!Array.isArray(value) || !value.every((tabId) => typeof tabId === 'string' && tabId !== '')) {
        throw new Error(`The server's answer has no ${name}`);
    }
    return value;
}

function rememberList(field, value) {
    if (JSON.stringify(moduleState[field]) !== JSON.stringify(value)) {
        moduleState[field] = Object.freeze([...value]);
    }
}

/** answer.folderContexts: the tabs that are folder contexts. */
export function recordFolderContextsFromServer(answer) {
    if (answer === null || typeof answer !== 'object') {
        throw new Error('recordFolderContextsFromServer requires the server\'s answer');
    }
    rememberList('folderTabIds', requireTabIds(answer.folderContexts, 'folderContexts'));
}

/** answer.recentTabs: every tab, the most recently shown first. */
export function recordRecentTabsFromServer(answer) {
    if (answer === null || typeof answer !== 'object') {
        throw new Error('recordRecentTabsFromServer requires the server\'s answer');
    }
    rememberList('recentTabIds', requireTabIds(answer.recentTabs, 'recentTabs'));
}

export function isFolderContext(tabId) {
    if (typeof tabId !== 'string' || tabId === '') {
        throw new Error('isFolderContext requires a tab id');
    }
    return moduleState.folderTabIds.includes(tabId);
}

/** Of tabIds, the one shown most recently ('' for none): a tab not shown yet comes after every
 * one that was, in tabIds' order. */
export function usedLastAmong(tabIds) {
    if (!Array.isArray(tabIds)) {
        throw new Error('usedLastAmong requires tab ids');
    }
    let best = '';
    let bestRank = Number.POSITIVE_INFINITY;
    for (const tabId of tabIds) {
        let rank = moduleState.recentTabIds.indexOf(tabId);
        if (rank === NOT_RECENT) rank = moduleState.recentTabIds.length;
        if (rank < bestRank) {
            best = tabId;
            bestRank = rank;
        }
    }
    return best;
}
