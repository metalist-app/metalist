import { ApplicationState } from '../application-state.js';
import { HttpRequestError } from '../expected-errors.js';
import { settleResult } from '../async-result.js';
import { CONFIG } from '../config.js';
import { buildSessionHeaders } from '../session-auth.js';
import { BaseModal } from '../modals/base-modal.js';
import { actionRowHtml } from '../modals/action-row.js';
import { showErrorDialogFor, showOpenFailure } from '../modals/error-dialog.js';
import { ErrorHandler } from '../error-handler.js';
import { escapeHtml } from '../html-escape.js';
import { MS_PER_SECOND } from '../time-units.js';
import { captureActiveAgentScope } from './ai-chat-panel-controller.js';
import { runMenuProposalOperation } from './bulk-proposal-ui.js';
import { handleDictationPasteEvent } from '../mode-manager/services/dictation-paste-service.js';

export async function removeAllTagSuggestionsFromCurrentContext() {
    return await runMenuProposalOperation({
        action: 'remove',
        target: 'current',
        tag_filter: '',
        scope: captureActiveAgentScope(),
    });
}

// AI-Proposed Tags and AI Tagging Vocabulary: MetaList dialogs like every other (docs/ui/modals.md),
// with the shared button row; a refused or failed Apply/Save opens the error dialog over them,
// and Apply's result is a corner card (docs/ui/floating-messages.md).
const VIEWS = Object.freeze({
    proposals: { modalName: 'aiProposedTagsModal', elementId: 'ai-proposed-tags-modal' },
    vocabulary: { modalName: 'aiTaggingVocabularyModal', elementId: 'ai-tagging-vocabulary-modal' },
});
const RESULT_CARD_SECONDS = 6;

function proposalsFormHtml() {
    return `
        <h2>AI-Proposed Tags</h2>
        <p>Tags the AI chat proposed for your notes. They are not your tags until you accept them; the robot count on a note shows how many it has.</p>
        <label>Action <select name="action"><option value="accept">Accept the proposed tags</option><option value="remove">Reject the proposed tags</option></select></label>
        <label>Scope <select name="target"><option value="current">Current context</option><option value="vault">Entire vault</option></select></label>
        <label>Only this tag (leave blank for all proposed tags)<input name="tag" maxlength="256"></label>
        <p>This bulk operation clears undo/redo after successful changes.</p>
        ${actionRowHtml({
            alternative: null,
            cancel: { id: 'ai-proposals-cancel', label: 'Cancel', disabled: false, attributes: [] },
            main: {
                id: 'ai-proposals-apply', label: 'Apply', disabled: false, attributes: [],
                isDestructive: false, isEnterAction: true, type: 'button',
            },
            rowClass: '',
        })}`;
}

function vocabularyFormHtml(policy) {
    const option = (value, label) => `<option value="${escapeHtml(value)}"${value === policy ? ' selected' : ''}${value === '' ? ' disabled' : ''}>${escapeHtml(label)}</option>`;
    return `
        <h2>AI Tagging Vocabulary</h2>
        <p>Which tags the AI chat may propose when it tags your notes.</p>
        <label>Vocabulary <select name="policy">${option('', 'Not chosen yet')}${option('existing', 'Existing tags only')}${option('new', 'Existing and new tags')}</select></label>
        ${actionRowHtml({
            alternative: null,
            cancel: { id: 'ai-vocabulary-cancel', label: 'Cancel', disabled: false, attributes: [] },
            main: {
                id: 'ai-vocabulary-save', label: 'Save', disabled: false, attributes: [],
                isDestructive: false, isEnterAction: true, type: 'button',
            },
            rowClass: '',
        })}`;
}

