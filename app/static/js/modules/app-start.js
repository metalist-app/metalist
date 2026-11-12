// The workspace: the notes, command palette, AI chat and reminders, and the ~290 modules under
// them. main.js and auth.js load it with import() (Auth.loadApp), after the login page shows its
// vaults or at once when no login is needed, so the login page waits for none of it (the
// maintainer, 2026-11-12: over Wi-Fi the vault list came 2.5 s late, every module downloaded
// first). It starts the workspace the same way whether the page opened logged in or after a
// login, which until now were two copies of these steps.
import { ModeManager } from './mode-manager/mode-manager-controller.js';
import { CommandPalette } from './command-palette/command-palette-controller.js';
import { ReminderSurface } from './reminder-surface-service.js';
import { initializeNoteHtmlSanitizer } from './note-html-sanitizer.js';
import { AiChatPanel } from './ai-chat/ai-chat-panel-controller.js';
import { PhoneMode } from './phone/phone-mode.js';
import { watchFoldArrows } from './mode-manager/services/fold-arrow-alignment-service.js';
import { watchFoldability } from './mode-manager/services/collapse-affordance-service.js';
import { queueMermaidDiagramRendering } from './mode-manager/services/mermaid-render-service.js';
// Loaded with the workspace: it sets window.ErrorHandler for the code that reads it there.
import './error-handler.js';

export { closeAllFloatingNotes } from './mode-manager/services/floating-note-service.js';

// Up to the workspace being shown and ready. onStage(stage) hears each step as it starts.
export async function startWorkspace({ auth, onStage }) {
    if (typeof onStage !== 'function') {
        throw new Error('startWorkspace requires onStage');
    }
    onStage('reading the note format rules');
    await initializeNoteHtmlSanitizer();
    window.ModeManager = ModeManager;
    onStage('initializing the workspace UI');
    await ModeManager.init({});
    const notesContainer = document.getElementById('notes-container');
    if (!notesContainer) {
        throw new Error('Notes container not found after ModeManager initialization');
    }
    watchFoldArrows(notesContainer);
    watchFoldability(notesContainer);
    await queueMermaidDiagramRendering(notesContainer);
    onStage('initializing the command palette');
    await CommandPalette.init();
    // Under 640 px: the phone's read-only view and capture (docs/ui/phone.md).
    PhoneMode.init();
    onStage('initializing AI chat');
    await AiChatPanel.init({
        getSettings: () => CommandPalette.getAiSettings(),
        saveSettings: (settings) => CommandPalette.saveAiSettings(settings),
        getPanelWidth: () => CommandPalette.getAiChatPanelWidth(),
        savePanelWidth: (width) => CommandPalette.saveAiChatPanelWidth(width),
        getDiagnosticsVisible: () => CommandPalette.getAiChatDiagnosticsVisible(),
        saveDiagnosticsVisible: (isVisible) => CommandPalette.saveAiChatDiagnosticsVisible(isVisible),
        getSpendVisible: () => CommandPalette.getAiChatSpendVisible(),
        saveSpendVisible: (isVisible) => CommandPalette.saveAiChatSpendVisible(isVisible),
        getComposerHeight: () => CommandPalette.getAiChatComposerHeight(),
        saveComposerHeight: (height) => CommandPalette.saveAiChatComposerHeight(height),
        setVisible: (isVisible) => CommandPalette.applyPreference('pref.show_ai_chat', isVisible),
        openSettings: () => CommandPalette.openAiAgentSettings('keys'),
        openMenu: (menuId, scope, signal) => CommandPalette.openAgentMenu(menuId, scope, signal),
    });
    onStage('revealing the workspace');
    auth.revealMainApp();
    onStage('starting reminders');
    await ReminderSurface.start();
    onStage('starting the backup reminder');
    await CommandPalette.startBackupReminder();
    document.body.dataset.appReady = 'true';
}

// Once the workspace is ready: what follows it.
export async function afterWorkspaceReady({ auth }) {
    await auth.announceWorkspaceReady();
    CommandPalette.startUpdateNotice();
    await CommandPalette.runSetupRequestedByAddress();
}
