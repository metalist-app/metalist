import { parseDecimalInteger } from '../decimal-integer.js';
import { ApplicationState } from '../application-state.js';
import { rethrowUnexpectedError } from '../expected-errors.js';
import { BaseModal } from './base-modal.js';
import {
    DEFAULT_PASSWORD_CHARSET,
    DEFAULT_PASSWORD_LENGTH,
    generateRandomPassword,
    normalizePasswordCharset,
} from '../password-generator.js';
import {
    evaluatePasswordStrength,
    loadPasswordStrengthEstimator,
} from '../password-strength.js';
import { PASSWORD_MIN_ZXCVBN_SCORE } from '../password-policy.js';
import {
    DEFAULT_PASSPHRASE_WORD_COUNT,
    MAX_PASSPHRASE_WORD_COUNT,
    generatePassphrase,
    loadPassphraseWords,
} from '../passphrase.js';
import { rememberGeneratedPasswordCopy } from '../mode-manager/services/password-clipboard-service.js';
import { escapeHtml } from '../html-escape.js';
import { showErrorDialog } from './error-dialog.js';

// Help lives in tooltips, so the dialog fits without scrolling (2026-10-29).
const COPY_HINT_DEFAULT = 'Copy to clipboard. Pasting into an empty note will add @password automatically.';
const COPIED_HINT = 'Copied. Pasting into an empty note will add @password.';
const COPY_LABEL = 'Copy';
const COPIED_LABEL = 'Copied';
const MAX_PASSWORD_LENGTH = 72;
// Characters from a set, or words from the passphrase list (docs/ui/command-palette.md).
const MODE_CHARACTERS = 'characters';
const MODE_WORDS = 'words';

// The Copy button says when the candidate was copied; its tooltip says what pasting does.
function showCopyState(copyButton, isCopied) {
    copyButton.textContent = isCopied ? COPIED_LABEL : COPY_LABEL;
    copyButton.title = isCopied ? COPIED_HINT : COPY_HINT_DEFAULT;
}

export class RandomPasswordModal extends BaseModal {
    constructor() {
        super('randomPasswordModal', 'random-password-modal');

        ApplicationState.own(this, 'RandomPasswordModal', new.target === RandomPasswordModal);
    }

