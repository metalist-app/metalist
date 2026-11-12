// Add or Remove Tag (Current View)… (the maintainer, 2026-11-11; docs/ui/command-palette.md):
// Add or Remove, one tag with suggestions as it is typed (adding: the vault's tags; removing:
// those the view's notes carry), and the button saying how many notes change. Resolves
// { action, tag, noteCount }, or null when cancelled. Its tag field and suggestions look like
// Prioritize Tag's (prioritize-modal.js), whose styles it shares.
import { NEXT_ROW, NO_SELECTION, PREVIOUS_ROW } from '../list-selection.js';
import { ApplicationState, stateValuesEqual } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { NotesAPI } from '../api-client.js';
import { isValidTagToken } from '../tag-token.js';
import { handleDictationPasteEvent } from '../mode-manager/services/dictation-paste-service.js';
import { escapeHtml } from '../html-escape.js';
import { showErrorDialog } from './error-dialog.js';
import { fitSuggestionList } from './suggestion-list-fit.js';

export const TAG_ADD = 'add';
export const TAG_REMOVE = 'remove';
const ACTIONS = [[TAG_ADD, 'Add'], [TAG_REMOVE, 'Remove']];
// No count yet: the tag is still being typed, or its count is on its way.
const NO_COUNT = -1;
const SINGLE_NOTE = 1;
const INPUT_ID = 'tag-in-view-input';
const SUGGESTIONS_ID = 'tag-in-view-suggestions';
const SUBMIT_ID = 'tag-in-view-submit-btn';

// The main button: what it does to how many notes.
export function tagInViewButtonLabel(action, noteCount) {
    const verb = action === TAG_ADD ? 'Add to' : 'Remove from';
    if (noteCount === NO_COUNT) return action === TAG_ADD ? 'Add' : 'Remove';
    if (noteCount === SINGLE_NOTE) return `${verb} 1 Note`;
    return `${verb} ${noteCount} Notes`;
}

export class TagInViewModal extends BaseModal {
    constructor() {
        super('tagInViewModal', 'tag-in-view-modal');
        this._pendingResolve = null;
        this._decision = null;
        this._suggestionsVersion = 0;
        this._countVersion = 0;
        ApplicationState.own(this, 'TagInViewModal', new.target === TagInViewModal);
    }

    // The dialog's state, changed only where it differs: the state store refuses a change that
    // changes nothing (a count answered twice the same, the one suggestion kept highlighted).
    _update(updates) {
        const current = this.getModalState();
        if (Object.entries(updates).every(([key, value]) => stateValuesEqual(current[key], value))) return;
        this.updateModalState(updates);
    }

    getInitialModalState() {
        return {
            action: TAG_ADD, tagInput: '', suggestions: [], selectedIndex: NO_SELECTION,
            isDropdownOpen: true, noteCount: NO_COUNT,
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

    openForView() {
        if (this.isOpen || this._pendingResolve !== null) {
            throw new Error('TagInViewModal is already open');
        }
        this._decision = { result: null };
        this.open();
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
        });
    }

    onOpen() {
        this.focusInputToEnd();
        void this.fetchSuggestions();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._decision.result;
        this._pendingResolve = null;
        this._decision = null;
        // Answers still on their way are for a dialog no longer open.
        this._suggestionsVersion += 1;
        this._countVersion += 1;
        resolve(result);
    }

    getElements() {
        const modalElement = document.getElementById(this.modalElementId);
        const input = modalElement?.querySelector(`#${INPUT_ID}`);
        const suggestions = modalElement?.querySelector(`#${SUGGESTIONS_ID}`);
        const submit = modalElement?.querySelector(`#${SUBMIT_ID}`);
        if (!(input instanceof HTMLInputElement) || !(suggestions instanceof HTMLElement) || !(submit instanceof HTMLButtonElement)) {
            throw new Error('Tag in view modal elements missing');
        }
        return { modalElement, input, suggestions, submit };
    }

