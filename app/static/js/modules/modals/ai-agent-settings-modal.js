import { ApplicationState, stateValuesEqual } from '../application-state.js';
import { rethrowUnexpectedError } from '../expected-errors.js';
import { BaseModal } from './base-modal.js';
import {
    AiApiError,
    clearAiCredential,
    loadAiCredentialStatus,
    saveAiCredential,
} from '../ai-chat/ai-chat-api.js';
import {
    getAgentRetrievalSettingsValidationMessage,
    validateAgentRetrievalSettings,
} from '../ai-chat/agent-retrieval-settings.js';
import {
    cloudPrivacyPolicyToTextFields,
    getCloudPrivacyTextFieldsValidationMessage,
    parseCloudPrivacyTextFields,
} from '../ai-chat/cloud-privacy-policy.js';
import { validateAgentWebAccessMode } from '../ai-chat/agent-web-settings.js';
import { escapeHtml } from '../html-escape.js';
import { attachTagSuggestions } from '../tag-input-suggestions.js';
import { actionRowHtml } from './action-row.js';
import { showErrorDialog, showErrorDialogFor } from './error-dialog.js';
import { AI_KEY_WARNINGS, AI_PROVIDERS, aiProvider } from '../ai-chat/ai-providers.js';

// AI Agent Settings (docs/ui/ai-chat.md, "AI Agent Settings"): four folder tabs, one Save.
// Keys: a switch per provider holding its key. Privacy: the rules for what the AI may see.
// Reading: web access and the token window. Tagging: which tags the AI may propose.
// Picking a model (and so a provider) happens in the chat. Explanations live in tooltips.

// The tabs, in order. Every panel is drawn, stacked in one place, and only the open one is
// visible: the dialog keeps the size of the largest, and switching tabs redraws nothing,
// so what is typed but not yet saved stays.
export const AI_SETTINGS_SECTIONS = Object.freeze([
    ['keys', 'Keys'], ['privacy', 'Privacy'], ['reading', 'Reading'], ['tagging', 'Tagging'],
]);
const SECTION_IDS = AI_SETTINGS_SECTIONS.map(([id]) => id);
// '' until the vocabulary has been chosen (here, or when a tagging run first asks).
const VOCABULARY_CHOICES = Object.freeze([
    ['existing', 'Existing tags only', 'The AI proposes only tags your notes already have.'],
    ['new', 'Existing and new tags', 'The AI may also propose tags no note has yet.'],
]);
export const TAGGING_VOCABULARIES = Object.freeze(['', ...VOCABULARY_CHOICES.map(([value]) => value)]);
const TAGGING_TOOLTIP = 'Which tags the AI may propose when it suggests tags for your notes.';

// One tab per provider MetaList offers, in its order (app/services/ai_catalog.py).
const PROVIDER_TABS = AI_PROVIDERS;
// Shown under a provider's key when what it does with the user's data depends on the key.
const KEY_WARNINGS = AI_KEY_WARNINGS;
const WEB_ACCESS_CHOICES = Object.freeze([
    ['none', 'Off', 'The AI never opens web pages.'],
    ['contextual', 'Links in your notes', 'The AI may open links that appear in the notes it can see or in your message.'],
    ['full', 'Any public page', 'The AI may open any public web page it chooses. Web pages are treated as untrusted.'],
]);
const PRIVACY_RULES_TOOLTIP = [
    'Tags count with everything MetaList infers: inherited tags, implications and synonyms.',
    'A hidden note hides everything under it, and never-send wins over only-send.',
    'Phrase rules read every note in view each time you send, so many notes start the chat more slowly.',
].join(' ');
const WINDOW_PERCENT_TOOLTIP = 'How much of the AI model\'s context window your notes may fill in one request: '
    + 'one answer, or one batch of a summary or of tag suggestions. It is a share of each model\'s own window, '
    + 'so one setting fits every model. Higher means fewer batches, each one slower. '
    + 'A note is never split from its children.';