    getInitialModalState() {
        return {
            mode: MODE_CHARACTERS,
            wordCount: DEFAULT_PASSPHRASE_WORD_COUNT,
            length: DEFAULT_PASSWORD_LENGTH,
            charsetInput: DEFAULT_PASSWORD_CHARSET,
            result: '',
            copyStatus: '',
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

    onOpen() {
        this.renderModalContent();
        this.regeneratePassword();
        loadPasswordStrengthEstimator()
            .then(() => {
                if (!this.isOpen) {
                    return;
                }
                const resultOutput = document.getElementById('password-result-output');
                if (!(resultOutput instanceof HTMLInputElement)) {
                    throw new Error('password-result-output missing');
                }
                this.renderPasswordStrength(resultOutput.value);
            })
            .catch((error) => {
            rethrowUnexpectedError(error);
                console.error('Password strength estimator failed');
                if (!this.isOpen) {
                    return;
                }
                this.renderPasswordStrengthUnavailable();
            });
    }

    onClose() {
        // BaseModal disposes the state scope; clear retained form DOM as well.
        document.getElementById(this.modalElementId).replaceChildren();
    }

    onKeyDown(event) {
        if (!(event instanceof KeyboardEvent)) {
            throw new Error('RandomPasswordModal.onKeyDown requires KeyboardEvent');
        }
        if (event.key !== 'Enter') {
            return;
        }

        const target = event.target;
        if (target instanceof HTMLTextAreaElement) {
            return;
        }
        if (target instanceof HTMLButtonElement) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        this.regeneratePassword();
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!modalElement) {
            throw new Error(`Modal element missing: ${this.modalElementId}`);
        }

        const state = this.getModalState();
        const lengthValue = Number.isInteger(state.length) ? state.length : DEFAULT_PASSWORD_LENGTH;
        const charsetInput = typeof state.charsetInput === 'string' ? state.charsetInput : DEFAULT_PASSWORD_CHARSET;
        const result = typeof state.result === 'string' ? state.result : '';
        const isWords = state.mode === MODE_WORDS;
        const lengthGroup = isWords ? `
                    <div class="form-group random-password-length-group">
                        <label for="password-word-count-input">Password length</label>
                        <div class="random-password-length-control">
                            <input type="number" id="password-word-count-input" min="1" max="${MAX_PASSPHRASE_WORD_COUNT}" step="1" inputmode="numeric">
                            <span class="random-password-length-unit">words</span>
                        </div>
                    </div>` : `
                    <div class="form-group random-password-length-group">
                        <label for="password-length-input">Password length</label>
                        <div class="random-password-length-control">
                            <input
                                type="number"
                                id="password-length-input"
                                min="1"
                                max="${MAX_PASSWORD_LENGTH}"
                                step="1"
                                inputmode="numeric"
                            >
                            <span class="random-password-length-unit">characters</span>
                        </div>
                    </div>`;
        const charsetGroup = isWords ? '' : `
                <div class="form-group">
                    <label for="password-charset-input">Character set</label>
                    <textarea id="password-charset-input" rows="4" spellcheck="false" title="Line breaks are ignored; every other character can be used."></textarea>
                </div>`;
        const isCopied = state.copyStatus === COPIED_HINT;

        modalElement.innerHTML = `
            <div class="modal-content random-password-modal-content">
                <div class="random-password-modal-header">
                    <h3>Generate Random Password</h3>
                </div>

                <div class="random-password-modal-top-row">
                    <div class="form-group random-password-mode-group">
                        <label for="password-mode-select">Made of</label>
                        <select id="password-mode-select">
                            <option value="${MODE_CHARACTERS}" ${isWords ? '' : 'selected'}>Characters</option>
                            <option value="${MODE_WORDS}" ${isWords ? 'selected' : ''}>Words</option>
                        </select>
                    </div>
                    ${lengthGroup}
                </div>
${charsetGroup}

                <div class="form-group">
                    <label for="password-result-output">Password candidate</label>
                    <div class="random-password-result-row">
                        <input
                            type="text"
                            id="password-result-output"
                            spellcheck="false"
                            autocomplete="off"
                            autocapitalize="none"
                            title="Type or paste your own password to test its strength locally."
                        >
                        <button
                            type="button"
                            class="secondary-btn random-password-copy-btn"
                            id="password-copy-btn"
                            title="${escapeHtml(isCopied ? COPIED_HINT : COPY_HINT_DEFAULT)}"
                            ${result.length === 0 ? 'disabled' : ''}
                        >${isCopied ? COPIED_LABEL : COPY_LABEL}</button>
                    </div>
                </div>

                <div class="password-strength" id="password-strength" data-score="pending">
                    <div class="password-strength-header">
                        <span>Strength</span>
                        <strong id="password-strength-label">Calculating...</strong>
                    </div>
                    <div
                        class="password-strength-meter"
                        id="password-strength-meter"
                        role="meter"
                        aria-label="Password candidate strength"
                        aria-valuemin="0"
                        aria-valuemax="4"
                    >
                        <span></span>
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                    <small class="form-help" id="password-strength-policy">Loading the local strength estimator.</small>
                </div>

                <div class="form-actions random-password-modal-actions">
                    <button type="button" class="primary-btn" id="password-regenerate-btn">Regenerate</button>
                </div>

            </div>
        `;

        if (isWords) {
            const wordCountInput = document.getElementById('password-word-count-input');
            if (!(wordCountInput instanceof HTMLInputElement)) {
                throw new Error('password-word-count-input missing');
            }
            wordCountInput.value = String(state.wordCount);
        } else {
            const lengthInput = document.getElementById('password-length-input');
            if (!(lengthInput instanceof HTMLInputElement)) {
                throw new Error('password-length-input missing');
            }
            lengthInput.value = String(lengthValue);

            const charsetTextArea = document.getElementById('password-charset-input');
            if (!(charsetTextArea instanceof HTMLTextAreaElement)) {
                throw new Error('password-charset-input missing');
            }
            charsetTextArea.value = charsetInput;
        }

        const resultOutput = document.getElementById('password-result-output');
        if (!(resultOutput instanceof HTMLInputElement)) {
            throw new Error('password-result-output missing');
        }
        resultOutput.value = result;

        this.renderPasswordStrength(result);
        this.setupFormEventListeners();
    }

    renderPasswordStrength(password) {
        const strengthContainer = document.getElementById('password-strength');
        const strengthLabel = document.getElementById('password-strength-label');
        const strengthMeter = document.getElementById('password-strength-meter');
        const strengthPolicy = document.getElementById('password-strength-policy');
        if (!(strengthContainer instanceof HTMLElement)) {
            throw new Error('password-strength missing');
        }
        if (!(strengthLabel instanceof HTMLElement)) {
            throw new Error('password-strength-label missing');
        }
        if (!(strengthMeter instanceof HTMLElement)) {
            throw new Error('password-strength-meter missing');
        }
        if (!(strengthPolicy instanceof HTMLElement)) {
            throw new Error('password-strength-policy missing');
        }

        if (password.length === 0) {
            strengthContainer.dataset.score = 'pending';
            strengthLabel.textContent = 'Enter a password';
            strengthMeter.removeAttribute('aria-valuenow');
            strengthPolicy.textContent = 'Type or paste a candidate to test it locally.';
            return;
        }
        if (typeof globalThis.zxcvbn !== 'function') {
            strengthContainer.dataset.score = 'pending';
            strengthLabel.textContent = 'Calculating...';
            strengthMeter.removeAttribute('aria-valuenow');
            strengthPolicy.textContent = 'Loading the local strength estimator.';
            return;
        }

        const strength = evaluatePasswordStrength(password, globalThis.zxcvbn);
        strengthContainer.dataset.score = String(strength.score);
        strengthLabel.textContent = `${strength.label} · ${strength.score}/4`;
        strengthMeter.setAttribute('aria-valuenow', String(strength.score));
        strengthPolicy.textContent = strength.meetsScoreThreshold
            ? 'Strong enough for a vault password.'
            : `A vault password needs ${PASSWORD_MIN_ZXCVBN_SCORE}/4.`;
    }

    renderPasswordStrengthUnavailable() {
        const strengthContainer = document.getElementById('password-strength');
        const strengthLabel = document.getElementById('password-strength-label');
        const strengthMeter = document.getElementById('password-strength-meter');
        const strengthPolicy = document.getElementById('password-strength-policy');
        if (!(strengthContainer instanceof HTMLElement)) {
            throw new Error('password-strength missing');
        }
        if (!(strengthLabel instanceof HTMLElement)) {
            throw new Error('password-strength-label missing');
        }
        if (!(strengthMeter instanceof HTMLElement)) {
            throw new Error('password-strength-meter missing');
        }
        if (!(strengthPolicy instanceof HTMLElement)) {
            throw new Error('password-strength-policy missing');
        }

        strengthContainer.dataset.score = 'unavailable';
        strengthLabel.textContent = 'Unavailable';
        strengthMeter.removeAttribute('aria-valuenow');
        strengthPolicy.textContent = 'The local strength estimator could not be loaded.';
    }

    setupFormEventListeners() {
        const modeSelect = document.getElementById('password-mode-select');
        if (modeSelect instanceof HTMLSelectElement) {
            modeSelect.onchange = () => {
                this.updateModalState({ mode: modeSelect.value, result: '' });
                this.renderModalContent();
                this.regeneratePassword();
            };
        }

        const regenerateButton = document.getElementById('password-regenerate-btn');
        if (regenerateButton instanceof HTMLButtonElement) {
            regenerateButton.onclick = () => this.regeneratePassword();
        }

        const copyButton = document.getElementById('password-copy-btn');
        if (copyButton instanceof HTMLButtonElement) {
            copyButton.onclick = async () => {
                await this.copyResultToClipboard();
            };
        }

        const resultOutput = document.getElementById('password-result-output');
        if (resultOutput instanceof HTMLInputElement) {
            resultOutput.oninput = () => {
                const password = resultOutput.value;
                if (!(copyButton instanceof HTMLButtonElement)) {
                    throw new Error('password-copy-btn missing');
                }

                copyButton.disabled = password.length === 0;
                showCopyState(copyButton, false);
                this.updateModalState({
                    result: password,
                    copyStatus: COPY_HINT_DEFAULT,
                });
                this.renderPasswordStrength(resultOutput.value);
            };
        }
    }

    async copyResultToClipboard() {
        const resultOutput = document.getElementById('password-result-output');
        if (!(resultOutput instanceof HTMLInputElement)) {
            throw new Error('password-result-output missing');
        }
        const value = resultOutput.value;
        if (value.length === 0) {
            return;
        }

        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(value);
        } else {
            resultOutput.focus();
            resultOutput.select();
            const copied = document.execCommand('copy');
            if (!copied) {
                throw new Error('Clipboard copy failed');
            }
        }

        rememberGeneratedPasswordCopy(value);
        resultOutput.focus();
        resultOutput.select();
        this.updateModalState({ copyStatus: COPIED_HINT });

        const copyButton = document.getElementById('password-copy-btn');
        if (!(copyButton instanceof HTMLButtonElement)) {
            throw new Error('password-copy-btn missing');
        }
        showCopyState(copyButton, true);
    }

