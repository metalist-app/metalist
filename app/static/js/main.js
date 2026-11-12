import { installInputRecorder } from './modules/problem-reports/input-recorder.js';
import { installGlobalErrorOverlay } from './modules/error-overlay.js';
import { MS_PER_SECOND } from './modules/time-units.js';
import { checkReleaseOnPageLoad } from './modules/app-update-service.js';
import { ModeManager } from './modules/mode-manager/mode-manager-controller.js';
import { CONFIG } from './modules/config.js';
import { DOMUtils } from './modules/dom-utils.js';
import { Auth } from './modules/auth.js';
import { ErrorHandler } from './modules/error-handler.js';
import { ActivityTracker } from './modules/activity-tracker.js';
import { CommandPalette } from './modules/command-palette/command-palette-controller.js';
import { ReminderSurface } from './modules/reminder-surface-service.js';
import { initializeNoteHtmlSanitizer } from './modules/note-html-sanitizer.js';
import { AiChatPanel } from './modules/ai-chat/ai-chat-panel-controller.js';
import { PhoneMode } from './modules/phone/phone-mode.js';
import { watchFoldArrows } from './modules/mode-manager/services/fold-arrow-alignment-service.js';
import { watchFoldability } from './modules/mode-manager/services/collapse-affordance-service.js';
import {
    queueMermaidDiagramRendering,
} from './modules/mode-manager/services/mermaid-render-service.js';

// How long a non-fatal warning from the red error's listener stays on screen.
const GLOBAL_WARNING_BANNER_SECONDS = 8;
// Before anything else listens or fetches: the trail a problem report is made from
// (docs/ready-to-build/error-reports.md §1), in memory only.
installInputRecorder();
// The red error, from the login page on (error-reports.md §8): an error before login shows
// it too, with Export Report…, made in memory only.
installGlobalErrorOverlay((message) => ErrorHandler.showInfoBanner(message, GLOBAL_WARNING_BANNER_SECONDS * MS_PER_SECOND));

document.addEventListener('DOMContentLoaded', async () => {
    console.log('DOMContentLoaded fired');
    document.body.dataset.appReady = 'false';
    checkReleaseOnPageLoad();

    await initializeNoteHtmlSanitizer();

    // Make ModeManager available globally for post-login initialization
    window.ModeManager = ModeManager;
    
    // Start activity tracking for token refresh
    ActivityTracker.start();

    // Initialize authentication first
    console.log('+++ main.js: About to initialize Auth');
    const isAuthOk = await Auth.init();
    console.log('+++ main.js: Auth init() completed, authOk:', isAuthOk);

    // Only initialize ModeManager if auth is OK
    if (isAuthOk) {
        console.log('+++ main.js: About to initialize ModeManager');
        await ModeManager.init({});
        const notesContainer = document.getElementById('notes-container');
        if (!notesContainer) {
            throw new Error('Notes container not found after ModeManager initialization');
        }
        watchFoldArrows(notesContainer);
        watchFoldability(notesContainer);
        await queueMermaidDiagramRendering(notesContainer);
        console.log('+++ main.js: ModeManager init() completed');

        await CommandPalette.init();
        // Under 640 px: the phone's read-only view and capture (docs/ui/phone.md).
        PhoneMode.init();
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
        Auth.revealMainApp();
        await ReminderSurface.start();
        await CommandPalette.startBackupReminder();
        document.body.dataset.appReady = 'true';
        await Auth.announceWorkspaceReady();
        CommandPalette.startUpdateNotice();
        await CommandPalette.runSetupRequestedByAddress();
    } else {
        console.log('+++ main.js: Skipping ModeManager init due to auth requirement');
    }

    document.addEventListener('focus', (e) => {
        const target = e && e.target;
        if (!target) {
            return;
        }

        let element = null;
        if (typeof target.closest === 'function') {
            element = target;
        } else if (target.nodeType === Node.TEXT_NODE && target.parentElement && typeof target.parentElement.closest === 'function') {
            element = target.parentElement;
        } else {
            return;
        }

        const noteContent = element.closest('.note-content');
        if (noteContent) {
            if (typeof e.clientY !== 'number') {
                return;
            }
            const rect = noteContent.getBoundingClientRect();
            if (!(e.clientY >= rect.top && e.clientY <= rect.bottom)) {
                const selection = window.getSelection();
                if (selection) {
                    selection.removeAllRanges();
                }
            }
        }
    }, true);  

    if (CONFIG.DEBUG.LOG_STATE_CHANGES) {
        console.log('Application initialized successfully');
    }
});

window.addEventListener('unhandledrejection', event => {
    console.error('Unhandled promise rejection:', event.reason);
});
