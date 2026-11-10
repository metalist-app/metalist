import assert from 'node:assert/strict';
import test from 'node:test';
import { SKIN_BASE_THEME, THEME_CHOICES, currentThemeChoice, isSkinTheme } from '../../app/static/js/modules/theme-choices.js';
import { resolveStoredThemePreference } from '../../app/static/js/modules/client-state-migration.js';

function rootWith(attributes) {
    return { getAttribute: (name) => (name in attributes ? attributes[name] : null) };
}

test('Theme offers the three themes and then the skins', () => {
    assert.deepEqual(THEME_CHOICES, [['system', 'System'], ['light', 'Light'], ['dark', 'Dark'], ['illuminated', 'Ye Olde Scrypte']]);
});

test('only a skin counts as a skin', () => {
    assert.equal(isSkinTheme('illuminated'), true);
    for (const theme of ['system', 'light', 'dark']) assert.equal(isSkinTheme(theme), false);
    assert.throws(() => isSkinTheme(null), /requires a theme string/);
});

test('the current choice is the skin when there is one, under its base theme', () => {
    assert.equal(SKIN_BASE_THEME, 'light');
    assert.equal(currentThemeChoice(rootWith({ 'data-skin': 'illuminated', 'data-theme': 'light' })), 'illuminated');
    assert.equal(currentThemeChoice(rootWith({ 'data-theme': 'light' })), 'light');
    assert.equal(currentThemeChoice(rootWith({ 'data-theme': 'dark' })), 'dark');
    assert.equal(currentThemeChoice(rootWith({})), 'system');
});

test('a skin opens on its base theme, at the login screen too', () => {
    assert.equal(resolveStoredThemePreference({ 'pref.theme': 'illuminated' }), 'light');
    assert.equal(resolveStoredThemePreference({ 'pref.theme': 'dark' }), 'dark');
    assert.equal(resolveStoredThemePreference({ 'pref.theme': 'system' }), null);
});
