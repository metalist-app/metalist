import { ApplicationState } from '../../application-state.js';
import { FilesAPI } from '../../api-client.js';
import { formatByteSize } from '../../byte-sizes.js';
import { serverRenderedHtml } from '../../server-rendered-html.js';
import { hydrateRemoteImageProxies } from './remote-image-proxy-service.js';
import { ensureAnchorsOpenInNewTabs } from './link-target-service.js';

// Email files (.eml) as cards (docs/ui/references.md, "Email files"; agreed 2026-10-29).
// The server draws a placeholder where an email is embedded; this fills it in from
// GET /files/{id}/email: the subject, then From, To, Cc and Date, then the body (the
// HTML version, sanitized by the server, or the plain text), then the attachments, each
// a button that downloads it. A long body is cut with a fade; Show all opens it whole.
// Folded (the note's ▾/▸), the card is one line, drawn as a file's pill: EML, the
// subject, the sender's name.
// Remote pictures go through MetaList's image proxy, and links open in a new tab.

const TARGET_SELECTOR = '.note-file-email-embed[data-preview-state="idle"]';
const HEADER_ROWS = Object.freeze([['from', 'From'], ['to', 'To'], ['cc', 'Cc'], ['date', 'Date']]);
const EXPANDED_CLASS = 'is-expanded';
const SHOW_ALL = 'Show all';
const SHOW_LESS = 'Show less';

const moduleState = ApplicationState.createFields('file-email-preview-service', {
    // Each email read once per revision of its file, for this page: { [fileId:revision]: Promise }.
    reads: new Map(),
});

function element(tagName, className, text) {
    const node = document.createElement(tagName);
    node.className = className;
    if (text !== '') node.textContent = text;
    return node;
}

function readEmail(fileId, revision) {
    const key = `${fileId}:${revision}`;
    if (!moduleState.reads.has(key)) moduleState.reads.set(key, FilesAPI.getEmail(fileId));
    return moduleState.reads.get(key);
}

function headersOf(email) {
    const headers = element('dl', 'note-file-email-headers', '');
    for (const [field, label] of HEADER_ROWS) {
        if (email[field] === '') continue;
        const row = element('div', 'note-file-email-header', '');
        row.append(element('dt', 'note-file-email-header-name', label), element('dd', 'note-file-email-header-value', email[field]));
        headers.append(row);
    }
    return headers;
}

function bodyOf(email) {
    const body = element('div', 'note-file-email-body', '');
    if (email.html !== '') {
        body.innerHTML = serverRenderedHtml(email.html);
    } else if (email.text !== '') {
        body.append(element('div', 'note-file-email-text', email.text));
    }
    return body;
}

function attachmentsOf(fileId, email) {
    const list = element('div', 'note-file-email-attachments', '');
    email.attachments.forEach((attachment, index) => {
        const button = element('button', 'note-file-email-attachment', '');
        button.type = 'button';
        button.dataset.fileRefId = fileId;
        button.dataset.attachmentIndex = String(index);
        button.title = `Download ${attachment.name}`;
        button.append(
            element('span', 'note-file-email-attachment-name', attachment.name),
            element('span', 'note-file-email-attachment-size', formatByteSize(attachment.sizeBytes)),
        );
        list.append(button);
    });
    return list;
}

// The card's line when its note is folded: shown only then (main.css).
function foldedLineOf(email) {
    // A span: a folded note makes every div of its content a block.
    const line = element('span', 'note-file-email-line', '');
    line.append(element('span', 'note-file-reference-badge', 'EML'));
    if (email.subject !== '') line.append(element('span', 'note-file-email-line-subject', email.subject));
    if (email.fromName !== '') line.append(element('span', 'note-file-email-line-sender', email.fromName));
    return line;
}

function cardOf(fileId, email) {
    const card = element('div', 'note-file-email-card', '');
    if (!email.isReadable) {
        card.append(element('div', 'note-file-email-unreadable', 'Not a readable email'));
        return card;
    }
    card.append(foldedLineOf(email));
    if (email.subject !== '') card.append(element('div', 'note-file-email-subject', email.subject));
    card.append(headersOf(email), bodyOf(email));
    if (email.attachments.length > 0) card.append(attachmentsOf(fileId, email));
    const more = element('button', 'note-file-email-more', SHOW_ALL);
    more.type = 'button';
    more.hidden = true;
    card.append(more);
    return card;
}

// Show all only when the body is cut.
function offerShowAll(card) {
    const body = card.querySelector('.note-file-email-body');
    const more = card.querySelector('.note-file-email-more');
    if (body === null || more === null) return;
    more.hidden = body.scrollHeight <= body.clientHeight;
}

async function fill(target) {
    const fileId = target.dataset.fileRefId;
    const revision = target.dataset.fileRevision;
    if (typeof fileId !== 'string' || fileId === '' || typeof revision !== 'string' || revision === '') {
        throw new Error('Email card target missing its file id or revision');
    }
    target.dataset.previewState = 'loading';
    const email = await readEmail(fileId, revision);
    const card = cardOf(fileId, email);
    target.replaceChildren(card);
    target.dataset.previewState = 'loaded';
    hydrateRemoteImageProxies(card);
    ensureAnchorsOpenInNewTabs(card);
    offerShowAll(card);
}

// Fills in every email card under `rootNode` not filled in yet (in the list, a floating
// window, full screen or a reference's preview card).
export function hydrateEmailPreviews(rootNode) {
    if (!rootNode || typeof rootNode.querySelectorAll !== 'function') {
        throw new Error('hydrateEmailPreviews requires a root node');
    }
    return Promise.all([...rootNode.querySelectorAll(TARGET_SELECTOR)].map(fill));
}

// Show all / Show less on a card: the user's own choice, so the card grows or shrinks in place.
export function toggleEmailBody(button) {
    const card = button.closest('.note-file-email-card');
    if (card === null) {
        throw new Error('Show all must be inside an email card');
    }
    const isExpanded = card.classList.toggle(EXPANDED_CLASS);
    button.textContent = isExpanded ? SHOW_LESS : SHOW_ALL;
}
