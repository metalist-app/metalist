import { KIB, MIB } from '../../byte-sizes.js';
import { MS_PER_SECOND } from '../../time-units.js';
import { escapeHtml } from '../../html-escape.js';
import { tabContextActionsHtml } from '../services/tab-context-actions.js';
import { ApplicationState } from '../../application-state.js';
import { HttpRequestError, rethrowUnexpectedError } from '../../expected-errors.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';
import {
    createNote,
    createNoteAtTop,
    deleteNote,
    createChildNote,
    moveNoteUp,
    moveNoteDown,
    moveNoteToBottom,
    moveNoteToTop,
    indentNote,
    outdentNote,
    actionCopyNote,
    actionPasteNoteSibling,
    actionPasteNoteChild,
    splitCurrentNoteFromSelection,
    unformatCurrentNoteContent,
    actionCopyNoteById,
    deleteNoteOutsideEdit,
} from '../actions/note-actions.js';
import { actionSaveNote } from '../actions/content-actions.js';
import { confirmRemovingReferencedNote, deleteEditedNoteAskingIfReferenced } from '../services/referenced-note-removal-service.js';
import { actionDeselectNote, actionExitEditingWithoutSavingOrRefreshing, actionSaveAndExitEditingWithoutRefreshing } from '../actions/selection-actions.js';
import { blockRootNoteCreation, requireCreatedNoteId } from '../services/root-note-creation-service.js';
import { actionUndo, actionRedo } from '../actions/history-actions.js';
import {
    consumePlainPasteRequest,
    detectClipboardFormat,
    planFormatPaste,
    rememberDetectedPaste,
    requestPlainPaste,
    takeDetectedPasteUndo,
} from '../services/paste-format-detection-service.js';
import { guessPastedFormat, isPlainClipboardHtml } from '../services/paste-format-guess-service.js';
import { offerPasteFormat } from '../services/paste-format-offer-service.js';
import { checkFormattedPaste, normalizePastedText, visibleTextOfHtml } from '../services/formatted-paste-format-service.js';
import {
    executeEditorRedo,
    shouldExecuteEditorRedo,
    shouldUseApplicationHistory,
} from '../services/history-shortcut-policy-service.js';
import { actionEnterSearchMode, actionExitSearchMode } from '../actions/search-actions.js';
import { HelpModal } from '../../modals/help-modal.js';
import { closeFindBar, isFindBarOpen, isFindInput, moveToMatch, openFindBar } from '../services/find-in-list-service.js';
import { DOMUtils } from '../../dom-utils.js';
import { CONFIG } from '../../config.js';
import { NotesAPI } from '../../api-client.js';
import { ErrorHandler } from '../../error-handler.js';
import { describeDroppedItems, loneDroppedFolderEntry, readDroppedFolder } from '../services/dropped-folders.js';
import {
    fileNewNoteInFolder, virtualFoldersUpToDate, folderOfTab, recordFolderContextFolder, showFolderOfActiveContext, virtualFolderAt,
} from '../services/virtual-folders-service.js';
import { isFolderContext, usedLastAmong } from '../services/folder-context-state.js';
import { searchContextLabel } from '../services/search-context-label.js';
import { checkBackgroundWork } from '../services/background-work-cards.js';
import { isCopyOfDialogSelection } from '../services/dialog-copy-service.js';
import {
    persistTabStateSnapshot, createTabOnServer, deleteTabOnServer, chooseFolderOnServer, createFolderContextOnServer,
} from '../services/tab-state-service.js';
import { cacheNotesDomForTab, restoreNotesDomForTab, cloneNotesDomForTab, clearCachedNotesDomForTab, clearActiveNotesDom } from '../services/tab-dom-cache-service.js';
import { finalizeDuplicatedTabClone, getDuplicateTabCloneOptions } from '../services/tab-duplication-service.js';
import { areScrollAnchorsEqual, computeScrollAnchor } from '../services/scroll-anchor-service.js';
import {
    blurFocusedSearchInput,
    focusSearchInputAndSelectAllText,
    resolveSearchInputDisplayQuery,
    syncSearchInputValue,
} from '../services/search-input-service.js';
import { analyzeSearchQueryInput } from '../services/search-syntax-service.js';
import { closeOpenSearchQuote } from './search-events.js';
import { buildBacklinksQuery } from '../services/backlinks-navigation-service.js';
import {
    AI_REFERENCE_VIEW_KINDS,
    captureReferenceOriginScopeForActiveTab,
    findReferenceLevelOnActivePath,
    getActiveReferenceSourceQuery,
    getActiveReferenceViewKind,
    getReferenceNavigationLabelForTab,
    getReferenceViewIconClasses,
    getReferenceViewKindForTab,
    isViewingReferenceSource,
    popActiveReferenceChain,
    popReferenceLevelsAbove,
    popReferenceNavigationEntryForActiveTab,
    pushReferenceNavigationEntry,
    replaceActiveReferenceNavigationQuery,
    showNewSearchInReferenceView,
    updateReferenceSourceIndicator,
} from '../services/reference-source-navigation-service.js';
import {
    beginReferenceViewTransition,
    cancelReferenceViewTransition,
    isReferenceViewTransitionPending,
    playReferenceViewTransition,
} from '../services/reference-view-transition-service.js';
import { shouldFocusSearchInputForViewModeTab } from '../services/view-mode-search-shortcut-service.js';
import {
    getTagBarValue,
    normalizeTagBarForNewTag,
    sanitizeTags,
    setTagBarValue,
    syncTagBar,
} from '../services/tag-bar-service.js';
import { sanitizeAndInsertExternalPaste } from '../services/html-paste-sanitizer-service.js';
import { cleanTrackingInText } from '../../url-tracking-cleaner.js';
import {
    resolveClipboardTrackingAfterPasteEvent,
    shouldCreateTopNoteForPaste,
} from '../services/clipboard-shortcut-policy-service.js';
import {
    writeRenderedNotePromiseToSystemClipboard,
    writeRenderedNoteToSystemClipboard,
} from '../services/note-clipboard-write-service.js';
import {
    addPasswordTag,
    shouldAutoTagGeneratedPasswordPaste,
} from '../services/password-clipboard-service.js';
import {
    estimateDataUrlPayloadBytes,
    getEmbedTargetImageBytes,
    getMaxClipboardImageBytes,
    getMaxPasteDataImageBytes,
    imageBlobToEmbeddedDataUrl,
} from '../services/embedded-image-service.js';
import { promptForImageFileInsertMode } from '../services/image-file-insert-choice-modal-service.js';
import { attachPickedFileToCurrentNote } from '../services/file-reference-service.js';
import { shouldCreateTopNoteForFileDrop } from '../services/file-drop-policy-service.js';
import { COMPRESSIBLE_IMAGE_RE } from '../../wizard/compressible-images.js';
import { scrollNoteIntoView } from '../services/scroll-restoration-service.js';
import { shouldDeleteSelectedNoteFromKeyboard } from '../services/note-delete-shortcut-policy-service.js';
import {
    hideSearchContextsOverlay,
    initializeSearchContextsHover,
    isSearchContextsKeyboardCreateActive,
    updateSearchContextsOverlayPlacement,
} from '../services/search-contexts-overlay-service.js';
import { CommandPalette } from '../../command-palette/command-palette-controller.js';
import { hasWebPageName, isBookmarksExportFile } from '../../wizard/bookmarks-file.js';
import { IMPORT_BOOKMARKS, promptForBookmarksDropChoice } from '../services/bookmarks-drop-choice-modal-service.js';
import { AS_FILE, promptForTextDropChoice } from '../services/text-drop-choice-modal-service.js';
import { CommandGate } from '../services/command-gate-service.js';
import { unlessDiagramEditorOpen } from '../../excalidraw/excalidraw-editor-state.js';
import { unlessNoteFullscreenOpen } from '../services/note-fullscreen-service.js';
import { captureSelectionSnapshot, getActiveEditable } from '../../editor-selection.js';
import { handleDictatedNotePaste, undoDictatedNotePasteTags } from '../services/dictation-paste-service.js';
import { TypeAhead } from '../services/type-ahead-service.js';

const helpModal = new HelpModal();

const MODIFIER_KEYS = new Set(['Control', 'Alt', 'Shift', 'Meta']);
// A drop of one file only can be a bookmarks export to import.
const LONE_FILE = 1;
const ATTACH_IMAGES = 'attach';
// The folder prefix of an import that goes into no virtual folder (the import walkthrough's top).
const IMPORT_INTO_NO_FOLDER = '';
const NAVIGATION_KEYS = new Set([
    'ArrowUp',
    'ArrowDown',
    'ArrowLeft',
    'ArrowRight',
    'Home',
    'End',
    'PageUp',
    'PageDown',
]);
const MOVE_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);
const DELETE_KEYS = new Set(['Backspace', 'Delete']);
const TAG_BAR_META_SHORTCUT_KEYS = new Set(['c', 'x', 'v', 'z', 'y', 'r', 's', 'j', 'u', 'p']);
// Tabs can be dragged to reorder only when there are at least this many.
const MIN_TABS_TO_DRAG = 2;
// Clicks this soon after a tab drag ends belong to the drag, not to the tab.
const TAB_DRAG_CLICK_SUPPRESSION_MS = 500;
const PASTE_AND_DROP_TIMEOUT_SECONDS = 120;
const COMMAND_BUSY_BANNER_SECONDS = 10;
const FAILURE_BANNER_SECONDS = 6;
const FAILURE_WITH_DETAIL_BANNER_SECONDS = 10;
const IMAGE_TOO_LARGE_BANNER_SECONDS = 6;
const IMAGE_SHRINK_FAILURE_BANNER_SECONDS = 6.5;
const FILE_REFERENCE_PASTE_BANNER_SECONDS = 7;
const TAB_LIMIT_BANNER_SECONDS = 6;
// A dropped folder with anything else.
const DROPPED_FOLDER_BANNER_SECONDS = 6;
const FOLDER_ON_ITS_OWN_TEXT = 'Drop a folder on its own.';
// Dropped text files ask Note or File; Markdown ones open the import walkthrough
// (docs/ready-to-build/files-shown-not-copied.md §5).
const DROPPED_TEXT_FILE_RE = /\.(md|markdown|txt)$/i;
const DROPPED_MARKDOWN_FILE_RE = /\.(md|markdown)$/i;
// Between dropped text files' text put into one note.
const TEXT_FILES_SEPARATOR = '\n\n';
// How often a text file's question looks whether the drop's other files are in.
const OTHER_FILES_POLL_MS = 50;
const NO_BACKLINKS_BANNER_SECONDS = 3;

const moduleState = ApplicationState.createFields('keyboard-events', {
    savedEditingSelection: null,
    noteClipboardRequiresBrowserValidation: false,
    // The plain text the last note copy or cut put on the clipboard: a paste that
    // carries only it (⇧⌘V, Paste and Match Style) is that note.
    copiedNotePlainText: '',
    tabDragCandidateId: null,
    draggedTabId: null,
    ignoreClickAfterTabDragUntil: null,
});


function isTagBarNoteShortcut(event) {
    if (!event) {
        throw new Error('isTagBarNoteShortcut called without event');
    }
    if (typeof event.key !== 'string') {
        throw new Error('isTagBarNoteShortcut requires event.key');
    }

    if (event.key === 'Tab') {
        return true;
    }

    if (!(event.metaKey || event.ctrlKey)) {
        return false;
    }

    if (event.key === 'Enter') {
        return true;
    }
    if (DELETE_KEYS.has(event.key)) {
        return true;
    }
    if (MOVE_KEYS.has(event.key)) {
        return true;
    }
    return TAG_BAR_META_SHORTCUT_KEYS.has(shortcutKeyOf(event));
}

export function initKeyboardEvents() {
        
    // While the full-screen diagram editor is open, keys, pastes and drops belong
    // to Excalidraw; while a note is shown full screen, to that view.
    const listen = (type, handler, options) => document.addEventListener(type, unlessDiagramEditorOpen(unlessNoteFullscreenOpen(handler)), options);
    listen('keydown', handleKeyDown, { capture: true });
    listen('paste', handlePasteEvent, { capture: false });
    document.addEventListener('visibilitychange', handleVisibilityChange, { capture: false });
    listen('dragover', handleDragOverEvent, { capture: false });
    listen('drop', handleDropEvent, { capture: false });
    listen('mousedown', handleTabDragCandidateMouseDown, { capture: true });
    listen('mouseup', clearTabDragCandidate, { capture: true });
    listen('dragstart', handleTabDragStart, { capture: true });
    listen('dragover', handleTabDragOver, { capture: true });
    listen('drop', handleTabDrop, { capture: true });
    document.addEventListener('dragend', handleTabDragEnd, { capture: true });
    document.addEventListener('click', handleTabDragClick, { capture: true });
    window.addEventListener('blur', handleWindowBlur, { capture: false });
    window.addEventListener('resize', handleSearchContextsViewportChange, { passive: true });
    document.addEventListener('metalist:tab-folders-changed', () => updateSearchContextsList());
    initializeSearchContextsHover();
        
    Logger.logInit('Keyboard events handler');
    
    // Initialize search contexts list on startup
    updateSearchContextsList();
    updateReferenceSourceIndicator();
}

function handleSearchContextsViewportChange() {
    updateSearchContextsOverlayPlacement();
}

function markSystemClipboardAsTrusted() {
    // A successful write resolves outstanding validation, if any.
    if (moduleState.noteClipboardRequiresBrowserValidation) {
        moduleState.noteClipboardRequiresBrowserValidation = false;
    }
    // System clipboard writes can happen repeatedly while the clipboard mode is already system.
    if (ModeContext.clipboardMode !== 'system') {
        ModeContext.setClipboardMode('system');
    }
}

// The plain text a note copy puts on the clipboard (note-clipboard-write-service.js):
// a note rendered without it writes empty text.
function copiedPlainText(copyResult) {
    if (!copyResult || typeof copyResult !== 'object') {
        throw new Error('A note copy needs the rendered note');
    }
    if (copyResult.plain_text === null || copyResult.plain_text === undefined) return '';
    if (typeof copyResult.plain_text !== 'string') throw new Error('A copied note\'s plain text must be text');
    return copyResult.plain_text;
}

function markNoteClipboardAsTrusted(copiedNotePlainText) {
    if (typeof copiedNotePlainText !== 'string') {
        throw new Error('markNoteClipboardAsTrusted requires the plain text the copy wrote');
    }
    // Copying the same note again writes the same text.
    if (moduleState.copiedNotePlainText !== copiedNotePlainText) moduleState.copiedNotePlainText = copiedNotePlainText;
    if (moduleState.noteClipboardRequiresBrowserValidation) {
        moduleState.noteClipboardRequiresBrowserValidation = false;
    }
    // Note clipboard writes can refresh clipboard contents without changing clipboard mode.
    if (ModeContext.clipboardMode !== 'note') {
        ModeContext.setClipboardMode('note');
    }
}

function invalidateTrustedNoteClipboard() {
    if (ModeContext.clipboardMode !== 'note') {
        return;
    }
    // Blur and visibilitychange may report the same departure from the app.
    if (!moduleState.noteClipboardRequiresBrowserValidation) {
        moduleState.noteClipboardRequiresBrowserValidation = true;
    }
}

function handleWindowBlur() {
    invalidateTrustedNoteClipboard();
    finishTabDrag();
}

function handleVisibilityChange() {
    if (document.visibilityState !== 'hidden') {
        return;
    }
    invalidateTrustedNoteClipboard();
}

function syncClipboardTrackingFromPasteEvent(clipboardHtml, clipboardPlainText) {
    const resolved = resolveClipboardTrackingAfterPasteEvent({
        clipboardMode: ModeContext.clipboardMode,
        noteClipboardRequiresBrowserValidation: moduleState.noteClipboardRequiresBrowserValidation,
        clipboardHtml,
        clipboardPlainText,
        copiedNotePlainText: moduleState.copiedNotePlainText,
    });
    // Paste observes browser contents, including repeated pastes of trusted data.
    if (moduleState.noteClipboardRequiresBrowserValidation !== resolved.noteClipboardRequiresBrowserValidation) {
        moduleState.noteClipboardRequiresBrowserValidation = resolved.noteClipboardRequiresBrowserValidation;
    }
    // Browser paste validation can confirm the existing clipboard mode.
    if (ModeContext.clipboardMode !== resolved.clipboardMode) {
        ModeContext.setClipboardMode(resolved.clipboardMode);
    }
    return resolved.hasNoteClipboardHtml;
}

// Find in the list (docs/ui/find.md): Cmd/Ctrl+F opens the find bar anywhere but in a
// dialog (there it stays the browser's); while it is open Cmd/Ctrl+G and Shift with it
// move through the matches, and in its text box Enter, Shift+Enter and Escape do.
// Returns whether the key was find's.
function handleFindKey(event) {
    let metaOrCtrl = false;
    if (event.metaKey) {
        metaOrCtrl = true;
    } else if (event.ctrlKey) {
        metaOrCtrl = true;
    }
    if (ModeContext.modalStack.length > 0) {
        return false;
    }
    if (event.code === 'KeyF' && metaOrCtrl && !event.altKey && !event.shiftKey) {
        event.preventDefault();
        event.stopPropagation();
        void openFindBar();
        return true;
    }
    if (!isFindBarOpen()) {
        return false;
    }
    if (event.code === 'KeyG' && metaOrCtrl && !event.altKey) {
        event.preventDefault();
        event.stopPropagation();
        void moveToMatch(event.shiftKey ? 'previous' : 'next');
        return true;
    }
    if (isFindInput(event.target) && event.key === 'Enter' && !metaOrCtrl && !event.altKey) {
        event.preventDefault();
        event.stopPropagation();
        void moveToMatch(event.shiftKey ? 'previous' : 'next');
        return true;
    }
    const isInSearchBox = event.target instanceof HTMLElement && event.target.id === 'search-input';
    if (event.key === 'Escape' && !ModeContext.isEditing && !isInSearchBox) {
        event.preventDefault();
        event.stopPropagation();
        void closeFindBar();
        return true;
    }
    return false;
}

// The key a shortcut is named by. With Shift held a letter arrives in upper
// case (Control+Shift+R is 'R'); ⌘/Control shortcuts name the lower-case letter.
function shortcutKeyOf(event) {
    if ((event.metaKey || event.ctrlKey) && /^[A-Z]$/.test(event.key)) {
        return event.key.toLowerCase();
    }
    return event.key;
}

