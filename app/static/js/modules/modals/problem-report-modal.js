import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';

// Report a Problem… (docs/ready-to-build/error-reports.md §1): a sentence or two about what
// went wrong, in view while it is exported, and exactly what the report carries. Resolves to
// the text typed ('' allowed), or null when cancelled.

export const MAX_DESCRIPTION_CHARACTERS = 300;

export class ProblemReportModal extends BaseModal {
    constructor() {
        super('problemReportModal', 'problem-report-modal');
        this._pendingResolve = null;
        this._result = null;

        ApplicationState.own(this, 'ProblemReportModal', new.target === ProblemReportModal);
    }

    getInitialModalState() {
        return {};
    }

    ask() {
        if (this._pendingResolve !== null) {
            throw new Error('ProblemReportModal already has a pending promise');
        }
        this.open();
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
        });
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
            throw new Error('Problem report modal has no element');
        }
        modalElement.innerHTML = `
            <div class="modal-content problem-report-modal-content">
                <h3>Report a Problem</h3>
                <div class="form-group">
                    <label for="problem-report-description">What went wrong?</label>
                    <textarea id="problem-report-description" rows="3" maxlength="${MAX_DESCRIPTION_CHARACTERS}" data-modal-initial-focus></textarea>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'problem-report-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'problem-report-export-btn', label: 'Export', disabled: false, attributes: [],
                        isDestructive: false, isEnterAction: false, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        const { submit, cancel } = this._elements();
        submit.onclick = () => this._submit();
        cancel.onclick = () => this.close();
    }

    _elements() {
        const field = document.getElementById('problem-report-description');
        const submit = document.getElementById('problem-report-export-btn');
        const cancel = document.getElementById('problem-report-cancel-btn');
        if (!(field instanceof HTMLTextAreaElement) || !(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)) {
            throw new Error('Problem report modal is missing its field or buttons');
        }
        return { field, submit, cancel };
    }

    onOpen() {
        this._elements().field.focus();
    }

    _submit() {
        this._result = this._elements().field.value.trim();
        this.close();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._result;
        if (resolve !== null) this._pendingResolve = null;
        if (result !== null) this._result = null;
        if (resolve !== null) resolve(result);
    }
}