const SEARCH_STRIP_QUOTES = /^["“](.*)["”]$/;

function retrievalStateFields(settings, provider) {
    return { windowPercent: validateAgentRetrievalSettings(settings, provider).windowPercent };
}

function nonEmptyLines(text) {
    return text.split('\n').map((line) => line.trim()).filter((line) => line !== '');
}

// A rule typed into a chip field: "a phrase" in quotes, or a tag.
export function parsePrivacyRuleEntry(text) {
    if (typeof text !== 'string') {
        throw new Error('parsePrivacyRuleEntry requires text');
    }
    const trimmed = text.trim();
    const quoted = SEARCH_STRIP_QUOTES.exec(trimmed);
    if (quoted !== null) {
        return { kind: 'phrase', value: quoted[1].trim() };
    }
    return { kind: 'tag', value: trimmed };
}

function renderRuleChips(tagsText, phrasesText, side) {
    const tags = nonEmptyLines(tagsText).map((tag) => ({ kind: 'tag', value: tag, shown: tag }));
    const phrases = nonEmptyLines(phrasesText).map((phrase) => ({ kind: 'phrase', value: phrase, shown: `“${phrase}”` }));
    return [...tags, ...phrases].map((rule) => `
        <span class="ai-settings-chip">${escapeHtml(rule.shown)}<button type="button" class="ai-settings-chip-remove" data-side="${side}" data-kind="${rule.kind}" data-value="${escapeHtml(rule.value)}" aria-label="Remove ${escapeHtml(rule.shown)}" title="Remove">×</button></span>`).join('');
}

function credentialStatusText(state) {
    if (state.credentialPersistent) return 'Key saved, encrypted in this vault';
    if (state.credentialConfigured) return 'Key saved for this session';
    return 'No key yet';
}

function renderKeyRow(state) {
    const busy = state.isLoadingCredential ? 'disabled' : '';
    if (state.credentialConfigured && !state.isChangingKey) {
        return `
            <div class="ai-settings-row">
                <span class="ai-settings-row-label">Key</span>
                <span class="ai-settings-key-status" role="status">${escapeHtml(credentialStatusText(state))}</span>
                <button type="button" class="secondary-btn" id="ai-agent-key-change" ${busy}>Change</button>
                <button type="button" class="secondary-btn" id="ai-agent-key-remove" ${busy}>Remove</button>
            </div>`;
    }
    let cancel = '';
    if (state.isChangingKey) cancel = `<button type="button" class="secondary-btn" id="ai-agent-key-cancel" ${busy}>Cancel</button>`;
    return `
        <div class="ai-settings-row">
            <label class="ai-settings-row-label" for="ai-agent-api-key">Key</label>
            <input id="ai-agent-api-key" type="password" value="" placeholder="Paste your API key" maxlength="512" autocomplete="new-password" data-1p-ignore data-lpignore="true" ${busy}>
            ${cancel}
            <button type="button" id="ai-agent-key-save" ${busy}>Save Key</button>
        </div>`;
}

function renderProviderPanel(state) {
    const billing = `<a class="ai-settings-indented ai-settings-link" href="${escapeHtml(aiProvider(state.provider).billingUrl)}" target="_blank" rel="noopener noreferrer">Usage and billing</a>`;
    let keyWarning = '';
    if (state.provider in KEY_WARNINGS) {
        const warning = KEY_WARNINGS[state.provider];
        keyWarning = `<p class="ai-settings-hint ai-settings-indented ai-settings-key-warning" title="${escapeHtml(warning.tooltip)}">${escapeHtml(warning.text)}</p>`;
    }
    return `
        <div class="ai-settings-tab-panel" role="tabpanel" aria-labelledby="ai-agent-tab-${escapeHtml(state.provider)}">
            ${renderKeyRow(state)}
            ${keyWarning}
            ${billing}
        </div>`;
}

