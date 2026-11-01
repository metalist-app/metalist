import { MS_PER_SECOND } from './time-units.js';
import { AiApiError, requestNoteTagSuggestions } from './ai-chat/ai-chat-api.js';
import { ErrorHandler } from './error-handler.js';
import { FloatingMessages } from './floating-messages.js';
import { NotesAPI } from './api-client.js';
import { CommandGate } from './mode-manager/services/command-gate-service.js';
import { actionRefreshAndMaybeSelect } from './mode-manager/actions/ui-actions.js';
import { withoutFolderTags } from './import-folder-tags.js';

// The AI suggests tags for an import (PLAN.md, slice 2b): each imported file's note with the
// notes under it, one after another, exactly as Suggest Tags with AI does for a note and its
// children (docs/ui/tag-bar.md): proposals, shown as robot counts, which search already
// finds; nothing is accepted for the user. The import's folder tags are never proposed: a
// note has its own folder's tag from its file, and on any other note it would be wrong.

const PROGRESS_KEY = 'import-tag-suggestions';
const FAILURE_BANNER_SECONDS = 8;

function progressText(done, total) {
    return `Asking the AI for tags… ${done + 1} of ${total} files`;
}

/**
 * Ask the AI for tags for every file note of an import (fileNoteIds, from the import's
 * answer), with the AI settings the chat uses now. Each file's proposals are added (one undo
 * step each) as they come; the first failure stops the run and says why.
 */
export async function suggestTagsForImport({ fileNoteIds, folderTags, settings }) {
    if (!Array.isArray(fileNoteIds) || !Array.isArray(folderTags) || !settings) {
        throw new Error('suggestTagsForImport requires fileNoteIds, folderTags and the AI settings');
    }
    if (fileNoteIds.length === 0) return;
    // The import's notes, whatever the search shows now: the tab's view without its search.
    const scope = { ...NotesAPI.viewScope(), search: '', isUntaggedView: false };
    FloatingMessages.showProgress(PROGRESS_KEY, progressText(0, fileNoteIds.length));
    let proposedNoteCount = 0;
    for (const [index, noteId] of fileNoteIds.entries()) {
        FloatingMessages.show({
            text: progressText(index, fileNoteIds.length), type: 'info', detail: '',
            isClosable: false, isLasting: true, key: PROGRESS_KEY,
        });
        const request = {
            noteId, includeChildren: true, scope, provider: settings.provider, model: settings.model,
            thinkingLevel: settings.thinkingLevel, onProgress: () => {},
        };
        let proposals = null;
        try {
            proposals = await requestNoteTagSuggestions(request);
        } catch (error) {
            if (!(error instanceof AiApiError)) {
                throw error;
            }
            FloatingMessages.end(PROGRESS_KEY);
            ErrorHandler.showInfoBanner(`The AI couldn't suggest tags: ${error.message}`, FAILURE_BANNER_SECONDS * MS_PER_SECOND);
        }
        if (proposals === null) {
            return;
        }
        const kept = withoutFolderTags(proposals, folderTags);
        if (Object.keys(kept).length === 0) {
            continue;
        }
        // The answer waits for any running command; it is never dropped.
        await CommandGate.runWhenFree('folderImport.addTagProposals', async () => {
            await NotesAPI.addTagProposals(noteId, kept);
            await actionRefreshAndMaybeSelect({ startedAt: performance.now(), context: 'folderImport.tagProposals' });
        });
        proposedNoteCount += Object.keys(kept).length;
    }
    FloatingMessages.end(PROGRESS_KEY);
    FloatingMessages.show({
        text: `The AI suggested tags for ${proposedNoteCount} notes.`, type: 'success', detail: '',
        isClosable: false, isLasting: false, key: null,
    });
}