async function loadVocabularyPolicy() {
    const response = await fetch(CONFIG.API.AI.CHAT.replace(/\/chat$/u, '/proposals/settings'), { headers: buildSessionHeaders(false) });
    if (!response.ok) throw new HttpRequestError('The tagging vocabulary could not be read. Try again in a moment.');
    const settings = await response.json();
    if (typeof settings.policy !== 'string') throw new Error('Tagging settings response missing policy');
    return settings.policy;
}

class AiTaggingModal extends BaseModal {
    constructor(preferences, settingsOnly) {
        const view = settingsOnly ? VIEWS.vocabulary : VIEWS.proposals;
        super(view.modalName, view.elementId);
        if (typeof settingsOnly !== 'boolean') {
            throw new Error('AiTaggingModal requires settingsOnly');
        }
        this._preferences = preferences;
        this._settingsOnly = settingsOnly;
        this._scope = captureActiveAgentScope();
        ApplicationState.own(this, 'AiTaggingModal', new.target === AiTaggingModal);
    }

    getInitialModalState() {
        return { policy: '' };
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

    // The vocabulary is read first; one that cannot be read leaves nothing to choose, so the
    // error dialog says why and closing it closes this one.
    async onOpen() {
        if (!this._settingsOnly) {
            return;
        }
        const generation = this._openGeneration;
        const loaded = await settleResult(() => loadVocabularyPolicy());
        if (!this.isCurrentOpen(generation)) return;
        if (!loaded.ok) {
            showOpenFailure(loaded.error, () => {
                if (this.isCurrentOpen(generation)) this.close();
            });
            return;
        }
        if (loaded.value !== this.getModalState().policy) {
            this.updateModalState({ policy: loaded.value });
            this.renderModalContent();
        }
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }
        const form = this._settingsOnly ? vocabularyFormHtml(this.getModalState().policy) : proposalsFormHtml();
        modalElement.innerHTML = `<div class="modal-content ai-tagging-modal-content">${form}</div>`;
        const cancelId = this._settingsOnly ? 'ai-vocabulary-cancel' : 'ai-proposals-cancel';
        modalElement.querySelector(`#${cancelId}`).addEventListener('click', () => this.requestClose());
        if (this._settingsOnly) {
            modalElement.querySelector('#ai-vocabulary-save').addEventListener('click', () => void this._save());
            return;
        }
        // Dictated text pasted into the tag filter becomes one tag.
        modalElement.querySelector('input[name="tag"]').addEventListener('paste', (event) => handleDictationPasteEvent(event, 'tag'));
        modalElement.querySelector('#ai-proposals-apply').addEventListener('click', () => void this._apply());
    }

    _field(name) {
        const field = document.querySelector(`#${this.modalElementId} [name="${name}"]`);
        if (!(field instanceof HTMLSelectElement) && !(field instanceof HTMLInputElement)) {
            throw new Error(`AI tagging field missing: ${name}`);
        }
        return field;
    }

    async _save() {
        const policy = this._field('policy').value;
        // Nothing to save until a vocabulary is chosen.
        if (policy !== '') {
            await this._preferences.setMany({ 'pref.ai.tagging.vocabulary': policy });
        }
        this.close();
    }

    async _apply() {
        const apply = document.getElementById('ai-proposals-apply');
        if (!(apply instanceof HTMLButtonElement)) {
            throw new Error('Apply button missing');
        }
        apply.disabled = true;
        const payload = {
            action: this._field('action').value, target: this._field('target').value,
            tag_filter: this._field('tag').value.trim(), scope: this._scope,
        };
        const result = await settleResult(() => runMenuProposalOperation(payload));
        apply.disabled = false;
        if (!result.ok) {
            await showErrorDialogFor(result.error, null);
            return;
        }
        ErrorHandler.showInfoBanner(`${result.value.proposals} proposals updated across ${result.value.notes} notes.`, RESULT_CARD_SECONDS * MS_PER_SECOND);
    }
}

export async function openProposalMenu(preferences, settingsOnly) {
    await new AiTaggingModal(preferences, settingsOnly).open();
}
