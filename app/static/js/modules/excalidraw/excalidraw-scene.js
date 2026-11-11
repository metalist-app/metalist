// Pure helpers for Excalidraw scene files stored as MetaList attachments.
import { UserInputRejected } from '../expected-errors.js';

export const EXCALIDRAW_MIME_TYPE = 'application/vnd.excalidraw+json';
export const EXCALIDRAW_FILENAME = 'Diagram.excalidraw';
export const EXCALIDRAW_AUTOSAVE_DELAY_MS = 2000;
export const EXCALIDRAW_PREVIEW_VARIANTS = ['light', 'dark'];
const EXPORT_PADDING = 16;
const DEFAULT_BACKGROUNDS = ['#ffffff', '#fff', 'white', 'transparent'];
// The Excalidraw scene file format version a new drawing is written in.
const EXCALIDRAW_SCENE_FORMAT_VERSION = 2;

export function buildEmptySceneJson() {
    return JSON.stringify({
        type: 'excalidraw',
        version: EXCALIDRAW_SCENE_FORMAT_VERSION,
        source: 'MetaList',
        elements: [],
        appState: { viewBackgroundColor: '#ffffff' },
        files: {},
    });
}

export function parseSceneJson(sceneText) {
    if (typeof sceneText !== 'string') {
        throw new Error('parseSceneJson requires scene text');
    }
    let scene;
    try {
        scene = JSON.parse(sceneText);
    } catch (error) {
        if (!(error instanceof SyntaxError)) {
            throw error;
        }
        throw new UserInputRejected('This file is not a valid Excalidraw diagram (it is not JSON).', { cause: error });
    }
    if (scene === null || typeof scene !== 'object' || scene.type !== 'excalidraw' || !Array.isArray(scene.elements)) {
        throw new UserInputRejected('This file is not a valid Excalidraw diagram.');
    }
    return scene;
}

// Same as Excalidraw's getSceneVersion: every element edit increments that element's version.
export function computeSceneVersion(elements) {
    if (!Array.isArray(elements)) {
        throw new Error('computeSceneVersion requires the elements array');
    }
    let version = 0;
    for (const sceneElement of elements) {
        if (!Number.isInteger(sceneElement.version)) {
            throw new Error('Excalidraw element is missing its integer version');
        }
        version += sceneElement.version;
    }
    return version;
}

// Changes Excalidraw reports on every pointer move are ignored unless drawing content changed.
export function sceneFingerprint(sceneVersion, files) {
    if (!Number.isInteger(sceneVersion) || sceneVersion < 0) {
        throw new Error('sceneFingerprint requires a non-negative integer scene version');
    }
    if (files === null || typeof files !== 'object') {
        throw new Error('sceneFingerprint requires the files map');
    }
    return `${sceneVersion}:${Object.keys(files).sort().join(',')}`;
}

export function previewExportAppState(sceneAppState, variant) {
    if (sceneAppState === null || typeof sceneAppState !== 'object') {
        throw new Error('previewExportAppState requires the scene appState');
    }
    if (!EXCALIDRAW_PREVIEW_VARIANTS.includes(variant)) {
        throw new Error(`Unknown preview variant: ${variant}`);
    }
    // Previews are transparent so they sit on the note's own background, unless the drawing
    // was given a canvas colour of its own.
    const background = String(sceneAppState.viewBackgroundColor).toLowerCase();
    return {
        ...sceneAppState,
        exportBackground: !DEFAULT_BACKGROUNDS.includes(background),
        exportWithDarkMode: variant === 'dark',
        exportPadding: EXPORT_PADDING,
    };
}

export function currentPreviewVariant(rootElement) {
    if (!(rootElement instanceof Element)) {
        throw new Error('currentPreviewVariant requires the document element');
    }
    return rootElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

// --- The editor's view, kept with the drawing (docs/ui/content-formatting.md) -----------------
// Excalidraw's own file leaves pan and zoom out; MetaList keeps them beside the scene, as the scene
// point in the middle of the editor and the zoom, so a window of another size shows the same middle.
const VIEW_KEY = 'metalistView';
// A first open fits the drawing with this margin, never above 100%, never below Excalidraw's least.
const FIT_MARGIN_PX = 40;
const MAX_FIT_ZOOM = 1;
const MIN_ZOOM = 0.1;
const MIDDLE_DIVISOR = 2;
// Moved less than this, a view is the one already kept: a resize or a stray scroll is no change.
const SAME_VIEW_SCENE_UNITS = 1;
const SAME_VIEW_ZOOM_RATIO = 0.01;

function requireView(view, caller) {
    if (view === null || typeof view !== 'object' || ![view.centerX, view.centerY, view.zoom].every(Number.isFinite) || view.zoom <= 0) {
        throw new Error(`${caller} requires a view {centerX, centerY, zoom}`);
    }
}

function requireSize(width, height, caller) {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
        throw new Error(`${caller} requires the editor's width and height`);
    }
}

