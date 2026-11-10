// The choices of Theme, in the palette and the right-click menu. A skin (docs/ui/skins.md) is a
// theme whose look comes from app/static/css/skins/<value>.css, drawn over the light theme.
export const SKIN_BASE_THEME = 'light';
const SKIN_CHOICES = [['illuminated', 'Illuminated']];
export const THEME_CHOICES = [['system', 'System'], ['light', 'Light'], ['dark', 'Dark'], ...SKIN_CHOICES];
const SKIN_VALUES = new Set(SKIN_CHOICES.map(([value]) => value));

export function isSkinTheme(theme) {
    if (typeof theme !== 'string') {
        throw new Error('isSkinTheme requires a theme string');
    }
    return SKIN_VALUES.has(theme);
}

// Which choice the page shows now: the skin if there is one, or the theme it was given.
export function currentThemeChoice(root) {
    const skin = root.getAttribute('data-skin');
    if (skin !== null) {
        return skin;
    }
    const theme = root.getAttribute('data-theme');
    return theme === 'light' || theme === 'dark' ? theme : 'system';
}
