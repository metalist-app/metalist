import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';

// Export Problem Reports… (docs/ready-to-build/error-reports.md §4): the kept reports, newest
// first, each with when it was made and what made it (the error's class, or Reported), all
// ticked. Resolves to the ids ticked, or null when cancelled.

const REPORTED = 'Reported';
const UNNAMED_ERROR = 'Error';
const MS_PER_SECOND = 1000;

function kindOf(summary) {
    if (summary.madeBy === 'user') return REPORTED;
    return summary.errorClass === '' ? UNNAMED_ERROR : summary.errorClass;
}

function whenOf(summary) {
    return new Date(summary.madeAt * MS_PER_SECOND).toLocaleString();
}

export class ProblemReportsExportModal extends BaseModal {
    constructor() {
        super('problemReportsExportModal', 'problem-reports-export-modal');
        this._pendingResolve = null;
        this._summaries = null;
        this._result = null;

        ApplicationState.own(this, 'ProblemReportsExportModal', new.target === ProblemReportsExportModal);
    }

    getInitialModalState() {
        return {};
    }

    askFor(summaries) {
        if (!Array.isArray(summaries) || summaries.length === 0) {
            throw new Error('ProblemReportsExportModal needs the kept reports');
        }
        if (this._pendingResolve !== null) {
            throw new Error('ProblemReportsExportModal already has a pending promise');
        }
        this._summaries = summaries;
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
        if (!(modalElement instanceof HTMLElement) || this._summaries === null) {
            throw new Error('Problem reports export modal has no element or reports');
        }
        const rows = this._summaries.map((summary) => `
            <label class="problem-reports-row">
                <input type="checkbox" checked data-report-id="${escapeHtml(summary.reportId)}">
                <span class="problem-reports-when">${escapeHtml(whenOf(summary))}</span>
                <span class="problem-reports-kind">${escapeHtml(kindOf(summary))}</span>
            </label>`).join('');
        modalElement.innerHTML = `
            <div class="modal-content problem-reports-export-modal-content">
                <h3>Export Problem Reports</h3>
                <div class="problem-reports-list">${rows}</div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'problem-reports-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'problem-reports-export-btn', label: 'Export', disabled: false, attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        const submit = document.getElementById('problem-reports-export-btn');
        const cancel = document.getElementById('problem-reports-cancel-btn');
        if (!(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)) {
            throw new Error('Problem reports export modal is missing its buttons');
        }
        for (const box of this._boxes()) {
            box.onchange = () => {
                const isNoneTicked = this._ticked().length === 0;
                if (submit.disabled !== isNoneTicked) submit.disabled = isNoneTicked;
            };
        }
        submit.onclick = () => {
            this._result = this._ticked();
            this.close();
        };
        cancel.onclick = () => this.close();
    }

    _boxes() {
        return [...document.querySelectorAll(`#${this.modalElementId} input[data-report-id]`)];
    }

    _ticked() {
        return this._boxes().filter((box) => box.checked).map((box) => box.dataset.reportId);
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._result;
        if (resolve !== null) this._pendingResolve = null;
        if (this._summaries !== null) this._summaries = null;
        if (result !== null) this._result = null;
        if (resolve !== null) resolve(result);
    }
}
