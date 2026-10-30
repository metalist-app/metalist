import { parseDecimalInteger } from '../decimal-integer.js';
import { ApplicationState } from '../application-state.js';
import { FieldInputRejected, HttpRequestError, rethrowUnexpectedError } from '../expected-errors.js';
import { BaseModal } from './base-modal.js';
import { CONFIG } from '../config.js';
import { buildSessionHeaders } from '../session-auth.js';
import { escapeHtml } from '../html-escape.js';
import { actionRowHtml } from './action-row.js';
import { failureFieldId, showErrorDialog, showErrorDialogFor, showOpenFailure } from './error-dialog.js';


// The id of a vault's checkbox.
function vaultCheckboxId(namespace) {
    return `backup-settings-vault-${namespace}`;
}


function parseResponseError(responseBody, statusCode) {
    if (responseBody && typeof responseBody === 'object') {
        if (typeof responseBody.detail === 'string' && responseBody.detail.length > 0) {
            return `Request failed (${statusCode}): ${responseBody.detail}`;
        }
        if (typeof responseBody.message === 'string' && responseBody.message.length > 0) {
            return `Request failed (${statusCode}): ${responseBody.message}`;
        }
    }
    return `Request failed (${statusCode})`;
}



export class BackupSettingsModal extends BaseModal {
    constructor() {
        super('backupSettingsModal', 'backup-settings-modal');
        this._pendingResolve = null;
        this._decision = null;
        this._pendingRunBackup = null;

        ApplicationState.own(this, 'BackupSettingsModal', new.target === BackupSettingsModal);
    }

    getInitialModalState() {
        return {
            loading: false,
            saving: false,
            pickingFolder: false,
            folderPath: '',
            selectedNamespaces: [],
            availableNamespaces: [],
            currentNamespace: '',
            // [{ label, path }]: Downloads, then a MetaList Backups folder in each synced folder found.
            suggestedFolders: [],
            retentionCountText: '30',
            statusMessage: '',
        };
    }


    _hasActiveOperation() {
        const state = this.getModalState();
        return [state.loading, state.saving, state.pickingFolder].includes(true);
    }

    canRequestClose() {
        return !this._hasActiveOperation();
    }

    handleKeyDown(event) {
        if (!(event instanceof KeyboardEvent)) {
            throw new Error('BackupSettingsModal.handleKeyDown requires KeyboardEvent');
        }
        if (this._hasActiveOperation() && (event.key === 'Escape' || event.key === 'Enter')) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        super.handleKeyDown(event);
    }

