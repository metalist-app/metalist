import {
    baseRootSortMode,
    isRootSortModeReversed,
    rootSortModeWithDirection,
} from '../mode-manager/services/root-sort-service.js';
import {
    BACKUP_REMINDER_DEFAULT,
    BACKUP_REMINDER_OPTIONS,
    BACKUP_REMINDER_PREFERENCE,
} from '../backup-reminder-schedule.js';

function requireAction(actions, key) {
    if (!actions || typeof actions !== 'object') {
        throw new Error('Endpoint registry requires actions object');
    }
    const fn = actions[key];
    if (typeof fn !== 'function') {
        throw new Error(`Endpoint registry missing action: ${key}`);
    }
    return fn;
}

function readBooleanPreference(preferencesStore, key, defaultValue) {
    if (typeof key !== 'string' || key.length === 0) {
        throw new Error('readBooleanPreference requires key');
    }
    if (typeof defaultValue !== 'boolean') {
        throw new Error('readBooleanPreference requires boolean default');
    }
    const raw = preferencesStore.getRaw(key);
    if (raw === null) {
        return defaultValue;
    }
    if (raw === 'true') {
        return true;
    }
    if (raw === 'false') {
        return false;
    }
    throw new Error(`Invalid stored boolean for ${key}`);
}

function visibilityLabel(preferencesStore, key, defaultValue, subject) {
    if (typeof subject !== 'string' || subject.length === 0) {
        throw new Error('visibilityLabel requires subject');
    }
    const isVisible = readBooleanPreference(preferencesStore, key, defaultValue);
    return `${isVisible ? 'Hide' : 'Show'} ${subject}`;
}

// Commands with a key of their own show it at the right of their row (rule 4): the
// key alone, or with Cmd (Ctrl).
export const COMMAND_SHORTCUTS = Object.freeze({
    'action.find_in_list': Object.freeze({ mod: true, shift: false, key: 'F' }),
    'action.open_keyboard_shortcuts_help': Object.freeze({ mod: false, shift: false, key: '?' }),
});

// Commands that lose what cannot be brought back are red (rule 3). The palette orders
// commands by use and search, so they keep their place.
export const DESTRUCTIVE_COMMAND_IDS = Object.freeze(new Set([
    'action.alphabetize_root_notes_asc',
    'action.alphabetize_root_notes_desc',
    'action.prioritize_tag_back',
    'action.prioritize_tag_front',
    'action.remove_all_tag_suggestions_current_context',
    'action.reset_all_preferences',
    'action.reset_updated_at_to_created_at',
    'action.trim_unused_files',
    'form.delete_current_namespace',
    'form.remove_password',
    'form.restore_backup',
]));

const PASSWORD_COMMANDS_WITHOUT_ONE = new Set(['form.add_password']);
const PASSWORD_COMMANDS_WITH_ONE = new Set(['form.change_password', 'form.remove_password']);
const ROOT_REORDER_COMMANDS = new Set([
    'action.prioritize_tag_front',
    'action.prioritize_tag_back',
    'action.alphabetize_root_notes_asc',
    'action.alphabetize_root_notes_desc',
]);

/**
 * Whether a command can apply now; one that cannot is left out of the palette (rule 5).
 * `state` is { hasPassword, isRootReorderLocked } (a sorted tab orders its root notes itself).
 */
export function isCommandAvailable(commandId, state) {
    if (typeof commandId !== 'string' || commandId === '') {
        throw new Error('isCommandAvailable requires a command id');
    }
    if (typeof state.hasPassword !== 'boolean' || typeof state.isRootReorderLocked !== 'boolean') {
        throw new Error('isCommandAvailable requires boolean hasPassword and isRootReorderLocked');
    }
    if (PASSWORD_COMMANDS_WITHOUT_ONE.has(commandId)) {
        return !state.hasPassword;
    }
    if (PASSWORD_COMMANDS_WITH_ONE.has(commandId)) {
        return state.hasPassword;
    }
    if (ROOT_REORDER_COMMANDS.has(commandId)) {
        return !state.isRootReorderLocked;
    }
    return true;
}