    regeneratePassword() {
        if (this.getModalState().mode === MODE_WORDS) {
            void this.regenerateWords();
            return;
        }
        const lengthInput = document.getElementById('password-length-input');
        const charsetInput = document.getElementById('password-charset-input');
        const resultOutput = document.getElementById('password-result-output');

        if (!(lengthInput instanceof HTMLInputElement)) {
            throw new Error('password-length-input missing');
        }
        if (!(charsetInput instanceof HTMLTextAreaElement)) {
            throw new Error('password-charset-input missing');
        }
        if (!(resultOutput instanceof HTMLInputElement)) {
            throw new Error('password-result-output missing');
        }

        const copyButton = document.getElementById('password-copy-btn');
        if (!(copyButton instanceof HTMLButtonElement)) {
            throw new Error('password-copy-btn missing');
        }

        const lengthValue = parseDecimalInteger(lengthInput.value);
        const charsetValue = charsetInput.value;
        if (!Number.isInteger(lengthValue) || lengthValue <= 0) {
            resultOutput.value = '';
            copyButton.disabled = true;
            this.updateModalState({
                length: lengthValue,
                charsetInput: charsetValue,
                result: '',
                copyStatus: COPY_HINT_DEFAULT,
            });
            showCopyState(copyButton, false);
            void showErrorDialog([{ text: 'Password length must be a positive integer.', fieldId: 'password-length-input' }]);
            return;
        }
        if (lengthValue > MAX_PASSWORD_LENGTH) {
            resultOutput.value = '';
            copyButton.disabled = true;
            this.updateModalState({
                length: lengthValue,
                charsetInput: charsetValue,
                result: '',
                copyStatus: COPY_HINT_DEFAULT,
            });
            showCopyState(copyButton, false);
            void showErrorDialog([{ text: `Password length must be ${MAX_PASSWORD_LENGTH} or less.`, fieldId: 'password-length-input' }]);
            return;
        }

        const charsetWithoutLineBreaks = charsetValue.replace(/\r/g, '').replace(/\n/g, '');
        if (charsetWithoutLineBreaks.length === 0) {
            resultOutput.value = '';
            copyButton.disabled = true;
            this.updateModalState({
                length: lengthValue,
                charsetInput: charsetValue,
                result: '',
                copyStatus: COPY_HINT_DEFAULT,
            });
            showCopyState(copyButton, false);
            void showErrorDialog([{ text: 'Character set must not be empty.', fieldId: 'password-charset-input' }]);
            return;
        }

        const normalizedCharset = normalizePasswordCharset(charsetValue);
        const generated = generateRandomPassword(lengthValue, normalizedCharset, null);
        this.showGenerated(generated, { length: lengthValue, charsetInput: charsetValue });
    }

