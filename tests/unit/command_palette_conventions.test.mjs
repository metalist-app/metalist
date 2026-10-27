import assert from 'node:assert/strict';
import test from 'node:test';

import {
    COMMAND_SHORTCUTS,
    DESTRUCTIVE_COMMAND_IDS,
    buildCommandPaletteEndpoints,
    isCommandAvailable,
} from '../../app/static/js/modules/command-palette/endpoint-registry.js';

// Command palette labels follow the menu rules (docs/ui/modals.md, "Dialog and menu conventions",
// rules 1-6; agreed 2026-10-24): Title Case, "…" exactly when a dialog asks for more first,
// shortcuts shown, destructive commands red, commands that cannot apply hidden.

function noop() {}

const STATE_READERS = {
    getSortMode: () => 'normal', getIsUntaggedView: () => false, getDateRangeKind: () => 'none',
    getDateRangeField: () => 'updated', getFileFilterKind: () => 'none',
};

function endpoints() {
    const actions = new Proxy({}, {
        get: (target, name) => (Object.hasOwn(STATE_READERS, name) ? STATE_READERS[name] : noop),
    });
    return buildCommandPaletteEndpoints({ preferencesStore: { getRaw: () => null }, actions });
}

const LABELS = {
    'pref.show_note_tags': 'Show Tags in List',
    'pref.show_tab_ui': 'Show Tabs',
    'pref.show_search_results_count': 'Hide Search Result Count',
    'pref.show_ai_chat': 'Show AI Chat',
    'pref.animated_transitions': 'Hide Animated Transitions',
    'view.sort_mode.normal': 'Sort Order: Normal',
    'view.sort_mode.created': 'Sort Order: Datetime Created',
    'view.sort_mode.updated': 'Sort Order: Datetime Last Updated',
    'view.sort_mode.alphabetical': 'Sort Order: Alphabetical',
    'view.sort_mode.content_volume': 'Sort Order: Content Volume',
    'view.sort_mode.reverse': 'Sort Order: Reverse',
    'view.all_notes': 'View: All Notes',
    'view.untagged_notes': 'View: Untagged Notes',
    'view.date_range.field.updated': 'Date Range: Last Updated',
    'view.date_range.field.created': 'Date Range: Created',
    'view.date_range.none': 'Date Range: Any Date',
    'view.date_range.today': 'Date Range: Today',
    'view.date_range.last_7_days': 'Date Range: Last 7 Days',
    'view.date_range.last_30_days': 'Date Range: Last 30 Days',
    'view.date_range.this_year': 'Date Range: This Year',
    'view.date_range.custom': 'Date Range: Custom Range…',
    'view.files.none': 'Notes with Files: All Notes',
    'view.files.any': 'Notes with Files: Any File',
    'view.files.image': 'Notes with Files: Images',
    'view.files.pdf': 'Notes with Files: PDFs',
    'view.files.markdown': 'Notes with Files: Markdown Files',
    'pref.theme': 'Theme',
    'form.search_suggestion_statistics': 'Search Suggestion Stats & Settings…',
    'form.ai_agent_settings': 'AI Agent Settings…',
    'form.cloud_ai_privacy': 'Cloud AI Privacy…',
    'form.proposals': 'Accept or Reject AI-Proposed Tags…',
    'action.remove_all_tag_suggestions_current_context': 'Reject All AI-Proposed Tags (Current Context)…',
    'form.tagging_vocabulary': 'AI Tagging Vocabulary…',
    'action.fully_expand_all': 'Fully Expand All Notes (Current View)',
    'action.fully_collapse_all': 'Fully Collapse All Notes (Current View)',
    'action.expand_all': 'Expand All Root Notes (Current View)',
    'action.collapse_all': 'Collapse All Root Notes (Current View)',
    'action.reset_view_filters': 'Reset Current View Filters',
    'action.reset_all_preferences': 'Reset All Preferences',
    'form.add_password': 'Add Password…',
    'form.change_password': 'Change Password…',
    'form.remove_password': 'Remove Password…',
    'form.session_timeout': 'Session Idle Timeout…',
    'form.reminders': 'Open Reminders',
    'form.version_info': 'Version Info',
    'form.memory_usage': 'Memory Usage',
    'form.recent_messages': 'Recent Messages',
    'form.note_layout_appearance': 'Note Layout & Appearance…',
    'form.visual_cues': 'Visual Cues…',
    'form.dictation_settings': 'Dictation Settings…',
    'form.open_namespace': 'Open/Switch Vault…',
    'form.create_namespace': 'Create Vault…',
    'form.manage_namespace_ports': 'Manage Vault Ports…',
    'form.rename_current_namespace': 'Rename Current Vault…',
    'form.delete_current_namespace': 'Delete Vault…',
    'action.create_backup': 'Back Up Now…',
    'pref.backup_reminder': 'Backup Reminder',
    'form.restore_backup': 'Restore from Backup…',
    'action.logout': 'Log Out',
    'form.random_password_generator': 'Generate Random Password…',
    'action.find_in_list': 'Find in List',
    'action.edit_tag_relationships': 'Edit Tag Relationships…',
    'action.export_html': 'Export View as HTML…',
    'action.print_view': 'Print View…',
    'action.attach_file_to_current_note': 'Attach File…',
    'action.link_to': 'Link to…',
    'action.embed': 'Embed…',
    'action.add_excalidraw_diagram': 'Add Excalidraw Diagram',
    'action.trim_unused_files': 'Trim Unused Files…',
    'action.retry_failed_link_titles': 'Retry Failed Link Titles…',
    'action.prioritize_tag_front': 'Prioritize Tag to Front (Global)…',
    'action.prioritize_tag_back': 'Prioritize Tag to Back (Global)…',
    'action.alphabetize_root_notes_asc': 'Alphabetize Root Notes A-Z (Current View)…',
    'action.alphabetize_root_notes_desc': 'Alphabetize Root Notes Z-A (Current View)…',
    'action.reset_updated_at_to_created_at': 'Repair: Reset Updated Time to Created Time (Current View)…',
    'action.open_keyboard_shortcuts_help': 'Keyboard Shortcuts',
};

