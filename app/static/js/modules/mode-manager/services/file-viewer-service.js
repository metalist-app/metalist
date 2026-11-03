import { ApplicationState } from '../../application-state.js';
import { FilesAPI } from '../../api-client.js';
import { downloadEmailAttachment, downloadFileReference } from './file-reference-service.js';
import { formatByteSize } from '../../byte-sizes.js';
import { hydrateRemoteImageProxies } from './remote-image-proxy-service.js';
import { serverRenderedHtml } from '../../server-rendered-html.js';

// The file viewer (docs/ready-to-build/files-shown-not-copied.md §4; the maintainer, 2026-11-03):
// a file opened from its card, over MetaList as Zoom Image is, made when opened and never
// stored. A PDF in the browser's own viewer, from a blob: made of the downloaded file (the
// page's policy frames blob: only); every other kind as the server draws it, as its note would
// look. Its bar: the file's name, Download and ×; Esc or a click outside closes it. Cmd+F in
// it is the browser's own find; no key reaches MetaList meanwhile. Every other kind is drawn
// in a frame of its own: drawn as a note, it is no note of the list's, and in the page the
// list's handlers for notes took it for one (2026-11-03: moving the pointer off it failed
// loudly, "Note element missing data-note-id"). A shadow root kept them out but lost the dark
// theme's rules (html[data-theme]); the frame's document has the page's theme and stylesheet.

const PDF_TYPE = 'application/pdf';
const PDF_VIEW = 'pdf';
// An email (or a web page saved whole): its headers above its body, its attachments below
// (the maintainer, 2026-11-03: emails open in the viewer, nothing of them drawn in the note).
const EMAIL_VIEW = 'email';
const EMAIL_DOCUMENT_CLASS = 'is-email';
const EMAIL_HEADER_ROWS = Object.freeze([['from', 'From'], ['to', 'To'], ['cc', 'Cc'], ['date', 'Date']]);
const READY = 'ready';
// Why a file shows nothing, by the server's status (file_view.py).
const UNSHOWN_MESSAGES = {
    not_readable: 'This file couldn\'t be read.',
    too_large: 'This file is too large to show.',
    no_text: 'This file has nothing to show.',
};
const CUT_MESSAGE = 'The rest of this file is in its download.';
const FIND_KEY = 'f';
// The drawn file's document: the list's stylesheet, the viewer's, and links opening outside it.
const DRAWING_DOCUMENT = '<!doctype html><html class="file-viewer-document"><head><meta charset="utf-8">'
    + '<link rel="stylesheet" href="/static/css/main.css"><link rel="stylesheet" href="/static/css/file-viewer.css">'
    + '<base target="_blank"></head><body></body></html>';

const moduleState = ApplicationState.createFields('file-viewer', {
    overlay: null,
    objectUrl: null,
});

/** Whether a click on button opens the viewer: Open, or a file linked in text that the viewer
 * shows (its data-file-view is set); any other file button downloads. */
export function opensInViewer(button) {
    if (button.classList.contains('note-file-open')) return true;
    return button.classList.contains('note-file-reference-link') && button.dataset.fileView !== '';
}

export function isFileViewerOpen() {
    return moduleState.overlay !== null;
}

/** Open fileId in the viewer (closing any viewer open). */
export async function openFileViewer(fileId) {
    if (typeof fileId !== 'string' || fileId === '') {
        throw new Error('openFileViewer requires a file id');
    }
    const view = await FilesAPI.viewFile(fileId);
    closeFileViewer();
    const overlay = buildOverlay(fileId, view.name);
    const body = overlay.querySelector('.file-viewer-body');
    if (view.kind === PDF_VIEW) {
        const downloaded = await FilesAPI.downloadFile(fileId);
        // A named file, so the PDF viewer's bar can name it.
        moduleState.objectUrl = URL.createObjectURL(new File([downloaded.blob], view.name, { type: PDF_TYPE }));
        const frame = document.createElement('iframe');
        frame.className = 'file-viewer-pdf';
        frame.title = view.name;
        frame.src = moduleState.objectUrl;
        body.appendChild(frame);
    } else if (view.status !== READY && view.kind !== EMAIL_VIEW) {
        body.appendChild(messageElement(unshownMessage(view.status)));
    }
    moduleState.overlay = overlay;
    document.body.appendChild(overlay);
    window.addEventListener('keydown', handleViewerKeyDown, { capture: true });
    overlay.querySelector('.file-viewer-close').focus({ preventScroll: true });
    if (view.kind === EMAIL_VIEW || (view.kind !== PDF_VIEW && view.status === READY)) {
        await drawFile(body, view, fileId);
    }
}

export function closeFileViewer() {
    if (moduleState.overlay === null) return;
    moduleState.overlay.remove();
    moduleState.overlay = null;
    if (moduleState.objectUrl !== null) {
        URL.revokeObjectURL(moduleState.objectUrl);
        moduleState.objectUrl = null;
    }
    window.removeEventListener('keydown', handleViewerKeyDown, { capture: true });
}

