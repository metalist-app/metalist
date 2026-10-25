import assert from 'node:assert/strict';
import test from 'node:test';

import { buildCommandPaletteEndpoints } from '../../app/static/js/modules/command-palette/endpoint-registry.js';

function noop() {}

test('buildCommandPaletteEndpoints includes utility action endpoints', async () => {
    const storedPreferences = new Map();
    let removeAllTagSuggestionsCalls = 0;
    const endpoints = buildCommandPaletteEndpoints({
        preferencesStore: {
            getRaw: (key) => storedPreferences.has(key) ? storedPreferences.get(key) : null,
        },
        actions: {
            applyPreference: noop,
            openAddPassword: noop,
            openChangePassword: noop,
            openRemovePassword: noop,
            openSessionTimeoutSettings: noop,
            openReminders: noop,
            openSoundManager: noop,
            openVersionInfo: noop,
            openMemoryUsage: noop,
            openNoteLayoutAppearance: noop,
            openVisualCues: noop,
            openDictationSettings: noop,
            openAiAgentSettings: noop,
            openCloudPrivacySettings: noop,
            openProposalManager: noop,
            removeAllTagSuggestionsFromCurrentContext: () => { removeAllTagSuggestionsCalls += 1; },
            openTaggingVocabulary: noop,
            openOntologyEditor: noop,
            openFindBar: noop,
            createBackup: noop,
            openBackupRestore: noop,
            logout: noop,
            openRandomPasswordGenerator: noop,
            collapseAll: noop,
            expandAll: noop,
            fullyCollapseAll: noop,
            fullyExpandAll: noop,
            resetViewFilters: noop,
            resetAllPreferences: noop,
            openSearchSuggestionStatistics: noop,
            openKeyboardShortcutsHelp: noop,
            exportCurrentViewAsHtml: noop,
            printView: noop,
            attachFileToCurrentNote: noop,
            addExcalidrawDiagram: noop,
            trimUnusedFiles: noop,
            retryFailedLinkTitles: noop,
            openOpenNamespace: noop,
            openCreateNamespace: noop,
            openManageNamespacePorts: noop,
            openRenameCurrentNamespace: noop,
            openDeleteCurrentNamespace: noop,
            prioritizeTagToFront: noop,
            prioritizeTagToBack: noop,
            alphabetizeRootNotesAsc: noop,
            alphabetizeRootNotesDesc: noop,
            resetUpdatedAtToCreatedAt: noop,
            getSortMode: () => 'normal',
            setSortMode: noop,
            getIsUntaggedView: () => false,
            setIsUntaggedView: noop,
            getDateRangeKind: () => 'none',
            getDateRangeField: () => 'updated',
            setDateRangePreset: noop,
            setDateRangeField: noop,
            openCustomDateRange: noop,
            getFileFilterKind: () => 'none',
            setFileFilter: noop,
        },
    });

    const endpointIds = new Set(endpoints.map((endpoint) => endpoint.id));
    // Every label, "…" included, is checked in command_palette_conventions.test.mjs.
    const attachFileEndpoint = endpoints.find((endpoint) => endpoint.id === 'action.attach_file_to_current_note');
    const animatedTransitionsEndpoint = endpoints.find((endpoint) => endpoint.id === 'pref.animated_transitions');
    assert.equal(endpointIds.has('action.create_backup'), true);
    assert.equal(endpointIds.has('form.open_namespace'), true);
    assert.equal(endpointIds.has('form.switch_namespace'), false);
    assert.equal(endpointIds.has('form.create_namespace'), true);
    assert.equal(endpointIds.has('form.manage_namespace_ports'), true);
    assert.equal(endpointIds.has('form.rename_current_namespace'), true);
    assert.equal(endpointIds.has('form.delete_current_namespace'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.delete_current_namespace').label,
        'Delete Vault…',
    );
    assert.equal(endpointIds.has('form.restore_backup'), true);
    assert.equal(endpointIds.has('form.add_password'), true);
    assert.equal(endpointIds.has('form.change_password'), true);
    assert.equal(endpointIds.has('form.remove_password'), true);
    assert.equal(endpointIds.has('form.password_protection'), false);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.add_password').label,
        'Add Password…',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.change_password').label,
        'Change Password…',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.remove_password').label,
        'Remove Password…',
    );
    assert.equal(endpointIds.has('form.session_timeout'), true);
    assert.equal(endpointIds.has('pref.show_rhs_panel'), false);
    assert.equal(endpointIds.has('pref.show_note_timestamps'), false);
    assert.equal(animatedTransitionsEndpoint.defaultValue, true);
    assert.equal(animatedTransitionsEndpoint.label, 'Hide Animated Transitions');
    assert.equal(endpointIds.has('form.reminders'), true);
    assert.equal(endpointIds.has('form.version_info'), true);
    assert.equal(endpointIds.has('form.memory_usage'), true);
    assert.equal(endpointIds.has('form.note_layout_appearance'), true);
    assert.equal(endpointIds.has('form.agent_prompts'), false);
    assert.equal(endpointIds.has('form.tagging_vocabulary'), true);
    const removeAllTagSuggestionsEndpoint = endpoints.find(
        (endpoint) => endpoint.id === 'action.remove_all_tag_suggestions_current_context',
    );
    assert.equal(removeAllTagSuggestionsEndpoint.label, 'Reject All AI-Proposed Tags (Current Context)…');
    assert.equal(removeAllTagSuggestionsEndpoint.closeOnExecute, true);
    await removeAllTagSuggestionsEndpoint.execute();
    assert.equal(removeAllTagSuggestionsCalls, 1);
    assert.equal(endpointIds.has('form.cloud_ai_privacy'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.cloud_ai_privacy').label,
        'Cloud AI Privacy…',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.note_layout_appearance').label,
        'Note Layout & Appearance…',
    );
    assert.equal(endpointIds.has('action.logout'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.expand_all').label,
        'Expand All Root Notes (Current View)',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.collapse_all').label,
        'Collapse All Root Notes (Current View)',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.fully_expand_all').label,
        'Fully Expand All Notes (Current View)',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.fully_collapse_all').label,
        'Fully Collapse All Notes (Current View)',
    );
    assert.equal(endpointIds.has('form.random_password_generator'), true);
    assert.equal(endpointIds.has('pref.auto_collapse_long_notes'), false);
    assert.equal(endpointIds.has('action.export_html'), true);
    assert.equal(endpointIds.has('action.attach_file_to_current_note'), true);
    assert.equal(attachFileEndpoint.label, 'Attach File…');
    assert.equal(endpointIds.has('action.trim_unused_files'), true);
    assert.equal(endpointIds.has('form.search_suggestion_statistics'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'form.search_suggestion_statistics').label,
        'Search Suggestion Stats & Settings…',
    );
    assert.equal(endpointIds.has('action.prioritize_tag_front'), true);
    assert.equal(endpointIds.has('action.prioritize_tag_back'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.prioritize_tag_front').label,
        'Prioritize Tag to Front (Global)…',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.prioritize_tag_back').label,
        'Prioritize Tag to Back (Global)…',
    );
    assert.equal(endpointIds.has('action.open_keyboard_shortcuts_help'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.open_keyboard_shortcuts_help').label,
        'Keyboard Shortcuts',
    );
    assert.equal(endpointIds.has('action.run_mcp_client'), false);
    assert.equal(endpointIds.has('view.sort_mode'), false);
    assert.equal(endpointIds.has('view.sort_mode.normal'), true);
    assert.equal(endpointIds.has('view.sort_mode.created'), true);
    assert.equal(endpointIds.has('view.sort_mode.updated'), true);
    assert.equal(endpointIds.has('view.sort_mode.alphabetical'), true);
    assert.equal(endpointIds.has('view.sort_mode.content_volume'), true);
    assert.equal(endpointIds.has('view.all_notes'), true);
    assert.equal(endpointIds.has('view.untagged_notes'), true);
    for (const id of ['field.updated', 'field.created', 'none', 'today', 'last_7_days', 'last_30_days', 'this_year', 'custom']) {
        assert.equal(endpointIds.has(`view.date_range.${id}`), true);
    }
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'view.sort_mode.alphabetical').label,
        'Sort Order: Alphabetical',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'view.sort_mode.content_volume').label,
        'Sort Order: Content Volume',
    );
    assert.equal(endpointIds.has('view.sort_mode.reverse'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'view.sort_mode.normal').getValue(),
        'Current',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'view.sort_mode.alphabetical').getValue(),
        '↵',
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'view.sort_mode.alphabetical').closeOnExecute,
        true,
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.alphabetize_root_notes_asc').closeOnExecute,
        true,
    );
    assert.equal(endpointIds.has('action.reset_updated_at_to_created_at'), true);
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.reset_updated_at_to_created_at').closeOnExecute,
        true,
    );
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'action.open_keyboard_shortcuts_help').closeOnExecute,
        undefined,
    );

    // The Backlinks panel is gone; ↖ and Referenced by replace it.
    assert.equal(endpointIds.has('pref.show_backlinks'), false);
    assert.equal(endpoints.find((endpoint) => endpoint.id === 'pref.show_note_tags').label, 'Show Tags in List');
    assert.equal(endpoints.find((endpoint) => endpoint.id === 'pref.show_tab_ui').label, 'Show Tabs');
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'pref.show_search_results_count').label,
        'Hide Search Result Count',
    );
    assert.equal(endpoints.some((endpoint) => endpoint.id === 'pref.show_perf_overlay'), false);

    storedPreferences.set('pref.show_note_tags', 'true');
    storedPreferences.set('pref.show_tab_ui', 'true');
    storedPreferences.set('pref.show_search_results_count', 'false');
    storedPreferences.set('pref.show_perf_overlay', 'true');
    storedPreferences.set('pref.animated_transitions', 'false');

    assert.equal(endpoints.find((endpoint) => endpoint.id === 'pref.show_note_tags').label, 'Hide Tags in List');
    assert.equal(endpoints.find((endpoint) => endpoint.id === 'pref.show_tab_ui').label, 'Hide Tabs');
    assert.equal(
        endpoints.find((endpoint) => endpoint.id === 'pref.show_search_results_count').label,
        'Show Search Result Count',
    );
    assert.equal(endpoints.some((endpoint) => endpoint.id === 'pref.show_perf_overlay'), false);
    assert.equal(animatedTransitionsEndpoint.label, 'Show Animated Transitions');
});
