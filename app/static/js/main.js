// The login page's own code only: the workspace (app-start.js, ~290 modules) loads with
// import() once the login page shows its vaults, or at once when no login is needed, so the
// vault list waits for none of it (the maintainer, 2026-11-12).
import { installInputRecorder } from './modules/problem-reports/input-recorder.js';
import { installGlobalErrorOverlay } from './modules/error-overlay.js';
import { checkReleaseOnPageLoad } from './modules/app-update-service.js';
import { CONFIG } from './modules/config.js';
import { Auth } from './modules/auth.js';
import { ActivityTracker } from './modules/activity-tracker.js';
import { FloatingMessages } from './modules/floating-messages.js';

// Before anything else listens or fetches: the trail a problem report is made from
// (docs/ready-to-build/error-reports.md §1), in memory only.
installInputRecorder();
// The red error, from the login page on (error-reports.md §8): an error before login shows
// it too, with Export Report…, made in memory only. Its warnings are passing info cards, as
// ErrorHandler.showInfoBanner shows them once the workspace has loaded.
installGlobalErrorOverlay((message) => FloatingMessages.show({
    text: message, type: 'info', detail: '', isClosable: false, isLasting: false, key: null, action: null,
}));

document.addEventListener('DOMContentLoaded', async () => {
    console.log('DOMContentLoaded fired');
    document.body.dataset.appReady = 'false';
    checkReleaseOnPageLoad();

    // Start activity tracking for token refresh
    ActivityTracker.start();

    // Authentication first: the login page, when one is needed, starts the workspace itself.
    const isAuthOk = await Auth.init();
    if (isAuthOk) {
        const app = await Auth.loadApp();
        await app.startWorkspace({
            auth: Auth,
            onStage: (stage) => console.log(`+++ main.js: ${stage}`),
        });
        await app.afterWorkspaceReady({ auth: Auth });
    } else {
        console.log('+++ main.js: the login page starts the workspace after login');
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
