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
import { AI_PROVIDERS, aiProvider } from '../ai-chat/ai-providers.js';

// AI Agent Settings (docs/ui/ai-chat.md, "AI Agent Settings"): one folder tab per
// provider holding its key; then web access, the rules
// for what the AI may see, and the token window. Picking a model (and so
// a provider) happens in the chat. Explanations live in tooltips.

// One tab per provider MetaList offers, in its order (app/services/ai_catalog.py).
const PROVIDER_TABS = AI_PROVIDERS;
// Shown under a provider's key when what it does with the user's data depends on the key.
const KEY_WARNINGS = Object.freeze({
    gemini: Object.freeze({
        text: 'Use a key with billing turned on: on the free tier, Google may use what you send to improve its products, and people may read it.',
        tooltip: 'Google\'s Gemini API terms (Unpaid Services): prompts and responses sent on free quota may be used to improve '
            + 'Google\'s products and read by human reviewers. This does not apply in the EEA, Switzerland or the UK. '
            + 'Use a key from a Google Cloud project with billing enabled.',
    }),
});
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
const TOKEN_WINDOW_TOOLTIP = 'The most the AI reads from your notes at once, in tokens (about ¾ of a word each), '
    + 'for one answer or one batch of tag suggestions. A note is never split from its children; '
    + 'notes past the limit are left out.';
const SEARCH_STRIP_QUOTES = /^["“](.*)["”]$/;

