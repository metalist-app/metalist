import { ApplicationState } from '../../application-state.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';
import { FilesAPI } from '../../api-client.js';
import {
    RECENT_PICTURES_CAPACITY,
    evictOldest,
    noteObjectUrlShown,
    releaseObjectUrls,
    rememberSize,
    useNewest,
} from '../../object-url-cache.js';


const moduleState = ApplicationState.createFields('file-image-preview-service', {
    // The most recent pictures by key, oldest first (object-url-cache.js).
    previewCache: new Map(),
    pendingPreviewRequests: new Map(),
    // Natural size of each loaded image file, for this page session: when the
    // same image renders again (e.g. after its note leaves edit mode) its frame
    // is sized up front, so text below it does not move while it loads. The most
    // recent ones only, oldest first.
    previewSizes: new Map(),

    cleanupRegistered: false,
});

function ensureCleanupHandlerRegistered() {
    if (moduleState.cleanupRegistered) {
        return;
    }
    if (typeof window === 'undefined') {
        return;
    }
    window.addEventListener('beforeunload', () => {
        for (const cachedPreview of moduleState.previewCache.values()) {
            URL.revokeObjectURL(cachedPreview.objectUrl);
        }
        if (moduleState.previewCache.size > 0) moduleState.previewCache.clear();
        if (moduleState.pendingPreviewRequests.size > 0) moduleState.pendingPreviewRequests.clear();
    });
    moduleState.cleanupRegistered = true;
}

function getImagePreviewTargets(rootNode) {
    if (!rootNode || typeof rootNode.querySelectorAll !== 'function') {
        throw new Error('getImagePreviewTargets expects root node with querySelectorAll');
    }
    return Array.from(rootNode.querySelectorAll('.note-file-image-embed[data-file-ref-id]'));
}

function setPreviewState(target, state) {
    if (!(target instanceof HTMLElement)) {
        throw new Error('setPreviewState expects HTMLElement target');
    }
    if (typeof state !== 'string' || state.length === 0) {
        throw new Error('setPreviewState expects state string');
    }
    target.dataset.previewState = state;
}

function applyPreviewObjectUrl(target, objectUrl) {
    if (!(target instanceof HTMLElement)) {
        throw new Error('applyPreviewObjectUrl expects HTMLElement target');
    }
    if (typeof objectUrl !== 'string' || objectUrl.length === 0) {
        throw new Error('applyPreviewObjectUrl expects objectUrl string');
    }

    const imageElement = target.querySelector('.note-file-image-preview');
    const placeholderElement = target.querySelector('.note-file-image-preview-placeholder');
    if (!(imageElement instanceof HTMLImageElement)) {
        throw new Error('Image file preview element missing');
    }
    if (!(placeholderElement instanceof HTMLElement)) {
        throw new Error('Image file preview placeholder missing');
    }

    const fileId = target.dataset.fileRefId;
    imageElement.addEventListener('load', () => {
        const size = `${imageElement.naturalWidth}/${imageElement.naturalHeight}`;
        if (imageElement.naturalWidth > 0 && imageElement.naturalHeight > 0) {
            rememberSize(moduleState.previewSizes, fileId, size);
        }
    }, { once: true });
    imageElement.src = objectUrl;
    noteObjectUrlShown(imageElement, objectUrl);
    imageElement.hidden = false;
    placeholderElement.textContent = '';
    setPreviewState(target, 'loaded');
}

function applyPreviewFailure(target) {
    if (!(target instanceof HTMLElement)) {
        throw new Error('applyPreviewFailure expects HTMLElement target');
    }

    const placeholderElement = target.querySelector('.note-file-image-preview-placeholder');
    if (!(placeholderElement instanceof HTMLElement)) {
        throw new Error('Image file preview placeholder missing');
    }

    placeholderElement.textContent = 'Preview unavailable';
    setPreviewState(target, 'failed');
}

// A PDF's tile in a gallery shows its first page (embedded_references._render_pdf_tile), loaded
// apart from the PDF itself.
const FIRST_PAGE_SOURCE = 'first-page';

function isFirstPage(target) {
    return target.dataset.pictureSource === FIRST_PAGE_SOURCE;
}

// The cache's key: a file's own picture, or a PDF's first page.
function pictureKey(target) {
    if (isFirstPage(target)) return `${FIRST_PAGE_SOURCE}:${target.dataset.fileRefId}`;
    return target.dataset.fileRefId;
}

const everyPicture = () => true;

