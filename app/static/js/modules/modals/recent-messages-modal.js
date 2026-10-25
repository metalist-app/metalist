import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { escapeHtml } from '../html-escape.js';
import { FloatingMessages } from '../floating-messages.js';

// Recent Messages: what the floating messages said since this page opened, newest first,
// so a card that left before it was read is not lost. Kept in memory only.
export class RecentMessagesModal extends BaseModal {
    constructor() {
        super('recentMessagesModal', 'recent-messages-modal');
        ApplicationState.own(this, 'RecentMessagesModal', new.target === RecentMessagesModal);
    }

    getInitialModalState() {
        return {};
    }

    showModalElement() {
        let modalElement = document.getElementById(this.modalElementId);
        if (!modalElement) {
            modalElement = document.createElement('div');
            modalElement.id = this.modalElementId;
            modalElement.className = 'modal';
            modalElement.style.display = 'none';
            document.body.appendChild(modalElement);
        }
        this.renderModalContent();
        modalElement.style.display = 'block';
    }

    _rowsHtml(messages) {
        return messages.map(message => {
            const time = new Date(message.shownAtMs).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
            const detail = message.detail === '' ? '' : ` title="${escapeHtml(message.detail)}"`;
            return `<li class="recent-message recent-message-${escapeHtml(message.type)}"${detail}>
                <span class="recent-message-time">${escapeHtml(time)}</span>
                <span class="recent-message-text">${escapeHtml(message.text)}</span>
            </li>`;
        }).join('');
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error('Recent messages modal element missing');
        }
        const messages = FloatingMessages.recentMessages();
        const body = messages.length === 0
            ? '<p class="note-layout-description">No messages yet.</p>'
            : `<ul class="recent-messages-list">${this._rowsHtml(messages)}</ul>`;
        modalElement.innerHTML = `
            <div class="modal-content recent-messages-modal-content">
                <h2>Recent Messages</h2>
                ${body}
            </div>
        `;
    }
}