export function buildCommandPaletteEndpoints(deps) {
    if (!deps || typeof deps !== 'object') {
        throw new Error('buildCommandPaletteEndpoints requires deps object');
    }

    const preferencesStore = deps.preferencesStore;
    if (!preferencesStore || typeof preferencesStore.getRaw !== 'function') {
        throw new Error('buildCommandPaletteEndpoints requires preferencesStore');
    }

    const actions = deps.actions;
    const applyPreference = requireAction(actions, 'applyPreference');
    const openAddPassword = requireAction(actions, 'openAddPassword');
    const openChangePassword = requireAction(actions, 'openChangePassword');
    const openRemovePassword = requireAction(actions, 'openRemovePassword');
    const openSessionTimeoutSettings = requireAction(actions, 'openSessionTimeoutSettings');
    const createBackup = requireAction(actions, 'createBackup');
    const openBackupRestore = requireAction(actions, 'openBackupRestore');
    const logout = requireAction(actions, 'logout');
    const openRandomPasswordGenerator = requireAction(actions, 'openRandomPasswordGenerator');
    const collapseAll = requireAction(actions, 'collapseAll');
    const expandAll = requireAction(actions, 'expandAll');
    const fullyCollapseAll = requireAction(actions, 'fullyCollapseAll');
    const fullyExpandAll = requireAction(actions, 'fullyExpandAll');
    const resetViewFilters = requireAction(actions, 'resetViewFilters');
    const resetAllPreferences = requireAction(actions, 'resetAllPreferences');
    const openSearchSuggestionStatistics = requireAction(actions, 'openSearchSuggestionStatistics');
    const openOntologyEditor = requireAction(actions, 'openOntologyEditor');
    const openFindBar = requireAction(actions, 'openFindBar');
    const openKeyboardShortcutsHelp = requireAction(actions, 'openKeyboardShortcutsHelp');
    const attachFileToCurrentNote = requireAction(actions, 'attachFileToCurrentNote');
    const addExcalidrawDiagram = requireAction(actions, 'addExcalidrawDiagram');
    const trimUnusedFiles = requireAction(actions, 'trimUnusedFiles');
    const retryFailedLinkTitles = requireAction(actions, 'retryFailedLinkTitles');
    const exportCurrentViewAsHtml = requireAction(actions, 'exportCurrentViewAsHtml');
    const printView = requireAction(actions, 'printView');
    const openOpenNamespace = requireAction(actions, 'openOpenNamespace');
    const openCreateNamespace = requireAction(actions, 'openCreateNamespace');
    const openManageNamespacePorts = requireAction(actions, 'openManageNamespacePorts');
    const openRenameCurrentNamespace = requireAction(actions, 'openRenameCurrentNamespace');
    const openDeleteCurrentNamespace = requireAction(actions, 'openDeleteCurrentNamespace');
    const prioritizeTagToFront = requireAction(actions, 'prioritizeTagToFront');
    const prioritizeTagToBack = requireAction(actions, 'prioritizeTagToBack');
    const alphabetizeRootNotesAsc = requireAction(actions, 'alphabetizeRootNotesAsc');
    const alphabetizeRootNotesDesc = requireAction(actions, 'alphabetizeRootNotesDesc');
    const resetUpdatedAtToCreatedAt = requireAction(actions, 'resetUpdatedAtToCreatedAt');
    const openReminders = requireAction(actions, 'openReminders');

    const openVersionInfo = requireAction(actions, 'openVersionInfo');
    const openMemoryUsage = requireAction(actions, 'openMemoryUsage');
    const openNoteLayoutAppearance = requireAction(actions, 'openNoteLayoutAppearance');
    const openVisualCues = requireAction(actions, 'openVisualCues');
    const openDictationSettings = requireAction(actions, 'openDictationSettings');
    const getSortMode = requireAction(actions, 'getSortMode');
    const setSortMode = requireAction(actions, 'setSortMode');
    const getIsUntaggedView = requireAction(actions, 'getIsUntaggedView');
    const setIsUntaggedView = requireAction(actions, 'setIsUntaggedView');
    const getDateRangeKind = requireAction(actions, 'getDateRangeKind');
    const getDateRangeField = requireAction(actions, 'getDateRangeField');
    const setDateRangePreset = requireAction(actions, 'setDateRangePreset');
    const setDateRangeField = requireAction(actions, 'setDateRangeField');
    const openCustomDateRange = requireAction(actions, 'openCustomDateRange');
    const getFileFilterKind = requireAction(actions, 'getFileFilterKind');
    const setFileFilter = requireAction(actions, 'setFileFilter');
    const openAiAgentSettings = requireAction(actions, 'openAiAgentSettings');
    const openCloudPrivacySettings = requireAction(actions, 'openCloudPrivacySettings');
    const openProposalManager = requireAction(actions, 'openProposalManager');
    const removeAllTagSuggestionsFromCurrentContext = requireAction(
        actions,
        'removeAllTagSuggestionsFromCurrentContext',
    );
    const openTaggingVocabulary = requireAction(actions, 'openTaggingVocabulary');

    const defaults = {
        showNoteTags: false,
        showTabUi: false,
        showSearchResultsCount: true,
        showAiChat: false,
        animatedTransitions: true,
        theme: 'system',
    };
    // An order and its direction are chosen apart: picking an order keeps Reverse Order.
    const sortModeActionValue = (sortMode) => (baseRootSortMode(getSortMode()) === sortMode ? 'Current' : '↵');
    const setSortOrderKeepingDirection = (sortMode) => setSortMode(
        rootSortModeWithDirection(sortMode, isRootSortModeReversed(getSortMode())),
    );

    return [
        {
            id: 'pref.show_note_tags',
            kind: 'boolean',
            get label() {
                return visibilityLabel(preferencesStore, 'pref.show_note_tags', defaults.showNoteTags, 'Tags in List');
            },
            persistenceKey: 'pref.show_note_tags',
            defaultValue: defaults.showNoteTags,
            apply: (next) => applyPreference('pref.show_note_tags', next),
        },
        {
            id: 'pref.show_tab_ui',
            kind: 'boolean',
            get label() {
                return visibilityLabel(preferencesStore, 'pref.show_tab_ui', defaults.showTabUi, 'Tabs');
            },
            persistenceKey: 'pref.show_tab_ui',
            defaultValue: defaults.showTabUi,
            apply: (next) => applyPreference('pref.show_tab_ui', next),
        },
        {
            id: 'pref.show_search_results_count',
            kind: 'boolean',
            get label() {
                return visibilityLabel(
                    preferencesStore,
                    'pref.show_search_results_count',
                    defaults.showSearchResultsCount,
                    'Search Result Count',
                );
            },
            persistenceKey: 'pref.show_search_results_count',
            defaultValue: defaults.showSearchResultsCount,
            apply: (next) => applyPreference('pref.show_search_results_count', next),
        },
        {
            id: 'pref.show_ai_chat',
            kind: 'boolean',
            get label() {
                return visibilityLabel(preferencesStore, 'pref.show_ai_chat', defaults.showAiChat, 'AI Chat');
            },
            persistenceKey: 'pref.show_ai_chat',
            defaultValue: defaults.showAiChat,
            apply: (next) => applyPreference('pref.show_ai_chat', next),
        },
        {
            id: 'pref.animated_transitions',
            kind: 'boolean',
            get label() {
                return visibilityLabel(
                    preferencesStore,
                    'pref.animated_transitions',
                    defaults.animatedTransitions,
                    'Animated Transitions',
                );
            },
            persistenceKey: 'pref.animated_transitions',
            defaultValue: defaults.animatedTransitions,
            apply: (next) => applyPreference('pref.animated_transitions', next),
        },
        {
            id: 'view.sort_mode.normal',
            kind: 'action',
            label: 'Sort Order: Normal',
            getValue: () => sortModeActionValue('normal'),
            closeOnExecute: true,
            execute: async () => setSortOrderKeepingDirection('normal'),
        },
        {
            id: 'view.sort_mode.created',
            kind: 'action',
            label: 'Sort Order: Datetime Created',
            getValue: () => sortModeActionValue('created'),
            closeOnExecute: true,
            execute: async () => setSortOrderKeepingDirection('created'),
        },
        {
            id: 'view.sort_mode.updated',
            kind: 'action',
            label: 'Sort Order: Datetime Last Updated',
            getValue: () => sortModeActionValue('updated'),
            closeOnExecute: true,
            execute: async () => setSortOrderKeepingDirection('updated'),
        },
        {
            id: 'view.sort_mode.alphabetical',
            kind: 'action',
            label: 'Sort Order: Alphabetical',
            getValue: () => sortModeActionValue('alphabetical'),
            closeOnExecute: true,
            execute: async () => setSortOrderKeepingDirection('alphabetical'),
        },
        {
            id: 'view.sort_mode.content_volume',
            kind: 'action',
            label: 'Sort Order: Content Volume',
            getValue: () => sortModeActionValue('content-volume'),
            closeOnExecute: true,
            execute: async () => setSortOrderKeepingDirection('content-volume'),
        },
        {
            id: 'view.sort_mode.reverse',
            kind: 'action',
            label: 'Sort Order: Reverse',
            getValue: () => (isRootSortModeReversed(getSortMode()) ? 'On' : 'Off'),
            closeOnExecute: true,
            execute: async () => setSortMode(rootSortModeWithDirection(
                getSortMode(),
                !isRootSortModeReversed(getSortMode()),
            )),
        },
        {
            id: 'view.all_notes',
            kind: 'action',
            label: 'View: All Notes',
            getValue: () => (getIsUntaggedView() ? '↵' : 'Current'),
            closeOnExecute: true,
            execute: async () => setIsUntaggedView(false),
        },
        {
            id: 'view.untagged_notes',
            kind: 'action',
            label: 'View: Untagged Notes',
            getValue: () => (getIsUntaggedView() ? 'Current' : '↵'),
            closeOnExecute: true,
            execute: async () => setIsUntaggedView(true),
        },
        // Date range (date-range-filter-service.js): which date, then its range.
        ...[['updated', 'Last Updated'], ['created', 'Created']].map(([field, label]) => ({
            id: `view.date_range.field.${field}`,
            kind: 'action',
            label: `Date Range: ${label}`,
            getValue: () => (getDateRangeField() === field ? 'Current' : '↵'),
            closeOnExecute: true,
            execute: async () => setDateRangeField(field),
        })),
        ...[
            ['none', 'none', 'Any Date'],
            ['today', 'today', 'Today'],
            ['last_7_days', 'last-7-days', 'Last 7 Days'],
            ['last_30_days', 'last-30-days', 'Last 30 Days'],
            ['this_year', 'this-year', 'This Year'],
        ].map(([idPart, rangeKind, label]) => ({
            id: `view.date_range.${idPart}`,
            kind: 'action',
            label: `Date Range: ${label}`,
            getValue: () => (getDateRangeKind() === rangeKind ? 'Current' : '↵'),
            closeOnExecute: true,
            execute: async () => setDateRangePreset(rangeKind),
        })),
        {
            id: 'view.date_range.custom',
            kind: 'action',
            label: 'Date Range: Custom Range…',
            getValue: () => (getDateRangeKind() === 'custom' ? 'Current' : '↵'),
            closeOnExecute: true,
            execute: async () => openCustomDateRange(),
        },
        ...[
            ['none', 'All Notes'],
            ['any', 'Any File'],
            ['image', 'Images'],
            ['pdf', 'PDFs'],
            ['markdown', 'Markdown Files'],
        ].map(([kind, label]) => ({
            id: `view.files.${kind}`,
            kind: 'action',
            label: `Notes with Files: ${label}`,
            getValue: () => (getFileFilterKind() === kind ? 'Current' : '↵'),
            closeOnExecute: true,
            execute: async () => setFileFilter(kind),
        })),
        {
            id: 'pref.theme',
            kind: 'select',
            label: 'Theme',
            persistenceKey: 'pref.theme',
            defaultValue: defaults.theme,
            options: [
                { value: 'system', label: 'System' },
                { value: 'light', label: 'Light' },
                { value: 'dark', label: 'Dark' },
            ],
            apply: (next) => applyPreference('pref.theme', next),
        },
        {
            id: 'form.search_suggestion_statistics',
            kind: 'form',
            label: 'Search Suggestion Stats & Settings…',
            execute: async () => openSearchSuggestionStatistics(),
        },
        {
            id: 'form.ai_agent_settings',
            kind: 'form',
            label: 'AI Agent Settings…',
            execute: async () => openAiAgentSettings(false),
        },
        {
            id: 'form.cloud_ai_privacy',
            kind: 'form',
            label: 'Cloud AI Privacy…',
            execute: async () => openCloudPrivacySettings(),
        },
        {
            id: 'form.proposals', kind: 'form', label: 'Accept or Reject AI-Proposed Tags…',
            execute: async () => openProposalManager(),
        },
        {
            id: 'action.remove_all_tag_suggestions_current_context',
            kind: 'action',
            label: 'Reject All AI-Proposed Tags (Current Context)…',
            closeOnExecute: true,
            execute: async () => removeAllTagSuggestionsFromCurrentContext(),
        },
        {
            id: 'form.tagging_vocabulary', kind: 'form', label: 'AI Tagging Vocabulary…',
            execute: async () => openTaggingVocabulary(),
        },
        {
            id: 'action.fully_expand_all',
            kind: 'action',
            label: 'Fully Expand All Notes (Current View)',
            closeOnExecute: true,
            execute: async () => fullyExpandAll(),
        },
        {
            id: 'action.fully_collapse_all',
            kind: 'action',
            label: 'Fully Collapse All Notes (Current View)',
            closeOnExecute: true,
            execute: async () => fullyCollapseAll(),
        },
        {
            id: 'action.expand_all',
            kind: 'action',
            label: 'Expand All Root Notes (Current View)',
            closeOnExecute: true,
            execute: async () => expandAll(),
        },
        {
            id: 'action.collapse_all',
            kind: 'action',
            label: 'Collapse All Root Notes (Current View)',
            closeOnExecute: true,
            execute: async () => collapseAll(),
        },
        {
            id: 'action.reset_view_filters',
            kind: 'action',
            label: 'Reset Current View Filters',
            closeOnExecute: true,
            execute: async () => resetViewFilters(),
        },
        {
            id: 'action.reset_all_preferences',
            kind: 'action',
            label: 'Reset All Preferences',
            execute: async () => resetAllPreferences(),
        },
        {
            id: 'form.add_password',
            kind: 'form',
            label: 'Add Password…',
            execute: async () => openAddPassword(),
        },
        {
            id: 'form.change_password',
            kind: 'form',
            label: 'Change Password…',
            execute: async () => openChangePassword(),
        },
        {
            id: 'form.remove_password',
            kind: 'form',
            label: 'Remove Password…',
            execute: async () => openRemovePassword(),
        },
        {
            id: 'form.session_timeout',
            kind: 'form',
            label: 'Session Idle Timeout…',
            execute: async () => openSessionTimeoutSettings(),
        },
        {
            id: 'form.reminders',
            kind: 'form',
            label: 'Open Reminders',
            execute: async () => openReminders({ search: '' }),
        },

        {
            id: 'form.version_info',
            kind: 'form',
            label: 'Version Info',
            execute: async () => openVersionInfo(),
        },
        {
            id: 'form.memory_usage',
            kind: 'form',
            label: 'Memory Usage',
            execute: async () => openMemoryUsage(),
        },
        {
            id: 'form.note_layout_appearance',
            kind: 'form',
            label: 'Note Layout & Appearance…',
            execute: async () => openNoteLayoutAppearance(),
        },
        {
            id: 'form.visual_cues',
            kind: 'form',
            label: 'Visual Cues…',
            execute: async () => openVisualCues(),
        },
        {
            id: 'form.dictation_settings',
            kind: 'form',
            label: 'Dictation Settings…',
            execute: async () => openDictationSettings(),
        },
        {
            id: 'form.open_namespace',
            kind: 'form',
            label: 'Open/Switch Vault…',
            execute: async () => openOpenNamespace(),
        },
        {
            id: 'form.create_namespace',
            kind: 'form',
            label: 'Create Vault…',
            execute: async () => openCreateNamespace(),
        },
        {
            id: 'form.manage_namespace_ports',
            kind: 'form',
            label: 'Manage Vault Ports…',
            execute: async () => openManageNamespacePorts(),
        },
        {
            id: 'form.rename_current_namespace',
            kind: 'form',
            label: 'Rename Current Vault…',
            execute: async () => openRenameCurrentNamespace(),
        },
        {
            id: 'form.delete_current_namespace',
            kind: 'form',
            label: 'Delete Vault…',
            execute: async () => openDeleteCurrentNamespace(),
        },
        {
            id: 'action.create_backup',
            kind: 'action',
            label: 'Back Up Now…',
            execute: async () => createBackup(),
        },
        {
            id: 'pref.backup_reminder',
            kind: 'select',
            label: 'Backup Reminder',
            persistenceKey: BACKUP_REMINDER_PREFERENCE,
            defaultValue: BACKUP_REMINDER_DEFAULT,
            options: BACKUP_REMINDER_OPTIONS,
            apply: (next) => applyPreference(BACKUP_REMINDER_PREFERENCE, next),
        },
        {
            id: 'form.restore_backup',
            kind: 'form',
            label: 'Restore from Backup…',
            execute: async () => openBackupRestore(),
        },
        {
            id: 'action.logout',
            kind: 'action',
            label: 'Log Out',
            execute: async () => logout(),
        },
        {
            id: 'form.random_password_generator',
            kind: 'form',
            label: 'Generate Random Password…',
            execute: async () => openRandomPasswordGenerator(),
        },
        {
            id: 'action.find_in_list',
            kind: 'action',
            label: 'Find in List',
            execute: async () => openFindBar(),
        },
        {
            id: 'action.edit_tag_relationships',
            kind: 'action',
            label: 'Edit Tag Relationships…',
            execute: async () => openOntologyEditor(),
        },
        {
            id: 'action.export_html',
            kind: 'action',
            label: 'Export View as HTML…',
            execute: async () => exportCurrentViewAsHtml(),
        },
        {
            id: 'action.print_view',
            kind: 'action',
            label: 'Print View…',
            execute: async () => printView(),
        },
        {
            id: 'action.attach_file_to_current_note',
            kind: 'action',
            label: 'Attach File…',
            closeOnExecute: true,
            execute: async () => attachFileToCurrentNote(),
        },
        {
            id: 'action.add_excalidraw_diagram',
            kind: 'action',
            label: 'Add Excalidraw Diagram',
            closeOnExecute: true,
            execute: async () => addExcalidrawDiagram(),
        },
        {
            id: 'action.trim_unused_files',
            kind: 'action',
            label: 'Trim Unused Files…',
            closeOnExecute: true,
            execute: async () => trimUnusedFiles(),
        },
        {
            id: 'action.retry_failed_link_titles',
            kind: 'action',
            label: 'Retry Failed Link Titles…',
            closeOnExecute: true,
            execute: async () => retryFailedLinkTitles(),
        },
        {
            id: 'action.prioritize_tag_front',
            kind: 'action',
            label: 'Prioritize Tag to Front (Global)…',
            closeOnExecute: true,
            execute: async () => prioritizeTagToFront(),
        },
        {
            id: 'action.prioritize_tag_back',
            kind: 'action',
            label: 'Prioritize Tag to Back (Global)…',
            closeOnExecute: true,
            execute: async () => prioritizeTagToBack(),
        },
        {
            id: 'action.alphabetize_root_notes_asc',
            kind: 'action',
            label: 'Alphabetize Root Notes A-Z (Current View)…',
            closeOnExecute: true,
            execute: async () => alphabetizeRootNotesAsc(),
        },
        {
            id: 'action.alphabetize_root_notes_desc',
            kind: 'action',
            label: 'Alphabetize Root Notes Z-A (Current View)…',
            closeOnExecute: true,
            execute: async () => alphabetizeRootNotesDesc(),
        },
        {
            id: 'action.reset_updated_at_to_created_at',
            kind: 'action',
            label: 'Repair: Reset Updated Time to Created Time (Current View)…',
            closeOnExecute: true,
            execute: async () => resetUpdatedAtToCreatedAt(),
        },
        {
            id: 'action.open_keyboard_shortcuts_help',
            kind: 'action',
            label: 'Keyboard Shortcuts',
            execute: async () => openKeyboardShortcutsHelp(),
        },
    ];
}