// state's rules for side (blacklist or whitelist) with entries added, as the state's fields.
function withRules(state, side, entries) {
    let tags = nonEmptyLines(state[`${side}TagsText`]);
    let phrases = nonEmptyLines(state[`${side}PhrasesText`]);
    for (const entry of entries) {
        if (entry.trim() === '') continue;
        const rule = parsePrivacyRuleEntry(entry);
        if (rule.kind === 'phrase' && !phrases.includes(rule.value)) phrases = [...phrases, rule.value];
        if (rule.kind === 'tag' && !tags.includes(rule.value)) tags = [...tags, rule.value];
    }
    return { [`${side}TagsText`]: tags.join('\n'), [`${side}PhrasesText`]: phrases.join('\n') };
}

// A rule field with its Add button: Add (or a pasted list) adds rules as chips and keeps the
// dialog open; Enter saves the dialog, and Save takes what is still typed (2026-10-31).
function ruleEntryHtml(side, ariaLabel) {
    return `
            <div class="ai-settings-rule-entry">
                <input id="ai-agent-${side}-input" type="text" placeholder="Tag, or &quot;a phrase&quot; in quotes" autocomplete="off" aria-label="${ariaLabel}">
                <button type="button" id="ai-agent-${side}-add" class="secondary-btn">Add</button>
            </div>`;
}

function renderRulesSection(state) {
    const hasWhitelistRules = nonEmptyLines(state.whitelistTagsText).length + nonEmptyLines(state.whitelistPhrasesText).length > 0;
    const showsWhitelist = [state.isWhitelistShown, hasWhitelistRules].includes(true);
    let whitelist = '';
    if (showsWhitelist) {
        whitelist = `
            <div class="ai-settings-chips">${renderRuleChips(state.whitelistTagsText, state.whitelistPhrasesText, 'whitelist')}</div>
            ${ruleEntryHtml('whitelist', 'Add an only-send rule')}`;
    }
    return `
        <section class="ai-settings-section ai-agent-cloud-privacy-settings">
            <h3 title="${escapeHtml(PRIVACY_RULES_TOOLTIP)}">Never send notes with <span class="ai-settings-term">(blacklist)</span></h3>
            <div class="ai-settings-chips">${renderRuleChips(state.blacklistTagsText, state.blacklistPhrasesText, 'blacklist')}</div>
            ${ruleEntryHtml('blacklist', 'Add a never-send rule')}
            <label class="ai-settings-check" title="${escapeHtml(PRIVACY_RULES_TOOLTIP)}">
                <input type="checkbox" id="ai-agent-whitelist-toggle" ${showsWhitelist ? 'checked' : ''}>
                <span>Only send notes with <span class="ai-settings-term">(whitelist)</span></span>
            </label>
            ${whitelist}
            <p class="ai-settings-hint">@password and @username notes are never sent.</p>
        </section>`;
}

function renderTaggingSection(state) {
    const choices = VOCABULARY_CHOICES.map(([value, label, tooltip]) => (
        `<button type="button" role="radio" class="ai-settings-segment" aria-checked="${state.taggingVocabulary === value}" data-vocabulary="${value}" title="${escapeHtml(tooltip)}">${escapeHtml(label)}</button>`
    )).join('');
    return `
        <section class="ai-settings-section">
            <h3 title="${escapeHtml(TAGGING_TOOLTIP)}">Tags the AI may propose</h3>
            <div class="ai-settings-segments" role="radiogroup" aria-label="Tags the AI may propose" id="ai-agent-tagging-vocabulary">${choices}</div>
        </section>`;
}

function sectionPanelHtml(state, section, content) {
    const inert = state.section === section ? '' : 'inert';
    return `<div class="ai-settings-section-panel" role="tabpanel" id="ai-agent-panel-${section}" aria-labelledby="ai-agent-section-${section}" ${inert}>${content}</div>`;
}

// A key saved or removed changes which models the chat offers, Save or not.
function announceKeyChange() {
    document.dispatchEvent(new CustomEvent('metalist:ai-settings-changed', { detail: { reloadModels: true } }));
}

