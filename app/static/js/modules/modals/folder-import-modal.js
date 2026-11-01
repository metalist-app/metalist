import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';
import { NotesAPI } from '../api-client.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { FloatingMessages } from '../floating-messages.js';
import { importSource } from '../import-sources.js';
import { suggestTagsForImport } from '../import-tag-suggestions.js';

const NO_FOLDER = 'No folder chosen';
// The import's two choices (import-export-launch.md §2.2), the defaults first.
const SPLIT_CHOICES = [
    { value: 'paragraphs', label: 'Headings, lists and paragraphs', title: 'Every heading, list item and paragraph becomes a note of its own, nested as in the file.' },
    { value: 'headings-and-lists', label: 'Headings and lists', title: 'Headings and list items become notes; a run of paragraphs stays together in one note.' },
    { value: 'none', label: 'No splitting', title: 'Each file becomes one note.' },
];
const CONTENT_CHOICES = [
    { value: 'rich', label: 'Rich text', title: "MetaList's own formatting: bold, links, tables and the rest drawn as you edit." },
    { value: 'markdown', label: 'Markdown', title: 'The Markdown as written, in notes tagged @markdown.' },
];

function choicesHtml(name, legend, choices, chosen, isDisabled) {
    const options = choices.map((choice) => `
            <label class="obsidian-import-choice" title="${escapeHtml(choice.title)}">
                <input type="radio" name="${name}" value="${choice.value}"${choice.value === chosen ? ' checked' : ''}${isDisabled ? ' disabled' : ''}>
                ${escapeHtml(choice.label)}
            </label>`).join('');
    return `<fieldset class="obsidian-import-choices"><legend>${escapeHtml(legend)}</legend>${options}</fieldset>`;
}
const PATH_SEPARATOR_RE = /[\\/]+$/;

// "Have the AI suggest tags", once a folder is chosen and an AI is set up (slice 2b).
function suggestTagsHtml(state) {
    if (!state.canSuggestTags || state.folderPath === '') {
        return '';
    }
    return `
            <label class="obsidian-import-choice folder-import-suggest-tags">
                <input type="checkbox" data-folder-import-suggest-tags${state.suggestsTags ? ' checked' : ''}${state.busy ? ' disabled' : ''}>
                Have the AI suggest tags (${state.markdownFileCount} files)
            </label>`;
}

// A chosen folder as its name and the path above it (the path as the folder dialog gave it).
function folderParts(folderPath) {
    if (folderPath === '') {
        return { name: NO_FOLDER, parent: '' };
    }
    const trimmed = folderPath.replace(PATH_SEPARATOR_RE, '');
    const cut = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
    return { name: trimmed.slice(cut + 1), parent: trimmed.slice(0, cut + 1) };
}

// The folder import's developer version (PLAN.md, slices 1 and 1c): plain controls, for an
// Obsidian vault or a plain Markdown folder (import-sources.js). Pick the folder in the
// operating system's dialog, import it into the vault in use; the report note is at the top
// of the list.
export class FolderImportModal extends BaseModal {
    constructor(afterImport, getAiSettings) {
        super('folderImportModal', 'obsidian-import-modal');
        if (typeof afterImport !== 'function' || typeof getAiSettings !== 'function') {
            throw new Error('FolderImportModal requires afterImport and getAiSettings');
        }
        this._afterImport = afterImport;
        this._getAiSettings = getAiSettings;
        // Which source the next open is for (openFor).
        this._sourceKey = 'obsidian';

        ApplicationState.own(this, 'FolderImportModal', new.target === FolderImportModal);
    }

    async openFor(sourceKey) {
        importSource(sourceKey);
        // Owned state refuses a change to the value it has (opening again for the same source).
        if (this._sourceKey !== sourceKey) {
            this._sourceKey = sourceKey;
        }
        await this.open();
    }

