import { AiApiError, requestImportTagSuggestions } from './ai-chat/ai-chat-api.js';
import { NotesAPI } from './api-client.js';
import { CommandGate } from './mode-manager/services/command-gate-service.js';
import { actionRefreshAndMaybeSelect } from './mode-manager/actions/ui-actions.js';
import { withoutFolderTags } from './import-folder-tags.js';

// The AI suggests tags for an import (PLAN.md, slice 2b): the import's files seen together,
// as many to a request as fit, so files on one topic get the same tags (the maintainer,
// 2026-11-01: one file at a time can't see what the files share). Proposals, shown as robot
// counts, which search already finds; nothing is accepted for the user. The import's folder
// tags and its own tag are never offered or proposed: a note has its own folder's tag from
// its file, and on any other note it would be wrong.

/**
 * Ask the AI for tags for the file notes of an import (fileNoteIds, from the import's
 * answer), with the AI settings the chat uses now; onProgress(done, total) as the AI's
 * batches finish. The proposals are added as one undo step. Resolves to
 * { proposedNoteCount, failure } (failure: why the AI stopped, or '').
 */
export async function suggestTagsForImport({ fileNoteIds, folderTags, sourceTag, settings, onProgress }) {
    if (!Array.isArray(fileNoteIds) || fileNoteIds.length === 0 || !Array.isArray(folderTags) || typeof sourceTag !== 'string'
        || !settings || typeof onProgress !== 'function') {
        throw new Error('suggestTagsForImport requires fileNoteIds, folderTags, sourceTag, the AI settings and onProgress');
    }
    // The import's notes, whatever the search shows now: the tab's view without its search.
    const scope = { ...NotesAPI.viewScope(), search: '', isUntaggedView: false };
    let proposals = null;
    let failure = '';
    try {
        proposals = await requestImportTagSuggestions({
            fileNoteIds, excludedTags: [...folderTags, sourceTag], scope, provider: settings.provider, model: settings.model,
            thinkingLevel: settings.thinkingLevel, onProgress,
        });
    } catch (error) {
        if (!(error instanceof AiApiError)) {
            throw error;
        }
        failure = error.message;
    }
    if (proposals === null) {
        return { proposedNoteCount: 0, failure };
    }
    const kept = withoutFolderTags(proposals, folderTags);
    const proposedNoteCount = Object.keys(kept).length;
    if (proposedNoteCount > 0) {
        // The answer waits for any running command; it is never dropped.
        await CommandGate.runWhenFree('importWizard.addTagProposals', async () => {
            await NotesAPI.addTagProposals(fileNoteIds[0], kept);
            await actionRefreshAndMaybeSelect({ startedAt: performance.now(), context: 'importWizard.tagProposals' });
        });
    }
    return { proposedNoteCount, failure };
}
