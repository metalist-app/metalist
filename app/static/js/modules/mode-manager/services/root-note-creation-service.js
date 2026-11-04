import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';
import { ErrorHandler } from '../../error-handler.js';
import { rootNoteCreationBlockMessage } from './root-sort-service.js';
import { findUnfillableSearchTerm } from './search-syntax-service.js';
import { MS_PER_SECOND } from '../../time-units.js';

const BLOCKED_REASON_BANNER_SECONDS = 6;

// Why no new root note can go here, or null: a sorted tab limits where they may go
// (rootNoteCreationBlockMessage), and a search with a property term no new note can be
// given (jogging:miles>3) has none at all (findUnfillableSearchTerm).
export function rootNoteCreationBlockReason(placement) {
    const sortMessage = rootNoteCreationBlockMessage(ModeContext.activeTabSortMode, placement);
    if (sortMessage !== null) {
        return sortMessage;
    }
    const unfillableTerm = findUnfillableSearchTerm(ModeContext.searchQuery);
    if (unfillableTerm === null) {
        return null;
    }
    return `New notes cannot be added in this search: a new note would not match ${unfillableTerm}.`;
}

// Shows the reason and returns true when this new root note is blocked
// (rootNoteCreationBlockReason). Flows that do work before creating the note
// (uploading a file, reading the clipboard) call this first and stop; creating
// the note checks again.
export function blockRootNoteCreation(placement, contextLabel) {
    if (typeof contextLabel !== 'string' || contextLabel.length === 0) {
        throw new Error('blockRootNoteCreation requires a context label');
    }
    const message = rootNoteCreationBlockReason(placement);
    if (message === null) {
        return false;
    }
    Logger.logNoop('Root note creation blocked', {
        placement,
        context: contextLabel,
        sortMode: ModeContext.activeTabSortMode,
        searchQuery: ModeContext.searchQuery,
    });
    ErrorHandler.showInfoBanner(message, BLOCKED_REASON_BANNER_SECONDS * MS_PER_SECOND);
    return true;
}

// For callers that already checked blockRootNoteCreation: a null note id from
// createNote/createNoteAtTop then means the check was skipped, a bug.
export function requireCreatedNoteId(noteId, contextLabel) {
    if (typeof noteId !== 'string' || noteId.length === 0) {
        throw new Error(`${contextLabel}: new root note was blocked after the creation check passed`);
    }
    return noteId;
}