export class AiAgentSettingsModal extends BaseModal {
    constructor(readSettings, saveSettings) {
        super('aiAgentSettingsModal', 'ai-agent-settings-modal');
        if (typeof readSettings !== 'function') {
            throw new Error('AiAgentSettingsModal requires readSettings');
        }
        if (typeof saveSettings !== 'function') {
            throw new Error('AiAgentSettingsModal requires saveSettings');
        }
        this._readSettings = readSettings;
        this._saveSettings = saveSettings;
        // The tab the next open starts on (openOn).
        this._openingSection = SECTION_IDS[0];

        ApplicationState.own(this, 'AiAgentSettingsModal', new.target === AiAgentSettingsModal);
    }

    getInitialModalState() {
        const settings = this._readSettings();
        const tab = PROVIDER_TABS.find((entry) => entry.provider === settings.provider);
        if (tab === undefined) {
            throw new Error(`Unsupported AI provider: ${settings.provider}`);
        }
        if (!TAGGING_VOCABULARIES.includes(settings.taggingVocabulary)) {
            throw new Error(`Unsupported tagging vocabulary: ${settings.taggingVocabulary}`);
        }
        return {
            section: this._openingSection,
            // The provider switch starts on the provider the chat uses.
            provider: settings.provider,
            // The token window belongs to the provider the chat uses, whichever tab is open.
            chatProvider: settings.provider,
            providerLabel: tab.label,
            webAccessMode: validateAgentWebAccessMode(settings.webAccessMode),
            ...cloudPrivacyPolicyToTextFields(settings.cloudPrivacyPolicy),
            ...retrievalStateFields(settings.openAiRetrievalSettings, settings.provider),
            taggingVocabulary: settings.taggingVocabulary,
            isWhitelistShown: false,
            isLoadingCredential: false,
            isChangingKey: false,
            credentialConfigured: false,
            credentialPersistent: false,
        };
    }

