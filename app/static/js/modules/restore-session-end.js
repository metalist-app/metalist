/**
 * Restoring the open vault restarts the server, which ends the session. While this page
 * restores it, background requests answered "not logged in" (a tab-state save,
 * reminders, ...) are expected: Auth.forceLogout does not send the page to Session
 * locked, and closing the restore dialog reloads the page into the login screen
 * (docs/BUGS.md, 2026-10-18). After a failed restore, a lost session locks the page as
 * usual. Only this page is spared: once it reloads, a lost session locks it again.
 *
 * Kept apart from auth.js so the restore dialog can set it without loading the app's
 * error handling.
 */

import { ApplicationState } from './application-state.js';

const moduleState = ApplicationState.createFields('restore-session-end', { isRestoringOpenVault: false });

export function setRestoringOpenVault(isRestoring) {
    if (typeof isRestoring !== 'boolean') {
        throw new Error('setRestoringOpenVault requires a boolean');
    }
    // The dialog marks the restore when it starts and again once the server answers.
    if (moduleState.isRestoringOpenVault === isRestoring) return;
    moduleState.isRestoringOpenVault = isRestoring;
}

export function isRestoringOpenVault() {
    return moduleState.isRestoringOpenVault;
}