test('every command palette label is as agreed', () => {
    const actual = Object.fromEntries(endpoints().map((endpoint) => [endpoint.id, endpoint.label]));
    assert.deepEqual(actual, LABELS);
});

test('commands with a key show it', () => {
    assert.deepEqual(COMMAND_SHORTCUTS, {
        'action.find_in_list': { mod: true, shift: false, key: 'F' },
        'action.open_keyboard_shortcuts_help': { mod: false, shift: false, key: '?' },
    });
});

test('destructive commands are the ones that lose what cannot be brought back', () => {
    assert.deepEqual([...DESTRUCTIVE_COMMAND_IDS].sort(), [
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
    ]);
    const ids = new Set(endpoints().map((endpoint) => endpoint.id));
    for (const id of DESTRUCTIVE_COMMAND_IDS) {
        assert.equal(ids.has(id), true, `${id} is not a command`);
    }
});

test('commands that cannot apply are hidden', () => {
    const withPassword = { hasPassword: true, isRootReorderLocked: false };
    const withoutPassword = { hasPassword: false, isRootReorderLocked: false };
    const sorted = { hasPassword: false, isRootReorderLocked: true };
    assert.equal(isCommandAvailable('form.add_password', withPassword), false);
    assert.equal(isCommandAvailable('form.add_password', withoutPassword), true);
    for (const id of ['form.change_password', 'form.remove_password']) {
        assert.equal(isCommandAvailable(id, withPassword), true);
        assert.equal(isCommandAvailable(id, withoutPassword), false);
    }
    for (const id of ['action.prioritize_tag_front', 'action.prioritize_tag_back',
        'action.alphabetize_root_notes_asc', 'action.alphabetize_root_notes_desc']) {
        assert.equal(isCommandAvailable(id, withoutPassword), true);
        assert.equal(isCommandAvailable(id, sorted), false);
    }
    assert.equal(isCommandAvailable('action.logout', sorted), true);
});

test('every list the palette shows or activates comes from the available commands', async () => {
    // _render once drew its rows from all commands while clicks used the available ones,
    // so a click activated the wrong row (2026-10-24).
    const { readFile } = await import('node:fs/promises');
    const source = await readFile(
        new URL('../../app/static/js/modules/command-palette/command-palette-controller.js', import.meta.url), 'utf8');
    const direct = source.match(/this\._endpoints\.filter\(/g);
    assert.equal(direct.length, 1, 'only _availableEndpoints may filter this._endpoints');
    assert.match(source, /_availableEndpoints\(\) \{[\s\S]*?return this\._endpoints\.filter\(\(endpoint\) => isCommandAvailable\(/);
});