    // Opens on one tab: AI Agent Settings on Keys, Cloud AI Privacy on Privacy (its first rule
    // field focused), AI Tagging Vocabulary on Tagging.
    async openOn(section) {
        if (!SECTION_IDS.includes(section)) {
            throw new Error(`Unknown AI settings tab: ${section}`);
        }
        // Owned state rejects a write that changes nothing: opening on the same tab again.
        if (this._openingSection !== section) this._openingSection = section;
        await this.open();
        if (section === 'privacy') {
            this._element('ai-agent-blacklist-input', HTMLInputElement).focus();
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

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }
        const state = this.getModalState();
        const sectionTabs = AI_SETTINGS_SECTIONS.map(([section, label]) => (
            `<button type="button" role="tab" id="ai-agent-section-${section}" class="ai-settings-section-tab" aria-selected="${state.section === section}" aria-controls="ai-agent-panel-${section}" data-section="${section}">${escapeHtml(label)}</button>`
        )).join('');
        const tabs = PROVIDER_TABS.map((tab) => {
            const selected = tab.provider === state.provider;
            return `<button type="button" role="tab" id="ai-agent-tab-${tab.provider}" class="ai-settings-tab" aria-selected="${selected}" data-provider="${tab.provider}">${escapeHtml(tab.label)}</button>`;
        }).join('');
        const webChoices = WEB_ACCESS_CHOICES.map(([mode, label, tooltip]) => (
            `<button type="button" role="radio" class="ai-settings-segment" aria-checked="${state.webAccessMode === mode}" data-mode="${mode}" title="${escapeHtml(tooltip)}">${escapeHtml(label)}</button>`
        )).join('');
        modalElement.innerHTML = `
            <div class="modal-content ai-agent-settings-modal-content">
                <h2>AI Agent Settings</h2>
                <div class="ai-settings-section-tabs" role="tablist" aria-label="AI settings">${sectionTabs}</div>
                <div class="ai-settings-panels">
                    ${sectionPanelHtml(state, 'keys', `
                        <div class="ai-settings-tabs ai-settings-provider-switch" role="tablist" aria-label="AI provider">${tabs}</div>
                        ${renderProviderPanel(state)}`)}
                    ${sectionPanelHtml(state, 'privacy', renderRulesSection(state))}
                    ${sectionPanelHtml(state, 'reading', `
                        <section class="ai-settings-section">
                            <h3>Web access</h3>
                            <div class="ai-settings-segments" role="radiogroup" aria-label="Web access" id="ai-agent-web-access">${webChoices}</div>
                        </section>
                        <section class="ai-settings-section ai-settings-limits">
                            <div class="ai-settings-stacked">
                                <span class="ai-settings-wide-label">
                                    <label for="ai-agent-window-percent">Model window used</label>
                                    <span class="ai-settings-help" tabindex="0" role="img" aria-label="${escapeHtml(WINDOW_PERCENT_TOOLTIP)}" title="${escapeHtml(WINDOW_PERCENT_TOOLTIP)}">?</span>
                                </span>
                                <span class="ai-settings-percent">
                                    <input id="ai-agent-window-percent" type="number" autocomplete="off" data-1p-ignore data-lpignore="true" min="1" max="100" step="1" value="${escapeHtml(String(state.windowPercent))}">
                                    <span aria-hidden="true">%</span>
                                </span>
                            </div>
                        </section>`)}
                    ${sectionPanelHtml(state, 'tagging', renderTaggingSection(state))}
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'ai-agent-cancel', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'ai-agent-save', label: 'Save', disabled: false, attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        this._setupControls();
    }

    _element(id, type) {
        const element = document.getElementById(id);
        if (!(element instanceof type)) {
            throw new Error(`AI settings control missing: ${id}`);
        }
        return element;
    }

    _setupControls() {
        const state = this.getModalState();
        for (const tab of document.querySelectorAll('#ai-agent-settings-modal .ai-settings-section-tab')) {
            tab.onclick = () => this._showSection(tab.dataset.section);
        }
        for (const segment of document.querySelectorAll('#ai-agent-tagging-vocabulary .ai-settings-segment')) {
            segment.onclick = () => this._update({ taggingVocabulary: segment.dataset.vocabulary });
        }
        for (const tab of document.querySelectorAll('#ai-agent-settings-modal .ai-settings-tab')) {
            tab.onclick = () => void this._selectProvider(tab.dataset.provider);
        }
        this._setupKeyControls(state);
        for (const segment of document.querySelectorAll('#ai-agent-web-access .ai-settings-segment')) {
            segment.onclick = () => this._update({ webAccessMode: validateAgentWebAccessMode(segment.dataset.mode) });
        }
        this._setupRuleControls();
        const limitInput = this._element('ai-agent-window-percent', HTMLInputElement);
        limitInput.oninput = () => {
            this._setState({ windowPercent: Number(limitInput.value) });
        };
        this._element('ai-agent-save', HTMLButtonElement).onclick = () => void this._handleSave();
        this._element('ai-agent-cancel', HTMLButtonElement).onclick = () => this.requestClose();
    }

    _setupKeyControls(state) {
        if (state.credentialConfigured && !state.isChangingKey) {
            this._element('ai-agent-key-change', HTMLButtonElement).onclick = () => this._update({ isChangingKey: true });
            this._element('ai-agent-key-remove', HTMLButtonElement).onclick = () => void this._handleRemoveKey();
            return;
        }
        const input = this._element('ai-agent-api-key', HTMLInputElement);
        this._element('ai-agent-key-save', HTMLButtonElement).onclick = () => void this._handleSaveKey(input.value);
        input.onkeydown = (event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            event.stopPropagation();
            void this._handleSaveKey(input.value);
        };
        if (state.isChangingKey) {
            this._element('ai-agent-key-cancel', HTMLButtonElement).onclick = () => this._update({ isChangingKey: false });
        }
    }

    _setupRuleControls() {
        for (const side of ['blacklist', 'whitelist']) {
            const input = document.getElementById(`ai-agent-${side}-input`);
            if (!(input instanceof HTMLInputElement)) continue;
            this._element(`ai-agent-${side}-add`, HTMLButtonElement).onclick = () => {
                void this._addRules(side, [input.value], `ai-agent-${side}-input`);
            };
            // Picking a suggested tag adds it at once, as Add does.
            if (input.dataset.offersTags !== 'true') {
                input.dataset.offersTags = 'true';
                attachTagSuggestions(input, {
                    chosenTags: () => nonEmptyLines(this.getModalState()[`${side}TagsText`]),
                    onPick: (tag) => void this._addRules(side, [tag], `ai-agent-${side}-input`),
                });
            }
            // A pasted list (one rule per line, or comma-separated) adds every rule.
            input.onpaste = (event) => {
                const text = event.clipboardData.getData('text/plain');
                if (!/[\n,]/.test(text)) return;
                event.preventDefault();
                void this._addRules(side, text.split(/[\n,]/), `ai-agent-${side}-input`);
            };
        }
        for (const removeButton of document.querySelectorAll('#ai-agent-settings-modal .ai-agent-cloud-privacy-settings .ai-settings-chip-remove')) {
            removeButton.onclick = () => this._removeRule(removeButton.dataset.side, removeButton.dataset.kind, removeButton.dataset.value);
        }
        const toggle = this._element('ai-agent-whitelist-toggle', HTMLInputElement);
        toggle.onchange = () => {
            if (toggle.checked) {
                this._update({ isWhitelistShown: true });
                this._element('ai-agent-whitelist-input', HTMLInputElement).focus();
                return;
            }
            // Off sends every note again: its rules go.
            this._update({ isWhitelistShown: false, whitelistTagsText: '', whitelistPhrasesText: '' });
        };
    }

    // Shows one tab's panel without redrawing, so what is typed in the others stays.
    _showSection(section) {
        if (!SECTION_IDS.includes(section)) {
            throw new Error(`Unknown AI settings tab: ${section}`);
        }
        this._setState({ section });
        for (const [id] of AI_SETTINGS_SECTIONS) {
            const isOpen = id === section;
            this._element(`ai-agent-section-${id}`, HTMLButtonElement).setAttribute('aria-selected', String(isOpen));
            this._element(`ai-agent-panel-${id}`, HTMLElement).toggleAttribute('inert', !isOpen);
        }
    }

    // The state store rejects a write that changes nothing; a repeated status or error is one.
    _setState(fields) {
        const current = this.getModalState();
        if (!stateValuesEqual(current, { ...current, ...fields })) this.updateModalState(fields);
    }

    _update(fields) {
        this._setState(fields);
        this.renderModalContent();
    }

    async _addRules(side, entries, focusId) {
        const state = this.getModalState();
        const fields = withRules(state, side, entries);
        const problem = getCloudPrivacyTextFieldsValidationMessage({ ...state, ...fields });
        if (problem !== '') {
            await showErrorDialog([{ text: problem, fieldId: focusId }]);
            return;
        }
        this._update(fields);
        this._element(focusId, HTMLInputElement).focus();
    }

    _removeRule(side, kind, value) {
        const field = kind === 'tag' ? `${side}TagsText` : `${side}PhrasesText`;
        const state = this.getModalState();
        this._update({ [field]: nonEmptyLines(state[field]).filter((line) => line !== value).join('\n') });
    }

    // A tab shows one provider's key; it does not pick the provider the chat uses.
    async _selectProvider(provider) {
        const tab = PROVIDER_TABS.find((entry) => entry.provider === provider);
        if (tab === undefined) {
            throw new Error(`Unsupported AI provider: ${provider}`);
        }
        if (provider === this.getModalState().provider) return;
        this._update({
            provider, providerLabel: tab.label,
            isChangingKey: false, credentialConfigured: false, credentialPersistent: false,
        });
        await this._loadCredentialStatus();
    }

    onOpen() {
        return this._loadCredentialStatus();
    }

    async _loadCredentialStatus() {
        const generation = this._openGeneration;
        const state = this.getModalState();
        if (state.isLoadingCredential) {
            return;
        }
        this._setState({ isLoadingCredential: true });
        this.renderModalContent();
        let failure = null;
        try {
            const payload = await loadAiCredentialStatus(state.provider);
            if (!this.isCurrentOpen(generation)) return;
            this._applyCredentialStatus(payload);
        // lint: allow-JS001 rationale="late external responses belong to the closed dialog generation; internal errors rethrow"
        } catch (error) {
            rethrowUnexpectedError(error);
            if (!this.isCurrentOpen(generation)) return;
            if (!(error instanceof AiApiError)) {
                throw error;
            }
            failure = error;
        } finally {
            if (this.isCurrentOpen(generation)) {
                this._setState({ isLoadingCredential: false });
                this.renderModalContent();
            }
        }
        // The dialog stays usable under it, and opening is not held up while it shows.
        if (failure !== null) {
            void showErrorDialogFor(failure, null);
        }
    }

    _applyCredentialStatus(payload) {
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
            throw new Error('AI key status must be an object');
        }
        if (typeof payload.configured !== 'boolean' || typeof payload.persistent !== 'boolean') {
            throw new Error('AI key status flags missing');
        }
        if (payload.persistent && !payload.configured) {
            throw new Error('A persistent AI key must be configured');
        }
        this._setState({
            credentialConfigured: payload.configured,
            credentialPersistent: payload.persistent,
        });
    }

    async _handleSaveKey(apiKey) {
        const state = this.getModalState();
        if (apiKey.trim() === '') {
            await showErrorDialog([{ text: `Paste your ${state.providerLabel} API key first.`, fieldId: 'ai-agent-api-key' }]);
            return;
        }
        this._setState({ isLoadingCredential: true });
        this.renderModalContent();
        let failure = null;
        try {
            this._applyCredentialStatus(await saveAiCredential(state.provider, apiKey));
            this._setState({ isChangingKey: false });
            announceKeyChange();
        } catch (error) {
            rethrowUnexpectedError(error);
            if (!(error instanceof AiApiError)) {
                throw error;
            }
            failure = error;
        } finally {
            this._setState({ isLoadingCredential: false });
            this.renderModalContent();
        }
        if (failure !== null) {
            await showErrorDialogFor(failure, 'ai-agent-api-key');
        }
    }

    async _handleRemoveKey() {
        const state = this.getModalState();
        try {
            this._applyCredentialStatus(await clearAiCredential(state.provider));
            announceKeyChange();
            this.renderModalContent();
        } catch (error) {
            rethrowUnexpectedError(error);
            if (!(error instanceof AiApiError)) {
                throw error;
            }
            await showErrorDialogFor(error, null);
        }
    }

    async _handleSave() {
        // A rule still typed in its field is a rule, as if Add had been pressed first.
        let state = this.getModalState();
        for (const side of ['blacklist', 'whitelist']) {
            const input = document.getElementById(`ai-agent-${side}-input`);
            if (input instanceof HTMLInputElement && input.value.trim() !== '') {
                state = { ...state, ...withRules(state, side, [input.value]) };
            }
        }
        const retrievalSettings = { windowPercent: state.windowPercent };
        // Every problem at once, the limit with its field.
        const problems = [
            { text: getAgentRetrievalSettingsValidationMessage(retrievalSettings, state.chatProvider), fieldId: 'ai-agent-window-percent' },
            { text: getCloudPrivacyTextFieldsValidationMessage(state), fieldId: null },
        ].filter((problem) => problem.text !== '');
        if (problems.length > 0) {
            await showErrorDialog(problems);
            return;
        }
        await this._saveSettings({
            taggingVocabulary: state.taggingVocabulary,
            webAccessMode: validateAgentWebAccessMode(state.webAccessMode),
            openAiRetrievalSettings: validateAgentRetrievalSettings(retrievalSettings, state.chatProvider),
            cloudPrivacyPolicy: parseCloudPrivacyTextFields(state),
        });
        this.close();
    }
}