function retrievalStateFields(settings, provider) {
    return { maxPageApproximateTokens: validateAgentRetrievalSettings(settings, provider).maxPageApproximateTokens };
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
            <button type="button" id="ai-agent-key-save" ${busy}>Save key</button>
            ${cancel}
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

function renderRulesSection(state) {
    const hasWhitelistRules = nonEmptyLines(state.whitelistTagsText).length + nonEmptyLines(state.whitelistPhrasesText).length > 0;
    const showsWhitelist = [state.isWhitelistShown, hasWhitelistRules].includes(true);
    let whitelist = '';
    if (showsWhitelist) {
        whitelist = `
            <div class="ai-settings-chips">${renderRuleChips(state.whitelistTagsText, state.whitelistPhrasesText, 'whitelist')}</div>
            <input id="ai-agent-whitelist-input" type="text" placeholder="Tag, or &quot;a phrase&quot; in quotes" autocomplete="off" aria-label="Add an only-send rule">`;
    }
    return `
        <section class="ai-settings-section ai-agent-cloud-privacy-settings">
            <h3 title="${escapeHtml(PRIVACY_RULES_TOOLTIP)}">Never send notes with <span class="ai-settings-term">(blacklist)</span></h3>
            <div class="ai-settings-chips">${renderRuleChips(state.blacklistTagsText, state.blacklistPhrasesText, 'blacklist')}</div>
            <input id="ai-agent-blacklist-input" type="text" placeholder="Tag, or &quot;a phrase&quot; in quotes" autocomplete="off" aria-label="Add a never-send rule">
            <label class="ai-settings-check" title="${escapeHtml(PRIVACY_RULES_TOOLTIP)}">
                <input type="checkbox" id="ai-agent-whitelist-toggle" ${showsWhitelist ? 'checked' : ''}>
                <span>Only send notes with <span class="ai-settings-term">(whitelist)</span></span>
            </label>
            ${whitelist}
            <p class="ai-settings-hint">@password and @username notes are never sent.</p>
        </section>`;
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

        ApplicationState.own(this, 'AiAgentSettingsModal', new.target === AiAgentSettingsModal);
    }

    getInitialModalState() {
        const settings = this._readSettings();
        const tab = PROVIDER_TABS.find((entry) => entry.provider === settings.provider);
        if (tab === undefined) {
            throw new Error(`Unsupported AI provider: ${settings.provider}`);
        }
        return {
            // The open tab: it starts on the provider the chat uses.
            provider: settings.provider,
            // The token window belongs to the provider the chat uses, whichever tab is open.
            chatProvider: settings.provider,
            providerLabel: tab.label,
            webAccessMode: validateAgentWebAccessMode(settings.webAccessMode),
            ...cloudPrivacyPolicyToTextFields(settings.cloudPrivacyPolicy),
            ...retrievalStateFields(settings.openAiRetrievalSettings, settings.provider),
            isWhitelistShown: false,
            isLoadingCredential: false,
            isChangingKey: false,
            credentialConfigured: false,
            credentialPersistent: false,
            error: '',
        };
    }

    // The right-click menu's Cloud privacy item opens the dialog at its rules.
    focusCloudPrivacySettings() {
        if (!this.isOpen) {
            throw new Error('Cloud privacy settings cannot be focused while the modal is closed');
        }
        const section = document.querySelector('#ai-agent-settings-modal .ai-agent-cloud-privacy-settings');
        const firstInput = document.getElementById('ai-agent-blacklist-input');
        if (!(section instanceof HTMLElement) || !(firstInput instanceof HTMLInputElement)) {
            throw new Error('AI settings privacy rules missing');
        }
        section.scrollIntoView({ block: 'start' });
        firstInput.focus({ preventScroll: true });
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
                <div class="ai-settings-tabs" role="tablist" aria-label="AI provider">${tabs}</div>
                ${renderProviderPanel(state)}
                <section class="ai-settings-section">
                    <h3>Web access</h3>
                    <div class="ai-settings-segments" role="radiogroup" aria-label="Web access" id="ai-agent-web-access">${webChoices}</div>
                </section>
                ${renderRulesSection(state)}
                <section class="ai-settings-section ai-settings-limits">
                    <div class="ai-settings-stacked">
                        <span class="ai-settings-wide-label">
                            <label for="ai-agent-max-page-approximate-tokens">Max token window</label>
                            <span class="ai-settings-help" tabindex="0" role="img" aria-label="${escapeHtml(TOKEN_WINDOW_TOOLTIP)}" title="${escapeHtml(TOKEN_WINDOW_TOOLTIP)}">?</span>
                        </span>
                        <input id="ai-agent-max-page-approximate-tokens" type="number" autocomplete="off" data-1p-ignore data-lpignore="true" min="500" max="500000" step="100" value="${escapeHtml(String(state.maxPageApproximateTokens))}">
                    </div>
                </section>
                <p class="error-message" role="alert">${escapeHtml(state.error)}</p>
                <div class="form-actions">
                    <button type="button" class="primary-btn" id="ai-agent-save" data-modal-enter-action>Save</button>
                    <button type="button" class="secondary-btn" id="ai-agent-cancel">Cancel</button>
                </div>
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
        for (const tab of document.querySelectorAll('#ai-agent-settings-modal .ai-settings-tab')) {
            tab.onclick = () => void this._selectProvider(tab.dataset.provider);
        }
        this._setupKeyControls(state);
        for (const segment of document.querySelectorAll('#ai-agent-web-access .ai-settings-segment')) {
            segment.onclick = () => this._update({ webAccessMode: validateAgentWebAccessMode(segment.dataset.mode) });
        }
        this._setupRuleControls();
        const limitInput = this._element('ai-agent-max-page-approximate-tokens', HTMLInputElement);
        limitInput.oninput = () => {
            this._setState({ maxPageApproximateTokens: Number(limitInput.value), error: '' });
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
            input.onkeydown = (event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                event.stopPropagation();
                this._addRules(side, [input.value], `ai-agent-${side}-input`);
            };
            // A pasted list (one rule per line, or comma-separated) adds every rule.
            input.onpaste = (event) => {
                const text = event.clipboardData.getData('text/plain');
                if (!/[\n,]/.test(text)) return;
                event.preventDefault();
                this._addRules(side, text.split(/[\n,]/), `ai-agent-${side}-input`);
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

    // The state store rejects a write that changes nothing; a repeated status or error is one.
    _setState(fields) {
        const current = this.getModalState();
        if (!stateValuesEqual(current, { ...current, ...fields })) this.updateModalState(fields);
    }

    _update(fields) {
        this._setState({ ...fields, error: '' });
        this.renderModalContent();
    }

    _addRules(side, entries, focusId) {
        const state = this.getModalState();
        let tags = nonEmptyLines(state[`${side}TagsText`]);
        let phrases = nonEmptyLines(state[`${side}PhrasesText`]);
        for (const entry of entries) {
            if (entry.trim() === '') continue;
            const rule = parsePrivacyRuleEntry(entry);
            if (rule.kind === 'phrase' && !phrases.includes(rule.value)) phrases = [...phrases, rule.value];
            if (rule.kind === 'tag' && !tags.includes(rule.value)) tags = [...tags, rule.value];
        }
        const fields = { [`${side}TagsText`]: tags.join('\n'), [`${side}PhrasesText`]: phrases.join('\n') };
        const problem = getCloudPrivacyTextFieldsValidationMessage({ ...state, ...fields });
        if (problem !== '') {
            this._setState({ error: problem });
            this.renderModalContent();
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
        this._setState({ isLoadingCredential: true, error: '' });
        this.renderModalContent();
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
            this._setState({ error: error.message });
        } finally {
            if (this.isCurrentOpen(generation)) {
                this._setState({ isLoadingCredential: false });
                this.renderModalContent();
            }
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
            this._setState({ error: `Paste your ${state.providerLabel} API key first.` });
            this.renderModalContent();
            return;
        }
        this._setState({ isLoadingCredential: true, error: '' });
        this.renderModalContent();
        try {
            this._applyCredentialStatus(await saveAiCredential(state.provider, apiKey));
            this._setState({ isChangingKey: false });
            announceKeyChange();
        } catch (error) {
            rethrowUnexpectedError(error);
            if (!(error instanceof AiApiError)) {
                throw error;
            }
            this._setState({ error: error.message });
        } finally {
            this._setState({ isLoadingCredential: false });
            this.renderModalContent();
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
            this._setState({ error: error.message });
            this.renderModalContent();
        }
    }

    async _handleSave() {
        const state = this.getModalState();
        const retrievalSettings = { maxPageApproximateTokens: state.maxPageApproximateTokens };
        const limitProblem = getAgentRetrievalSettingsValidationMessage(retrievalSettings, state.chatProvider);
        if (limitProblem !== '') {
            this._setState({ error: limitProblem });
            this.renderModalContent();
            return;
        }
        const privacyProblem = getCloudPrivacyTextFieldsValidationMessage(state);
        if (privacyProblem !== '') {
            this._setState({ error: privacyProblem });
            this.renderModalContent();
            return;
        }
        await this._saveSettings({
            webAccessMode: validateAgentWebAccessMode(state.webAccessMode),
            openAiRetrievalSettings: validateAgentRetrievalSettings(retrievalSettings, state.chatProvider),
            cloudPrivacyPolicy: parseCloudPrivacyTextFields(state),
        });
        this.close();
    }
}