    focusInputToEnd() {
        const { input } = this.getElements();
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error('Tag in view modal element missing');
        }
        const state = this.getModalState();
        const segments = ACTIONS.map(([value, label]) => (
            `<button type="button" role="radio" class="ai-settings-segment" aria-checked="${state.action === value}" data-tag-action="${value}">${label}</button>`
        )).join('');
        modalElement.innerHTML = `
            <div class="modal-content prioritize-modal-content tag-in-view-modal-content">
                <div class="prioritize-modal-header">
                    <h3>Add or Remove Tag</h3>
                </div>
                <div class="ai-settings-segments tag-in-view-actions" role="radiogroup" aria-label="Add or remove">${segments}</div>
                <div class="form-group prioritize-modal-input-group">
                    <div class="prioritize-modal-tag-bar">
                        <input type="text" id="${INPUT_ID}" class="prioritize-modal-tag-input" data-modal-initial-focus
                            autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
                            aria-label="Tag" aria-autocomplete="list" aria-controls="${SUGGESTIONS_ID}" aria-expanded="true"
                            placeholder="tag" value="${escapeHtml(state.tagInput)}">
                        <div id="${SUGGESTIONS_ID}" class="prioritize-modal-suggestions"></div>
                    </div>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'tag-in-view-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: SUBMIT_ID, label: tagInViewButtonLabel(state.action, state.noteCount), disabled: false, attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: 'prioritize-modal-actions',
                })}
            </div>
        `;
        this.setupFormEventListeners();
        this.syncSuggestionUi();
    }

    setupFormEventListeners() {
        const { modalElement, input, submit } = this.getElements();
        modalElement.querySelectorAll('[data-tag-action]').forEach((button) => {
            button.onclick = () => this.chooseAction(button.getAttribute('data-tag-action'));
        });
        input.onpaste = (event) => handleDictationPasteEvent(event, 'tag');
        input.oninput = () => {
            this._update({ tagInput: input.value, isDropdownOpen: true, noteCount: NO_COUNT });
            this.syncButton();
            void this.fetchSuggestions();
            void this.fetchCount();
        };
        input.onfocus = () => {
            if (this.getModalState().isDropdownOpen) return;
            this._update({ isDropdownOpen: true });
            this.syncSuggestionUi();
        };
        input.onblur = () => {
            // Closing hides the field, which blurs it after the dialog's state is gone.
            if (!this.isOpen || !this.getModalState().isDropdownOpen) return;
            this._update({ isDropdownOpen: false, selectedIndex: NO_SELECTION });
            this.syncSuggestionUi();
        };
        document.getElementById('tag-in-view-cancel-btn').onclick = () => this.close();
        submit.onclick = () => this.submit();
    }

    chooseAction(action) {
        if (action !== TAG_ADD && action !== TAG_REMOVE) {
            throw new Error(`Unknown tag action: ${action}`);
        }
        if (this.getModalState().action === action) {
            this.focusInputToEnd();
            return;
        }
        this._update({ action, noteCount: NO_COUNT, suggestions: [], selectedIndex: NO_SELECTION, isDropdownOpen: true });
        const { modalElement } = this.getElements();
        modalElement.querySelectorAll('[data-tag-action]').forEach((button) => {
            button.setAttribute('aria-checked', String(button.getAttribute('data-tag-action') === action));
        });
        this.syncButton();
        this.syncSuggestionUi();
        this.focusInputToEnd();
        void this.fetchSuggestions();
        void this.fetchCount();
    }

    syncButton() {
        const state = this.getModalState();
        this.getElements().submit.textContent = tagInViewButtonLabel(state.action, state.noteCount);
    }

    syncSuggestionUi() {
        if (!this.isOpen) return;
        const state = this.getModalState();
        const { input, suggestions } = this.getElements();
        const isShown = state.isDropdownOpen && state.suggestions.length > 0;
        input.setAttribute('aria-expanded', String(isShown));
        suggestions.hidden = !isShown;
        suggestions.classList.toggle('is-hidden', !isShown);
        if (!isShown) {
            suggestions.innerHTML = '';
            return;
        }
        suggestions.innerHTML = state.suggestions.map((tag, index) => (
            `<button type="button" class="prioritize-modal-suggestion${index === state.selectedIndex ? ' is-selected' : ''}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`
        )).join('');
        fitSuggestionList(suggestions);
        suggestions.querySelectorAll('[data-tag]').forEach((button) => {
            // Before the field blurs, which would close the list under the click.
            button.onmousedown = (event) => {
                event.preventDefault();
                this.applySuggestion(button.getAttribute('data-tag'));
            };
        });
    }

    onKeyDown(event) {
        const state = this.getModalState();
        const isListed = state.isDropdownOpen && state.suggestions.length > 0;
        if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && isListed) {
            event.preventDefault();
            const delta = event.key === 'ArrowDown' ? NEXT_ROW : PREVIOUS_ROW;
            const count = state.suggestions.length;
            this._update({ selectedIndex: (state.selectedIndex + delta + count) % count });
            this.syncSuggestionUi();
            return;
        }
        // Enter takes the highlighted suggestion; with none, it presses the button.
        if (event.key === 'Enter' && !event.isComposing && isListed && state.selectedIndex !== NO_SELECTION) {
            event.preventDefault();
            this.applySuggestion(state.suggestions[state.selectedIndex]);
        }
    }

    applySuggestion(tag) {
        if (typeof tag !== 'string' || !isValidTagToken(tag)) {
            throw new Error('A suggestion must be one tag');
        }
        this._update({ tagInput: tag, isDropdownOpen: false, selectedIndex: NO_SELECTION, noteCount: NO_COUNT });
        this.getElements().input.value = tag;
        this.syncSuggestionUi();
        this.syncButton();
        this.focusInputToEnd();
        void this.fetchCount();
    }

    submit() {
        const state = this.getModalState();
        const tag = state.tagInput.trim();
        if (tag === '') {
            void showErrorDialog([{ text: 'Enter a tag.', fieldId: INPUT_ID }]);
            return;
        }
        if (!isValidTagToken(tag)) {
            void showErrorDialog([{ text: 'Enter one tag, without spaces or quotes.', fieldId: INPUT_ID }]);
            return;
        }
        if (state.noteCount === NO_COUNT) {
            // Counted as soon as it is typed; pressed sooner, the count comes first.
            void this.fetchCount().then(() => {
                if (this.isOpen && this.getModalState().noteCount !== NO_COUNT) this.submit();
            });
            return;
        }
        if (state.noteCount === 0) {
            const text = state.action === TAG_ADD
                ? `Every note in this view has ${tag} already.`
                : `No note in this view has ${tag}.`;
            void showErrorDialog([{ text, fieldId: INPUT_ID }]);
            return;
        }
        this._decision.result = { action: state.action, tag, noteCount: state.noteCount };
        this.close();
    }

    async fetchSuggestions() {
        const version = this._suggestionsVersion + 1;
        this._suggestionsVersion = version;
        const state = this.getModalState();
        const { suggestions } = await NotesAPI.tagInViewSuggestions(state.action, state.tagInput.trim());
        if (version !== this._suggestionsVersion || !this.isOpen) return;
        if (!Array.isArray(suggestions)) {
            throw new Error('Tag in view suggestions response malformed');
        }
        let selectedIndex = NO_SELECTION;
        if (suggestions.length > 0 && this.getModalState().tagInput.trim() !== '') selectedIndex = 0;
        this._update({ suggestions, selectedIndex });
        this.syncSuggestionUi();
    }

    async fetchCount() {
        const version = this._countVersion + 1;
        this._countVersion = version;
        const state = this.getModalState();
        const tag = state.tagInput.trim();
        if (!isValidTagToken(tag)) return;
        const { noteCount } = await NotesAPI.countTagInView(state.action, tag);
        if (version !== this._countVersion || !this.isOpen) return;
        if (!Number.isInteger(noteCount)) {
            throw new Error('Tag in view count response malformed');
        }
        this._update({ noteCount });
        this.syncButton();
    }
}