function handleKeyDown(event) {
    if (!event) {
        throw new Error('handleKeyDown called without an event object');
    }

    // ⇧⌘V / Ctrl+Shift+V pastes as plain text: the paste that follows skips format detection.
    if (event.code === 'KeyV' && event.shiftKey && (event.metaKey || event.ctrlKey)) {
        requestPlainPaste();
    }

    // The chat's batch operations remain keyboard-operable while CommandGate locks the
    // rest of the app. Never treat their Enter/Escape/arrow keys as note commands.
    if (event.target instanceof HTMLElement && event.target.closest('#ai-chat-panel')) {
        return;
    }

    if (typeof event.key !== 'string') {
        Logger.logNoop('Ignoring keyboard event missing key', {
            eventType: event.type,
            keyValue: event.key,
        });
        return;
    }

    if (handleFindKey(event)) {
        return;
    }

    if ((event.key === 'Enter' || event.key === ' ')
        && event.target instanceof HTMLElement
        && event.target.closest('.note-source-arrow, .note-backlinks-badge, #reference-source-indicator-clear, #reference-view-chip-back, #reference-view-new-search, .meta-value-button')) {
        return;
    }

    if (event.key === 'Enter') {
        const searchInput = document.getElementById('search-input');
        const suggestions = document.getElementById('search-suggestions');
        // Open suggestions take Enter, unless the pointer is over the open list of search contexts:
        // then Enter makes a new one (handleEnterKey), and the suggestions never see it (the
        // maintainer, 2026-11-08: with suggestions open it did nothing).
        if (searchInput && suggestions && !suggestions.hidden && document.activeElement === searchInput
            && !isSearchContextsKeyboardCreateActive()) {
            Logger.logNoop('Ignoring Enter for global shortcuts while search suggestions are open');
            return;
        }
        if (document.activeElement === searchInput) {
            closeOpenSearchQuote();
        }
    }

    // Never interpret typing/navigation within inputs as global shortcuts.
    // In particular, Backspace/Delete must not delete notes while editing the search box.
    // Exception: Enter in the search input is treated like a global "create note" action.
	    if (event.key !== 'Escape') {
	        const target = event.target;
	        if (target instanceof HTMLElement) {
	            const tagName = target.tagName;
	            let isTextInput = false;
	            if (tagName === 'INPUT') {
	                isTextInput = true;
	            } else if (tagName === 'TEXTAREA') {
	                isTextInput = true;
	            }
	            const isSearchInput = tagName === 'INPUT' && target.id === 'search-input';
	            const isTagBarInput = tagName === 'INPUT' && target.classList.contains('note-tag-bar-input');
	            const isCommandPaletteShortcut = event.key === '/' && (event.metaKey || event.ctrlKey);
                const isTagBarShortcut = isTagBarInput && ModeContext.isEditing && isTagBarNoteShortcut(event);

	            if (isTextInput && !(isSearchInput && event.key === 'Enter') && !isCommandPaletteShortcut) {
	                if (!isTagBarShortcut) {
	                    return;
	                }
	            }
	        }
	    }

    if (ModeContext.isLoading) {
        // A character typed while a clicked note opens is kept for it (type-ahead-service.js).
        if (TypeAhead.keep(event)) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        Logger.logNoop('Keyboard event ignored while system is loading', {
            key: event.key,
            meta: event.metaKey || event.ctrlKey,  // shockharness: ignore[DEF003] reason="a boolean OR of two conditions, not a fallback"
            shift: event.shiftKey,
            isLoading: true
        });
        event.preventDefault();
        event.stopPropagation();
        return;
    }

    let metaOrCtrl = false;
    if (event.metaKey) {
        metaOrCtrl = true;
    } else if (event.ctrlKey) {
        metaOrCtrl = true;
    }

    const previousKeyInfo = ModeContext.keyInfo;
    // Key-repeat and modifier-only sequences can produce identical key snapshots.
    if (
        previousKeyInfo.key !== event.key
        || previousKeyInfo.meta !== metaOrCtrl
        || previousKeyInfo.shift !== Boolean(event.shiftKey)
    ) {
        ModeContext.setKeyPressed(event.key, metaOrCtrl, event.shiftKey);
    }

    Logger.logDebug('Key pressed', {
        key: event.key,
        meta: event.metaKey || event.ctrlKey,  // shockharness: ignore[DEF003] reason="a boolean OR of two conditions, not a fallback"
        shift: event.shiftKey
    }, Logger.LogCategory.EVENT);

    revealCaretForCurrentNote();

    if (ModeContext.modalStack && ModeContext.modalStack.length > 0) {
        const targetElement = event.target instanceof Element ? event.target.closest('.modal') : null;
        if (targetElement) {
            return;
        }
        if (isCopyOfDialogSelection({ shortcutKey: shortcutKeyOf(event), metaOrCtrl, selection: window.getSelection() })) {
            return;
        }

        if (event.key !== 'Escape') {
            Logger.logNoop('Keyboard event ignored while a modal is open', {
                key: event.key,
                modalStack: ModeContext.modalStack.slice()
            });
            event.preventDefault();
            event.stopPropagation();
            return;
        }
    }

    if (ModeContext.isEditing) {
                
        const isModifierKey = MODIFIER_KEYS.has(event.key);
        const isNavigationKey = NAVIGATION_KEYS.has(event.key);
        const isFunctionKey = event.key.startsWith('F') && event.key.length > 1; 

        if (!isModifierKey && !isNavigationKey && !isFunctionKey && 
                !event.ctrlKey && !event.metaKey && event.key !== 'Escape') {

            Logger.logDebug('Detected content-changing keypress', {
                key: event.key,
                noteId: ModeContext.currentNoteId
            }, Logger.LogCategory.EVENT);

            if (!ModeContext.isDirty) {
                ModeContext.setDirty(true);
                Logger.logDebug('Content marked as dirty due to typing', {
                    key: event.key,
                    noteId: ModeContext.currentNoteId
                }, Logger.LogCategory.STATE);
            }
        }
    }
    
	    const isMoveKey = MOVE_KEYS.has(event.key);
    const isSelectedDeleteShortcut = shouldDeleteSelectedNoteFromKeyboard({
        key: event.key,
        metaKey: Boolean(event.metaKey),
        ctrlKey: Boolean(event.ctrlKey),
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId,
    });

    // Check if we're disconnected from server for operations that need it
	    if (!ModeContext.isConnected) {
        let needsServer = false;
        if (event.key === 'Enter' && (metaOrCtrl || !ModeContext.isEditing)) {
            needsServer = true;
        } else if (isSelectedDeleteShortcut) {
            needsServer = true;
	        } else if (isMoveKey && metaOrCtrl) {
	            needsServer = true;
        } else if (shortcutKeyOf(event) === 'v' && metaOrCtrl) {
            needsServer = true;
        } else if (shortcutKeyOf(event) === 'u' && metaOrCtrl) {
            needsServer = true;
        } else if (shortcutKeyOf(event) === 's' && metaOrCtrl) {
            needsServer = true;
        } else if (shortcutKeyOf(event) === 'c' && metaOrCtrl) {
            needsServer = true;
        } else if ((shortcutKeyOf(event) === 'z' || shortcutKeyOf(event) === 'y') && metaOrCtrl) {
            needsServer = true;
        }
        
        if (needsServer) {
            Logger.logNoop('Keyboard shortcut ignored while disconnected from server', {
                key: event.key,
                meta: event.metaKey || event.ctrlKey,  // shockharness: ignore[DEF003] reason="a boolean OR of two conditions, not a fallback"
                isConnected: false
            });
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        // Allow ESC and search while disconnected.
    }

    switch (shortcutKeyOf(event)) {
        case 'Tab':
            if (ModeContext.isEditing) {
                handleToggleTagBarFocusShortcut(event);
            } else {
                handleViewModeSearchFocusShortcut(event);
            }
            break;
        case 'Escape':
            handleEscapeKey();
            break;
        case 'Enter':
            if ((event.metaKey || event.ctrlKey) && event.shiftKey) {
                handleCreateChildNoteShortcut(event);
            } else if (event.metaKey || event.ctrlKey) {
                handleCreateNoteShortcut(event);
            } else {
                handleEnterKey(event);
            }
            break;
        case 'Backspace':
        case 'Delete':
            if (isSelectedDeleteShortcut) {
                handleDeleteNoteShortcut(event);
            }
            break;
        case '/':
            if (event.metaKey || event.ctrlKey) {
                event.preventDefault();
                event.stopPropagation();
                void CommandPalette.toggle();
            }
            break;
	        case 'ArrowUp':
	            if (event.metaKey || event.ctrlKey) {
                    if (event.shiftKey) {
                        handleMoveNoteToTopShortcut(event);
                    } else {
	                    handleMoveNoteUpShortcut(event);
                    }
	            }
	            break;
	        case 'ArrowDown':
	            if (event.metaKey || event.ctrlKey) {
                    if (event.shiftKey) {
                        handleMoveNoteToBottomShortcut(event);
                    } else {
	                    handleMoveNoteDownShortcut(event);
                    }
	            }
	            break;
	        case 'ArrowLeft':
	            if (event.metaKey || event.ctrlKey) {
	                handleOutdentNoteShortcut(event);
	            }
	            break;
	        case 'ArrowRight':
	            if (event.metaKey || event.ctrlKey) {
	                handleIndentNoteShortcut(event);
	            }
	            break;
        // ⌘V / ⇧⌘V: the browser pastes, and handlePasteEvent decides from what
        // was pasted. Only MetaList's note marker in the pasted HTML pastes the
        // copied note; another app's ⌘V (a dictation app typing words) is text.
        case 'z':
            if (event.metaKey || event.ctrlKey) {
                if (event.shiftKey) {
                    handleRedoShortcut(event);
                } else {
                    handleUndoShortcut(event);
                }
            }
            break;
        case 'c':
            if (event.metaKey || event.ctrlKey) {
                // Not awaited: it decides and prevents the default before its first await,
                // and the copy itself runs under the CommandGate.
                void handleCopyNoteShortcut(event);
            }
            break;
        case 'r':
            if (event.metaKey || event.ctrlKey) {
                handleRetiredReferenceShortcut(event);
            }
            break;
        case 's':
            if (event.metaKey || event.ctrlKey) {
                void handleSplitNoteShortcut(event);
            }
            break;
        case 'u':
            if (event.metaKey || event.ctrlKey) {
                void handleUnformatNoteShortcut(event);
            }
            break;
        case 'x':
            if (event.metaKey || event.ctrlKey) {
                void handleCutNoteShortcut(event);
            }
            break;
        case 'y':
            if (event.metaKey || event.ctrlKey) {
                handleRedoShortcut(event);
            }
            break;
        case '?':
            if (!event.metaKey && !event.ctrlKey) {
                handleHelpModalShortcut(event);
            }
            break;
        default:
            break;
                
    }
}

function handleViewModeSearchFocusShortcut(event) {
    if (!event) {
        throw new Error('handleViewModeSearchFocusShortcut called without an event object');
    }

    const modalStack = Array.isArray(ModeContext.modalStack) ? ModeContext.modalStack : [];
    const shouldFocusSearch = shouldFocusSearchInputForViewModeTab({
        key: event.key,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        metaKey: event.metaKey,
        ctrlKey: event.ctrlKey,
        isEditing: ModeContext.isEditing,
        isSearching: ModeContext.isSearching,
        isLoading: ModeContext.isLoading,
        modalStack,
    });

    if (!shouldFocusSearch) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    // In a reference view the input is behind the chip: bring it out, as the magnifier does.
    if (isViewingReferenceSource()) {
        showNewSearchInReferenceView();
    }
    void actionEnterSearchMode();
    const didFocus = focusSearchInputAndSelectAllText();
    Logger.logDebug('Search input focused via view-mode Tab shortcut', {
        didFocus,
    }, Logger.LogCategory.EVENT);
}

function handleToggleTagBarFocusShortcut(event) {
    if (!event) {
        throw new Error('handleToggleTagBarFocusShortcut called without an event object');
    }

    if (!ModeContext.isEditing || !ModeContext.currentNoteId) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    const currentNoteId = ModeContext.currentNoteId;
    const noteElement = DOMUtils.getNoteById(currentNoteId);

    const activeElement = document.activeElement;
    const activeIsTagInput = activeElement && activeElement.classList
        ? activeElement.classList.contains('note-tag-bar-input')
        : false;

	    if (activeIsTagInput) {
	        const tagInput = noteElement.querySelector('.note-tag-bar-input');
	        if (!tagInput) {
	            throw new Error('Expected tag input to exist when toggling focus back to content');
	        }
	
	        const rawTags = tagInput.value;
	        if (typeof rawTags !== 'string') {
	            throw new Error('Tag input value must be string');
	        }
	        const sanitized = sanitizeTags(rawTags);
	        setTagBarValue(noteElement, sanitized);

        const contentElement = DOMUtils.getNoteContent(noteElement);
        if (!contentElement) {
            throw new Error('Note missing content element when restoring focus');
        }

        const savedSelection = moduleState.savedEditingSelection;
        if (savedSelection !== null) {
            moduleState.savedEditingSelection = null;
        }
        contentElement.focus();

        if (savedSelection !== null && savedSelection.noteId === currentNoteId) {
            const range = savedSelection.range;
            const startOk = range.startContainer && contentElement.contains(range.startContainer);
            const endOk = range.endContainer && contentElement.contains(range.endContainer);
            if (startOk && endOk) {
                const selection = window.getSelection();
                if (!selection) {
                    throw new Error('No selection available when restoring editor range');
                }
                selection.removeAllRanges();
                selection.addRange(range);
                return;
            }
            if (Number.isInteger(savedSelection.cursorOffset)) {
                DOMUtils.focusNote(noteElement, savedSelection.cursorOffset);
                return;
            }
        }

        DOMUtils.focusNoteEdge(noteElement, 'end');
        return;
    }

    // A new transfer expires any range left by clicking back into the editor.
    if (moduleState.savedEditingSelection !== null) {
        moduleState.savedEditingSelection = null;
    }
    const selection = window.getSelection();
    if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        const contentElement = DOMUtils.getNoteContent(noteElement);
        if (contentElement && range && range.commonAncestorContainer && contentElement.contains(range.commonAncestorContainer)) {
            let cursorOffset = null;
            const anchorNode = selection.anchorNode;
            if (anchorNode && contentElement.contains(anchorNode)) {
                cursorOffset = DOMUtils.getCursorOffset(noteElement);
            }
            moduleState.savedEditingSelection = {
                noteId: currentNoteId, range: range.cloneRange(), cursorOffset,
            };
        }
    }

    syncTagBar(noteElement);
    const tagInput = noteElement.querySelector('.note-tag-bar-input');
    if (!tagInput) {
        throw new Error('Tag input missing after syncTagBar');
    }

    normalizeTagBarForNewTag(noteElement, tagInput);

    tagInput.focus();
    const end = tagInput.value.length;
    tagInput.setSelectionRange(end, end);
}

function revealCaretForCurrentNote() {
    // A click shows the caret; a note selected without one (a pasted note, a robot press) shows it on the first key.
    if (!ModeContext.isEditing || !ModeContext.isCaretHidden) {
        return;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (!currentNoteId) {
        return;
    }

    const noteElement = DOMUtils.getNoteById(currentNoteId);
    DOMUtils.revealCaret(noteElement);
    ModeContext.markCaretVisible();
}

function handleEscapeKey() {
    if (ModeContext.isSearching === undefined) {
        throw new Error('ModeContext missing isSearching property in handleEscapeKey');
    }

    const didHideSearchContexts = hideSearchContextsOverlay();

    if (!didHideSearchContexts && !ModeContext.isEditing && isViewingReferenceSource()) {
        void CommandGate.run('keyboard.escape.reference', async () => {
            await navigateBackFromReferenceContext();
        });
        return;
    }

    if (blurFocusedSearchInput()) {
        if (ModeContext.isSearching) {
            actionExitSearchMode();
        }
        Logger.logDebug('Search input blurred via Escape key', {}, Logger.LogCategory.EVENT);
        return;
    }

    if (didHideSearchContexts) {
        Logger.logDebug('Search contexts hidden via Escape key', {}, Logger.LogCategory.EVENT);
        return;
    }
        
    if (ModeContext.isSearching) {
        ModeContext.setSearching(false);
        ModeContext.validate();
        Logger.logDebug('Search cancelled via Escape key', {}, Logger.LogCategory.EVENT);
    }
	else if (ModeContext.isEditing) {
	    void CommandGate.run('keyboard.escape.deselect', async () => {
	        await actionDeselectNote();
	    });
	            
		Logger.logDebug('Editing cancelled via Escape key', {
			previousNoteId: ModeContext.currentNoteId 
		}, Logger.LogCategory.EVENT);
	}
    else {
                
        Logger.logNoop('Escape key pressed but had no effect', {
            isSearching: ModeContext.isSearching,
            isEditing: ModeContext.isEditing
        });
    }
}

function handleEnterKey(event) {
    if (!event) {
        throw new Error('handleEnterKey called without an event object');
    }
        
    if (ModeContext.isEditing === undefined) {
        throw new Error('ModeContext missing isEditing property in handleEnterKey');
    }

    Logger.logDebug('Enter key pressed', {
        inEditor: ModeContext.isEditing,
        noteId: ModeContext.currentNoteId
    });

    if (ModeContext.isEditing) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    if (isSearchContextsKeyboardCreateActive()) {
        void CommandGate.run('keyboard.enter.blank_search_context', async () => {
            await createBlankSearchContextFromHover();
        });
        return;
    }

	if (ModeContext.isSearching) {
		actionExitSearchMode();
	}

	void CommandGate.run('keyboard.enter.create', async () => {
		await createNote();
	});
}

function handleCreateNoteShortcut(event) {
    if (!event) {
        throw new Error('handleCreateNoteShortcut called without an event object');
    }

    Logger.logDebug('Create note shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    event.preventDefault();

	if (ModeContext.isSearching) {
		actionExitSearchMode();
	}

	void CommandGate.run('keyboard.create_note', async () => {
		await createNote();
	});
}

function handleCreateChildNoteShortcut(event) {
    if (!event) {
        throw new Error('handleCreateChildNoteShortcut called without an event object');
    }

    Logger.logDebug('Create child note shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    event.preventDefault();

	if (ModeContext.isSearching) {
		actionExitSearchMode();
	}

	void CommandGate.run('keyboard.create_child', async () => {
		await createChildNote();
	});
}

function handleDeleteNoteShortcut(event) {
    if (!event) {
        throw new Error('handleDeleteNoteShortcut called without an event object');
    }
        
    const noteId = ModeContext.currentNoteId;

    Logger.logDebug('Delete note shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: noteId
    }, Logger.LogCategory.EVENT);

    event.preventDefault();

	if (noteId) {
	    void deleteEditedNoteAskingIfReferenced(noteId, 'keyboard.delete');
	} else {
                
        Logger.logNoop('Delete shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null
        });
    }
}

function handleMoveNoteUpShortcut(event) {
    if (!event) {
        throw new Error('handleMoveNoteUpShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Move up shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null
        });
        return;
    }

    Logger.logDebug('Move note up shortcut triggered', {
        noteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

	void CommandGate.run('keyboard.move_up', async () => {
		await moveNoteUp(noteId);
	});
}

function handleMoveNoteToTopShortcut(event) {
    if (!event) {
        throw new Error('handleMoveNoteToTopShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Move to top shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null,
        });
        return;
    }

    Logger.logDebug('Move note to top shortcut triggered', {
        noteId: ModeContext.currentNoteId,
        searchQuery: ModeContext.searchQuery,
    }, Logger.LogCategory.EVENT);

    void CommandGate.run('keyboard.move_to_top', async () => {
        await moveNoteToTop(noteId);
    });
}

function handleMoveNoteToBottomShortcut(event) {
    if (!event) {
        throw new Error('handleMoveNoteToBottomShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Move to bottom shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null,
        });
        return;
    }

    void CommandGate.run('keyboard.move_to_bottom', async () => {
        await moveNoteToBottom(noteId);
    });
}

function handleMoveNoteDownShortcut(event) {
    if (!event) {
        throw new Error('handleMoveNoteDownShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Move down shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null
        });
        return;
    }

	Logger.logDebug('Move note down shortcut triggered', {
		noteId: ModeContext.currentNoteId
	}, Logger.LogCategory.EVENT);

	void CommandGate.run('keyboard.move_down', async () => {
		await moveNoteDown(noteId);
	});
}

