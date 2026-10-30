import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { showSearchInputChip } from './search-input-chip-service.js';

// Summaries beside the result count (app/services/search_summary.py; docs/ui/search-
// semantics.md, Summaries): a view option picks a calculation and a property, and the
// server sends the figure over exactly the notes the view finds. Each tab keeps its own
// (tab state `summaries`); this keeps what the server last sent, for the menus, the chip
// in the search input and the figure beside the count.

// The calculations, in the dialog's order (search_summary.py SUMMARY_KINDS).
export const SUMMARY_KINDS = Object.freeze([
    ['sum', 'Sum'],
    ['avg', 'Average per note'],
    ['median', 'Median per note'],
    ['min', 'Min per note'],
    ['max', 'Max per note'],
    ['mode', 'Most common value'],
]);
export const NO_SUMMARY = 'none';
const CHIP_LABELS = Object.freeze({ sum: 'Σ', avg: 'avg', median: 'median', min: 'min', max: 'max', mode: 'mode' });

const moduleState = ApplicationState.createFields('summary-service', {
    // Each tab's summary as the server last sent it, by tab id: { kind, property }.
    summariesByTabId: Object.freeze({}),
});

function requireSummary(entry) {
    if (!entry || typeof entry !== 'object' || !Object.hasOwn(CHIP_LABELS, entry.kind)) {
        throw new Error(`Unknown summary: ${JSON.stringify(entry)}`);
    }
    if (typeof entry.property !== 'string' || entry.property.length === 0) {
        throw new Error('A summary names its property');
    }
    return Object.freeze({ kind: entry.kind, property: entry.property });
}

/** Take the summaries from a tab-state response (every one carries summaries). */
export function recordSummariesFromServer(serverState) {
    if (!serverState || typeof serverState !== 'object') {
        throw new Error('recordSummariesFromServer requires the server tab state');
    }
    const summaries = serverState.summaries;
    if (!summaries || typeof summaries !== 'object' || Array.isArray(summaries)) {
        throw new Error('Tab state response missing summaries');
    }
    const next = {};
    for (const [tabId, entry] of Object.entries(summaries)) {
        next[tabId] = requireSummary(entry);
    }
    if (JSON.stringify(next) !== JSON.stringify(moduleState.summariesByTabId)) {
        moduleState.summariesByTabId = Object.freeze(next);
    }
}

/** The active tab's summary ({ kind, property }), or null when it shows the count alone. */
export function getActiveSummary() {
    const tabId = ModeContext.activeTabId;
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('getActiveSummary requires an active tab');
    }
    if (!Object.hasOwn(moduleState.summariesByTabId, tabId)) {
        return null;
    }
    return moduleState.summariesByTabId[tabId];
}

/** The chip inside the search input: shown while the active tab has a summary. */
export function updateSummaryIndicator() {
    const indicator = document.getElementById('summary-indicator');
    const label = document.getElementById('summary-indicator-label');
    if (!(indicator instanceof HTMLElement) || !(label instanceof HTMLElement)) {
        throw new Error('summary-indicator elements missing');
    }
    const summary = getActiveSummary();
    if (summary === null) {
        showSearchInputChip(indicator, { isShown: false });
        return;
    }
    const text = `${CHIP_LABELS[summary.kind]} ${summary.property}`;
    if (label.textContent !== text) {
        label.textContent = text;
    }
    indicator.title = 'Summary beside the result count';
    showSearchInputChip(indicator, { isShown: true });
}

/** The figure beside the result count, from a view snapshot's summary ({ text, title }). */
export function updateSummaryFigure(snapshot) {
    const figure = document.getElementById('search-summary');
    if (!(figure instanceof HTMLElement)) {
        throw new Error('search-summary element missing');
    }
    const summary = snapshot.summary;
    if (!summary || typeof summary.text !== 'string' || typeof summary.title !== 'string') {
        throw new Error('View snapshot missing its summary');
    }
    figure.hidden = summary.text === '';
    if (figure.textContent !== summary.text) {
        figure.textContent = summary.text;
    }
    figure.title = summary.title;
}