    async regenerateWords() {
        const wordCountInput = document.getElementById('password-word-count-input');
        if (!(wordCountInput instanceof HTMLInputElement)) {
            throw new Error('password-word-count-input missing');
        }
        const wordCount = parseDecimalInteger(wordCountInput.value);
        if (!Number.isInteger(wordCount) || wordCount <= 0 || wordCount > MAX_PASSPHRASE_WORD_COUNT) {
            void showErrorDialog([{
                text: `Words must be a whole number from 1 through ${MAX_PASSPHRASE_WORD_COUNT}.`, fieldId: 'password-word-count-input',
            }]);
            return;
        }
        const words = await loadPassphraseWords();
        if (!this.isOpen || this.getModalState().mode !== MODE_WORDS) {
            return;
        }
        this.showGenerated(generatePassphrase(words, wordCount, null), { wordCount });
    }

    showGenerated(generated, settings) {
        const resultOutput = document.getElementById('password-result-output');
        const copyButton = document.getElementById('password-copy-btn');
        if (!(resultOutput instanceof HTMLInputElement)) {
            throw new Error('password-result-output missing');
        }
        if (!(copyButton instanceof HTMLButtonElement)) {
            throw new Error('password-copy-btn missing');
        }
        resultOutput.value = generated;
        this.renderPasswordStrength(generated);
        copyButton.disabled = false;
        showCopyState(copyButton, false);
        this.updateModalState({ ...settings, result: generated, copyStatus: COPY_HINT_DEFAULT });
    }
}