function handleIndentNoteShortcut(event) {
    if (!event) {
        throw new Error('handleIndentNoteShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Indent shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null
        });
        return;
    }

    Logger.logDebug('Indent note shortcut triggered', {
        noteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

	void CommandGate.run('keyboard.indent', async () => {
		await indentNote(noteId);
	});
}

function handleOutdentNoteShortcut(event) {
    if (!event) {
        throw new Error('handleOutdentNoteShortcut called without an event object');
    }

    event.preventDefault();
    event.stopPropagation();

    const noteId = ModeContext.currentNoteId;
    if (!noteId) {
        Logger.logNoop('Outdent shortcut pressed but no note is selected', {
            isEditing: ModeContext.isEditing,
            currentNoteId: null
        });
        return;
    }

    Logger.logDebug('Outdent note shortcut triggered', {
        noteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

	void CommandGate.run('keyboard.outdent', async () => {
		await outdentNote(noteId);
	});
}

function handleUndoShortcut(event) {
    if (!event) {
        throw new Error('handleUndoShortcut called without an event object');
    }

    // Right after a paste that added a format tag, undo also removes the tag; the
    // editor's own undo then removes the pasted text.
    undoDetectedFormatPasteTag();

    // Right after a dictated paste that added tags, undo also removes the tags.
    if (undoDictatedNotePasteTags(event)) {
        event.stopPropagation();
        return;
    }

    if (!shouldUseApplicationHistory({
        isEditing: ModeContext.isEditing,
        isDirty: ModeContext.isDirty,
        editSessionHasEdits: ModeContext.editSessionHasEdits,
    })) {
        Logger.logDebug('Undo shortcut left to the active note editor', {
            isEditing: ModeContext.isEditing,
            currentNoteId: ModeContext.currentNoteId,
            isDirty: ModeContext.isDirty,
            editSessionHasEdits: ModeContext.editSessionHasEdits
        }, Logger.LogCategory.EVENT);
        return;
    }

    Logger.logDebug('Undo shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    event.preventDefault();

    event.stopPropagation();

	void CommandGate.run('keyboard.undo', async () => {
		await actionUndo();
	});
}

function handleRedoShortcut(event) {
    if (!event) {
        throw new Error('handleRedoShortcut called without an event object');
    }

    if (!shouldUseApplicationHistory({
        isEditing: ModeContext.isEditing,
        isDirty: ModeContext.isDirty,
        editSessionHasEdits: ModeContext.editSessionHasEdits,
    })) {
        if (shouldExecuteEditorRedo({ isEditing: ModeContext.isEditing, key: event.key })) {
            event.preventDefault();
            event.stopPropagation();
            const didRedo = executeEditorRedo(document);
            Logger.logDebug('Redo shortcut executed in the active note editor', {
                currentNoteId: ModeContext.currentNoteId,
                didRedo,
            }, Logger.LogCategory.EVENT);
            return;
        }
        Logger.logDebug('Redo shortcut left to the active note editor', {
            isEditing: ModeContext.isEditing,
            currentNoteId: ModeContext.currentNoteId,
            isDirty: ModeContext.isDirty,
            editSessionHasEdits: ModeContext.editSessionHasEdits,
        }, Logger.LogCategory.EVENT);
        return;
    }

    Logger.logDebug('Redo shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    event.preventDefault();

    event.stopPropagation();

	void CommandGate.run('keyboard.redo', async () => {
		await actionRedo();
	});
}

async function handleCopyNoteShortcut(event) {
    if (!event) {
        throw new Error('handleCopyNoteShortcut called without an event object');
    }

    Logger.logDebug('Copy note shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    if (!ModeContext.isEditing) {
        Logger.logNoop('Copy shortcut pressed but not in editing mode', {
            isEditing: false
        });
        return;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (!currentNoteId) {
        Logger.logNoop('Copy shortcut pressed but no note is selected', {
            isEditing: true,
            currentNoteId: null
        });
        return;
    }

    const activeElement = document.activeElement;
    const activeElementIsTextInput = activeElement
        && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
    if (activeElementIsTextInput) {
        const selectionStart = activeElement.selectionStart;
        const selectionEnd = activeElement.selectionEnd;
        if (typeof selectionStart === 'number' && typeof selectionEnd === 'number' && selectionEnd > selectionStart) {
            markSystemClipboardAsTrusted();
            return;
        }
    }

    const selection = window.getSelection();
    if (selection && !selection.isCollapsed && document.activeElement.isContentEditable) {

        Logger.logDebug('Text selection detected, using system clipboard for text copy', {}, Logger.LogCategory.EVENT);

        // Set clipboard mode to system and allow default browser behavior
        markSystemClipboardAsTrusted();
        
        return; // Let browser handle text copy
    }

    // No text selected - do note copy
    event.preventDefault();

    const copyResultPromise = CommandGate.run('keyboard.copy_note', async () => {
        return await actionCopyNote();
    });
    const clipboardResult = await writeRenderedNotePromiseToSystemClipboard({
        renderedNotePromise: copyResultPromise,
        logger: Logger,
    });
    const copyResult = clipboardResult.renderedNote;
    if (copyResult === null) {
        return;
    }
    markNoteClipboardAsTrusted(copiedPlainText(copyResult));

    Logger.logDebug('Note copied to server clipboard', {
        noteId: ModeContext.currentNoteId
    }, Logger.LogCategory.EVENT);

    if (!copyResult?.html && !copyResult?.plain_text) {
        Logger.logDebug('Copy endpoint returned no rendered content', {}, Logger.LogCategory.EVENT);
        return;
    }

    if (!clipboardResult.didWrite) {
        Logger.logDebug('Unable to write rendered note content to system clipboard', {}, Logger.LogCategory.EVENT);
    }
}

function insertPlainTextAtCurrentSelection(text) {
    if (typeof text !== 'string') {
        throw new Error('insertPlainTextAtCurrentSelection requires text string');
    }

    const inserted = document.execCommand('insertText', false, text);
    if (inserted) {
        return;
    }

    const selection = window.getSelection();
    if (!selection) {
        throw new Error('Selection API unavailable while inserting text');
    }
    if (selection.rangeCount === 0) {
        throw new Error('Selection range missing while inserting text');
    }

    const range = selection.getRangeAt(0);
    range.deleteContents();
    const textNode = document.createTextNode(text);
    range.insertNode(textNode);
    range.setStartAfter(textNode);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
}

// ⌘R makes nothing (a reference is made by typing `[[`), and it is not the
// browser's reload either: a press from habit leaves MetaList as it is.
function handleRetiredReferenceShortcut(event) {
    event.preventDefault();
    event.stopPropagation();
}

async function handleSplitNoteShortcut(event) {
    if (!event) {
        throw new Error('handleSplitNoteShortcut called without an event object');
    }

    if (!ModeContext.isEditing) {
        return;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (typeof currentNoteId !== 'string' || currentNoteId.length === 0) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    await CommandGate.run('keyboard.split_note', async () => {
        await splitCurrentNoteFromSelection();
    });
}

async function handleUnformatNoteShortcut(event) {
    if (!event) {
        throw new Error('handleUnformatNoteShortcut called without an event object');
    }

    if (!ModeContext.isEditing) {
        return;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (typeof currentNoteId !== 'string' || currentNoteId.length === 0) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    await CommandGate.run('keyboard.unformat_note', async () => {
        await unformatCurrentNoteContent(null);
    });
}

async function handleCutNoteShortcut(event) {
    if (!event) {
        throw new Error('handleCutNoteShortcut called without an event object');
    }

    Logger.logDebug('Cut note shortcut triggered', {
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId,
    }, Logger.LogCategory.EVENT);

    if (!ModeContext.isEditing) {
        return;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (!currentNoteId) {
        return;
    }

    const activeElement = document.activeElement;
    const isTextInput = activeElement
        && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
    if (isTextInput) {
        const selectionStart = activeElement.selectionStart;
        const selectionEnd = activeElement.selectionEnd;
        if (typeof selectionStart === 'number' && typeof selectionEnd === 'number' && selectionEnd > selectionStart) {
            markSystemClipboardAsTrusted();
            return;
        }
    }

    const selection = window.getSelection();
    if (selection && !selection.isCollapsed && document.activeElement && document.activeElement.isContentEditable) {
        markSystemClipboardAsTrusted();
        return;
    }

    if (!ModeContext.isConnected) {
        Logger.logNoop('Cut note shortcut ignored while disconnected from server', {
            isConnected: false,
        });
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    // Other notes referencing it: asked first; the dialog leaves edit mode.
    const decision = await confirmRemovingReferencedNote(currentNoteId, 'cut');
    if (decision === null || decision === 'cancelled') {
        return;
    }
    let cutPlainText = '';
    const cutResult = await CommandGate.run('keyboard.cut_note', async () => {
        const copyResult = await actionCopyNoteById(currentNoteId);
        cutPlainText = copiedPlainText(copyResult);
        const renderedHtml = copyResult?.html;
        const renderedPlainText = copyResult?.plain_text;

        if (renderedHtml || renderedPlainText) {
            await writeRenderedNoteToSystemClipboard({
                renderedHtml,
                renderedPlainText,
                logger: Logger,
            });
        }

        if (decision === 'unreferenced') {
            await deleteNote(currentNoteId);
        } else {
            await deleteNoteOutsideEdit(currentNoteId);
        }
    });
    if (cutResult === null) {
        return;
    }
    markNoteClipboardAsTrusted(cutPlainText);
}


function handleHelpModalShortcut(event) {
    if (!event) {
        throw new Error('handleHelpModalShortcut called without an event object');
    }

    if (ModeContext.isEditing || ModeContext.isSearching || ModeContext.isLoading) {
        Logger.logNoop('Help modal shortcut ignored: not in idle state', {
            isEditing: ModeContext.isEditing,
            isSearching: ModeContext.isSearching,
            isLoading: ModeContext.isLoading
        });
        return;
    }

    if (ModeContext.modalStack && ModeContext.modalStack.length > 0) {
        Logger.logNoop('Help modal shortcut ignored: another modal already open', {
            stackDepth: ModeContext.modalStack.length
        });
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    helpModal.open();
    Logger.logDebug('Help modal opened via keyboard shortcut', {}, Logger.LogCategory.EVENT);
}

function isImageFile(candidate) {
    if (!(candidate instanceof File)) {
        return false;
    }
    return typeof candidate.type === 'string' && candidate.type.toLowerCase().startsWith('image/');
}

function getFilesFromTransfer(transferData) {
    if (!transferData) {
        throw new Error('getFilesFromTransfer expects transferData');
    }

    const foundFiles = [];
    const seenKeys = new Set();

    const addFileCandidate = (candidate) => {
        if (!(candidate instanceof File)) {
            return;
        }
        const dedupeKey = `${candidate.name}|${candidate.size}|${candidate.type}|${candidate.lastModified}`;
        if (seenKeys.has(dedupeKey)) {
            return;
        }
        seenKeys.add(dedupeKey);
        foundFiles.push(candidate);
    };

    if (transferData.items && transferData.items.length > 0) {
        let i = 0;
        while (i < transferData.items.length) {
            const item = transferData.items[i];
            if (item && item.kind === 'file') {
                const file = item.getAsFile();
                addFileCandidate(file);
            }
            i += 1;
        }
    }

    if (transferData.files && transferData.files.length > 0) {
        let i = 0;
        while (i < transferData.files.length) {
            const file = transferData.files[i];
            addFileCandidate(file);
            i += 1;
        }
    }

    return foundFiles;
}

function getImageFilesFromTransfer(transferData) {
    const foundFiles = getFilesFromTransfer(transferData).filter((file) => isImageFile(file));
    if (foundFiles.length === 0) {
        return foundFiles;
    }

    foundFiles.sort((left, right) => right.size - left.size);
    return [foundFiles[0]];
}

function transferHasFiles(transferData) {
    if (!transferData) {
        return false;
    }

    if (transferData.items && transferData.items.length > 0) {
        let i = 0;
        while (i < transferData.items.length) {
            const item = transferData.items[i];
            if (item && item.kind === 'file') {
                return true;
            }
            i += 1;
        }
    }

    if (transferData.files && transferData.files.length > 0) {
        return true;
    }

    return false;
}

function formatKiB(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) {
        throw new Error(`formatKiB invalid bytes: ${bytes}`);
    }
    return `${(bytes / KIB).toFixed(1)} KiB`;
}

function formatMiB(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) {
        throw new Error(`formatMiB invalid bytes: ${bytes}`);
    }
    return `${(bytes / MIB).toFixed(1)} MiB`;
}

function showImageTooLargeForEmbedError(fileName) {
    const targetBytes = getEmbedTargetImageBytes();
    const maxBytes = getMaxPasteDataImageBytes();
    const label = typeof fileName === 'string' && fileName.length > 0
        ? fileName
        : 'clipboard image';
    ErrorHandler.showErrorBanner(
        `Could not shrink ${label} enough. Target ${formatKiB(targetBytes)}, hard max ${formatMiB(maxBytes)}.`,
        'error',
        IMAGE_SHRINK_FAILURE_BANNER_SECONDS * MS_PER_SECOND,
        { closable: true },
    );
}

function buildEmbeddedImageHtmlFromDataUrls(dataUrls) {
    if (!Array.isArray(dataUrls)) {
        throw new Error('buildEmbeddedImageHtmlFromDataUrls expects array');
    }
    if (dataUrls.length === 0) {
        return '';
    }

    let html = '';
    let i = 0;
    while (i < dataUrls.length) {
        const dataUrl = dataUrls[i];
        if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) {
            throw new Error(`Invalid data URL at index ${i}`);
        }

        const imageIndex = i + 1;
        html += `<img src="${dataUrl}" alt="pasted-image-${imageIndex}" style="max-width: 100%; width: auto; height: auto;" />`;
        if (imageIndex < dataUrls.length) {
            html += '<br />';
        }
        i += 1;
    }
    return html;
}

function clipboardHasFileUriReference(clipboardData) {
    if (!clipboardData || typeof clipboardData.getData !== 'function') {
        return false;
    }

    const uriList = clipboardData.getData('text/uri-list');
    if (typeof uriList !== 'string' || uriList.length === 0) {
        return false;
    }

    const lines = uriList.split(/\r?\n/);
    let i = 0;
    while (i < lines.length) {
        const line = lines[i].trim();
        if (line.length > 0 && !line.startsWith('#') && line.toLowerCase().startsWith('file://')) {
            return true;
        }
        i += 1;
    }
    return false;
}

function contentElementHasRenderableMedia(contentElement) {
    if (!(contentElement instanceof HTMLElement)) {
        throw new Error('contentElementHasRenderableMedia requires contentElement');
    }

    return Boolean(
        contentElement.querySelector('img,video,audio,iframe,svg,math,canvas,input,textarea,button,table,hr'),
    );
}

function isCurrentEditingNoteEmptyForPasswordAutoTag() {
    if (!ModeContext.isEditing || typeof ModeContext.currentNoteId !== 'string' || ModeContext.currentNoteId.length === 0) {
        return false;
    }

    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const contentElement = DOMUtils.getNoteContent(noteElement);
    if (!(contentElement instanceof HTMLElement)) {
        throw new Error('Current editing note content missing');
    }

    if (contentElementHasRenderableMedia(contentElement)) {
        return false;
    }

    const renderedText = typeof contentElement.textContent === 'string'
        ? contentElement.textContent.replace(/\u00A0/g, ' ').trim()
        : '';
    return renderedText.length === 0;
}

function maybeApplyPasswordTagForClipboardPaste(clipboardPlainText) {
    if (typeof clipboardPlainText !== 'string') {
        throw new Error('maybeApplyPasswordTagForClipboardPaste requires clipboardPlainText string');
    }
    if (!ModeContext.isEditing || typeof ModeContext.currentNoteId !== 'string' || ModeContext.currentNoteId.length === 0) {
        return false;
    }

    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const existingTags = getTagBarValue(noteElement);
    const shouldAutoTag = shouldAutoTagGeneratedPasswordPaste({
        clipboardPlainText,
        existingTags,
        noteIsEmpty: isCurrentEditingNoteEmptyForPasswordAutoTag(),
    });
    if (!shouldAutoTag) {
        return false;
    }

    const nextTags = addPasswordTag(existingTags);
    if (nextTags === existingTags) {
        return false;
    }

    setTagBarValue(noteElement, nextTags);
    return true;
}

function undoDetectedFormatPasteTag() {
    if (!ModeContext.isEditing || typeof ModeContext.currentNoteId !== 'string') {
        return;
    }
    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const contentElement = DOMUtils.getNoteContent(noteElement);
    if (!(document.activeElement instanceof Node) || !contentElement.contains(document.activeElement)) {
        return;
    }
    const tagsBefore = takeDetectedPasteUndo({
        noteId: ModeContext.currentNoteId,
        tags: getTagBarValue(noteElement),
        content: DOMUtils.getNoteContentHTML(noteElement),
    });
    if (tagsBefore !== null) {
        setTagBarValue(noteElement, tagsBefore);
    }
}

function textBeforeSelection(contentElement) {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
        throw new Error('Selection range missing while pasting');
    }
    const range = selection.getRangeAt(0);
    const before = document.createRange();
    before.setStart(contentElement, 0);
    before.setEnd(range.startContainer, range.startOffset);
    return before.toString();
}

// Empty apart from what the paste replaces: an empty note, or all of its text selected.
function isNoteOtherwiseEmptyForPaste(contentElement) {
    if (isCurrentEditingNoteEmptyForPasswordAutoTag()) {
        return true;
    }
    if (contentElementHasRenderableMedia(contentElement)) {
        return false;
    }
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
        return false;
    }
    const noteText = contentElement.textContent.replace(/\u00A0/g, ' ').trim();
    return noteText.length > 0 && selection.toString().replace(/\u00A0/g, ' ').trim() === noteText;
}

// Pasted text in an unambiguous format (JSON, a chess FEN, a diff, Mermaid,
// LaTeX) tags the note for it as it is pasted: the plain tag into an otherwise
// empty note, ((...)) and ((tag)) into a note with content
// (paste-format-detection-service.js). Returns whether it handled the paste.
// The editor merges consecutive typing into one undo step, and inserted text
// counts as typing; setting the selection again ends that step, so ⌘Z undoes the
// paste alone, as it does a normal paste.
function startSeparateUndoStep() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
        throw new Error('Selection range missing while pasting');
    }
    const range = selection.getRangeAt(0).cloneRange();
    selection.removeAllRanges();
    selection.addRange(range);
}

function handleFormatDetectingPaste(event, plainText) {
    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const contentElement = DOMUtils.getNoteContent(noteElement);
    if (!(document.activeElement instanceof Node) || !contentElement.contains(document.activeElement)) {
        return false;
    }
    const detected = detectClipboardFormat({
        plainText,
        html: event.clipboardData.getData('text/html'),
        vscodeEditorData: event.clipboardData.getData('vscode-editor-data'),
    });
    if (detected === null) {
        return false;
    }
    const tagsBefore = getTagBarValue(noteElement);
    const plan = planFormatPaste({
        detected,
        tags: tagsBefore,
        noteIsEmpty: isNoteOtherwiseEmptyForPaste(contentElement),
        textBeforeCaret: textBeforeSelection(contentElement),
    });
    if (plan === null) {
        return false;
    }
    event.preventDefault();
    setTagBarValue(noteElement, plan.nextTags);
    startSeparateUndoStep();
    insertPlainTextAtCurrentSelection(plan.insertText);
    markCurrentNoteDirtyFromPaste('Content marked as dirty due to a format-detected paste');
    rememberDetectedPaste({
        noteId: ModeContext.currentNoteId,
        tagsBefore,
        tagsAfter: getTagBarValue(noteElement),
        contentAfter: DOMUtils.getNoteContentHTML(noteElement),
    });
    Logger.logDebug('Paste tagged by detected format', { tag: detected.tag }, Logger.LogCategory.EVENT);
    return true;
}

// Pasted text whose format is likely but not certain (CSV-like, Markdown-like,
// code in an unnamed language) is pasted as plain text, and a card offers the
// format: "Apply as Markdown" or a few languages, and "Skip"
// (paste-format-guess-service.js, paste-format-offer-service.js). Returns
// whether it handled the paste.
function handleFormatGuessingPaste(event, plainText) {
    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const contentElement = DOMUtils.getNoteContent(noteElement);
    if (!(document.activeElement instanceof Node) || !contentElement.contains(document.activeElement)) {
        return false;
    }
    if (!isPlainClipboardHtml(event.clipboardData.getData('text/html'))) {
        return false;
    }
    const guess = guessPastedFormat(plainText);
    if (guess === null) {
        return false;
    }
    const text = normalizePastedText(plainText);
    const record = {
        noteId: ModeContext.currentNoteId,
        tagsBefore: getTagBarValue(noteElement),
        noteWasEmpty: isNoteOtherwiseEmptyForPaste(contentElement),
        textBeforeCaret: textBeforeSelection(contentElement),
        pastedText: text,
        isFormatted: false,
    };
    // Offered only where applying could happen: no format yet, not inside a wrapped region.
    if (planGuessedFormat(record, guess.options[0].tag) === null) {
        return false;
    }
    event.preventDefault();
    startSeparateUndoStep();
    insertPlainTextAtCurrentSelection(text);
    markCurrentNoteDirtyFromPaste('Content marked as dirty due to a paste with a guessed format');
    offerGuessedFormat({ record, guess });
    return true;
}

// The card for a paste just inserted as plain text (record: the note and what was pasted).
function offerGuessedFormat({ record, guess }) {
    const noteElement = DOMUtils.getNoteById(record.noteId);
    const pasted = Object.freeze({ ...record, contentAfter: DOMUtils.getNoteContentHTML(noteElement) });
    offerPasteFormat({
        noteId: pasted.noteId,
        contentElement: DOMUtils.getNoteContent(noteElement),
        kind: guess.kind,
        options: guess.options,
        pastedText: pasted.pastedText,
        onApply: (tag) => applyGuessedFormat(pasted, tag),
    });
    Logger.logDebug('Paste format offered', { kind: guess.kind, tags: guess.options.map((option) => option.tag) },
        Logger.LogCategory.EVENT);
}

// A new note made by pasting text that only looks like a format: the text goes
// in as plain text; the card is offered once the note is saved. Returns what to
// offer, or null to paste as usual.
function insertFormatGuessedPasteIntoNewNote(clipboardData) {
    if (!isPlainClipboardHtml(clipboardData.getData('text/html'))) {
        return null;
    }
    const plainText = clipboardData.getData('text/plain');
    const guess = guessPastedFormat(plainText);
    if (guess === null) {
        return null;
    }
    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const record = {
        noteId: ModeContext.currentNoteId,
        tagsBefore: getTagBarValue(noteElement),
        noteWasEmpty: true,
        textBeforeCaret: '',
        pastedText: normalizePastedText(plainText),
        isFormatted: false,
    };
    if (planGuessedFormat(record, guess.options[0].tag) === null) {
        return null;
    }
    insertPlainTextAtCurrentSelection(record.pastedText);
    return { record, guess };
}

// A paste with formatting goes in with it; when its text without the formatting
// is a format, the card offers that format once the paste is in
// (formatted-paste-format-service.js). Checked before the paste goes in, from
// the place it goes to. Returns what to offer, or null.
function planFormattedPasteOffer({ html, plainText, noteWasEmpty, textBeforeCaret }) {
    if (html === '' || isPlainClipboardHtml(html)) {
        return null;
    }
    const offer = checkFormattedPaste({ visibleText: visibleTextOfHtml(html), plainText });
    if (offer === null) {
        return null;
    }
    const record = {
        noteId: ModeContext.currentNoteId,
        tagsBefore: getTagBarValue(DOMUtils.getNoteById(ModeContext.currentNoteId)),
        noteWasEmpty,
        textBeforeCaret,
        pastedText: offer.text,
        isFormatted: true,
    };
    if (planGuessedFormat(record, offer.options[0].tag) === null) {
        return null;
    }
    return { record, guess: { kind: offer.kind, options: offer.options } };
}

// The formatted paste about to go into the edited note, if it is checked there.
function planFormattedInlinePasteOffer(html, plainText) {
    const contentElement = DOMUtils.getNoteContent(DOMUtils.getNoteById(ModeContext.currentNoteId));
    if (!(document.activeElement instanceof Node) || !contentElement.contains(document.activeElement)) {
        return null;
    }
    return planFormattedPasteOffer({
        html,
        plainText,
        noteWasEmpty: isNoteOtherwiseEmptyForPaste(contentElement),
        textBeforeCaret: textBeforeSelection(contentElement),
    });
}

function planGuessedFormat(record, tag) {
    return planFormatPaste({
        detected: { tag, text: record.pastedText },
        tags: record.tagsBefore,
        noteIsEmpty: record.noteWasEmpty,
        textBeforeCaret: record.textBeforeCaret,
    });
}

// Apply the chosen format, as a detected format is applied at the paste: the
// plain tag in an otherwise empty note; in a note with other text the paste is
// replaced by the wrapped text (the editor's own undo takes the paste back out,
// with its selection, before the wrapped text goes in). Nothing happens when
// the note changed since the paste. ⌘Z right after removes it with the paste.
function applyGuessedFormat(pasted, tag) {
    if (!ModeContext.isEditingNote(pasted.noteId)) {
        return;
    }
    const noteElement = DOMUtils.getNoteById(pasted.noteId);
    if (DOMUtils.getNoteContentHTML(noteElement) !== pasted.contentAfter || getTagBarValue(noteElement) !== pasted.tagsBefore) {
        return;
    }
    const plan = planGuessedFormat(pasted, tag);
    if (plan === null) {
        throw new Error(`A guessed format ${tag} was offered where it cannot apply`);
    }
    if (pasted.isFormatted && pasted.noteWasEmpty) {
        // The note holds only the formatted paste: its text replaces it.
        const range = document.createRange();
        range.selectNodeContents(DOMUtils.getNoteContent(noteElement));
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        insertPlainTextAtCurrentSelection(plan.insertText);
    } else if (!pasted.noteWasEmpty) {
        document.execCommand('undo');
        startSeparateUndoStep();
        insertPlainTextAtCurrentSelection(plan.insertText);
    }
    setTagBarValue(noteElement, plan.nextTags);
    markCurrentNoteDirtyFromPaste('Content marked as dirty due to an applied paste format');
    rememberDetectedPaste({
        noteId: pasted.noteId,
        tagsBefore: pasted.tagsBefore,
        tagsAfter: getTagBarValue(noteElement),
        contentAfter: DOMUtils.getNoteContentHTML(noteElement),
    });
    Logger.logDebug('Paste format applied', { tag }, Logger.LogCategory.EVENT);
}

function buildClipboardPasteEventSnapshot(html, plainText, vscodeEditorData) {
    if (typeof html !== 'string') {
        throw new Error('buildClipboardPasteEventSnapshot expects html string');
    }
    if (typeof plainText !== 'string') {
        throw new Error('buildClipboardPasteEventSnapshot expects plainText string');
    }
    if (typeof vscodeEditorData !== 'string') {
        throw new Error('buildClipboardPasteEventSnapshot expects vscodeEditorData string');
    }

    return {
        clipboardData: {
            getData(format) {
                if (format === 'text/html') {
                    return html;
                }
                if (format === 'text/plain') {
                    return plainText;
                }
                if (format === 'vscode-editor-data') {
                    return vscodeEditorData;
                }
                return '';
            },
        },
    };
}

function getSelectionRangeSnapshot() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
        return null;
    }

    const range = selection.getRangeAt(0);
    const activeEditable = getActiveEditable();
    if (activeEditable instanceof HTMLElement && !activeEditable.contains(range.startContainer)) {
        return null;
    }
    return range.cloneRange();
}

function restoreSelectionRangeSnapshot(selectionRange) {
    if (selectionRange === null) {
        return;
    }
    if (!(selectionRange instanceof Range)) {
        throw new Error('restoreSelectionRangeSnapshot expects Range or null');
    }

    const selection = window.getSelection();
    if (!selection) {
        throw new Error('Selection API unavailable while restoring selection range');
    }

    selection.removeAllRanges();
    selection.addRange(selectionRange.cloneRange());
    captureSelectionSnapshot();
}

async function resolveImageFileHandlingMode(imageFiles, source, options) {
    if (!Array.isArray(imageFiles) || imageFiles.length === 0) {
        throw new Error('resolveImageFileHandlingMode expects non-empty imageFiles');
    }
    if (source !== 'paste' && source !== 'drop') {
        throw new Error(`resolveImageFileHandlingMode invalid source: ${source}`);
    }
    if (typeof options === 'undefined') {
        options = {};
    }
    if (options === null || typeof options !== 'object') {
        throw new Error('resolveImageFileHandlingMode options must be object');
    }

    if (source === 'paste') {
        let shouldPrompt = options.forcePrompt === true;
        if (!shouldPrompt) {
            shouldPrompt = imageFiles.length > 1;
        }
        if (!shouldPrompt) {
            shouldPrompt = imageFiles.some((file) => typeof file.name === 'string' && file.name.trim().length > 0);
        }
        if (!shouldPrompt) {
            return 'embed';
        }
    }

    return await promptForImageFileInsertMode({
        imageCount: imageFiles.length,
        source,
    });
}

async function attachFilesAsReferenceTokens(files, options) {
    if (!Array.isArray(files) || files.length === 0) {
        return false;
    }
    if (options === null || typeof options !== 'object') {
        throw new Error('attachFilesAsReferenceTokens requires options object');
    }

    const createTopNote = options.createTopNote === true;
    if (!('selectionRange' in options)) {
        throw new Error('selectionRange is required (null when there is none)');
    }
    const selectionRange = options.selectionRange;
    if (selectionRange !== null && !(selectionRange instanceof Range)) {
        throw new Error('attachFilesAsReferenceTokens selectionRange must be Range or null');
    }
    // Before any upload: the new top note may not be allowed in this sort order.
    if (createTopNote && blockRootNoteCreation('top', 'attachFilesNewTopNote')) {
        return false;
    }

    let currentTargetNoteId = createTopNote ? null : ModeContext.currentNoteId;
    let createdTopNote = false;
    let insertedAnything = false;
    let shouldRestoreSelection = selectionRange instanceof Range && !createTopNote;

    let i = 0;
    while (i < files.length) {
        const file = files[i];
        if (!(file instanceof File)) {
            throw new Error(`attachFilesAsReferenceTokens file at index ${i} is not a File`);
        }

        if (shouldRestoreSelection) {
            restoreSelectionRangeSnapshot(selectionRange);
            shouldRestoreSelection = false;
        }

        await attachPickedFileToCurrentNote(file, currentTargetNoteId, {
            createAtTop: createTopNote && !createdTopNote && currentTargetNoteId === null,
        });
        insertedAnything = true;
        currentTargetNoteId = ModeContext.currentNoteId;
        if (createTopNote) {
            createdTopNote = true;
        }
        i += 1;
    }

    return insertedAnything;
}

function resolveEditingDropTarget(event) {
    if (!event) {
        throw new Error('resolveEditingDropTarget expects event');
    }
    if (!ModeContext.isEditing || !ModeContext.currentNoteId) {
        return null;
    }

    const rawTarget = event.target;
    if (!(rawTarget instanceof Element)) {
        return null;
    }

    // Anywhere on the note being edited counts, its margin too.
    const noteElement = rawTarget.closest('.note');
    if (!(noteElement instanceof HTMLElement)) {
        return null;
    }
    const noteId = noteElement.dataset.noteId;
    if (!noteId || noteId !== ModeContext.currentNoteId) {
        return null;
    }
    const noteContent = noteElement.querySelector('.note-content');
    if (!(noteContent instanceof HTMLElement) || noteContent.getAttribute('contenteditable') !== 'true') {
        return null;
    }

    return noteContent;
}

function getCurrentEditableDropTarget() {
    const activeEditable = getActiveEditable();
    if (activeEditable instanceof HTMLElement) {
        return activeEditable;
    }

    const currentNoteId = ModeContext.currentNoteId;
    if (typeof currentNoteId !== 'string' || currentNoteId.length === 0) {
        throw new Error('Current editable drop target requires current note id');
    }

    const noteElement = document.querySelector(`.note[data-note-id="${currentNoteId}"]`);
    if (!(noteElement instanceof HTMLElement)) {
        throw new Error(`Could not find current note element for drop target: ${currentNoteId}`);
    }

    const noteContent = noteElement.querySelector('.note-content');
    if (!(noteContent instanceof HTMLElement)) {
        throw new Error(`Current note is missing editable content: ${currentNoteId}`);
    }
    if (noteContent.getAttribute('contenteditable') !== 'true') {
        throw new Error(`Current note is not editable for drop target: ${currentNoteId}`);
    }

    return noteContent;
}

function focusDropTargetForInsertion(target, event) {
    if (!(target instanceof HTMLElement)) {
        throw new Error('focusDropTargetForInsertion requires HTMLElement target');
    }

    target.focus();
    const positioned = placeCaretAtDropPoint(target, event);
    if (!positioned) {
        placeCaretAtEnd(target);
    }
    captureSelectionSnapshot();
}

function focusCurrentEditableAtEnd() {
    const target = getCurrentEditableDropTarget();
    target.focus();
    placeCaretAtEnd(target);
    captureSelectionSnapshot();
    return target;
}

function placeCaretAtEnd(element) {
    if (!(element instanceof HTMLElement)) {
        throw new Error('placeCaretAtEnd expects HTMLElement');
    }

    const selection = window.getSelection();
    if (!selection) {
        throw new Error('Selection API unavailable while placing caret');
    }

    const range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
}

function placeCaretAtDropPoint(noteContent, event) {
    if (!(noteContent instanceof HTMLElement)) {
        throw new Error('placeCaretAtDropPoint expects HTMLElement noteContent');
    }
    if (!event) {
        throw new Error('placeCaretAtDropPoint expects event');
    }
    if (typeof event.clientX !== 'number' || typeof event.clientY !== 'number') {
        return false;
    }

    let range = null;
    if (typeof document.caretRangeFromPoint === 'function') {
        range = document.caretRangeFromPoint(event.clientX, event.clientY);
    } else if (typeof document.caretPositionFromPoint === 'function') {
        const position = document.caretPositionFromPoint(event.clientX, event.clientY);
        if (position && position.offsetNode) {
            const candidateRange = document.createRange();
            candidateRange.setStart(position.offsetNode, position.offset);
            candidateRange.collapse(true);
            range = candidateRange;
        }
    }

    if (!(range instanceof Range)) {
        return false;
    }
    if (!noteContent.contains(range.startContainer)) {
        return false;
    }

    const selection = window.getSelection();
    if (!selection) {
        throw new Error('Selection API unavailable while placing drop caret');
    }

    selection.removeAllRanges();
    selection.addRange(range);
    return true;
}

async function pasteClipboardImagesAsEmbeddedContent(files, selectionRange) {
    if (!Array.isArray(files) || files.length === 0) {
        return false;
    }

    let insertionSelectionRange = selectionRange;
    if (typeof insertionSelectionRange === 'undefined') {
        insertionSelectionRange = getSelectionRangeSnapshot();
    } else if (insertionSelectionRange !== null && !(insertionSelectionRange instanceof Range)) {
        throw new Error('pasteClipboardImagesAsEmbeddedContent selectionRange must be Range or null');
    }
    const dataUrls = [];

    let i = 0;
    while (i < files.length) {
        const file = files[i];
        if (!(file instanceof File)) {
            throw new Error(`Clipboard image at index ${i} is not a File`);
        }
        const maxClipboardBytes = getMaxClipboardImageBytes();
        if (file.size > maxClipboardBytes) {
            const maxMiB = (maxClipboardBytes / MIB).toFixed(1);
            ErrorHandler.showErrorBanner(
                `Image too large to process. Max allowed is ${maxMiB} MiB.`,
                'error',
                IMAGE_TOO_LARGE_BANNER_SECONDS * MS_PER_SECOND,
                { closable: true },
            );
            return false;
        }

        const dataUrl = await imageBlobToEmbeddedDataUrl(file);
        if (dataUrl === null) {
            showImageTooLargeForEmbedError(file.name);
            return false;
        }
        const embeddedPayloadBytes = estimateDataUrlPayloadBytes(dataUrl);
        if (embeddedPayloadBytes === null) {
            throw new Error('Embedded image data URL missing payload bytes');
        }
        Logger.logDebug('Clipboard image compressed for embed', {
            fileName: file.name,
            originalBytes: file.size,
            embeddedPayloadBytes,
            embedTargetBytes: getEmbedTargetImageBytes(),
            embedMaxBytes: getMaxPasteDataImageBytes(),
        }, Logger.LogCategory.EVENT);
        dataUrls.push(dataUrl);
        i += 1;
    }

    const html = buildEmbeddedImageHtmlFromDataUrls(dataUrls);
    if (html.length === 0) {
        return false;
    }

    const syntheticPasteEvent = buildClipboardPasteEventSnapshot(html, '', '');
    return await sanitizeAndInsertExternalPaste(syntheticPasteEvent, insertionSelectionRange);
}

async function embedDroppedImageFiles(imageFiles, selectionRange) {
    if (!Array.isArray(imageFiles) || imageFiles.length === 0) {
        return false;
    }

    const inserted = await pasteClipboardImagesAsEmbeddedContent(imageFiles, selectionRange);
    Logger.logDebug('Dropped image file handled', {
        imageCount: imageFiles.length,
        inserted,
        selectedImageBytes: imageFiles[0] ? imageFiles[0].size : null,
    }, Logger.LogCategory.EVENT);

    if (inserted) {
        captureSelectionSnapshot();
        if (!ModeContext.isDirty) {
            ModeContext.setDirty(true);
            Logger.logDebug('Content marked as dirty due to dropped embedded image', {
                noteId: ModeContext.currentNoteId,
            }, Logger.LogCategory.STATE);
        }
    }

    return inserted;
}

async function handleClipboardImageFiles(imageFiles, options) {
    if (!Array.isArray(imageFiles) || imageFiles.length === 0) {
        return {
            inserted: false,
            imageHandlingMode: null,
            wasBlocked: false,
        };
    }
    if (typeof options === 'undefined') {
        options = {};
    }
    if (options === null || typeof options !== 'object') {
        throw new Error('handleClipboardImageFiles options must be object');
    }

    const createTopNote = options.createTopNote === true;
    if (!('selectionRange' in options)) {
        throw new Error('handleClipboardImageFiles requires selectionRange (null when there is none)');
    }
    const selectionRange = options.selectionRange;
    if (selectionRange !== null && !(selectionRange instanceof Range)) {
        throw new Error('handleClipboardImageFiles selectionRange must be Range or null');
    }
    if (createTopNote && selectionRange !== null) {
        throw new Error('handleClipboardImageFiles cannot use selectionRange when creating a top note');
    }
    if (createTopNote && blockRootNoteCreation('top', 'pasteImagesNewTopNote')) {
        return {
            inserted: false,
            imageHandlingMode: null,
            wasBlocked: false,
        };
    }
    const imageHandlingMode = await resolveImageFileHandlingMode(imageFiles, 'paste', {
        forcePrompt: options.forcePrompt === true,
    });
    if (imageHandlingMode === null) {
        return {
            inserted: false,
            imageHandlingMode: null,
            wasBlocked: false,
        };
    }
    if (imageHandlingMode === 'attach') {
        const result = await CommandGate.run('keyboard.pasteImageFiles.attach', async () => {
            const inserted = await attachFilesAsReferenceTokens(imageFiles, {
                createTopNote,
                selectionRange,
            });
            if (
                createTopNote
                && inserted
                && ModeContext.isDirty
                && typeof ModeContext.currentNoteId === 'string'
                && ModeContext.currentNoteId.length > 0
            ) {
                await actionSaveNote(ModeContext.currentNoteId);
            }
            return inserted;
        }, {
            timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
        });
        return {
            inserted: result === true,
            imageHandlingMode,
            wasBlocked: result === null,
        };
    }

    if (createTopNote) {
        const result = await CommandGate.run('keyboard.pasteImageFiles.embedNewTopNote', async () => {
            const newNoteId = requireCreatedNoteId(await createNoteAtTop(), 'pasteImagesNewTopNote');
            focusCurrentEditableAtEnd();
            const inserted = await pasteClipboardImagesAsEmbeddedContent(imageFiles, null);
            if (inserted && !ModeContext.isDirty) {
                ModeContext.setDirty(true);
            }
            if (inserted) {
                await actionSaveNote(newNoteId);
            }
            return inserted;
        }, {
            timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
        });
        return {
            inserted: result === true,
            imageHandlingMode,
            wasBlocked: result === null,
        };
    }

    return {
        inserted: await pasteClipboardImagesAsEmbeddedContent(imageFiles, selectionRange),
        imageHandlingMode,
        wasBlocked: false,
    };
}

async function processDroppedFiles(droppedFiles, options) {
    if (!Array.isArray(droppedFiles) || droppedFiles.length === 0) {
        return false;
    }
    if (options === null || typeof options !== 'object') {
        throw new Error('processDroppedFiles requires options object');
    }

    const createTopNote = options.createTopNote === true;
    const imageHandlingMode = options.imageHandlingMode;
    if (imageHandlingMode !== 'embed' && imageHandlingMode !== 'attach') {
        throw new Error(`processDroppedFiles invalid imageHandlingMode: ${imageHandlingMode}`);
    }
    if (!('selectionRange' in options)) {
        throw new Error('selectionRange is required (null when there is none)');
    }
    const selectionRange = options.selectionRange;
    if (selectionRange !== null && !(selectionRange instanceof Range)) {
        throw new Error('processDroppedFiles selectionRange must be Range or null');
    }
    // Before any upload: the new top note may not be allowed in this sort order.
    if (createTopNote && blockRootNoteCreation('top', 'dropFilesNewTopNote')) {
        return false;
    }
    let currentTargetNoteId = createTopNote ? null : ModeContext.currentNoteId;
    let createdTopNote = false;
    let insertedAnything = false;
    let sawAttachedFile = false;
    let pendingSelectionRange = selectionRange;

    let i = 0;
    while (i < droppedFiles.length) {
        const file = droppedFiles[i];
        if (!(file instanceof File)) {
            throw new Error(`Dropped file at index ${i} is not a File`);
        }

        if (isImageFile(file)) {
            if (imageHandlingMode === 'attach') {
                if (pendingSelectionRange instanceof Range) {
                    restoreSelectionRangeSnapshot(pendingSelectionRange);
                    pendingSelectionRange = null;
                }
                sawAttachedFile = true;
                await attachPickedFileToCurrentNote(file, currentTargetNoteId, {
                    createAtTop: createTopNote && !createdTopNote && currentTargetNoteId === null,
                });
                insertedAnything = true;
                currentTargetNoteId = ModeContext.currentNoteId;
                if (createTopNote) {
                    createdTopNote = true;
                }
            } else {
                if (createTopNote && !createdTopNote && currentTargetNoteId === null) {
                    requireCreatedNoteId(await createNoteAtTop(), 'dropFilesNewTopNote');
                    focusCurrentEditableAtEnd();
                    currentTargetNoteId = ModeContext.currentNoteId;
                    createdTopNote = true;
                }

                const inserted = await embedDroppedImageFiles([file], pendingSelectionRange);
                if (inserted) {
                    insertedAnything = true;
                }
                pendingSelectionRange = null;
                currentTargetNoteId = ModeContext.currentNoteId;
            }
        } else {
            if (pendingSelectionRange instanceof Range) {
                restoreSelectionRangeSnapshot(pendingSelectionRange);
                pendingSelectionRange = null;
            }
            sawAttachedFile = true;
            await attachPickedFileToCurrentNote(file, currentTargetNoteId, {
                createAtTop: createTopNote && !createdTopNote && currentTargetNoteId === null,
            });
            insertedAnything = true;
            currentTargetNoteId = ModeContext.currentNoteId;
            if (createTopNote) {
                createdTopNote = true;
            }
        }

        i += 1;
    }

    let shouldSaveAfterDrop = false;
    if (createTopNote) {
        shouldSaveAfterDrop = true;
    }
    if (sawAttachedFile) {
        shouldSaveAfterDrop = true;
    }
    if (
        shouldSaveAfterDrop
        && ModeContext.isDirty
        && typeof ModeContext.currentNoteId === 'string'
        && ModeContext.currentNoteId.length > 0
    ) {
        await actionSaveNote(ModeContext.currentNoteId);
    }
    // A dropped file's text is read next, beside the user's work: shown as it goes.
    if (sawAttachedFile) void checkBackgroundWork();

    return insertedAnything;
}

function handleDragOverEvent(event) {
    if (!event || !event.dataTransfer) {
        return;
    }

    if (!transferHasFiles(event.dataTransfer)) {
        return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
}

function handleDropEvent(event) {
    if (!event || !event.dataTransfer) {
        return;
    }

    if (!transferHasFiles(event.dataTransfer)) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    // A folder is handed over as a file the browser can't read (uploading it failed with
    // "NetworkError when attempting to fetch resource", 2026-11-02): looked at before anything
    // is uploaded. With anything else it is refused; alone it is to go through the import
    // walkthrough (docs/ready-to-build/desktop-drops-into-folders.md).
    // On a virtual folder (or the tree's top), what is dropped goes into it.
    const intoFolder = virtualFolderAt(event.target);
    const dropped = describeDroppedItems(event.dataTransfer);
    if (dropped.folderCount > 0) {
        if (dropped.itemCount !== LONE_FILE) {
            ErrorHandler.showInfoBanner(FOLDER_ON_ITS_OWN_TEXT, DROPPED_FOLDER_BANNER_SECONDS * MS_PER_SECOND);
            return;
        }
        void openDroppedFolder(loneDroppedFolderEntry(event.dataTransfer), importFolderOf(intoFolder));
        return;
    }

    const droppedFiles = getFilesFromTransfer(event.dataTransfer);
    if (droppedFiles.length === 0) {
        return;
    }
    // Images dropped on a folder in the tree come in as an import does: its screen asks whether
    // to compress them, and the whole drop goes with them (the maintainer, 2026-11-08).
    if (intoFolder !== null && droppedFiles.some((file) => COMPRESSIBLE_IMAGE_RE.test(file.name))) {
        void CommandPalette.openImportWizardWithDroppedFiles(droppedFiles, importFolderOf(intoFolder)).catch((error) => {
            rethrowUnexpectedError(error);
            const message = error instanceof Error ? error.message : String(error);
            ErrorHandler.showErrorBanner(
                `File drop failed: ${message}`,
                'error',
                FAILURE_WITH_DETAIL_BANNER_SECONDS * MS_PER_SECOND,
                { closable: true },
            );
        });
        return;
    }
    // Dropped text files ask first: a note or a file; with a Markdown file among them, the
    // import walkthrough at its Markdown screen (docs/ready-to-build/files-shown-not-copied.md §5).
    if (droppedFiles.some(isDroppedTextFile)) {
        void dropWithTextFiles(event, droppedFiles, intoFolder).catch((error) => {
            rethrowUnexpectedError(error);
            const message = error instanceof Error ? error.message : String(error);
            ErrorHandler.showErrorBanner(
                `File drop failed: ${message}`,
                'error',
                FAILURE_WITH_DETAIL_BANNER_SECONDS * MS_PER_SECOND,
                { closable: true },
            );
        });
        return;
    }
    // A browser's bookmarks export asks first: import it (the default) or keep it as a file
    // (docs/ready-to-build/bookmark-import.md §5). Only a lone web page is read to tell.
    if (droppedFiles.length === LONE_FILE && hasWebPageName(droppedFiles[0])) {
        void dropPossibleBookmarksFile(event, droppedFiles, intoFolder).catch((error) => {
            rethrowUnexpectedError(error);
            const message = error instanceof Error ? error.message : String(error);
            ErrorHandler.showErrorBanner(
                `File drop failed: ${message}`,
                'error',
                FAILURE_WITH_DETAIL_BANNER_SECONDS * MS_PER_SECOND,
                { closable: true },
            );
        });
        return;
    }
    dropFilesThere(event, droppedFiles, intoFolder);
}

function isDroppedTextFile(file) {
    return DROPPED_TEXT_FILE_RE.test(file.name);
}

// Dropped text files (files-shown-not-copied.md §5, checks 22 to 26). Into a note being edited:
// one question, then the text (or the cards) at the drop point, then the other files. Elsewhere
// the other files come in at once, then the text files ask Note or File, or, with a Markdown
// file among them, all of them go through the walkthrough's Markdown screen.
async function dropWithTextFiles(event, droppedFiles, intoFolder) {
    const textFiles = droppedFiles.filter(isDroppedTextFile);
    const otherFiles = droppedFiles.filter((file) => !isDroppedTextFile(file));
    let editingTarget = null;
    if (intoFolder === null) editingTarget = resolveEditingDropTarget(event);
    if (editingTarget instanceof HTMLElement) {
        const choice = await promptForTextDropChoice(textFiles.map((file) => file.name));
        if (choice === null) return;
        if (choice === AS_FILE) {
            dropFilesWhereDropped(event, droppedFiles);
            return;
        }
        await insertTextFilesWhereDropped(event, textFiles);
        if (otherFiles.length > 0) dropFilesWhereDropped(event, otherFiles);
        return;
    }
    if (otherFiles.length > 0) {
        dropFilesThere(event, otherFiles, intoFolder);
        await untilNothingElseAsks();
    }
    if (textFiles.some((file) => DROPPED_MARKDOWN_FILE_RE.test(file.name))) {
        await CommandPalette.openImportWizardWithDroppedFiles(textFiles, importFolderOf(intoFolder));
        return;
    }
    const choice = await promptForTextDropChoice(textFiles.map((file) => file.name));
    if (choice === null) return;
    if (choice === AS_FILE) {
        dropFilesThere(event, textFiles, intoFolder);
        return;
    }
    await makeNotesOfTextFiles(textFiles, intoFolder);
}

// The drop's other files are coming in: their own question (pictures: embed or attach) and
// their upload go first, so no two dialogs open at once.
async function untilNothingElseAsks() {
    do {
        await new Promise((resolve) => setTimeout(resolve, OTHER_FILES_POLL_MS));
    } while (ModeContext.modalStack.length > 0 || CommandGate.isBusy());
}

// Note, dropped into a note being edited: the files' text at the drop point, one after another.
async function insertTextFilesWhereDropped(event, textFiles) {
    const texts = await Promise.all(textFiles.map((file) => file.text()));
    await CommandGate.runWhenFree('keyboard.dropTextIntoNote', async () => {
        const target = resolveEditingDropTarget(event);
        if (!(target instanceof HTMLElement)) {
            throw new Error('The note a text file was dropped into is no longer being edited');
        }
        focusDropTargetForInsertion(target, event);
        insertPlainTextAtCurrentSelection(texts.join(TEXT_FILES_SEPARATOR));
        await actionSaveNote(ModeContext.currentNoteId);
    }, {
        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
    });
}

// Note, dropped elsewhere: a note at the top for each file, holding its text, in the order
// dropped; on a tree folder, filed in it. One alone stays open to edit, as a dropped file's.
async function makeNotesOfTextFiles(textFiles, intoFolder) {
    const texts = await Promise.all(textFiles.map((file) => file.text()));
    await CommandGate.runWhenFree('keyboard.dropTextFilesAsNotes', async () => {
        if (ModeContext.isEditing) {
            await actionSaveAndExitEditingWithoutRefreshing();
        }
        if (blockRootNoteCreation('top', 'dropTextFilesAsNotes')) {
            return;
        }
        // Each goes to the top: the last made first.
        for (const text of [...texts].reverse()) {
            requireCreatedNoteId(await createNoteAtTop(), 'dropTextFileNote');
            insertPlainTextAtCurrentSelection(text);
            const noteId = ModeContext.currentNoteId;
            await actionSaveNote(noteId);
            if (intoFolder !== null || texts.length > LONE_FILE) {
                await actionSaveAndExitEditingWithoutRefreshing();
            }
            if (intoFolder !== null) {
                await fileNewNoteInFolder(noteId, intoFolder);
            }
        }
    }, {
        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
    });
}

// The folder an import walkthrough started by a drop goes into: the virtual folder it was dropped
// on (the tree's top is ''); a drop outside the tree goes into no folder.
function importFolderOf(intoFolder) {
    if (intoFolder === null) return IMPORT_INTO_NO_FOLDER;
    return intoFolder;
}

// A folder dropped alone: the import walkthrough on Any folder, its files read in the browser
// (nothing sent yet), going into the folder it was dropped on.
async function openDroppedFolder(folderEntry, intoFolder) {
    const folder = await readDroppedFolder(folderEntry);
    await CommandPalette.openImportWizardWithDroppedFolder(folder, intoFolder);
}

function dropFilesThere(event, droppedFiles, intoFolder) {
    if (intoFolder === null) {
        dropFilesWhereDropped(event, droppedFiles);
        return;
    }
    void dropFilesIntoFolder(droppedFiles, intoFolder);
}

async function dropPossibleBookmarksFile(event, droppedFiles, intoFolder) {
    const file = droppedFiles[0];
    if (await isBookmarksExportFile(file)) {
        const choice = await promptForBookmarksDropChoice(file.name);
        if (choice === null) {
            return;
        }
        if (choice === IMPORT_BOOKMARKS) {
            await CommandPalette.openImportWizardWithBookmarksFile(file, importFolderOf(intoFolder));
            return;
        }
    }
    dropFilesThere(event, droppedFiles, intoFolder);
}

// Files dropped on a virtual folder: the new note at the top a drop on the column makes, then
// in exactly that folder ('' the top: in none), left open no longer
// (docs/ready-to-build/desktop-drops-into-folders.md §1).
// Files dropped on a folder in the tree: a note each, filed in it. Images compression shrinks
// went to the walkthrough first, so any here (a GIF) come in as files, with nothing to ask.
function dropFilesIntoFolder(droppedFiles, intoFolder) {
    return CommandGate.run('keyboard.dropFilesIntoFolder', async () => {
        return await makeANoteForEachFile(droppedFiles, ATTACH_IMAGES, intoFolder);
    }, {
        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
    });
}

// Files not aimed at a note get a note each, at the top, the first file on top (the maintainer,
// 2026-11-08). With several none is left open; the first is brought into sight. A file that
// fails stops the drop, the notes made staying, and the error says which it was.
async function makeANoteForEachFile(files, imageHandlingMode, intoFolder) {
    if (ModeContext.isEditing) {
        await actionSaveAndExitEditingWithoutRefreshing();
        await refreshAfterDroppedFiles(null);
    }
    const isSeveral = files.length > LONE_FILE;
    let firstFileNoteId = null;
    for (const file of [...files].reverse()) {
        let inserted = false;
        // lint: allow-JS001 rationale="an upload can fail; the message says which file, internal errors propagate"
        try {
            inserted = await processDroppedFiles([file], { createTopNote: true, imageHandlingMode, selectionRange: null });
        } catch (error) {
            rethrowUnexpectedError(error);
            if (isSeveral) await refreshAfterDroppedFiles(null);
            throw new HttpRequestError(`${file.name}: ${error instanceof Error ? error.message : String(error)}`);
        }
        if (inserted === false) return false;
        const noteId = ModeContext.currentNoteId;
        if (isSeveral || intoFolder !== null) {
            await actionSaveAndExitEditingWithoutRefreshing();
        }
        if (intoFolder !== null) {
            await fileNewNoteInFolder(noteId, intoFolder);
        }
        firstFileNoteId = noteId;
        await virtualFoldersUpToDate();
    }
    if (isSeveral) {
        await refreshAfterDroppedFiles(firstFileNoteId);
        scrollNoteIntoView(firstFileNoteId, { align: 'nearest', jump: true });
    }
    return true;
}

// A note closed without a refresh still shows its files as their ![[tokens]]: this draws them.
async function refreshAfterDroppedFiles(visibleRootAnchorId) {
    const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
    await actionRefreshAndMaybeSelect({
        startedAt: performance.now(), context: 'keyboard.dropFiles', visibleRootAnchorId,
    });
}

// Files dropped where the drop lands: a note's text being edited, or a new note at the top.
function dropFilesWhereDropped(event, droppedFiles) {
    const target = resolveEditingDropTarget(event);
    const imageFiles = droppedFiles.filter((file) => isImageFile(file));
    const onlyImages = imageFiles.length === droppedFiles.length;
    const shouldCreateTopNote = shouldCreateTopNoteForFileDrop({
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId,
        hasEditingDropTarget: target instanceof HTMLElement,
    });
    let targetSelectionRange = null;
    if (target instanceof HTMLElement) {
        focusDropTargetForInsertion(target, event);
        targetSelectionRange = getSelectionRangeSnapshot();
        if (onlyImages) {
            const selectionRange = targetSelectionRange;
            void (async () => {
                const imageHandlingMode = await resolveImageFileHandlingMode(droppedFiles, 'drop');
                if (imageHandlingMode === null) {
                    return false;
                }
                if (imageHandlingMode === 'attach') {
                    return await CommandGate.run('keyboard.dropImageFiles.attach', async () => {
                        return await attachFilesAsReferenceTokens(droppedFiles, {
                            createTopNote: false,
                            selectionRange,
                        });
                    }, {
                        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
                    });
                }
                return await embedDroppedImageFiles(droppedFiles, selectionRange);
            })()
                .then((result) => {
                    if (result !== null) {
                        return;
                    }
                    ErrorHandler.showErrorBanner(
                        'Dropped image files did not start because another command is still running.',
                        'error',
                        COMMAND_BUSY_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                })
                .catch((error) => {
            rethrowUnexpectedError(error);
                    const message = error instanceof Error ? error.message : String(error);
                    Logger.logDebug('Dropped image file handling failed', {
                        error: message,
                        fileCount: droppedFiles.length,
                    }, Logger.LogCategory.EVENT);
                    ErrorHandler.showErrorBanner(
                        'Failed to handle dropped image files.',
                        'error',
                        FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                });
            return;
        }
    }

    void (async () => {
        let imageHandlingMode = 'embed';
        if (imageFiles.length > 0) {
            const choice = await resolveImageFileHandlingMode(imageFiles, 'drop');
            if (choice === null) {
                return false;
            }
            imageHandlingMode = choice;
        }

        return await CommandGate.run('keyboard.dropFiles', async () => {
            if (shouldCreateTopNote) {
                return await makeANoteForEachFile(droppedFiles, imageHandlingMode, null);
            }
            return await processDroppedFiles(droppedFiles, {
                createTopNote: false,
                imageHandlingMode,
                selectionRange: targetSelectionRange,
            });
        }, {
            timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
        });
    })()
        .then((result) => {
            if (result === false) {
                return;
            }
            if (result === null) {
                ErrorHandler.showErrorBanner(
                    'File drop did not start because another command is still running.',
                    'error',
                    COMMAND_BUSY_BANNER_SECONDS * MS_PER_SECOND,
                    { closable: true },
                );
                return;
            }
            Logger.logDebug('Dropped files processed', {
                fileCount: droppedFiles.length,
                createTopNote: shouldCreateTopNote,
                inserted: result,
            }, Logger.LogCategory.EVENT);
        })
        .catch((error) => {
            rethrowUnexpectedError(error);
            const message = error instanceof Error ? error.message : String(error);
            Logger.logDebug('Dropped file handling failed', {
                error: message,
                fileCount: droppedFiles.length,
                onlyImages,
            }, Logger.LogCategory.EVENT);
            if (onlyImages) {
                ErrorHandler.showErrorBanner(
                    'Failed to handle dropped image files.',
                    'error',
                    FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                    { closable: true },
                );
                return;
            }
            ErrorHandler.showErrorBanner(
                `File drop failed: ${message}`,
                'error',
                FAILURE_WITH_DETAIL_BANNER_SECONDS * MS_PER_SECOND,
                { closable: true },
            );
        });
}

function pasteEventHasNativeTextTarget(event) {
    if (!event) {
        throw new Error('pasteEventHasNativeTextTarget expects event');
    }

    const nativeTargetSelector = 'input, textarea, [contenteditable="true"], [contenteditable="plaintext-only"]';
    const eventTarget = event.target;
    if (eventTarget instanceof Element && eventTarget.closest(nativeTargetSelector)) {
        return true;
    }

    const activeElement = document.activeElement;
    return Boolean(activeElement instanceof Element && activeElement.closest(nativeTargetSelector));
}

function markCurrentNoteDirtyFromPaste(logMessage) {
    if (typeof logMessage !== 'string' || logMessage.length === 0) {
        throw new Error('markCurrentNoteDirtyFromPaste requires logMessage');
    }
    if (ModeContext.isDirty) {
        return;
    }

    ModeContext.setDirty(true);
    Logger.logDebug(logMessage, {
        noteId: ModeContext.currentNoteId,
    }, Logger.LogCategory.STATE);
}

async function pasteExternalContentIntoNewTopNote(pasteEventSnapshot, plainText, isPlainPaste) {
    if (!pasteEventSnapshot || !pasteEventSnapshot.clipboardData) {
        throw new Error('pasteExternalContentIntoNewTopNote requires clipboard data');
    }
    if (typeof plainText !== 'string') {
        throw new Error('pasteExternalContentIntoNewTopNote requires plainText string');
    }
    if (typeof isPlainPaste !== 'boolean') {
        throw new Error('pasteExternalContentIntoNewTopNote requires isPlainPaste boolean');
    }

    if (blockRootNoteCreation('top', 'pasteExternalNewTopNote')) {
        return {
            inserted: false,
            autoTaggedPasswordPaste: false,
        };
    }
    return await CommandGate.run('paste_event.external_new_top_note', async () => {
        const newNoteId = requireCreatedNoteId(await createNoteAtTop(), 'pasteExternalNewTopNote');
        focusCurrentEditableAtEnd();
        const autoTaggedPasswordPaste = maybeApplyPasswordTagForClipboardPaste(plainText);
        const isFormatChecked = !autoTaggedPasswordPaste && !isPlainPaste;
        const formatTagged = isFormatChecked && insertFormatDetectedPasteIntoNewNote(pasteEventSnapshot.clipboardData);
        let guessed = null;
        if (isFormatChecked && !formatTagged) guessed = insertFormatGuessedPasteIntoNewNote(pasteEventSnapshot.clipboardData);
        let inserted = formatTagged;
        if (guessed !== null) inserted = true;
        if (!inserted && isFormatChecked) {
            guessed = planFormattedPasteOffer({
                html: pasteEventSnapshot.clipboardData.getData('text/html'), plainText, noteWasEmpty: true, textBeforeCaret: '',
            });
        }
        if (!inserted) inserted = await sanitizeAndInsertExternalPaste(pasteEventSnapshot, null);
        if (inserted) {
            markCurrentNoteDirtyFromPaste('Content marked as dirty due to paste into new top note');
        }
        if (inserted || autoTaggedPasswordPaste) {
            await actionSaveNote(newNoteId);
        }
        if (inserted && guessed !== null && ModeContext.isEditingNote(newNoteId)) {
            offerGuessedFormat(guessed);
        }
        return {
            inserted,
            autoTaggedPasswordPaste,
        };
    }, {
        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
    });
}

// A new note made by pasting is empty: a detected format gets the plain tag.
function insertFormatDetectedPasteIntoNewNote(clipboardData) {
    const detected = detectClipboardFormat({
        plainText: clipboardData.getData('text/plain'),
        html: clipboardData.getData('text/html'),
        vscodeEditorData: clipboardData.getData('vscode-editor-data'),
    });
    if (detected === null) {
        return false;
    }
    const noteElement = DOMUtils.getNoteById(ModeContext.currentNoteId);
    const tagsBefore = getTagBarValue(noteElement);
    const plan = planFormatPaste({ detected, tags: tagsBefore, noteIsEmpty: true, textBeforeCaret: '' });
    if (plan === null) {
        return false;
    }
    setTagBarValue(noteElement, plan.nextTags);
    insertPlainTextAtCurrentSelection(plan.insertText);
    Logger.logDebug('New note from paste tagged by detected format', { tag: detected.tag }, Logger.LogCategory.EVENT);
    return true;
}

export async function pasteCopiedNoteIntoNewTopNote() {
    if (blockRootNoteCreation('top', 'pasteNoteNewTopNote')) {
        return false;
    }
    return await CommandGate.run('paste_event.note_new_top_note', async () => {
        requireCreatedNoteId(await createNoteAtTop(), 'pasteNoteNewTopNote');
        await actionPasteNoteSibling();
        return true;
    }, {
        timeoutMs: PASTE_AND_DROP_TIMEOUT_SECONDS * MS_PER_SECOND,
    });
}


function handlePasteEvent(event) {
    if (!event || !event.clipboardData) {
        Logger.logDebug('Paste event without clipboard data - allowing default behavior', {}, Logger.LogCategory.EVENT);
        return;
    }

    const isPlainPaste = consumePlainPasteRequest();
    const activeElement = document.activeElement;
    const hasEditableTarget = Boolean(activeElement && activeElement.isContentEditable);
    const hasActiveNote = (
        ModeContext.isEditing
        && typeof ModeContext.currentNoteId === 'string'
        && ModeContext.currentNoteId.length > 0
    );
    const shouldHandleInlinePaste = hasActiveNote && hasEditableTarget;
    const imageFiles = getImageFilesFromTransfer(event.clipboardData);
    const clipboardContainsFileReference = clipboardHasFileUriReference(event.clipboardData);

    // Get HTML from clipboard if available
    const html = event.clipboardData.getData('text/html');
    // Pasted URLs lose their tracking parameters (url-tracking-cleaner.js);
    // pasted HTML loses them in the sanitizer, link by link.
    const rawPlainText = event.clipboardData.getData('text/plain');
    const plainText = cleanTrackingInText(rawPlainText);
    const hasTrackedNoteClipboardHtml = syncClipboardTrackingFromPasteEvent(html, rawPlainText);
    const hasClipboardPayload = (
        imageFiles.length > 0
        || hasTrackedNoteClipboardHtml
        || html.length > 0
        || plainText.length > 0
    );
    const hasNativePasteTarget = pasteEventHasNativeTextTarget(event);
    const isModalOpen = Boolean(ModeContext.modalStack && ModeContext.modalStack.length > 0);
    const shouldCreateTopNote = shouldCreateTopNoteForPaste({
        isEditing: ModeContext.isEditing,
        currentNoteId: ModeContext.currentNoteId,
        hasNativePasteTarget,
        hasClipboardPayload,
        isModalOpen,
    });
    const autoTaggedPasswordPaste = shouldHandleInlinePaste
        ? maybeApplyPasswordTagForClipboardPaste(plainText)
        : false;
    
    Logger.logDebug('Paste event detected', {
        hasHtml: !!html,
        htmlLength: html ? html.length : 0,
        plainTextLength: plainText ? plainText.length : 0,
        imageFileCount: imageFiles.length,
        hasFileUriReference: clipboardContainsFileReference,
        isEditing: ModeContext.isEditing,
        shouldCreateTopNote,
        autoTaggedPasswordPaste,
    }, Logger.LogCategory.EVENT);

    if ((shouldHandleInlinePaste || shouldCreateTopNote) && imageFiles.length > 0) {
        event.preventDefault();
        const selectionRange = shouldCreateTopNote ? null : getSelectionRangeSnapshot();
        void handleClipboardImageFiles(imageFiles, {
            createTopNote: shouldCreateTopNote,
            selectionRange,
            forcePrompt: clipboardContainsFileReference,
        })
            .then((result) => {
                const inserted = result.inserted;
                Logger.logDebug('Clipboard image paste handled', {
                    imageCount: imageFiles.length,
                    inserted,
                    imageHandlingMode: result.imageHandlingMode,
                    createdTopNote: shouldCreateTopNote,
                    wasBlocked: result.wasBlocked,
                    selectedImageBytes: imageFiles[0] ? imageFiles[0].size : null,
                }, Logger.LogCategory.EVENT);

                if (result.wasBlocked) {
                    ErrorHandler.showErrorBanner(
                        'Pasted image file did not start because another command is still running.',
                        'error',
                        COMMAND_BUSY_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                    return;
                }

                if (inserted && result.imageHandlingMode === 'embed' && !shouldCreateTopNote) {
                    markCurrentNoteDirtyFromPaste('Content marked as dirty due to pasted embedded image');
                }
            })
            .catch((error) => {
            rethrowUnexpectedError(error);
                const message = error instanceof Error ? error.message : String(error);
                Logger.logDebug('Clipboard image paste failed', {
                    error: message,
                }, Logger.LogCategory.EVENT);
                ErrorHandler.showErrorBanner(
                    'Failed to handle pasted image file.',
                    'error',
                    FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                    { closable: true },
                );
            });
        return;
    }

    if (
        (shouldHandleInlinePaste || shouldCreateTopNote)
        && imageFiles.length === 0
        && typeof html === 'string'
        && html.includes('<img')
        && clipboardContainsFileReference
    ) {
        event.preventDefault();
        ErrorHandler.showErrorBanner(
            'Clipboard contains a file reference/icon preview, not image bytes. Open the image and copy the pixels, then paste again.',
            'error',
            FILE_REFERENCE_PASTE_BANNER_SECONDS * MS_PER_SECOND,
            { closable: true },
        );
        return;
    }

    // Dictated text whose tag phrase ("start tags") starts tags: the text before
    // it goes into the note, the words after it into the tag bar.
    if (shouldHandleInlinePaste && imageFiles.length === 0 && !hasTrackedNoteClipboardHtml
        && handleDictatedNotePaste(event, DOMUtils.getNoteById(ModeContext.currentNoteId), plainText)) {
        return;
    }

    if (shouldHandleInlinePaste && imageFiles.length === 0 && !hasTrackedNoteClipboardHtml
        && !autoTaggedPasswordPaste && !isPlainPaste && handleFormatDetectingPaste(event, plainText)) {
        return;
    }

    if (shouldHandleInlinePaste && imageFiles.length === 0 && !hasTrackedNoteClipboardHtml
        && !autoTaggedPasswordPaste && !isPlainPaste && handleFormatGuessingPaste(event, plainText)) {
        return;
    }

    // A pasted URL that lost its tracking parameters, with no HTML to go through
    // the sanitizer: MetaList inserts the cleaned text itself, since the browser
    // would paste the clipboard as it is.
    if (shouldHandleInlinePaste && imageFiles.length === 0 && !hasTrackedNoteClipboardHtml
        && html.length === 0 && plainText !== rawPlainText) {
        event.preventDefault();
        startSeparateUndoStep();
        insertPlainTextAtCurrentSelection(plainText);
        markCurrentNoteDirtyFromPaste('Content marked as dirty due to a paste with tracking parameters removed');
        return;
    }

    // Check if this is our note HTML (contains note-content class)
    if (hasTrackedNoteClipboardHtml) {
        Logger.logDebug('Detected note HTML in clipboard - using server clipboard', {}, Logger.LogCategory.EVENT);
        
        // This is our note HTML - prevent default and use server clipboard
        if (hasActiveNote) {
            event.preventDefault();
            
			// ⇧⌘V (its keystroke asked for a plain paste) pastes the note as a child.
			if (isPlainPaste) {
				void CommandGate.run('paste_event.child', async () => {
					await actionPasteNoteChild();
				});
			} else {
				void CommandGate.run('paste_event.sibling', async () => {
					await actionPasteNoteSibling();
				});
			}
		} else if (shouldCreateTopNote) {
            event.preventDefault();
            void pasteCopiedNoteIntoNewTopNote()
                .then((result) => {
                    if (result !== null) {
                        return;
                    }
                    ErrorHandler.showErrorBanner(
                        'Copied note paste did not start because another command is still running.',
                        'error',
                        COMMAND_BUSY_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                })
                .catch((error) => {
            rethrowUnexpectedError(error);
                    const message = error instanceof Error ? error.message : String(error);
                    Logger.logDebug('Copied note paste into new top note failed', {
                        error: message,
                    }, Logger.LogCategory.EVENT);
                    ErrorHandler.showErrorBanner(
                        'Failed to paste copied note into a new top note.',
                        'error',
                        FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                });
		}
    } else {
        const shouldSanitizeExternalHtml = ModeContext.isEditing && hasEditableTarget && typeof html === 'string' && html.length > 0;

        if (shouldSanitizeExternalHtml) {
            const pasteEventSnapshot = buildClipboardPasteEventSnapshot(
                html, plainText, event.clipboardData.getData('vscode-editor-data'),
            );
            const selectionRange = getSelectionRangeSnapshot();
            let formattedOffer = null;
            if (shouldHandleInlinePaste && !isPlainPaste && !autoTaggedPasswordPaste) {
                formattedOffer = planFormattedInlinePasteOffer(html, plainText);
            }
            event.preventDefault();
            void sanitizeAndInsertExternalPaste(pasteEventSnapshot, selectionRange)
                .then((inserted) => {
                    Logger.logDebug('External HTML paste sanitized and inserted', {
                        inserted,
                        htmlLength: html.length,
                    }, Logger.LogCategory.EVENT);

                    if (inserted && !ModeContext.isDirty) {
                        markCurrentNoteDirtyFromPaste('Content marked as dirty due to sanitized external paste');
                    }
                    if (inserted && formattedOffer !== null && ModeContext.isEditingNote(formattedOffer.record.noteId)) {
                        offerGuessedFormat(formattedOffer);
                    }
                })
                .catch((error) => {
            rethrowUnexpectedError(error);
                    const message = error instanceof Error ? error.message : String(error);
                    Logger.logDebug('External HTML paste sanitization failed', {
                        error: message,
                        htmlLength: html.length,
                    }, Logger.LogCategory.EVENT);
                    ErrorHandler.showErrorBanner(
                        'Failed to sanitize pasted HTML.',
                        'error',
                        FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                });
        } else if (shouldCreateTopNote) {
            const pasteEventSnapshot = buildClipboardPasteEventSnapshot(
                html, plainText, event.clipboardData.getData('vscode-editor-data'),
            );
            event.preventDefault();
            void pasteExternalContentIntoNewTopNote(pasteEventSnapshot, plainText, isPlainPaste)
                .then((result) => {
                    if (result === null) {
                        ErrorHandler.showErrorBanner(
                            'Paste did not start because another command is still running.',
                            'error',
                            COMMAND_BUSY_BANNER_SECONDS * MS_PER_SECOND,
                            { closable: true },
                        );
                        return;
                    }
                    Logger.logDebug('External content pasted into new top note', {
                        inserted: result.inserted,
                        autoTaggedPasswordPaste: result.autoTaggedPasswordPaste,
                    }, Logger.LogCategory.EVENT);
                })
                .catch((error) => {
            rethrowUnexpectedError(error);
                    const message = error instanceof Error ? error.message : String(error);
                    Logger.logDebug('External paste into new top note failed', {
                        error: message,
                    }, Logger.LogCategory.EVENT);
                    ErrorHandler.showErrorBanner(
                        'Failed to paste into a new top note.',
                        'error',
                        FAILURE_BANNER_SECONDS * MS_PER_SECOND,
                        { closable: true },
                    );
                });
        } else {
            Logger.logDebug('External content detected - using browser default paste', {
                hasHtml: !!html,
                autoTaggedPasswordPaste,
            }, Logger.LogCategory.EVENT);

            if (ModeContext.isEditing && !ModeContext.isDirty) {
                markCurrentNoteDirtyFromPaste('Content marked as dirty due to paste');
            }
        }
    }
}

function getTabContextItem(target) {
    if (!(target instanceof Element)) {
        return null;
    }
    const item = target.closest('.tab-context-item');
    if (!item) {
        return null;
    }
    const searchContextsList = document.getElementById('search-contexts-list');
    if (!searchContextsList || !searchContextsList.contains(item)) {
        return null;
    }
    return item;
}

function getTabIdFromContextItem(item) {
    if (!(item instanceof Element) || !item.classList.contains('tab-context-item')) {
        throw new Error('getTabIdFromContextItem requires a tab context item');
    }
    const tabId = item.getAttribute('data-tab-id');
    if (!tabId) {
        throw new Error('Tab context item missing data-tab-id');
    }
    return tabId;
}

function clearTabDragCandidate() {
    // Most mouse events do not belong to a tab drag episode.
    if (moduleState.tabDragCandidateId === null) return;
    moduleState.tabDragCandidateId = null;
}

function clearTabDragStyling() {
    document.querySelectorAll('.tab-context-item.is-dragging, .tab-context-item.is-drop-target')
        .forEach((item) => {
            item.classList.remove('is-dragging', 'is-drop-target');
        });
    if (document.body) {
        document.body.classList.remove('tab-drag-active');
    }
}

function finishTabDrag() {
    clearTabDragCandidate();
    if (moduleState.draggedTabId !== null) moduleState.draggedTabId = null;
    clearTabDragStyling();
}

function handleTabDragCandidateMouseDown(event) {
    clearTabDragCandidate();
    if (!event || event.button !== 0 || !(event.target instanceof Element)) {
        return;
    }
    if (event.target.closest('.tab-context-action')) {
        return;
    }
    const item = getTabContextItem(event.target);
    if (!item || ModeContext.tabOrder.length < MIN_TABS_TO_DRAG) {
        return;
    }
    moduleState.tabDragCandidateId = getTabIdFromContextItem(item);
}

function handleTabDragStart(event) {
    const item = getTabContextItem(event.target);
    if (!item) {
        return;
    }
    const tabId = getTabIdFromContextItem(item);
    if (moduleState.tabDragCandidateId !== tabId || ModeContext.isLoading) {
        event.preventDefault();
        finishTabDrag();
        return;
    }
    if (!event.dataTransfer) {
        throw new Error('Tab dragstart requires dataTransfer');
    }

    moduleState.draggedTabId = tabId;
    item.classList.add('is-dragging');
    document.body.classList.add('tab-drag-active');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', tabId);
}

function handleTabDragOver(event) {
    if (moduleState.draggedTabId === null) {
        return;
    }
    event.preventDefault();
    if (event.dataTransfer) {
        event.dataTransfer.dropEffect = 'move';
    }

    document.querySelectorAll('.tab-context-item.is-drop-target').forEach((item) => {
        item.classList.remove('is-drop-target');
    });
    const hoveredItem = getTabContextItem(event.target);
    if (hoveredItem && getTabIdFromContextItem(hoveredItem) !== moduleState.draggedTabId) {
        hoveredItem.classList.add('is-drop-target');
    }
}

function handleTabDrop(event) {
    if (moduleState.draggedTabId === null) {
        return;
    }
    event.preventDefault();
    event.stopPropagation();

    const sourceTabId = moduleState.draggedTabId;
    const hoveredItem = getTabContextItem(event.target);
    const hoveredTabId = hoveredItem ? getTabIdFromContextItem(hoveredItem) : null;
    moduleState.ignoreClickAfterTabDragUntil = performance.now() + TAB_DRAG_CLICK_SUPPRESSION_MS;
    finishTabDrag();

    if (hoveredTabId === null || hoveredTabId === sourceTabId) {
        return;
    }
    void CommandGate.run('tab.drag_reorder', async () => {
        await moveTabContext(sourceTabId, hoveredTabId);
    });
}

function handleTabDragEnd() {
    if (moduleState.draggedTabId !== null) {
        moduleState.ignoreClickAfterTabDragUntil = performance.now() + TAB_DRAG_CLICK_SUPPRESSION_MS;
    }
    finishTabDrag();
}

function handleTabDragClick(event) {
    if (moduleState.ignoreClickAfterTabDragUntil === null) {
        return;
    }
    if (performance.now() > moduleState.ignoreClickAfterTabDragUntil) {
        moduleState.ignoreClickAfterTabDragUntil = null;
        return;
    }
    if (!getTabContextItem(event.target)) {
        return;
    }

    moduleState.ignoreClickAfterTabDragUntil = null;
    event.preventDefault();
    event.stopImmediatePropagation();
}

function buildTabReferenceIconHtml(tabId) {
    const viewKind = getReferenceViewKindForTab(tabId);
    if (viewKind === '') return '';
    const iconClasses = getReferenceViewIconClasses(viewKind);
    if (iconClasses.length === 0) return '';
    return `<span class="${iconClasses.join(' ')} tab-context-reference-icon" aria-hidden="true"></span>`;
}

// A folder context's row starts with the tree's folder icon, beside its folder's name (the
// maintainer, 2026-11-07).
function buildTabFolderIconHtml(tabId) {
    if (!isFolderContext(tabId)) return '';
    return '<span class="virtual-folder-icon tab-context-folder-icon" aria-hidden="true"></span>';
}

export function updateSearchContextsList() {
    const searchContextsList = document.getElementById('search-contexts-list');
    updateReferenceSourceIndicator();
    if (!searchContextsList) return;
    const tabs = ModeContext.tabs;
    const activeTabId = ModeContext.activeTabId;
    const tabOrder = ModeContext.tabOrder;

    if (!CONFIG.TABS || typeof CONFIG.TABS.MAX_TABS !== 'number' || CONFIG.TABS.MAX_TABS <= 0) {
        throw new Error('CONFIG.TABS.MAX_TABS must be a positive number');
    }
    
    // Build the list of search contexts
    let contextsList = [];
    if (!Array.isArray(tabOrder) || tabOrder.length === 0) {
        throw new Error('ModeContext.tabOrder must be a non-empty array');
    }
    for (let i = 0; i < tabOrder.length; i++) {
        const tabId = tabOrder[i];
        const tabEntry = tabs[tabId];
        if (!tabEntry || typeof tabEntry !== 'object') {
            throw new Error(`ModeContext.tabs missing entry for tab ${tabId}`);
        }

        let originalQuery = tabEntry.searchQuery;
        if (typeof originalQuery !== 'string') {
            originalQuery = '';
        }
        const referenceNavigationLabel = getReferenceNavigationLabelForTab(tabId);
        // A context narrowed to a folder is named by its search and its folder, as its search
        // box shows them: one with only a folder is that folder, never "(empty)". The name uses
        // the row's whole width and ends in an ellipsis only where it runs out (main.css).
        const displayQuery = referenceNavigationLabel !== ''
            ? referenceNavigationLabel
            : searchContextLabel({ search: originalQuery, folder: folderOfTab(tabId), isFolderContext: isFolderContext(tabId) });
        
        const isActive = tabId === activeTabId;

        const actions = tabContextActionsHtml({
            tabId,
            isAtTabLimit: tabOrder.length >= CONFIG.TABS.MAX_TABS,
            canDelete: tabOrder.length > 1,
        });

        const activeClass = isActive ? 'is-active' : '';
        contextsList.push(
            `<div data-tab-id="${escapeHtml(tabId)}" class="tab-context-item ${activeClass}" draggable="true">`
            + `<span class="tab-context-index">${i + 1}:</span>`
            // The search is the user's text: shown as text, never as markup.
            // A reference view's tab starts with its chip's icon.
            + `<span class="tab-context-query">${buildTabFolderIconHtml(tabId)}${buildTabReferenceIconHtml(tabId)}${escapeHtml(displayQuery)}</span>`
            + `<span class="tab-context-actions">${actions}</span>`
            + `</div>`
        );
    }
    
    if (contextsList.length > 0) {
        // The number column is as wide as the longest number and its colon, in the list's
        // monospace font: no gap left of "5:" when there are fewer than ten (main.css).
        searchContextsList.style.setProperty('--tab-context-index-width', `${String(tabOrder.length).length + 1}ch`);
        searchContextsList.innerHTML = contextsList.join('');
        updateSearchContextsOverlayPlacement();
        
        // Add click handlers to each tab context item
        searchContextsList.querySelectorAll('.tab-context-item').forEach(item => {
            item.addEventListener('click', async (e) => {
                const tabId = e.currentTarget.getAttribute('data-tab-id');
                if (!tabId) {
                    return;
                }
                const searchQuery = ModeContext.getExecutedSearchQuery(tabId);
                if (typeof searchQuery !== 'string') {
                    throw new Error('Clicked tab executed search query must be a string');
                }
                const referenceNavigationLabel = getReferenceNavigationLabelForTab(tabId);
                const activityPromise = referenceNavigationLabel !== ''
                    ? null
                    : NotesAPI.recordTabSearchSelection(searchQuery);
                hideSearchContextsOverlay();
                // Picking the search context already shown changes nothing: its Untagged view
                // stays until View → All Notes or its chip's × ends it (docs/ui/state-handling.md).
                void CommandGate.run('tab.select', async () => {
                    if (tabId !== ModeContext.activeTabId) {
                        await switchToTabContext(tabId, {});
                    }
                });
                if (activityPromise !== null) await activityPromise;
            });
        });
        
        // Add click handlers for per-tab + (duplicate)
        searchContextsList.querySelectorAll('.duplicate-context').forEach(addBtn => {
            addBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (e.currentTarget.getAttribute('aria-disabled') === 'true') {
                    return;
                }
                const sourceTabId = e.currentTarget.getAttribute('data-source-tab-id');
	                void CommandGate.run('tab.duplicate', async () => {
	                    await duplicateTabContext(sourceTabId, true, true, CONFIG.TABS.CREATE_AND_SWITCH);
	                });
	            });
	        });
        
        // Add click handler for delete buttons
        searchContextsList.querySelectorAll('.delete-context').forEach(deleteBtn => {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                // A single tab's − is hidden: it cannot be deleted.
                if (e.currentTarget.getAttribute('aria-hidden') === 'true') {
                    return;
                }
                const deleteTabId = e.currentTarget.getAttribute('data-delete-tab-id');
	                void CommandGate.run('tab.delete', async () => {
	                    await deleteTabContext(deleteTabId);
	                });
	            });
	        });

    } else {
        searchContextsList.style.display = 'none';
        updateSearchContextsOverlayPlacement();
    }

    updateReferenceSourceIndicator();
}

// The server records each notes.view response as the requesting tab's warm
// view, so a response must land in its own tab. Anything that changes which
// tab is active, or clears tab DOM, first lets in-flight view requests apply.
async function settleViewRequestsBeforeTabChange() {
    const { waitForViewRequestIdle } = await import('../actions/ui-actions.js');
    await waitForViewRequestIdle();
}

export async function switchToTabContext(tabId, options) {
	if (options === null || typeof options !== 'object') {
		throw new Error('switchToTabContext requires options object');
	}
    closeOpenSearchQuote();
    await settleViewRequestsBeforeTabChange();
    const canAnimatePreviousView = !ModeContext.isUntaggedView
        && ModeContext.activeTabSortMode === 'normal'
        && !isViewingReferenceSource();

    if (ModeContext.isEditing) {
        await actionSaveAndExitEditingWithoutRefreshing();
    }

    const previousTabId = ModeContext.activeTabId;
    const tabOrder = ModeContext.tabOrder;
    if (!Array.isArray(tabOrder) || tabOrder.length === 0) {
        throw new Error('ModeContext.tabOrder must be a non-empty array');
    }
    const previousTabIndex = tabOrder.indexOf(previousTabId);
    if (previousTabIndex === -1) {
        throw new Error(`previousTabId not present in ModeContext.tabOrder: ${previousTabId}`);
    }
    const nextTabIndex = tabOrder.indexOf(tabId);
    if (nextTabIndex === -1) {
        throw new Error(`tabId not present in ModeContext.tabOrder: ${tabId}`);
    }
    const perfContext = `switchTab tab#${previousTabIndex + 1}→tab#${nextTabIndex + 1}`;

	ModeContext.beginIgnoreScrollEvents();
	await (async () => {
		await persistCurrentTabState();

		await settleViewRequestsBeforeTabChange();
		ModeContext.switchToTab(tabId, { force: true });
		cacheNotesDomForTab(previousTabId);
		const restoredDom = restoreNotesDomForTab(tabId);
		if (restoredDom.restored) {
			ModeContext.restoreScrollForActiveTabNow();
		}

		syncSearchInputField();
		// Into or out of a reference view, the tree follows once the slide lands (navigateWithReferenceSlide).
		if (!isReferenceViewTransitionPending()) {
			showFolderOfActiveContext();
		}
		updateSearchContextsList();

		// Persist new tab selection and any newly created tab immediately
		await persistTabStateSnapshot();

		const startedAt = performance.now();
		const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
		await actionRefreshAndMaybeSelect({
			startedAt,
			context: perfContext,
			animateNoteChanges: options.animateNoteChanges !== false
                && canAnimatePreviousView
                && ModeContext.activeTabSortMode === 'normal'
                && !isViewingReferenceSource(),
			expectedUpdatedNotesMax: options.expectedUpdatedNotesMax,
			expectedVdomOpsMax: options.expectedVdomOpsMax,
		});

		ModeContext.restoreScrollForActiveTab();
	})().finally(() => {
		ModeContext.endIgnoreScrollEvents();
	});
}

function snapshotActiveTabScrollState() {
    const currentScroll = Math.max(0, Math.round(window.scrollY));
    // Multiple tab commands can snapshot without an intervening scroll event.
    if (ModeContext.getTabScrollPosition(ModeContext.activeTabId) !== currentScroll) {
        ModeContext.updateActiveTabScroll(currentScroll);
    }
    const nextScrollAnchor = computeScrollAnchor({ anchorBias: 'auto' });
    // Tab commands can snapshot a view with no root anchor, leaving both anchors null.
    if (!areScrollAnchorsEqual(ModeContext.getTabScrollAnchor(ModeContext.activeTabId), nextScrollAnchor)) {
        ModeContext.updateActiveTabScrollAnchor(nextScrollAnchor);
    }
}

// A copy of sourceTabId. With copiesView, a duplicate of everything it shows (search, sort,
// date range, Files filter, folder, Untagged view); without it, a new view that starts with
// nothing (a reference view, docs/ui/state-handling.md) though its notes are cloned from the source
// for the slide.
async function duplicateTabContext(sourceTabId, copiesView, animateNoteChanges, shouldSwitchImmediately) {
    if (typeof copiesView !== 'boolean') {
        throw new Error('duplicateTabContext requires copiesView boolean');
    }
    if (typeof animateNoteChanges !== 'boolean') {
        throw new Error('duplicateTabContext requires animateNoteChanges boolean');
    }
    if (typeof shouldSwitchImmediately !== 'boolean') {
        throw new Error('duplicateTabContext requires shouldSwitchImmediately boolean');
    }
    // The copy takes the search as the user finished it.
    closeOpenSearchQuote();
	const startedEditing = ModeContext.isEditing;

    if (startedEditing) {
        await actionSaveAndExitEditingWithoutRefreshing();
    }
    if (typeof sourceTabId !== 'string' || sourceTabId.length === 0) {
        throw new Error('sourceTabId is required for tab duplication');
    }
    if (!CONFIG.TABS || typeof CONFIG.TABS.MAX_TABS !== 'number' || CONFIG.TABS.MAX_TABS <= 0) {
        throw new Error('CONFIG.TABS.MAX_TABS must be a positive number');
    }
    if (typeof CONFIG.TABS.CREATE_AND_SWITCH !== 'boolean') {
        throw new Error('CONFIG.TABS.CREATE_AND_SWITCH must be a boolean');
    }

    if (!ModeContext.tabs[sourceTabId]) {
        throw new Error(`Cannot duplicate missing tab: ${sourceTabId}`);
    }

    const payload = ModeContext.getTabStatePayload();
	if (payload.tabOrder.length >= CONFIG.TABS.MAX_TABS) {
		ErrorHandler.showInfoBanner(
			`Search context limit reached (${CONFIG.TABS.MAX_TABS}). Close one before adding another.`,
			TAB_LIMIT_BANNER_SECONDS * MS_PER_SECOND,
		);
		return;
	}

    snapshotActiveTabScrollState();
    await persistTabStateSnapshot();

    const sourceEntry = ModeContext.tabs[sourceTabId];
    if (!sourceEntry || typeof sourceEntry !== 'object') {
        throw new Error(`Cannot duplicate tab with missing state: ${sourceTabId}`);
    }

    const response = await createTabOnServer(sourceTabId, copiesView);
    const newTabId = response?.newTabId;
    if (typeof newTabId !== 'string' || newTabId.length === 0) {
        throw new Error('Server did not return newTabId');
    }

    if (!response || typeof response !== 'object' || !response.tabs || typeof response.tabs !== 'object') {
        throw new Error('Server did not return tab-state payload');
    }
    if (!response.tabs[newTabId] || typeof response.tabs[newTabId] !== 'object') {
        throw new Error('Server tab-state response missing new tab payload');
    }

    const sourceScrollY = typeof sourceEntry.scrollY === 'number' && sourceEntry.scrollY >= 0
        ? Math.round(sourceEntry.scrollY)
        : 0;
    const sourceSearchQuery = typeof sourceEntry.searchQuery === 'string' ? sourceEntry.searchQuery : '';
    const sourceScrollAnchor = sourceEntry.scrollAnchor && typeof sourceEntry.scrollAnchor === 'object'
        ? sourceEntry.scrollAnchor
        : null;

	let sourceAnchorRootId = null;
	if (sourceTabId === ModeContext.activeTabId) {
		let anchorRootId = ModeContext.getRootAnchorId();
		if (!anchorRootId) {
			anchorRootId = ModeContext.getLastKnownRootId();
		}
		sourceAnchorRootId = anchorRootId;
	} else if (typeof sourceEntry.anchorRootId === 'string' && sourceEntry.anchorRootId.length > 0) {
		sourceAnchorRootId = sourceEntry.anchorRootId;
	}

    response.tabs[newTabId].scrollY = sourceScrollY;
    response.tabs[newTabId].searchQuery = sourceSearchQuery;
    response.tabs[newTabId].scrollAnchor = sourceScrollAnchor;
    response.tabs[newTabId].anchorRootId = sourceAnchorRootId;

    const sourceHashCount = ModeContext.getTabNoteHashCount(sourceTabId);
    const cloneResult = cloneNotesDomForTab(sourceTabId, newTabId, {
        activeTabId: ModeContext.activeTabId,
        ...getDuplicateTabCloneOptions(sourceHashCount),
    });

    await settleViewRequestsBeforeTabChange();
    ModeContext.hydrateTabState(response);
    ModeContext.cloneTabRedactedReveals(sourceTabId, newTabId);

    // When the source tab DOM is unavailable after a restart, leave the new
    // tab's diff state empty so the next notes.view round-trip can rebuild it
    // from the server instead of assuming a cloned DOM exists.
    finalizeDuplicatedTabClone({
        sourceHashCount,
        sourceTabId,
        newTabId,
        cloneResult,
        cloneTabNoteHashes: (fromTabId, toTabId) => ModeContext.cloneTabNoteHashes(fromTabId, toTabId),
        seedTabNoteHashes: (tabId, noteHashes) => ModeContext.seedTabNoteHashes(tabId, noteHashes),
        resetTabDiffCache: (tabId, options) => ModeContext.resetTabDiffCache(tabId, options),
    });
    updateSearchContextsList();

    if (shouldSwitchImmediately) {
        const switchOptions = { animateNoteChanges };

        await switchToTabContext(newTabId, switchOptions);
        focusSearchInputAndSelectAllText();
        return newTabId;
    }

    return newTabId;
}

export async function createBlankSearchContextFromHover() {
    const newTabId = await openBlankSearchContext();
    if (newTabId === null) {
        return null;
    }
    focusSearchInputAndSelectAllText();
    await persistTabStateSnapshot();
    return newTabId;
}

/**
 * A new search context searching query (an import's notes, once it is done), switched to;
 * null when the limit of search contexts is reached (a banner says so).
 */
export async function openSearchInNewSearchContext(query, context) {
    const newTabId = await openBlankSearchContext();
    if (newTabId === null) {
        return null;
    }
    await runReferenceSearchInActiveTab(query, context);
    await persistTabStateSnapshot();
    return newTabId;
}

// A new, blank search context in Normal order, switched to in search mode; null at the limit.
async function openBlankSearchContext() {
    closeOpenSearchQuote();
    const sourceTabId = ModeContext.activeTabId;
    if (typeof sourceTabId !== 'string' || sourceTabId.length === 0) {
        throw new Error('ModeContext.activeTabId must be a non-empty string');
    }
    if (!CONFIG.TABS || typeof CONFIG.TABS.MAX_TABS !== 'number' || CONFIG.TABS.MAX_TABS <= 0) {
        throw new Error('CONFIG.TABS.MAX_TABS must be a positive number');
    }

    const payload = ModeContext.getTabStatePayload();
    if (payload.tabOrder.length >= CONFIG.TABS.MAX_TABS) {
        ErrorHandler.showInfoBanner(
            `Search context limit reached (${CONFIG.TABS.MAX_TABS}). Close one before adding another.`,
            TAB_LIMIT_BANNER_SECONDS * MS_PER_SECOND,
        );
        return null;
    }

    snapshotActiveTabScrollState();
    await persistTabStateSnapshot();

    // The server starts it with nothing: no search, Normal order, no filter, all notes.
    const response = await createTabOnServer(sourceTabId, false);
    const newTabId = response?.newTabId;
    if (typeof newTabId !== 'string' || newTabId.length === 0) {
        throw new Error('Server did not return newTabId');
    }
    if (!response || typeof response !== 'object' || !response.tabs || typeof response.tabs !== 'object') {
        throw new Error('Server did not return tab-state payload');
    }
    const newTab = response.tabs[newTabId];
    if (!newTab || typeof newTab !== 'object') {
        throw new Error('Server tab-state response missing new tab payload');
    }

    await settleViewRequestsBeforeTabChange();
    ModeContext.hydrateTabState(response);
    ModeContext.resetTabDiffCache(newTabId, { preserveRootAnchor: false });

    await switchToTabContext(newTabId, {});
    await actionEnterSearchMode();
    return newTabId;
}

/**
 * A folder clicked in the tree ('' for `/`): the folder context it was clicked in, narrowed to it,
 * its search emptied, shown from the top (docs/ready-to-build/virtual-folders.md, "Folder contexts"). From a
 * reference view opened from it, back there first.
 */
export async function chooseFolder(folder) {
    if (typeof folder !== 'string') {
        throw new Error('chooseFolder requires a folder or \'\'');
    }
    if (isViewingReferenceSource()) {
        await navigateToReferenceOrigin();
    }
    const folderTabId = ModeContext.activeTabId;
    if (!isFolderContext(folderTabId)) {
        throw new Error('A folder is chosen only in a folder context: the tree shows nowhere else');
    }
    closeOpenSearchQuote();
    if (ModeContext.isEditing) {
        await actionSaveAndExitEditingWithoutRefreshing();
    }
    await persistTabStateSnapshot();
    const response = await chooseFolderOnServer(folderTabId, folder);
    ModeContext.bumpUndoContextEpoch('virtualFolder');
    recordFolderContextFolder(folderTabId, folder);
    await settleViewRequestsBeforeTabChange();
    // Its emptied search and top scroll come with the answer; it is the search the view now runs.
    ModeContext.hydrateTabState(response, { preserveActiveRootTracking: true });
    ModeContext.clearTabRevealedRedactions(folderTabId);
    ModeContext.clearActiveTabDiffCacheForSearchExecution(ModeContext.searchQuery, { forceClear: true });
    if (ModeContext.getRootAnchorId() !== null) {
        ModeContext.setRootAnchorId(null);
    }
    ModeContext.beginIgnoreScrollEvents();
    window.scrollTo(0, 0);
    ModeContext.endIgnoreScrollEvents();
    syncSearchInputField();
    showFolderOfActiveContext();
    updateSearchContextsList();
    const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
    await actionRefreshAndMaybeSelect({ startedAt: performance.now(), context: 'folderContext.choose', animateNoteChanges: false, startAtListTop: true, scrollToTopAfterRender: true });
}

/** Open folders tab: the folder context used last, as left; with none, a new one at the end of
 * the list on every note (`/`), the tree with it (docs/ready-to-build/virtual-folders.md, "Folder contexts"). */
export async function openFoldersTab() {
    if (isViewingReferenceSource()) {
        await navigateToReferenceOrigin();
    }
    const usedLast = usedLastAmong(ModeContext.tabOrder.filter((tabId) => isFolderContext(tabId)));
    if (usedLast !== '') {
        await switchToTabContext(usedLast, { animateNoteChanges: false });
        return;
    }
    if (ModeContext.tabOrder.length >= CONFIG.TABS.MAX_TABS) {
        ErrorHandler.showInfoBanner(
            `Search context limit reached (${CONFIG.TABS.MAX_TABS}). Close one before adding another.`,
            TAB_LIMIT_BANNER_SECONDS * MS_PER_SECOND,
        );
        return;
    }
    closeOpenSearchQuote();
    snapshotActiveTabScrollState();
    await persistTabStateSnapshot();
    const response = await createFolderContextOnServer();
    const folderTabId = response.newTabId;
    if (typeof folderTabId !== 'string' || !response.tabs[folderTabId] || !isFolderContext(folderTabId)) {
        throw new Error('The server made no folder context');
    }
    await settleViewRequestsBeforeTabChange();
    ModeContext.hydrateTabState(response, { preserveActiveRootTracking: true });
    ModeContext.resetTabDiffCache(folderTabId, { preserveRootAnchor: false });
    await switchToTabContext(folderTabId, { animateNoteChanges: false });
}

/** Close folders tab: the plain search used last, as left, with no tree; with none, a new blank
 * one at the end of the list. Nothing is deleted. */
export async function closeFoldersTab() {
    if (isViewingReferenceSource()) {
        await navigateToReferenceOrigin();
    }
    // A reference view is a passing look, not a search to go back to.
    const plainSearches = ModeContext.tabOrder.filter(
        (tabId) => !isFolderContext(tabId) && getReferenceViewKindForTab(tabId) === '',
    );
    const usedLast = usedLastAmong(plainSearches);
    if (usedLast !== '') {
        await switchToTabContext(usedLast, { animateNoteChanges: false });
        return;
    }
    await openBlankSearchContext();
}

export async function openReferenceInNewTab(referenceNoteId) {
    if (typeof referenceNoteId !== 'string' || referenceNoteId.length === 0) {
        throw new Error('openReferenceInNewTab requires referenceNoteId');
    }
    return openReferenceQueryInNewTabWithContext(
        referenceNoteId,
        'reference.link_open_tab',
        false,
        'source',
    );
}

/** An AI answer's references: one of them ('reference') or all of them ('references'). */
export async function openReferenceQueryInNewTab(referenceQuery, viewKind) {
    if (typeof referenceQuery !== 'string' || referenceQuery.length === 0) {
        throw new Error('openReferenceQueryInNewTab requires referenceQuery');
    }
    if (!AI_REFERENCE_VIEW_KINDS.has(viewKind)) {
        throw new Error('openReferenceQueryInNewTab requires an AI reference viewKind');
    }
    return openReferenceQueryInNewTabWithContext(
        referenceQuery,
        'reference.collection_open_tab',
        true,
        viewKind,
    );
}

export async function openBacklinksInNewTab(sourceNoteId) {
    const payload = await NotesAPI.fetchBacklinks(sourceNoteId, null);
    const query = buildBacklinksQuery(payload, sourceNoteId);
    if (query === '') {
        ErrorHandler.showInfoBanner('No notes reference this source anymore.', NO_BACKLINKS_BANNER_SECONDS * MS_PER_SECOND);
        return;
    }
    await openReferenceQueryInNewTabWithContext(query, 'reference.backlinks_open_tab', false, 'backlinks');
}

async function openReferenceQueryInNewTabWithContext(
    rawReferenceQuery,
    context,
    replaceActiveReference,
    viewKind,
) {
    if (typeof replaceActiveReference !== 'boolean') {
        throw new Error('Reference navigation requires replacement policy');
    }
    // The view is kept as the tab's search reads it, so the server can tell it still runs.
    const queryAnalysis = analyzeSearchQueryInput(rawReferenceQuery);
    if (!queryAnalysis.isComplete) {
        throw new Error('Reference navigation query must be a complete search query');
    }
    const referenceQuery = queryAnalysis.normalizedText;
    // The same AI references clicked again while they are shown: already there.
    if (
        replaceActiveReference
        && isViewingReferenceSource()
        && getActiveReferenceViewKind() === viewKind
        && getActiveReferenceSourceQuery() === referenceQuery
    ) {
        return ModeContext.activeTabId;
    }
    // A reference already open on this path: back to its level, with no new tab
    // (docs/ui/references.md, Reference views). The view shown now: already there.
    if (!replaceActiveReference) {
        const levelTabId = findReferenceLevelOnActivePath(referenceQuery, viewKind);
        if (levelTabId === ModeContext.activeTabId) {
            return levelTabId;
        }
        if (levelTabId !== '') {
            await navigateWithReferenceSlide('back', () => returnToReferenceLevel(levelTabId));
            return levelTabId;
        }
    }
    let resultTabId = '';
    await navigateWithReferenceSlide('forward', async () => {
        resultTabId = await openReferenceQueryBehindTransition(
            referenceQuery,
            context,
            replaceActiveReference,
            viewKind,
        );
        return true;
    });
    return resultTabId;
}

/**
 * Run a reference navigation behind a still copy of the view it leaves, then show
 * the result: the column slides (forward: left, back: right) and the chip grows in
 * or out. navigate resolves to false when it did not navigate after all.
 */
async function navigateWithReferenceSlide(direction, navigate) {
    beginReferenceViewTransition(direction);
    let hasNavigated = false;
    await navigate().then((result) => {
        hasNavigated = result;
    }).finally(() => {
        // A navigation that stopped or failed leaves the view as it was.
        if (hasNavigated !== true && isReferenceViewTransitionPending()) {
            cancelReferenceViewTransition();
        }
    });
    if (typeof hasNavigated !== 'boolean') {
        throw new Error('A reference navigation must say whether it navigated');
    }
    if (!hasNavigated) {
        return false;
    }
    // A reference view opened from a folder context keeps the tree; back at a search, it closes.
    showFolderOfActiveContext();
    const isReferenceView = isViewingReferenceSource();
    // Back at the search, the input fades in with its text; into a reference view, it
    // fades out with the text it had and is emptied once out of sight.
    playReferenceViewTransition(() => {
        if (!isReferenceView) {
            syncSearchInputField();
        }
        updateReferenceSourceIndicator();
    }, () => {
        if (isReferenceView) {
            syncSearchInputField();
        }
    });
    return true;
}

async function openReferenceQueryBehindTransition(
    referenceQuery,
    context,
    replaceActiveReference,
    viewKind,
) {
    // A later AI reference replaces the AI references being viewed: no new level.
    if (
        replaceActiveReference
        && isViewingReferenceSource()
        && AI_REFERENCE_VIEW_KINDS.has(getActiveReferenceViewKind())
    ) {
        replaceActiveReferenceNavigationQuery(referenceQuery, viewKind);
        await runReferenceSearchInActiveTab(referenceQuery, context);
        return ModeContext.activeTabId;
    }

    const sourceTabId = ModeContext.activeTabId;
    const originScope = captureReferenceOriginScopeForActiveTab();
    const newTabId = await duplicateTabContext(sourceTabId, false, false, false);
    if (typeof newTabId !== 'string' || newTabId.length === 0) {
        throw new Error('Reference navigation expected duplicateTabContext to return a tab id');
    }

    // Register the hidden-query view before any tab activation renders its search field.
    pushReferenceNavigationEntry(sourceTabId, newTabId, referenceQuery, originScope, viewKind);
    if (ModeContext.activeTabId !== newTabId) {
        await switchToTabContext(newTabId, { animateNoteChanges: false });
    }

    await runReferenceSearchInActiveTab(referenceQuery, context);
    return newTabId;
}

async function runReferenceSearchInActiveTab(referenceQuery, context) {
    if (typeof referenceQuery !== 'string' || referenceQuery.length === 0) {
        throw new Error('runReferenceSearchInActiveTab requires referenceQuery');
    }
    if (typeof context !== 'string' || context.length === 0) {
        throw new Error('runReferenceSearchInActiveTab requires context');
    }

    const searchInput = document.getElementById('search-input');
    if (!(searchInput instanceof HTMLInputElement)) {
        throw new Error('Search input element not found for reference tab navigation');
    }

    const queryAnalysis = analyzeSearchQueryInput(referenceQuery);
    if (!queryAnalysis.isComplete) {
        throw new Error('Reference navigation query must be a complete search query');
    }
    const normalizedReferenceQuery = queryAnalysis.normalizedText;
    // Opening the same reference from the same tab can leave the search query unchanged.
    if (ModeContext.searchQuery !== normalizedReferenceQuery) {
        ModeContext.setSearchQuery(normalizedReferenceQuery);
    }
    syncSearchInputField();
    updateSearchContextsList();

    await actionEnterSearchMode();
    ModeContext.clearActiveTabDiffCacheForSearchExecution(normalizedReferenceQuery);
    ModeContext.resetRootTracking({ clear: true });
    window.scrollTo(0, 0);
    // Reference navigation can run while the active tab is already scrolled to top.
    if (ModeContext.getTabScrollPosition(ModeContext.activeTabId) !== 0) {
        ModeContext.updateActiveTabScroll(0);
    }
    // updateActiveTabScroll and resetRootTracking leave anchors null.
    if (ModeContext.getTabScrollAnchor(ModeContext.activeTabId) !== null) {
        ModeContext.updateActiveTabScrollAnchor(null);
    }
    // resetRootTracking clears the root anchor for the reference search.
    if (ModeContext.getRootAnchorId() !== null) {
        ModeContext.setRootAnchorId(null);
    }
    const startedAt = performance.now();
    const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
    await actionRefreshAndMaybeSelect({
        startedAt,
        context,
        animateNoteChanges: false,
    });
    await persistTabStateSnapshot();

    syncSearchInputField();
    if (!isViewingReferenceSource()) {
        searchInput.focus();
        searchInput.setSelectionRange(
            normalizedReferenceQuery.length,
            normalizedReferenceQuery.length,
        );
    }
}

async function moveTabContext(tabId, hoveredTabId) {
	if (ModeContext.isEditing) {
		await actionSaveAndExitEditingWithoutRefreshing();
	}
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId is required for tab reorder');
    }
    if (typeof hoveredTabId !== 'string' || hoveredTabId.length === 0) {
        throw new Error('hoveredTabId is required for tab reorder');
    }

    const tabOrder = ModeContext.tabOrder;
    if (!Array.isArray(tabOrder) || tabOrder.length === 0) {
        throw new Error('ModeContext.tabOrder must be a non-empty array');
    }
    if (tabOrder.length === 1) {
        return;
    }

    if (!tabOrder.includes(tabId)) {
        throw new Error(`tabOrder missing dragged tab: ${tabId}`);
    }
    if (!tabOrder.includes(hoveredTabId)) {
        throw new Error(`tabOrder missing hovered tab: ${hoveredTabId}`);
    }
    if (tabId === hoveredTabId) {
        return;
    }

    const currentScroll = Math.max(0, Math.round(window.scrollY));
    // Reordering tabs can be requested without the page moving first.
    if (ModeContext.getTabScrollPosition(ModeContext.activeTabId) !== currentScroll) {
        ModeContext.updateActiveTabScroll(currentScroll);
    }
    const nextScrollAnchor = computeScrollAnchor({ anchorBias: 'auto' });
    // Reordering tabs can snapshot a view with no root anchor, leaving both anchors null.
    if (!areScrollAnchorsEqual(ModeContext.getTabScrollAnchor(ModeContext.activeTabId), nextScrollAnchor)) {
        ModeContext.updateActiveTabScrollAnchor(nextScrollAnchor);
    }

    ModeContext.moveTabToHoveredSlot(tabId, hoveredTabId);
    updateSearchContextsList();
    await persistTabStateSnapshot();
}

async function deleteTabContext(deleteTabId) {
	if (ModeContext.isEditing) {
		await actionSaveAndExitEditingWithoutRefreshing();
	}

    await settleViewRequestsBeforeTabChange();
    if (typeof deleteTabId !== 'string' || deleteTabId.length === 0) {
        throw new Error('deleteTabId is required for tab deletion');
    }

    const payload = ModeContext.getTabStatePayload();
    if (payload.tabOrder.length <= 1) {
        return;
    }
    if (!payload.tabs[deleteTabId]) {
        throw new Error(`Cannot delete missing tab: ${deleteTabId}`);
    }

    const activeBeforeDelete = ModeContext.activeTabId;
    const beforeTabOrder = payload.tabOrder;
    if (!Array.isArray(beforeTabOrder) || beforeTabOrder.length === 0) {
        throw new Error('ModeContext.tabOrder must be a non-empty array');
    }
    const activeBeforeIndex = beforeTabOrder.indexOf(activeBeforeDelete);
    if (activeBeforeIndex === -1) {
        throw new Error(`activeTabId not present in ModeContext.tabOrder: ${activeBeforeDelete}`);
    }
    const deleteTabIndex = beforeTabOrder.indexOf(deleteTabId);
    if (deleteTabIndex === -1) {
        throw new Error(`deleteTabId not present in ModeContext.tabOrder: ${deleteTabId}`);
    }

    if (deleteTabId === activeBeforeDelete) {
        clearActiveNotesDom();
    } else {
        clearCachedNotesDomForTab(deleteTabId);
    }

    snapshotActiveTabScrollState();
    await persistTabStateSnapshot();

    const response = await deleteTabOnServer(deleteTabId);
    await settleViewRequestsBeforeTabChange();
    ModeContext.hydrateTabState(response, {
        preserveActiveRootTracking: deleteTabId !== activeBeforeDelete,
    });

    syncSearchInputField();
    updateSearchContextsList();

	    if (ModeContext.activeTabId !== activeBeforeDelete) {
        restoreNotesDomForTab(ModeContext.activeTabId);
        const afterTabOrder = ModeContext.tabOrder;
        if (!Array.isArray(afterTabOrder) || afterTabOrder.length === 0) {
            throw new Error('ModeContext.tabOrder must be a non-empty array');
        }
        const activeAfterIndex = afterTabOrder.indexOf(ModeContext.activeTabId);
        if (activeAfterIndex === -1) {
            throw new Error(`activeTabId not present in ModeContext.tabOrder: ${ModeContext.activeTabId}`);
        }
        const perfContext = `deleteTab tab#${deleteTabIndex + 1}→switch tab#${activeBeforeIndex + 1}→tab#${activeAfterIndex + 1}`;
        const startedAt = performance.now();
        const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
        await actionRefreshAndMaybeSelect({ startedAt, context: perfContext });
	        ModeContext.restoreScrollForActiveTab();
	    }
}

/** ← on the chip, or Escape: back one level, to where the user left it. */
export async function navigateBackFromReferenceContext() {
    if (!isViewingReferenceSource()) {
        return false;
    }
    return navigateWithReferenceSlide('back', () => leaveActiveReferenceLevel());
}

/** × on the chip: back to the search the reference views started from, at any depth. */
export async function navigateToReferenceOrigin() {
    if (!isViewingReferenceSource()) {
        return false;
    }
    return navigateWithReferenceSlide('back', () => leaveActiveReferenceChain());
}

function requireCloseReferenceTabOnBack() {
    if (
        !CONFIG.REFERENCE_NAVIGATION
        || typeof CONFIG.REFERENCE_NAVIGATION.CLOSE_REF_TAB_ON_BACK !== 'boolean'
    ) {
        throw new Error('CONFIG.REFERENCE_NAVIGATION.CLOSE_REF_TAB_ON_BACK must be a boolean');
    }
    return CONFIG.REFERENCE_NAVIGATION.CLOSE_REF_TAB_ON_BACK;
}

async function leaveActiveReferenceChain() {
    const chain = popActiveReferenceChain();
    const originTabId = chain[0].fromTabId;
    if (typeof originTabId !== 'string' || originTabId.length === 0) {
        throw new Error('Reference chain missing its origin tab');
    }
    if (!ModeContext.tabs[originTabId]) {
        return false;
    }

    await switchToTabContext(originTabId, { animateNoteChanges: false });

    if (requireCloseReferenceTabOnBack()) {
        for (const entry of chain) {
            if (ModeContext.tabs[entry.toTabId]) {
                await deleteTabContext(entry.toTabId);
            }
        }
    }
    updateReferenceSourceIndicator();
    return true;
}

/** Back to a level further up the active reference path, closing the levels after it. */
async function returnToReferenceLevel(levelTabId) {
    const left = popReferenceLevelsAbove(levelTabId);
    if (!ModeContext.tabs[levelTabId]) {
        return false;
    }

    await switchToTabContext(levelTabId, { animateNoteChanges: false });

    if (requireCloseReferenceTabOnBack()) {
        for (const entry of left) {
            if (ModeContext.tabs[entry.toTabId]) {
                await deleteTabContext(entry.toTabId);
            }
        }
    }
    updateReferenceSourceIndicator();
    return true;
}

async function leaveActiveReferenceLevel() {
    const entry = popReferenceNavigationEntryForActiveTab();
    if (entry === null) {
        return false;
    }

    const fromTabId = entry.fromTabId;
    const toTabId = entry.toTabId;
    if (typeof fromTabId !== 'string' || fromTabId.length === 0) {
        throw new Error('Reference back entry missing fromTabId');
    }
    if (typeof toTabId !== 'string' || toTabId.length === 0) {
        throw new Error('Reference back entry missing toTabId');
    }
    if (!ModeContext.tabs[fromTabId]) {
        return false;
    }

    await switchToTabContext(fromTabId, { animateNoteChanges: false });

    if (requireCloseReferenceTabOnBack()) {
        if (ModeContext.tabs[toTabId]) {
            await deleteTabContext(toTabId);
        }
    }

    updateReferenceSourceIndicator();
    return true;
}

function syncSearchInputField() {
    const searchInput = document.getElementById('search-input');
    if (!searchInput) {
        return;
    }
    // A reference navigation keeps the bar as the user left it until it plays.
    if (isReferenceViewTransitionPending()) {
        return;
    }

    const activeQuery = ModeContext.searchQuery;
    if (typeof activeQuery !== 'string') {
        throw new Error('ModeContext.searchQuery must be a string');
    }

    syncSearchInputValue(
        searchInput,
        resolveSearchInputDisplayQuery(
            activeQuery,
            ModeContext.isUntaggedView,
            isViewingReferenceSource(),
        ),
    );
}

async function persistCurrentTabState() {
    const currentScroll = Math.max(0, Math.round(window.scrollY));
    // Explicit tab-state persists may follow a scroll watcher that already stored this Y.
    if (ModeContext.getTabScrollPosition(ModeContext.activeTabId) !== currentScroll) {
        ModeContext.updateActiveTabScroll(currentScroll);
    }
    const nextScrollAnchor = computeScrollAnchor({ anchorBias: 'auto' });
    // Explicit tab-state persists can run when the stored anchor already matches the DOM anchor.
    if (!areScrollAnchorsEqual(ModeContext.getTabScrollAnchor(ModeContext.activeTabId), nextScrollAnchor)) {
        ModeContext.updateActiveTabScrollAnchor(nextScrollAnchor);
    }
    await persistTabStateSnapshot();
}