    getInitialModalState() {
        return {
            source: this._sourceKey, folderPath: '', busy: false,
            splitMode: SPLIT_CHOICES[0].value, contentFormat: CONTENT_CHOICES[0].value,
            // The AI's tag suggestions (PLAN.md, slice 2b), offered once a folder is chosen
            // and an AI is set up.
            markdownFileCount: 0, canSuggestTags: false, suggestsTags: false,
        };
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
        const source = importSource(state.source);
        modalElement.innerHTML = `
            <div class="modal-content obsidian-import-modal-content">
                <h2>${escapeHtml(source.title)}</h2>
                <p class="note-layout-description">Developer version. Every Markdown file becomes a note at the top of
                    your list, tagged with its folder and <code>imported:source=${escapeHtml(source.key)}</code>. The
                    folder is only read, never changed.</p>
                <div class="obsidian-import-folder">
                    <div class="obsidian-import-folder-box" title="${escapeHtml(state.folderPath)}">
                        <span class="obsidian-import-folder-name">${escapeHtml(folder.name)}</span>
                        <span class="obsidian-import-folder-parent">${escapeHtml(folder.parent)}</span>
                    </div>
                    <button type="button" class="secondary-btn" data-obsidian-import-choose${state.busy ? ' disabled' : ''}>Choose Folder…</button>
                </div>
                ${choicesHtml('obsidian-import-split', 'Split each file into', SPLIT_CHOICES, state.splitMode, state.busy)}
                ${choicesHtml('obsidian-import-content', 'Write notes as', CONTENT_CHOICES, state.contentFormat, state.busy)}
                ${suggestTagsHtml(state)}
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
        for (const input of modalElement.querySelectorAll('input[name="obsidian-import-split"]')) {
            input.onchange = () => this.updateModalState({ splitMode: input.value });
        }
        for (const input of modalElement.querySelectorAll('input[name="obsidian-import-content"]')) {
            input.onchange = () => this.updateModalState({ contentFormat: input.value });
        }
        const suggestChoice = modalElement.querySelector('[data-folder-import-suggest-tags]');
        if (suggestChoice instanceof HTMLInputElement) {
            suggestChoice.onchange = () => this.updateModalState({ suggestsTags: suggestChoice.checked });
        }
        modalElement.querySelector('[data-obsidian-import-run]').onclick = async () => this._import();
    }

    async _chooseFolder() {
        this.updateModalState({ busy: true });
        this.renderModalContent();
        const picked = await NotesAPI.pickImportFolder(this.getModalState().source, this._getAiSettings().provider);
        if (typeof picked.selected !== 'boolean' || typeof picked.folderPath !== 'string'
            || !Number.isInteger(picked.markdownFileCount) || typeof picked.canSuggestTags !== 'boolean') {
            throw new Error('Import folder pick response malformed');
        }
        const updates = { busy: false };
        if (picked.selected) {
            updates.folderPath = picked.folderPath;
            updates.markdownFileCount = picked.markdownFileCount;
            updates.canSuggestTags = picked.canSuggestTags;
            updates.suggestsTags = picked.canSuggestTags && this.getModalState().suggestsTags;
        }
        this.updateModalState(updates);
        this.renderModalContent();
    }

    async _import() {
        // A refused folder (gone, no Markdown files) shows as MetaList's calm banner and the
        // dialog stays as it was, ready for another folder.
        // Through the command gate, as every server action: a second click meanwhile is dropped.
        let tagRequest = null;
        await CommandGate.run('folderImport.import', async () => {
            const { source, folderPath, splitMode, contentFormat, suggestsTags } = this.getModalState();
            const result = await NotesAPI.importFolder(source, folderPath, splitMode, contentFormat);
            if (!Number.isInteger(result.noteCount) || !Array.isArray(result.fileNoteIds) || !Array.isArray(result.folderTags)) {
                throw new Error('Folder import response missing noteCount, fileNoteIds or folderTags');
            }
            if (suggestsTags) {
                tagRequest = { fileNoteIds: result.fileNoteIds, folderTags: result.folderTags, settings: this._getAiSettings() };
            }
            // Done: the dialog closes, nothing is left to press twice, the report is on top.
            this.close();
            await this._afterImport();
            FloatingMessages.show({
                text: `Imported ${result.noteCount} notes from ${importSource(source).label}.`, type: 'success', detail: '',
                isClosable: false, isLasting: false, key: null,
            });
        });
        // Outside the command gate: the AI works while the user does (as Suggest Tags with AI).
        if (tagRequest !== null) {
            await suggestTagsForImport(tagRequest);
        }
    }
}
