import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';
import { actionSaveNoteOnIdle } from '../actions/content-actions.js';
import { CommandGate } from '../services/command-gate-service.js';
import { TypeAhead } from '../services/type-ahead-service.js';
import { prefetchEditingLinkTitles } from '../services/link-title-prefetch-service.js';

const CHECK_INTERVAL = 500;
// A note being edited saves after 10 s without typing (decided 2026-10-31,
// docs/ready-to-build/commit-and-shutdown-protocol.md §3.1).
const CONTENT_INACTIVITY_THRESHOLD = 10000;

const moduleState = ApplicationState.createFields('inactivity-events', {
    contentCheckTimer: null,
});

function initContentAutoSave() {
    
    moduleState.contentCheckTimer = setInterval(checkAndSaveContent, CHECK_INTERVAL);
    
    Logger.logInit('Content auto-save initialized');
}

function checkAndSaveContent() {
    void prefetchEditingLinkTitles();
    
    if (!ModeContext.isEditing || !ModeContext.isDirty) {
        return;
    }
    
    const lastChangeTime = ModeContext.lastContentChangeTime;

    const timeSinceLastChange = Date.now() - lastChangeTime;

    if (timeSinceLastChange >= CONTENT_INACTIVITY_THRESHOLD) {
        Logger.logDebug('Auto-saving content after inactivity', {
            noteId: ModeContext.currentNoteId,
            inactivityDuration: timeSinceLastChange
        });

        // Letters typed while the save runs are kept and typed in after it (agreed
        // 2026-10-31), once MetaList is no longer busy, so they count as typing.
        const noteId = ModeContext.currentNoteId;
        let saving = TypeAhead.NONE;
        void CommandGate.run('autosave', async () => {
            saving = TypeAhead.begin(noteId);
            await actionSaveNoteOnIdle(noteId);
        }).then(() => TypeAhead.finish(saving));

    }
}

export { initContentAutoSave };
