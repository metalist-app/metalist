// Changes made in another view (another browser tab, the phone) shown here without a reload
// (multi-view editing step 3; docs/design/multi-view-editing.md, "Step 3's cases").
//
// The status the app polls (polling-service.js) carries two revisions: the notes' (any change, from
// any view) and the shared search contexts' (their list, order, searches, sorts and filters). A
// notes revision later than the one this view's last answer was built at, or a contexts revision
// that moved, is applied here: the notes refreshed with the note at the window's top (or the caret
// of the note being edited) held still, the contexts taken again. Nothing is highlighted or animated
// (case 8). A change waits while the user is busy with something it would disturb: scrolling, a drag,
// a menu, a dialog, Find, a command running, a search being typed, a reference page opening (cases 9
// and 10). A change of this view's own is never taken again (noticeOwnContextsChange).
import { findNoteElement } from '../../editing-surface.js';
import { ApplicationState } from '../../application-state.js';
import { ErrorHandler } from '../../error-handler.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { CommandGate } from './command-gate-service.js';
import { isContextMenuOpen } from '../../context-menu/context-menu-service.js';
import { isFindBarOpen } from './find-in-list-service.js';
import { isMovingNoteByDrag } from '../events/mouse-events.js';
import { isDebouncedSearchPending } from './search-debounce-service.js';
import { isReferenceViewTransitionPending } from './reference-view-transition-service.js';
import { captureNoteAnchor, captureWindowTopNote } from './viewport-hold-service.js';
import { askOtherTabsToCheckNow } from '../../views-in-this-browser.js';

const NOT_YET_SEEN = -1;
// A change waits this long after the last scroll, so nothing moves while the page is moving.
const SCROLL_SETTLE_MS = 300;
// How soon a waiting change looks again whether the user is free.
const WAIT_RETRY_MS = 250;

const moduleState = ApplicationState.createFields('live-changes-service', {
    notesShownAt: NOT_YET_SEEN,
    contextsSeenAt: NOT_YET_SEEN,
    locksSeenAt: NOT_YET_SEEN,
    hasNotesChange: false,
    hasContextsChange: false,
    isApplying: false,
    retryTimer: null,
    lastScrollAt: Number.NEGATIVE_INFINITY,
    isScrollWatched: false,
});

function requireRevision(revision, name) {
    if (!Number.isInteger(revision) || revision < 0) {
        throw new Error(`${name} must be a non-negative integer`);
    }
}

function watchScrolling() {
    if (moduleState.isScrollWatched) {
        return;
    }
    moduleState.isScrollWatched = true;
    window.addEventListener('scroll', () => {
        // Two scroll events can read the same time (Firefox rounds its clock), and a state set
        // again is refused: the second is no news (exit-edit-scroll, Firefox, CI, 2026-11-15).
        const now = performance.now();
        if (moduleState.lastScrollAt !== now) {
            moduleState.lastScrollAt = now;
        }
    }, { passive: true });
}

// Every answer to a view request: the notes it shows are those of this revision at least.
export function recordNotesShown(revision) {
    requireRevision(revision, 'notes.view notesRevision');
    // Most answers come with no change since the last (a state set again is refused).
    if (moduleState.notesShownAt !== revision) {
        moduleState.notesShownAt = revision;
    }
}

// Every tab-state answer: the shared contexts' revision before and after that request. When this
// view had seen the one before, the change (if any) was its own and is not taken again; when it had
// not, another view changed them meanwhile, and the next status brings that.
export function noticeOwnContextsChange(revision) {
    if (revision === null || typeof revision !== 'object') {
        throw new Error('tab-state searchContextsRevision must be { before, after }');
    }
    requireRevision(revision.before, 'tab-state searchContextsRevision.before');
    requireRevision(revision.after, 'tab-state searchContextsRevision.after');
    if (moduleState.contextsSeenAt === revision.before && revision.after !== revision.before) {
        moduleState.contextsSeenAt = revision.after;
    }
    // This request changed the shared contexts: this browser's other tabs take them now.
    if (revision.after !== revision.before) {
        askOtherTabsToCheckNow();
    }
}