async function fetchPreviewObjectUrl(fileId, key, isFirstPagePicture) {
    if (typeof fileId !== 'string' || fileId.length === 0) {
        throw new Error('fetchPreviewObjectUrl expects fileId');
    }

    if (moduleState.previewCache.has(key)) {
        return useNewest(moduleState.previewCache, key).objectUrl;
    }
    if (moduleState.pendingPreviewRequests.has(key)) {
        return await moduleState.pendingPreviewRequests.get(key);
    }

    ensureCleanupHandlerRegistered();

    const download = isFirstPagePicture ? FilesAPI.downloadFirstPage(fileId) : FilesAPI.downloadFile(fileId);
    const request = download
        .then((payload) => {
            if (!payload || typeof payload !== 'object') {
                throw new Error('Image file preview response missing payload');
            }
            if (!(payload.blob instanceof Blob)) {
                throw new Error('Image file preview response missing blob');
            }
            const mimeType = typeof payload.blob.type === 'string' ? payload.blob.type.toLowerCase() : '';
            if (!mimeType.startsWith('image/')) {
                throw new Error(`Image file preview requires image blob, received: ${mimeType}`);
            }
            if (moduleState.pendingPreviewRequests.get(key) !== request) {
                throw new DOMException('Image preview canceled by page cleanup', 'AbortError');
            }
            const objectUrl = URL.createObjectURL(payload.blob);
            moduleState.previewCache.set(key, { objectUrl });
            // The newest stays: its targets take it in this same run of promise callbacks.
            const dropped = evictOldest(moduleState.previewCache, RECENT_PICTURES_CAPACITY, everyPicture);
            releaseObjectUrls(dropped.map(([, cachedPreview]) => cachedPreview.objectUrl));
            return objectUrl;
        })
        .finally(() => {
            if (moduleState.pendingPreviewRequests.get(key) === request) {
                moduleState.pendingPreviewRequests.delete(key);
            }
        });

    moduleState.pendingPreviewRequests.set(key, request);
    return await request;
}

// Collapsed-note and link thumbnails have fixed sizes of their own.
function reservePreviewSpace(target, fileId) {
    if (!moduleState.previewSizes.has(fileId) || target.closest('.note.collapsed, .note-reference-link-thumbnail') !== null) {
        return;
    }
    const frame = target.querySelector('.note-file-image-preview-frame');
    if (!(frame instanceof HTMLElement)) {
        throw new Error('Image file preview frame missing');
    }
    frame.style.aspectRatio = moduleState.previewSizes.get(fileId).replace('/', ' / ');
    frame.style.minHeight = '0px';
}

export function hydrateImageFilePreviews(rootNode) {
    const targets = getImagePreviewTargets(rootNode);
    if (targets.length === 0) {
        return;
    }

    // The targets under `rootNode` by picture: the document cannot find those in a shadow
    // root (a reference's preview card), so they are filled as well as the document's.
    const targetsByKey = new Map();
    for (const target of targets) {
        if (!(target instanceof HTMLElement)) {
            throw new Error('hydrateImageFilePreviews target must be HTMLElement');
        }
        const fileId = target.dataset.fileRefId;
        if (typeof fileId !== 'string' || fileId.length === 0) {
            throw new Error('Image file preview target missing fileRefId');
        }
        if (target.dataset.previewState === 'loaded') {
            continue;
        }
        setPreviewState(target, 'loading');
        reservePreviewSpace(target, fileId);
        const key = pictureKey(target);
        if (!targetsByKey.has(key)) targetsByKey.set(key, []);
        targetsByKey.get(key).push(target);
    }

    const targetsOf = (key) => new Set([
        ...targetsByKey.get(key),
        ...[...document.querySelectorAll('.note-file-image-embed[data-file-ref-id]')].filter((target) => pictureKey(target) === key),
    ]);
    const requests = [];
    for (const [key, keyTargets] of targetsByKey) {
        const first = keyTargets[0];
        requests.push(fetchPreviewObjectUrl(first.dataset.fileRefId, key, isFirstPage(first))
            .then((objectUrl) => {
                targetsOf(key).forEach((target) => {
                    if (!(target instanceof HTMLElement)) {
                        throw new Error('Image file preview target must remain HTMLElement');
                    }
                    applyPreviewObjectUrl(target, objectUrl);
                });
            })
            .catch((error) => {
            rethrowUnexpectedError(error);
                targetsOf(key).forEach((target) => {
                    if (!(target instanceof HTMLElement)) {
                        throw new Error('Image file preview target must remain HTMLElement');
                    }
                    applyPreviewFailure(target);
                });
            }));
    }
    return Promise.all(requests);
}
