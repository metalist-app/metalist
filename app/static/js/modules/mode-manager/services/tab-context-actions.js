import { escapeHtml } from '../../html-escape.js';

// A tab row's actions in the tabs overlay: + duplicates the tab, − deletes it (red). Each
// says what it does on hover. At the tab limit + is greyed (the reason is discoverable);
// with a single tab − can never apply, so it is hidden, keeping its place so + does not move
// (docs/ui/modals.md, "Dialog and menu conventions", rule 8).
export function tabContextActionsHtml({ tabId, isAtTabLimit, canDelete }) {
    if (typeof tabId !== 'string' || tabId === '') {
        throw new Error('tabContextActionsHtml requires a tab id');
    }
    if (typeof isAtTabLimit !== 'boolean' || typeof canDelete !== 'boolean') {
        throw new Error('tabContextActionsHtml requires boolean isAtTabLimit and canDelete');
    }
    const addClass = isAtTabLimit ? 'is-disabled' : '';
    const deleteClass = canDelete ? '' : 'is-hidden';
    return `
            <span class="tab-context-action duplicate-context ${addClass}" data-source-tab-id="${escapeHtml(tabId)}" title="Duplicate Tab" aria-label="Duplicate Tab" aria-disabled="${isAtTabLimit}">+</span>
            <span class="tab-context-action tab-context-action--danger delete-context ${deleteClass}" data-delete-tab-id="${escapeHtml(tabId)}" title="Delete Tab" aria-label="Delete Tab" aria-hidden="${!canDelete}">-</span>
        `;
}
