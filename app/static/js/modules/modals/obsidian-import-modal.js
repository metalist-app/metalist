import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';
import { NotesAPI } from '../api-client.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { FloatingMessages } from '../floating-messages.js';

const NO_FOLDER = 'No folder chosen';
const PATH_SEPARATOR_RE = /[\\/]+$/;

// A chosen folder as its name and the path above it (the path as the folder dialog gave it).
function folderParts(folderPath) {
    if (folderPath === '') {
        return { name: NO_FOLDER, parent: '' };
    }
    const trimmed = folderPath.replace(PATH_SEPARATOR_RE, '');
    const cut = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
    return { name: trimmed.slice(cut + 1), parent: trimmed.slice(0, cut + 1) };
}

// The Obsidian import's developer version (PLAN.md, slice 1): plain controls, only in
// development. Pick the vault's folder in the operating system's dialog, import it into the
// vault in use, read the counts; the report note is at the top of the list.
export class ObsidianImportModal extends BaseModal {
    constructor(afterImport) {
        super('obsidianImportModal', 'obsidian-import-modal');
        if (typeof afterImport !== 'function') {
            throw new Error('ObsidianImportModal requires afterImport');
        }
        this._afterImport = afterImport;

        ApplicationState.own(this, 'ObsidianImportModal', new.target === ObsidianImportModal);
    }

    getInitialModalState() {
        return { folderPath: '', busy: false };
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
        if (!modalElement) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }
        const state = this.getModalState();
        // The folder's name stands out; its full path sits under it, small, cut at the start
        // when too long (the whole path in its tooltip).
        const folder = folderParts(state.folderPath);
        modalElement.innerHTML = `
            <div class="modal-content obsidian-import-modal-content">
                <h2>Import Obsidian Vault</h2>
                <p class="note-layout-description">Developer version. Every Markdown file becomes a note at the top of
                    your list, as Markdown, tagged with its folder and <code>imported:source=obsidian</code>.
                    The vault's folder is only read.</p>
                <div class="obsidian-import-folder">
                    <div class="obsidian-import-folder-box" title="${escapeHtml(state.folderPath)}">
                        <span class="obsidian-import-folder-name">${escapeHtml(folder.name)}</span>
                        <span class="obsidian-import-folder-parent">${escapeHtml(folder.parent)}</span>
                    </div>
                    <button type="button" class="secondary-btn" data-obsidian-import-choose${state.busy ? ' disabled' : ''}>Choose Folder…</button>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: null,
                    main: {
                        id: null, label: 'Import', disabled: state.busy || state.folderPath === '',
                        attributes: ['data-obsidian-import-run'], isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        modalElement.querySelector('[data-obsidian-import-choose]').onclick = async () => this._chooseFolder();
        modalElement.querySelector('[data-obsidian-import-run]').onclick = async () => this._import();
    }

    async _chooseFolder() {
        this.updateModalState({ busy: true });
        this.renderModalContent();
        const picked = await NotesAPI.pickObsidianVaultFolder();
        if (typeof picked.selected !== 'boolean' || typeof picked.folderPath !== 'string') {
            throw new Error('Obsidian folder pick response malformed');
        }
        const updates = { busy: false };
        if (picked.selected) {
            updates.folderPath = picked.folderPath;
        }
        this.updateModalState(updates);
        this.renderModalContent();
    }

    async _import() {
        // A refused folder (gone, no Markdown files) shows as MetaList's calm banner and the
        // dialog stays as it was, ready for another folder.
        // Through the command gate, as every server action: a second click meanwhile is dropped.
        await CommandGate.run('obsidianImport.import', async () => {
            const result = await NotesAPI.importObsidianVault(this.getModalState().folderPath);
            if (!Number.isInteger(result.noteCount)) {
                throw new Error('Obsidian import response missing noteCount');
            }
            // Done: the dialog closes, nothing is left to press twice, the report is on top.
            this.close();
            await this._afterImport();
            FloatingMessages.show({
                text: `Imported ${result.noteCount} notes from Obsidian.`, type: 'success', detail: '',
                isClosable: false, isLasting: false, key: null,
            });
        });
    }
}
