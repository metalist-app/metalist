import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';
import { ModeContextInstance as ModeContext } from '../mode-manager/mode-context.js';
import { SUMMARY_KINDS } from '../mode-manager/services/summary-service.js';

// Summary…: a calculation and a property, shown beside the result count over the notes
// the view finds (summary-service.js). The properties are those used on any tag, most
// used first. Resolves with the chosen { kind, property }, or null when cancelled.

export class SummaryModal extends BaseModal {
    constructor() {
        super('summaryModal', 'summary-modal');
        this._pendingResolve = null;
        this._context = null;
        this._decision = null;

        ApplicationState.own(this, 'SummaryModal', new.target === SummaryModal);
    }

    getInitialModalState() {
        if (this._context === null) {
            throw new Error('SummaryModal requires context before initialization');
        }
        return { ...this._context };
    }

    validateCleanState() {
        if (ModeContext.isLoading) {
            throw new Error('Cannot open the summary dialog while application is loading');
        }
        if (ModeContext.modalStack && ModeContext.modalStack.length > 0) {
            throw new Error(`Cannot open the summary dialog while ${ModeContext.topModal} is open`);
        }
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

    /** context: { kind, property } chosen now (kind 'sum' and the first name when none), and the names to offer. */
    openForSummary(context) {
        if (!context || typeof context !== 'object' || !Array.isArray(context.propertyNames)) {
            throw new Error('SummaryModal.openForSummary requires the property names');
        }
        if (!SUMMARY_KINDS.some(([kind]) => kind === context.kind) || typeof context.property !== 'string') {
            throw new Error('SummaryModal.openForSummary requires a kind and a property');
        }
        if (this.isOpen || this._pendingResolve !== null) {
            throw new Error('SummaryModal is already open');
        }
        this._context = { kind: context.kind, property: context.property, propertyNames: [...context.propertyNames] };
        this._decision = { result: null };
        this.open();
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
        });
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._decision.result;
        this._pendingResolve = null;
        this._decision = null;
        this._context = null;
        if (resolve !== null) {
            resolve(result);
        }
    }

    onKeyDown(event) {
        if (!(event instanceof KeyboardEvent)) {
            throw new Error('SummaryModal.onKeyDown requires KeyboardEvent');
        }
        if (event.key !== 'Enter' || document.activeElement instanceof HTMLButtonElement) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        this.submit();
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error('Summary modal element missing');
        }
        const state = this.getModalState();
        const kinds = SUMMARY_KINDS.map(([kind, label]) => (
            `<option value="${kind}" ${kind === state.kind ? 'selected' : ''}>${escapeHtml(label)}</option>`
        )).join('');
        const names = state.propertyNames.map((name) => (
            `<option value="${escapeHtml(name)}" ${name === state.property ? 'selected' : ''}>${escapeHtml(name)}</option>`
        )).join('');
        const hasNames = state.propertyNames.length > 0;
        modalElement.innerHTML = `
            <div class="modal-content summary-modal-content">
                <div class="prioritize-modal-header">
                    <h3>Summary</h3>
                </div>
                <div class="summary-modal-fields">
                    <label for="summary-kind">Calculation</label><select id="summary-kind">${kinds}</select>
                    <label for="summary-property">Property</label><select id="summary-property" ${hasNames ? '' : 'disabled'}>${names}</select>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'summary-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'summary-apply-btn', label: 'Show', disabled: !hasNames, attributes: [],
                        isDestructive: false, isEnterAction: false, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        document.getElementById('summary-cancel-btn').onclick = () => this.close();
        const applyButton = document.getElementById('summary-apply-btn');
        applyButton.onclick = () => this.submit();
        if (!hasNames) {
            applyButton.title = 'No note has a property yet (for example calories=300)';
        }
        this._requireSelect('summary-kind').focus();
    }

    _requireSelect(id) {
        const select = document.getElementById(id);
        if (!(select instanceof HTMLSelectElement)) {
            throw new Error(`Summary select ${id} missing`);
        }
        return select;
    }

    submit() {
        const property = this._requireSelect('summary-property');
        if (property.disabled || property.value === '') {
            return;
        }
        this._decision.result = { kind: this._requireSelect('summary-kind').value, property: property.value };
        this.close();
    }
}
