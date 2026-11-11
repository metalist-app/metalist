import { ApplicationState } from '../application-state.js';
import { settleResult } from '../async-result.js';
import { BaseModal } from '../modals/base-modal.js';
import { actionRowHtml } from '../modals/action-row.js';
import { showErrorDialogFor } from '../modals/error-dialog.js';
import { ErrorHandler } from '../error-handler.js';
import { MS_PER_SECOND } from '../time-units.js';
import { captureActiveAgentScope } from './ai-chat-panel-controller.js';
import { runMenuProposalOperation } from './bulk-proposal-ui.js';
import { attachTagSuggestions } from '../tag-input-suggestions.js';
import { handleDictationPasteEvent } from '../mode-manager/services/dictation-paste-service.js';

export async function removeAllTagSuggestionsFromCurrentContext() {
    return await runMenuProposalOperation({
        action: 'remove',
        target: 'current',
        tag_filter: '',
        scope: captureActiveAgentScope(),
    });
}

// AI-Proposed Tags: a MetaList dialog like every other (docs/ui/modals.md), with the shared
// button row; a refused or failed Apply opens the error dialog over it, and Apply's result is
// a corner card (docs/ui/floating-messages.md). Which tags the AI may propose is set on AI
// Agent Settings' Tagging tab.
const MODAL_NAME = 'aiProposedTagsModal';
const MODAL_ELEMENT_ID = 'ai-proposed-tags-modal';
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

class AiProposalsModal extends BaseModal {
    constructor() {
        super(MODAL_NAME, MODAL_ELEMENT_ID);
        this._scope = captureActiveAgentScope();
        ApplicationState.own(this, 'AiProposalsModal', new.target === AiProposalsModal);
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

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }
        modalElement.innerHTML = `<div class="modal-content ai-tagging-modal-content">${proposalsFormHtml()}</div>`;
        modalElement.querySelector('#ai-proposals-cancel').addEventListener('click', () => this.requestClose());
        // Dictated text pasted into the tag filter becomes one tag.
        const tagInput = modalElement.querySelector('input[name="tag"]');
        tagInput.addEventListener('paste', (event) => handleDictationPasteEvent(event, 'tag'));
        tagInput.setAttribute('autocomplete', 'off');
        attachTagSuggestions(tagInput, { chosenTags: () => [], onPick: (tag) => { tagInput.value = tag; } });
        modalElement.querySelector('#ai-proposals-apply').addEventListener('click', () => void this._apply());
    }

    _field(name) {
        const field = document.querySelector(`#${this.modalElementId} [name="${name}"]`);
        if (!(field instanceof HTMLSelectElement) && !(field instanceof HTMLInputElement)) {
            throw new Error(`AI tagging field missing: ${name}`);
        }
        return field;
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

export async function openProposalMenu() {
    await new AiProposalsModal().open();
}