export function viewOfAppState(appState) {
    if (appState === null || typeof appState !== 'object' || appState.zoom === null || typeof appState.zoom !== 'object') {
        throw new Error('viewOfAppState requires the editor appState');
    }
    requireSize(appState.width, appState.height, 'viewOfAppState');
    const zoom = appState.zoom.value;
    return {
        centerX: appState.width / MIDDLE_DIVISOR / zoom - appState.scrollX,
        centerY: appState.height / MIDDLE_DIVISOR / zoom - appState.scrollY,
        zoom,
    };
}

export function appStateForView(view, width, height) {
    requireView(view, 'appStateForView');
    requireSize(width, height, 'appStateForView');
    return {
        scrollX: width / MIDDLE_DIVISOR / view.zoom - view.centerX,
        scrollY: height / MIDDLE_DIVISOR / view.zoom - view.centerY,
        zoom: { value: view.zoom },
    };
}

// The view a drawing file keeps, or null: none kept, or a broken one in a file from elsewhere.
export function savedViewOf(scene) {
    if (scene === null || typeof scene !== 'object') {
        throw new Error('savedViewOf requires the parsed scene');
    }
    if (!(VIEW_KEY in scene)) {
        return null;
    }
    const view = scene[VIEW_KEY];
    if (view === null || typeof view !== 'object' || ![view.centerX, view.centerY, view.zoom].every(Number.isFinite) || view.zoom <= 0) {
        return null;
    }
    return { centerX: view.centerX, centerY: view.centerY, zoom: view.zoom };
}

export function withSavedView(sceneText, view) {
    requireView(view, 'withSavedView');
    const scene = JSON.parse(sceneText);
    scene[VIEW_KEY] = { centerX: view.centerX, centerY: view.centerY, zoom: view.zoom };
    return JSON.stringify(scene);
}

function elementBounds(element) {
    if (Array.isArray(element.points) && element.points.length > 0) {
        const xs = element.points.map((point) => element.x + point[0]);
        const ys = element.points.map((point) => element.y + point[1]);
        return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    return [element.x, element.y, element.x + element.width, element.y + element.height];
}

// The whole drawing in the editor, with a margin, at 100% at most; null for an empty drawing.
export function fittedView(elements, width, height) {
    if (!Array.isArray(elements)) {
        throw new Error('fittedView requires the elements array');
    }
    requireSize(width, height, 'fittedView');
    const shown = elements.filter((element) => element.isDeleted !== true);
    if (shown.length === 0) {
        return null;
    }
    const bounds = shown.map(elementBounds);
    // Each box is [left, top, right, bottom].
    const minX = Math.min(...bounds.map(([left]) => left));
    const minY = Math.min(...bounds.map(([, top]) => top));
    const maxX = Math.max(...bounds.map(([, , right]) => right));
    const maxY = Math.max(...bounds.map(([, , , bottom]) => bottom));
    const fit = Math.min(
        (width - FIT_MARGIN_PX * MIDDLE_DIVISOR) / Math.max(maxX - minX, SAME_VIEW_SCENE_UNITS),
        (height - FIT_MARGIN_PX * MIDDLE_DIVISOR) / Math.max(maxY - minY, SAME_VIEW_SCENE_UNITS),
    );
    return {
        centerX: (minX + maxX) / MIDDLE_DIVISOR,
        centerY: (minY + maxY) / MIDDLE_DIVISOR,
        zoom: Math.max(MIN_ZOOM, Math.min(MAX_FIT_ZOOM, fit)),
    };
}

export function viewsDiffer(kept, current) {
    requireView(kept, 'viewsDiffer');
    requireView(current, 'viewsDiffer');
    const moves = [
        Math.abs(kept.centerX - current.centerX) >= SAME_VIEW_SCENE_UNITS,
        Math.abs(kept.centerY - current.centerY) >= SAME_VIEW_SCENE_UNITS,
        Math.abs(kept.zoom - current.zoom) / kept.zoom >= SAME_VIEW_ZOOM_RATIO,
    ];
    return moves.includes(true);
}