// The status just polled (polling-service.js).
export function noticeStatusRevisions(status) {
    if (status === null || typeof status !== 'object') {
        throw new Error('auth status response must be an object');
    }
    if (status.authenticated !== true) {
        if (moduleState.contextsSeenAt !== NOT_YET_SEEN) moduleState.contextsSeenAt = NOT_YET_SEEN;
        if (moduleState.locksSeenAt !== NOT_YET_SEEN) moduleState.locksSeenAt = NOT_YET_SEEN;
        if (moduleState.hasNotesChange) moduleState.hasNotesChange = false;
        if (moduleState.hasContextsChange) moduleState.hasContextsChange = false;
        return;
    }
    watchScrolling();
    requireRevision(status.notes_revision, 'auth status notes_revision');
    requireRevision(status.search_contexts_revision, 'auth status search_contexts_revision');
    requireRevision(status.edit_locks_revision, 'auth status edit_locks_revision');
    // A root another view started or stopped editing: the view shows its markers again (a search's
    // lock moves the contexts revision itself).
    if (moduleState.locksSeenAt === NOT_YET_SEEN) {
        moduleState.locksSeenAt = status.edit_locks_revision;
    } else if (status.edit_locks_revision !== moduleState.locksSeenAt) {
        moduleState.locksSeenAt = status.edit_locks_revision;
        if (!moduleState.hasNotesChange) moduleState.hasNotesChange = true;
    }
    // Before the first view is shown, the view about to load is the news.
    if (moduleState.notesShownAt !== NOT_YET_SEEN && status.notes_revision !== moduleState.notesShownAt
        && !moduleState.hasNotesChange) {
        moduleState.hasNotesChange = true;
    }
    // The first status: the contexts this view loaded are already the server's.
    if (moduleState.contextsSeenAt === NOT_YET_SEEN) {
        moduleState.contextsSeenAt = status.search_contexts_revision;
    } else if (status.search_contexts_revision !== moduleState.contextsSeenAt) {
        moduleState.contextsSeenAt = status.search_contexts_revision;
        if (!moduleState.hasContextsChange) moduleState.hasContextsChange = true;
    }
    applyWhenFree();
}

// Why a change must wait, or '' when it can be applied now.
function reasonToWait() {
    if (document.hidden) return 'hidden';
    if (CommandGate.isTurnTaken()) return 'command';
    if (ModeContext.modalStack.length > 0) return 'dialog';
    if (isContextMenuOpen()) return 'menu';
    if (isFindBarOpen()) return 'find';
    if (isMovingNoteByDrag()) return 'drag';
    if (isDebouncedSearchPending()) return 'search typing';
    if (isReferenceViewTransitionPending()) return 'reference page opening';
    if (performance.now() - moduleState.lastScrollAt < SCROLL_SETTLE_MS) return 'scrolling';
    return '';
}

// What a change waits for that only the user ends: it may wait as long as they like.
const HELD_BY_THE_USER = ['hidden', 'dialog', 'menu', 'find', 'drag'];

/**
 * Whether a change made elsewhere is being shown or will be within moments: one is known, and
 * nothing the user holds open keeps it waiting. The browser suites ask, to know that the page has
 * finished (browser-app-idle.mjs); a change waiting behind an open dialog is not about to be shown.
 */
export function isChangeAboutToBeShown() {
    if (moduleState.isApplying) return true;
    if (!moduleState.hasNotesChange && !moduleState.hasContextsChange) return false;
    return !HELD_BY_THE_USER.includes(reasonToWait());
}

function retryLater() {
    if (moduleState.retryTimer !== null) {
        return;
    }
    moduleState.retryTimer = window.setTimeout(() => {
        moduleState.retryTimer = null;
        applyWhenFree();
    }, WAIT_RETRY_MS);
}

function applyWhenFree() {
    if (!moduleState.hasNotesChange && !moduleState.hasContextsChange) {
        return;
    }
    if (moduleState.isApplying) {
        return;
    }
    // A hidden view looks again when shown (polling-service.js checks at once).
    if (document.hidden) {
        return;
    }
    if (reasonToWait() !== '') {
        retryLater();
        return;
    }
    moduleState.isApplying = true;
    // In a turn: a command asked for meanwhile runs after the change is shown (turns.js).
    CommandGate.runBackground('liveChanges.apply', applyChanges)
        .catch((error) => {
            rethrowUnexpectedError(error);
            ErrorHandler.handleApiError(error, null);
        })
        .finally(() => {
            moduleState.isApplying = false;
            applyWhenFree();
        });
}

async function applyChanges() {
    if (moduleState.hasContextsChange) {
        moduleState.hasContextsChange = false;
        const { adoptSharedSearchContexts } = await import('../events/keyboard-events.js');
        await adoptSharedSearchContexts();
    }
    if (moduleState.hasNotesChange) {
        moduleState.hasNotesChange = false;
        await showNotesChangedElsewhere();
    }
}

// What stays still: the caret (or reading line) of the note being edited, else the note at the
// window's top (cases 2 to 6).
function captureWhatStaysStill() {
    if (ModeContext.isEditing) {
        const editedNote = findNoteElement(ModeContext.currentNoteId);
        if (editedNote instanceof HTMLElement) {
            return captureNoteAnchor(editedNote);
        }
    }
    return captureWindowTopNote();
}

async function showNotesChangedElsewhere() {
    const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
    // What stays still is what is there when the change lands: a scroll made meanwhile stays.
    await actionRefreshAndMaybeSelect({
        context: 'changed-elsewhere', animateNoteChanges: false, keepEditingFocus: true,
        leaveFocusElsewhere: true, captureViewportHold: captureWhatStaysStill,
    });
}
