// Which search contexts the `[[` list offers as search links (docs/ready-to-build/search-links.md
// §4): those whose search holds what is typed after `[[`, the current one first; with nothing
// typed, the current one alone. Only search contexts with a search are offered, folder contexts
// included (folder-tags-in-search.md §5): never a reference view (isSearch false), a blank search, or one holding [ or ],
// which a link can't hold. After `![[` the same are offered: `![[search:…]]` embeds the results.

const SEARCH_LINK_PREFIX = 'search:';
const BRACKETS_RE = /[[\]]/;

function offerable(context) {
    return context.isSearch && context.search.trim() !== '' && !BRACKETS_RE.test(context.search);
}

/**
 * @param {{query: string, contexts: Array<{tabId: string, search: string, isSearch: boolean}>,
 *          activeTabId: string, isEmbed: boolean}} options contexts in list order
 * @returns {string[]} the searches, each once, as their contexts hold them
 */
export function searchesToOffer({ query, contexts, activeTabId, isEmbed }) {
    if (typeof query !== 'string' || !Array.isArray(contexts) || typeof activeTabId !== 'string' || typeof isEmbed !== 'boolean') {
        throw new Error('searchesToOffer requires the query, the contexts, the current one and whether it is an embed');
    }
    let typed = query.trim();
    if (typed.startsWith(SEARCH_LINK_PREFIX)) typed = typed.slice(SEARCH_LINK_PREFIX.length).trim();
    const current = contexts.filter((context) => context.tabId === activeTabId && offerable(context));
    if (typed === '') return current.map((context) => context.search.trim());
    const folded = typed.toLocaleLowerCase();
    const others = contexts.filter((context) => context.tabId !== activeTabId && offerable(context));
    const searches = [...current, ...others]
        .map((context) => context.search.trim())
        .filter((search) => search.toLocaleLowerCase().includes(folded));
    return [...new Set(searches)];
}
