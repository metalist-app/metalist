import { ApplicationState } from '../../application-state.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';
import { FilesAPI } from '../../api-client.js';


const moduleState = ApplicationState.createFields('file-image-preview-service', {
    previewCache: new Map(),
    pendingPreviewRequests: new Map(),
    // Natural size of each loaded image file, for this page session: when the
    // same image renders again (e.g. after its note leaves edit mode) its frame
    // is sized up front, so text below it does not move while it loads.
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
        if (imageElement.naturalWidth > 0 && imageElement.naturalHeight > 0 && moduleState.previewSizes.get(fileId) !== size) {
            moduleState.previewSizes.set(fileId, size);
        }
    }, { once: true });
    imageElement.src = objectUrl;
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

async function fetchPreviewObjectUrl(fileId) {
    if (typeof fileId !== 'string' || fileId.length === 0) {
        throw new Error('fetchPreviewObjectUrl expects fileId');
    }

    if (moduleState.previewCache.has(fileId)) {
        return moduleState.previewCache.get(fileId).objectUrl;
    }
    if (moduleState.pendingPreviewRequests.has(fileId)) {
        return await moduleState.pendingPreviewRequests.get(fileId);
    }

    ensureCleanupHandlerRegistered();

    const request = FilesAPI.downloadFile(fileId)
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
            if (moduleState.pendingPreviewRequests.get(fileId) !== request) {
                throw new DOMException('Image preview canceled by page cleanup', 'AbortError');
            }
            const objectUrl = URL.createObjectURL(payload.blob);
            moduleState.previewCache.set(fileId, { objectUrl });
            return objectUrl;
        })
        .finally(() => {
            if (moduleState.pendingPreviewRequests.get(fileId) === request) {
                moduleState.pendingPreviewRequests.delete(fileId);
            }
        });

    moduleState.pendingPreviewRequests.set(fileId, request);
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

    // The targets under `rootNode` by file: the document cannot find those in a shadow
    // root (a reference's preview card), so they are filled as well as the document's.
    const targetsByFile = new Map();
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
        if (!targetsByFile.has(fileId)) targetsByFile.set(fileId, []);
        targetsByFile.get(fileId).push(target);
    }

    const targetsOf = (fileId) => new Set([
        ...targetsByFile.get(fileId),
        ...document.querySelectorAll(`.note-file-image-embed[data-file-ref-id="${fileId}"]`),
    ]);
    const requests = [];
    for (const fileId of targetsByFile.keys()) {
        requests.push(fetchPreviewObjectUrl(fileId)
            .then((objectUrl) => {
                targetsOf(fileId).forEach((target) => {
                    if (!(target instanceof HTMLElement)) {
                        throw new Error('Image file preview target must remain HTMLElement');
                    }
                    applyPreviewObjectUrl(target, objectUrl);
                });
            })
            .catch((error) => {
            rethrowUnexpectedError(error);
                targetsOf(fileId).forEach((target) => {
                    if (!(target instanceof HTMLElement)) {
                        throw new Error('Image file preview target must remain HTMLElement');
                    }
                    applyPreviewFailure(target);
                });
            }));
    }
    return Promise.all(requests);
}