    handleClickOutside(event) {
        if (!event || typeof event !== 'object') {
            throw new Error('BackupSettingsModal.handleClickOutside requires event object');
        }
        if (this._hasActiveOperation() && event.target === event.currentTarget) {
            return;
        }
        super.handleClickOutside(event);
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

    openForBackup() {
        if (this.isOpen) {
            throw new Error('BackupSettingsModal is already open');
        }
        if (this._pendingResolve !== null) {
            throw new Error('BackupSettingsModal already has a pending promise');
        }
        this._decision = { result: { action: 'cancel' } };
        this.open();
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
        });
    }

    async onOpen() {
        await this.loadSettings();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const closeResult = this._decision.result;
        this._pendingResolve = null;
        this._decision = null;
        if (resolve !== null) {
            resolve(closeResult);
        }
    }

    onKeyDown(event) {
        if (!(event instanceof KeyboardEvent)) {
            throw new Error('BackupSettingsModal.onKeyDown requires KeyboardEvent');
        }
        if (event.key !== 'Enter') {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        void this.handleRunBackup();
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!modalElement) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }
        const state = this.getModalState();
        const loading = Boolean(state.loading);
        const saving = Boolean(state.saving);
        const pickingFolder = Boolean(state.pickingFolder);
        const folderPath = typeof state.folderPath === 'string' ? state.folderPath : '';
        const selectedNamespaces = Array.isArray(state.selectedNamespaces) ? state.selectedNamespaces : [];
        const availableNamespaces = Array.isArray(state.availableNamespaces) ? state.availableNamespaces : [];
        const currentNamespace = typeof state.currentNamespace === 'string' ? state.currentNamespace : '';
        const retentionCountText = typeof state.retentionCountText === 'string' ? state.retentionCountText : '';
        const statusMessage = typeof state.statusMessage === 'string' ? state.statusMessage : '';
        const showNamespaceSelection = availableNamespaces.length > 1;
        const singleNamespaceLabel = availableNamespaces.length > 0 ? availableNamespaces[0] : '';
        const namespaceSelectionHtml = showNamespaceSelection
            ? availableNamespaces.map((namespace) => {
                // The vault in use is always backed up: checked, and locked. It looks checked like
                // the others (a disabled box draws grey, which reads as unsure); clicks do nothing.
                const isCurrent = namespace === currentNamespace;
                const checked = [isCurrent, selectedNamespaces.includes(namespace)].includes(true);
                const locked = isCurrent ? ' title="The vault you&#39;re in is always backed up" data-backup-current="true"' : '';
                return `
                    <label class="backup-settings-checkbox-row backup-settings-namespace-row"${locked}>
                        <input type="checkbox" id="${escapeHtml(vaultCheckboxId(namespace))}" data-backup-namespace="${escapeHtml(namespace)}" ${checked ? 'checked' : ''} ${isCurrent ? 'aria-disabled="true"' : ''} ${loading || saving ? 'disabled' : ''}>
                        <span>${escapeHtml(namespace)}</span>
                    </label>
                `;
            }).join('')
            : `<p class="backup-settings-single-namespace"><strong>Vault:</strong> ${escapeHtml(singleNamespaceLabel)}</p>`;

        // Downloads, and synced folders that keep backups off this computer (docs/ui/command-palette.md, `Back Up Now…`).
        const suggestedFolders = Array.isArray(state.suggestedFolders) ? state.suggestedFolders : [];
        const syncedFoldersHtml = suggestedFolders.length === 0 ? '' : `
                <div class="form-group backup-settings-synced-folders">
                    <label>Suggested folders</label>
                    <div class="backup-settings-synced-folder-list">
                        ${suggestedFolders.map((folder) => `
                            <button type="button" class="secondary-btn backup-settings-synced-folder" data-synced-folder-path="${escapeHtml(folder.path)}"
                                aria-pressed="${folder.path === folderPath ? 'true' : 'false'}" title="${escapeHtml(folder.path)}" ${loading || saving ? 'disabled' : ''}>${escapeHtml(folder.label)}</button>
                        `).join('')}
                    </div>
                </div>`;

        let effectiveStatusMessage = statusMessage;
        if (effectiveStatusMessage.length === 0 && loading) {
            effectiveStatusMessage = 'Loading backup settings...';
        }

        modalElement.innerHTML = `
            <div class="modal-content backup-retention-modal-content">
                <h3 class="backup-settings-modal-title">Backup Settings</h3>
                <p>Choose one backup folder and how many snapshots to keep for each selected vault.</p>

                ${syncedFoldersHtml}
                <div class="form-group">
                    <label for="backup-settings-folder-path">Folder path</label>
                    <input type="text" id="backup-settings-folder-path" value="${escapeHtml(folderPath)}" placeholder="/Users/you/Backups/MetaList" title="Choose a folder" readonly ${loading || saving || pickingFolder ? 'disabled' : ''}>
                    <div class="form-actions">
                        <button type="button" class="secondary-btn" id="backup-settings-folder-pick-btn" ${loading || saving || pickingFolder ? 'disabled' : ''}>${pickingFolder ? 'Choosing...' : 'Choose Folder...'}</button>
                        <button type="button" class="secondary-btn" id="backup-settings-folder-clear-btn" ${loading || saving || pickingFolder || folderPath.length === 0 ? 'disabled' : ''}>Clear</button>
                    </div>
                    <p>Use an absolute path. MetaList will create the folder if needed.</p>
                </div>

                <div class="form-group">
                    <label>Vaults to include</label>
                    ${namespaceSelectionHtml}
                </div>

                <div class="form-group">
                    <label for="backup-settings-retention-count">Backups to retain per vault</label>
                    <input type="number" id="backup-settings-retention-count" min="1" step="1" value="${escapeHtml(retentionCountText)}" ${loading || saving ? 'disabled' : ''}>
                </div>

                ${actionRowHtml({
                    alternative: null,
                    cancel: {
                        id: 'backup-settings-cancel-btn', label: 'Cancel',
                        disabled: [loading, saving, pickingFolder].includes(true), attributes: [],
                    },
                    main: {
                        id: 'backup-settings-run-btn', label: saving ? 'Backing Up…' : 'Back Up Now',
                        disabled: [loading, saving].includes(true), attributes: [],
                        isDestructive: false, isEnterAction: false, type: 'button',
                    },
                    rowClass: '',
                })}

                <p id="backup-settings-status">${escapeHtml(effectiveStatusMessage)}</p>
            </div>
        `;

        this.setupFormEventListeners();
        setTimeout(() => this._focusPreferredControl(), 0);
    }

    _focusPreferredControl() {
        const focusCandidateIds = [
            'backup-settings-retention-count',
            'backup-settings-folder-pick-btn',
            'backup-settings-run-btn',
            'backup-settings-cancel-btn',
        ];

        for (const candidateId of focusCandidateIds) {
            const candidate = document.getElementById(candidateId);
            if (!(candidate instanceof HTMLElement)) {
                continue;
            }
            if (candidate.hasAttribute('disabled')) {
                continue;
            }
            candidate.focus();
            return;
        }
    }

    setupFormEventListeners() {
        const cancelButton = document.getElementById('backup-settings-cancel-btn');
        if (cancelButton instanceof HTMLButtonElement) {
            cancelButton.onclick = () => {
                this.close();
            };
        }

        const folderPickButton = document.getElementById('backup-settings-folder-pick-btn');
        if (folderPickButton instanceof HTMLButtonElement) {
            folderPickButton.onclick = async () => {
                await this.pickFolderPath();
            };
        }

        // The path field only shows the folder: clicking it opens the folder picker too.
        const folderPathInput = document.getElementById('backup-settings-folder-path');
        if (folderPathInput instanceof HTMLInputElement) {
            folderPathInput.onclick = async () => {
                if (this.getModalState().pickingFolder) {
                    return;
                }
                await this.pickFolderPath();
            };
        }

        const folderClearButton = document.getElementById('backup-settings-folder-clear-btn');
        if (folderClearButton instanceof HTMLButtonElement) {
            folderClearButton.onclick = () => {
                this.updateModalState({
                    folderPath: '',
                });
                this.renderModalContent();
            };
        }

        for (const syncedFolderButton of document.querySelectorAll('[data-synced-folder-path]')) {
            syncedFolderButton.onclick = () => {
                const folderPath = syncedFolderButton.dataset.syncedFolderPath;
                // The folder already chosen: nothing changes (owned state rejects a same-value write).
                if (this.getModalState().folderPath === folderPath) {
                    return;
                }
                this.updateModalState({ folderPath });
                this.renderModalContent();
            };
        }

        const namespaceCheckboxes = document.querySelectorAll('[data-backup-namespace]');
        namespaceCheckboxes.forEach((element) => {
            if (!(element instanceof HTMLInputElement)) {
                throw new Error('Namespace checkbox must be an input');
            }
            if (element.getAttribute('aria-disabled') === 'true') {
                element.onclick = (event) => event.preventDefault();
                return;
            }
            element.onchange = () => {
                const state = this.getModalState();
                const availableNamespaces = Array.isArray(state.availableNamespaces) ? state.availableNamespaces : [];
                const checkedNamespaces = availableNamespaces.filter((candidate) => {
                    const candidateElement = document.querySelector(`[data-backup-namespace="${CSS.escape(candidate)}"]`);
                    return candidateElement instanceof HTMLInputElement && candidateElement.checked;
                });
                this.updateModalState({
                    selectedNamespaces: checkedNamespaces,
                });
            };
        });

        const retentionInput = document.getElementById('backup-settings-retention-count');
        if (retentionInput instanceof HTMLInputElement) {
            retentionInput.oninput = () => {
                this.updateModalState({
                    retentionCountText: retentionInput.value,
                });
            };
        }

        const runButton = document.getElementById('backup-settings-run-btn');
        if (runButton instanceof HTMLButtonElement) {
            runButton.onclick = async () => {
                await this.handleRunBackup();
            };
        }
    }

    _buildAuthHeaders(includeContentType) {
        return buildSessionHeaders(includeContentType);
    }

    async _authRequest(url, method, payload) {
        if (typeof url !== 'string' || url.length === 0) {
            throw new Error('_authRequest requires url');
        }
        if (typeof method !== 'string' || method.length === 0) {
            throw new Error('_authRequest requires method');
        }
        const includeContentType = payload !== null;
        const response = await fetch(url, {
            method,
            headers: this._buildAuthHeaders(includeContentType),
            body: payload === null ? undefined : JSON.stringify(payload),
        });

        let responseBody = null;
        const contentType = response.headers.get('content-type');
        if (typeof contentType === 'string' && contentType.includes('application/json')) {
            responseBody = await response.json();
        }
        if (!response.ok) {
            throw new HttpRequestError(parseResponseError(responseBody, response.status));
        }
        if (responseBody === null) {
            throw new Error('Response payload missing');
        }
        return responseBody;
    }

    async loadSettings() {
        this.updateModalState({
            loading: true,
            pickingFolder: false,
            statusMessage: 'Loading backup settings...',
        });
        this.renderModalContent();
        const settled = await this._authRequest(CONFIG.API.BACKUP.SETTINGS, 'GET', null).then(
            (payload) => ({ ok: true, payload }),
            (error) => { rethrowUnexpectedError(error); return ({ ok: false, error }); },
        );
        if (!settled.ok) {
            // Nothing to set without the settings: the error dialog says why, and closing it
            // closes this one.
            showOpenFailure(settled.error, () => {
                if (this.isOpen) {
                    this.close();
                }
            });
            return;
        }
        const payload = settled.payload;
        if (!payload || typeof payload !== 'object') {
            throw new Error('Backup settings response missing body');
        }
        if (!Array.isArray(payload.selected_namespaces)) {
            throw new Error('Backup settings response missing selected_namespaces');
        }
        if (!Array.isArray(payload.available_namespaces)) {
            throw new Error('Backup settings response missing available_namespaces');
        }
        if (typeof payload.current_namespace !== 'string' || !payload.available_namespaces.includes(payload.current_namespace)) {
            throw new Error('Backup settings response missing current_namespace');
        }
        if (!Array.isArray(payload.suggested_folders)) {
            throw new Error('Backup settings response missing suggested_folders');
        }
        this.updateModalState({
            loading: false,
            pickingFolder: false,
            folderPath: typeof payload.folder_path === 'string' ? payload.folder_path : '',
            selectedNamespaces: payload.selected_namespaces,
            availableNamespaces: payload.available_namespaces,
            currentNamespace: payload.current_namespace,
            suggestedFolders: payload.suggested_folders,
            retentionCountText: String(payload.retention_count),
            statusMessage: '',
        });
        this.renderModalContent();
    }

    _parseRetentionCount() {
        const state = this.getModalState();
        const raw = typeof state.retentionCountText === 'string' ? state.retentionCountText.trim() : '';
        if (!/^[0-9]+$/.test(raw)) {
            throw new FieldInputRejected('Backups to retain must be a whole number.', 'backup-settings-retention-count');
        }
        const retentionCount = parseDecimalInteger(raw);
        if (!Number.isInteger(retentionCount) || retentionCount <= 0) {
            throw new FieldInputRejected('Keep at least one backup.', 'backup-settings-retention-count');
        }
        return retentionCount;
    }

    async pickFolderPath() {
        this.updateModalState({ pickingFolder: true });
        this.renderModalContent();
        // No progress card: the system's folder picker is on screen until it answers.
        const settled = await this._authRequest(CONFIG.API.BACKUP.FOLDER_PICK, 'POST', {}).then(
            (payload) => ({ ok: true, payload }),
            (error) => { rethrowUnexpectedError(error); return ({ ok: false, error }); },
        );
        if (!settled.ok) {
            this.updateModalState({
                pickingFolder: false,
                statusMessage: '',
            });
            this.renderModalContent();
            await showErrorDialogFor(settled.error, null);
            return;
        }
        const payload = settled.payload;
        if (!payload || typeof payload !== 'object') {
            throw new Error('Folder picker response missing body');
        }
        if (payload.selected === true) {
            if (typeof payload.folder_path !== 'string' || payload.folder_path.length === 0) {
                throw new Error('Folder picker response missing folder path');
            }
            this.updateModalState({
                pickingFolder: false,
                folderPath: payload.folder_path,
                statusMessage: '',
            });
            this.renderModalContent();
            return;
        }
        this.updateModalState({
            pickingFolder: false,
            statusMessage: '',
        });
        this.renderModalContent();
    }

    handleRunBackup() {
        if (this._pendingRunBackup !== null) {
            return this._pendingRunBackup;
        }
        const pendingRunBackup = this._runBackupOnce();
        this._pendingRunBackup = pendingRunBackup;
        return pendingRunBackup.then(
            (result) => {
                if (this._pendingRunBackup !== pendingRunBackup) {
                    throw new Error('Backup settings run promise changed before completion');
                }
                this._pendingRunBackup = null;
                return result;
            },
            (error) => {
            rethrowUnexpectedError(error);
                if (this._pendingRunBackup !== pendingRunBackup) {
                    throw new Error('Backup settings run promise changed before failure');
                }
                this._pendingRunBackup = null;
                throw error;
            },
        );
    }

    async _runBackupOnce() {
        const state = this.getModalState();
        const folderPath = typeof state.folderPath === 'string' ? state.folderPath.trim() : '';
        const selectedNamespaces = Array.isArray(state.selectedNamespaces) ? state.selectedNamespaces : [];
        const retentionResult = await Promise.resolve()
            .then(() => this._parseRetentionCount())
            .then(
                (value) => ({ ok: true, value }),
                (error) => { rethrowUnexpectedError(error); return ({ ok: false, error }); },
            );
        const problems = [];
        if (folderPath.length === 0) {
            problems.push({ text: 'Choose a backup folder first.', fieldId: 'backup-settings-folder-pick-btn' });
        }
        if (!retentionResult.ok) {
            problems.push({ text: retentionResult.error.message, fieldId: failureFieldId(retentionResult.error) });
        }
        if (problems.length > 0) {
            await showErrorDialog(problems);
            return;
        }
        const retentionCount = retentionResult.value;

        this._decision.result = {
            action: 'run_backup',
            settings: {
                folder_path: folderPath,
                selected_namespaces: selectedNamespaces,
                retention_count: retentionCount,
                // Filled in once the person answers the synced-folder warning (createBackup).
                plaintext_sync_acknowledged: [],
            },
        };
        this.close();
    }
}