function buildOverlay(fileId, name) {
    const overlay = document.createElement('div');
    overlay.className = 'file-viewer-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', name);
    const panel = document.createElement('div');
    panel.className = 'file-viewer-panel';
    const bar = document.createElement('div');
    bar.className = 'file-viewer-bar';
    const title = document.createElement('span');
    title.className = 'file-viewer-name';
    title.textContent = name;
    title.title = name;
    const download = document.createElement('button');
    download.type = 'button';
    download.className = 'file-viewer-download';
    download.textContent = 'Download';
    download.title = `Download ${name}`;
    download.addEventListener('click', () => {
        void downloadFileReference(fileId);
    });
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'file-viewer-close';
    close.setAttribute('aria-label', 'Close');
    close.title = 'Close (Esc)';
    close.textContent = '×';
    close.addEventListener('click', closeFileViewer);
    bar.append(title, download, close);
    const body = document.createElement('div');
    body.className = 'file-viewer-body';
    panel.append(bar, body);
    overlay.appendChild(panel);
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) closeFileViewer();
    });
    return overlay;
}

// The server's drawing, sanitized there as a note's (note_fullscreen.build_file_view_markup),
// in its frame, shown once its stylesheets have loaded. A frame loads once it is in the page.
function unshownMessage(status) {
    if (!Object.hasOwn(UNSHOWN_MESSAGES, status)) {
        throw new Error(`Unknown file view status: ${status}`);
    }
    return UNSHOWN_MESSAGES[status];
}

async function drawFile(body, view, fileId) {
    const frame = document.createElement('iframe');
    frame.className = 'file-viewer-drawing';
    frame.title = view.name;
    frame.style.visibility = 'hidden';
    const loaded = new Promise((resolve) => {
        frame.addEventListener('load', resolve, { once: true });
    });
    frame.srcdoc = DRAWING_DOCUMENT;
    body.appendChild(frame);
    await loaded;
    // Closed, or another file opened, while it loaded.
    if (!body.isConnected) return;
    const drawing = frame.contentDocument;
    // The page's theme: a chosen one is set on its root; the system's is none.
    if (document.documentElement.hasAttribute('data-theme')) {
        drawing.documentElement.dataset.theme = document.documentElement.dataset.theme;
    }
    drawing.body.innerHTML = serverRenderedHtml(view.html);
    if (view.isCut) drawing.body.appendChild(messageElement(CUT_MESSAGE));
    if (view.kind === EMAIL_VIEW) {
        // Web HTML: its tables are its layout, drawn without a document table's lines.
        drawing.documentElement.classList.add(EMAIL_DOCUMENT_CLASS);
        drawEmail(drawing, view, fileId);
        // Its pictures from the web, through MetaList's image proxy, now that it is opened.
        void hydrateRemoteImageProxies(drawing.body);
    }
    // Keys pressed in the drawn file are the viewer's too: Esc closes it.
    frame.contentWindow.addEventListener('keydown', handleViewerKeyDown, { capture: true });
    frame.style.visibility = '';
}

// The email's subject and From, To, Cc and Date above its body; its attachments, each a button
// that downloads it, below; a body with nothing to show says so between them.
function drawEmail(drawing, view, fileId) {
    const email = view.email;
    if (email === null || typeof email !== 'object' || !Array.isArray(email.attachments)) {
        throw new Error('An email view needs its headers and attachments');
    }
    const make = (tagName, className, text) => {
        const node = drawing.createElement(tagName);
        node.className = className;
        if (text !== '') node.textContent = text;
        return node;
    };
    const header = make('header', 'file-viewer-email-header', '');
    if (email.subject !== '') header.appendChild(make('h1', 'file-viewer-email-subject', email.subject));
    const rows = make('dl', 'file-viewer-email-rows', '');
    for (const [field, label] of EMAIL_HEADER_ROWS) {
        if (email[field] === '') continue;
        const row = make('div', 'file-viewer-email-row', '');
        row.append(make('dt', 'file-viewer-email-label', label), make('dd', 'file-viewer-email-value', email[field]));
        rows.appendChild(row);
    }
    header.appendChild(rows);
    drawing.body.prepend(header);
    if (view.status !== READY) drawing.body.appendChild(messageElement(unshownMessage(view.status)));
    if (email.attachments.length === 0) return;
    const list = make('div', 'file-viewer-email-attachments', '');
    email.attachments.forEach((attachment, index) => {
        const button = make('button', 'file-viewer-email-attachment', '');
        button.type = 'button';
        button.title = `Download ${attachment.name}`;
        button.append(
            make('span', 'file-viewer-email-attachment-name', attachment.name),
            make('span', 'file-viewer-email-attachment-size', formatByteSize(attachment.sizeBytes)),
        );
        button.addEventListener('click', () => {
            void downloadEmailAttachment(fileId, index);
        });
        list.appendChild(button);
    });
    drawing.body.appendChild(list);
}

function messageElement(text) {
    const message = document.createElement('p');
    message.className = 'file-viewer-message';
    message.textContent = text;
    return message;
}

// Keys stay with the viewer: Esc closes it; Cmd+F (Ctrl+F) is the browser's own find, so it is
// kept from MetaList's find but not prevented; every other key goes no further than the viewer.
function handleViewerKeyDown(event) {
    if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeFileViewer();
        return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === FIND_KEY) {
        event.stopImmediatePropagation();
        return;
    }
    event.stopImmediatePropagation();
}
