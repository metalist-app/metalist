// The choices of Theme, in the palette and the right-click menu. A skin (docs/ui/skins.md) is a
// theme whose look comes from app/static/css/skins/<value>.css, drawn over its base theme.
// In the order Theme offers them (the maintainer, 2026-11-11: Fathom first; 2026-11-12:
// Fathom, Phosphor, Vellum, Ye Olde Scrypte).
const SKINS = Object.freeze({
    // A code editor's deep blue-grey, in the style of Sublime Text, in the system's own
    // monospace font (2026-11-11).
    fathom: Object.freeze({ label: 'Fathom', baseTheme: 'dark', isManuscript: false }),
    // A green terminal screen, in the system's own monospace font (2026-11-12).
    phosphor: Object.freeze({ label: 'Phosphor', baseTheme: 'dark', isManuscript: false }),
    // Warm paper for long reading, notes in a book serif (2026-11-12).
    vellum: Object.freeze({ label: 'Vellum', baseTheme: 'light', isManuscript: false }),
    illuminated: Object.freeze({ label: 'Ye Olde Scrypte', baseTheme: 'light', isManuscript: true }),
});
const SKIN_CHOICES = Object.entries(SKINS).map(([value, skin]) => [value, skin.label]);
export const THEME_CHOICES = [['system', 'System'], ['light', 'Light'], ['dark', 'Dark'], ...SKIN_CHOICES];

export function isSkinTheme(theme) {
    if (typeof theme !== 'string') {
        throw new Error('isSkinTheme requires a theme string');
    }
    return Object.hasOwn(SKINS, theme);
}

function requireSkin(skin) {
    if (!isSkinTheme(skin)) {
        throw new Error(`Not a skin: ${skin}`);
    }
    return SKINS[skin];
}

// The theme a skin is drawn over: what exports, diagrams and Excalidraw see.
export function skinBaseTheme(skin) {
    return requireSkin(skin).baseTheme;
}

// Whether the skin is the painted manuscript, with its initials, old-English words and drawn
// pointer (skin-initials.js, skin-olde-words.js, skin-pointer.js).
export function isManuscriptSkin(skin) {
    return requireSkin(skin).isManuscript;
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
