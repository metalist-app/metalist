import { ApplicationState } from '../application-state.js';
import { escapeHtml } from '../html-escape.js';
import { CONFIG } from '../config.js';
import { settleResult } from '../async-result.js';
import { AI_KEY_WARNINGS, AI_PROVIDERS, aiProvider } from '../ai-chat/ai-providers.js';
import { checkAiCredential, saveAiCredential } from '../ai-chat/ai-chat-api.js';
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, calculatePasswordLengthProgress } from '../password-policy.js';
import { evaluatePasswordStrength, loadPasswordStrengthEstimator } from '../password-strength.js';
import {
    assertCatalogShape, assertProfileShape, parsePort, portOverlapProblems, portProblem, requestVaultApi, stringifyPort,
} from '../modals/namespace-modals.js';
import { vaultNameProblem } from '../modals/namespace-rename-validation.js';
import { renderNamespaceLoadingTab } from '../modals/namespace-loading-page.js';
import { rewriteNamespaceUrlPreservingCurrentHost } from '../login-namespace-picker.js';
import { showErrorDialogFor } from '../modals/error-dialog.js';
import { VAULT_WIZARD_STEP, withSetupSteps } from '../new-vault-setup.js';
import { LOWEST_PORT, HIGHEST_PORT } from '../tcp-ports.js';
import {
    NOTHING_MISSING, choiceCardsHtml, fillImportPreview, importSteps, makeStep, runImport, runStep, toggledSectionHtml,
    wireToggles,
} from './import-wizard-steps.js';

// The new vault wizard's steps (PLAN.md, phase 2): Vault (Create Vault, in the vault it is
// opened from), then, in the new vault, Password, AI, Your notes and the import's steps,
// the Summary, and Setting up, which applies them: the password first (this window stays
// logged in), then the AI key (kept, as the vault now has a password), then the import.

const NEXT = 'Next';
const PERCENT = 100;
const ALWAYS = () => true;
const NOTHING_TO_WIRE = () => {};
const PASSWORD_SELECTOR = '.wizard-password';
const CONFIRM_SELECTOR = '.wizard-password-confirm';
const KEY_SELECTOR = '.wizard-key-input';

// What is typed for the password and the AI key: kept out of the wizard's choices and
// screens (a screen is gone once left), until the setup uses them or the wizard closes.
const typed = ApplicationState.createFields('new-vault-typed', { password: '', aiKey: '', aiKeyProvider: '' });

function remember(field, value) {
    if (typed[field] !== value) typed[field] = value;
}

export function forgetTypedSecrets() {
    for (const field of ['password', 'aiKey', 'aiKeyProvider']) remember(field, '');
}

/** A new run's choices: the import's, and the vault's name and ports (read on its step). */
export function newVaultChoices(importChoices) {
    return {
        ...importChoices, catalogLoaded: false, vaultNames: [], supportsHttps: false,
        vaultName: '', httpPort: '', httpsPort: '',
        protectsWithPassword: true, setsUpAi: true, aiProvider: AI_PROVIDERS[0].provider,
    };
}

// --- Vault: the name and ports, in the vault Create Vault is opened from -------------------

async function loadVaultCatalog(wizard) {
    const catalog = await requestVaultApi(CONFIG.API.AUTH.NAMESPACES.LIST, 'GET', null);
    assertCatalogShape(catalog);
    const profile = catalog.new_namespace_profile;
    assertProfileShape(profile);
    if (!wizard.isOpen) return;
    wizard.chooseMany({
        catalogLoaded: true, vaultNames: catalog.namespaces.map((entry) => entry.namespace),
        supportsHttps: Boolean(catalog.supports_https), httpPort: stringifyPort(profile.port),
        httpsPort: stringifyPort(profile.https_port),
    });
    wizard.redrawScreen();
}

// What is wrong with the name and ports, said for the user ('' when nothing is).
function vaultProblem(choices) {
    if (!choices.catalogLoaded) return 'The vaults are still loading.';
    const problems = [
        vaultNameProblem({ name: choices.vaultName.trim(), existingNamespaces: choices.vaultNames, currentNamespace: null }),
        portProblem(choices.httpPort, 'HTTP port'),
    ];
    if (choices.supportsHttps) problems.push(portProblem(choices.httpsPort, 'HTTPS port'));
    const typed = problems.find((text) => text !== '');
    if (typed !== undefined) return typed;
    const overlaps = portOverlapProblems([vaultPortRow(choices)]);
    if (overlaps.length > 0) return overlaps[0].text;
    return '';
}

function vaultPortRow(choices) {
    let httpsPort = null;
    if (choices.supportsHttps) httpsPort = parsePort(choices.httpsPort);
    return {
        namespace: choices.vaultName.trim(), port: parsePort(choices.httpPort), https_port: httpsPort,
        portFieldId: null, httpsPortFieldId: null,
    };
}

function portFieldHtml(label, choiceKey, value) {
    return `<label class="wizard-field"><span>${escapeHtml(label)}</span>
        <input type="number" class="wizard-input" data-wizard-text="${escapeHtml(choiceKey)}" min="${LOWEST_PORT}" max="${HIGHEST_PORT}"
            value="${escapeHtml(value)}"></label>`;
}

// Creating opens the new vault in a new tab (opened before the request, so no blocker stops
// it), straight into the rest of the wizard; this tab's wizard closes.
async function createVault(wizard) {
    const row = vaultPortRow(wizard.choices);
    const pendingTab = window.open('about:blank', '_blank');
    if (pendingTab !== null) renderNamespaceLoadingTab(pendingTab, row.namespace);
    const created = await settleResult(async () => {
        const response = await requestVaultApi(CONFIG.API.AUTH.NAMESPACES.OPEN, 'POST',
            { namespace: row.namespace, port: row.port, https_port: row.https_port });
        if (!response || typeof response.url !== 'string' || response.url === '') {
            throw new Error('Vault create response missing url');
        }
        return response.url;
    });
    if (!created.ok) {
        if (pendingTab !== null && !pendingTab.closed) pendingTab.close();
        await showErrorDialogFor(created.error, null);
        return;
    }
    const address = withSetupSteps(rewriteNamespaceUrlPreservingCurrentHost(created.value, window.location), [VAULT_WIZARD_STEP]);
    if (pendingTab !== null && !pendingTab.closed) {
        pendingTab.location.replace(address);
    } else {
        window.open(address, '_blank', 'noopener,noreferrer');
    }
    wizard.close();
}

function vaultStep() {
    return makeStep({
        key: 'vault', label: 'Vault', title: 'Name your new vault',
        intro: 'A vault is a separate set of notes at its own address. It opens in a new tab.',
        nextLabel: 'Create Vault', isAction: false, applies: ALWAYS,
        render: (choices) => {
            if (!choices.catalogLoaded) return '<p class="wizard-note">Loading your vaults…</p>';
            let httpsField = '';
            if (choices.supportsHttps) httpsField = portFieldHtml('HTTPS port', 'httpsPort', choices.httpsPort);
            return `
                <label class="wizard-field"><span>Vault name</span>
                    <input type="text" class="wizard-input" data-wizard-text="vaultName" value="${escapeHtml(choices.vaultName)}"
                        placeholder="work" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-wizard-focus></label>
                <div class="wizard-port-row">${portFieldHtml('HTTP port', 'httpPort', choices.httpPort)}${httpsField}</div>`;
        },
        wire: async (screen, wizard) => {
            if (!wizard.choices.catalogLoaded) {
                await loadVaultCatalog(wizard);
                return;
            }
            for (const input of screen.querySelectorAll('[data-wizard-text]')) {
                input.addEventListener('input', () => wizard.choose(input.dataset.wizardText, input.value));
            }
        },
        onChoice: null, onNext: createVault, missing: vaultProblem,
    });
}

// --- Password ---------------------------------------------------------------------------

function strengthHtml() {
    return `
        <div class="password-strength wizard-strength" data-score="pending">
            <div class="password-strength-header"><span>Strength</span><strong class="wizard-strength-label">Enter a password</strong></div>
            <div class="password-strength-meter" role="meter" aria-label="Password strength" aria-valuemin="0" aria-valuemax="4">
                <span></span><span></span><span></span><span></span>
            </div>
        </div>`;
}

function showStrength(screen) {
    const container = screen.querySelector('.wizard-strength');
    const label = screen.querySelector('.wizard-strength-label');
    const password = screen.querySelector(PASSWORD_SELECTOR).value;
    if (password === '' || typeof globalThis.zxcvbn !== 'function') {
        container.dataset.score = 'pending';
        label.textContent = password === '' ? 'Enter a password' : 'Checking…';
        return;
    }
    const strength = evaluatePasswordStrength(password, globalThis.zxcvbn);
    container.dataset.score = String(strength.score);
    label.textContent = strength.label;
}

// What the password still needs ('' when it is ready): long enough, strong enough, typed twice.
function missingPassword(choices, screen) {
    if (!choices.protectsWithPassword) return '';
    const password = screen.querySelector(PASSWORD_SELECTOR).value;
    if (password === '') return 'Type a password, or untick the box to go without one.';
    const length = calculatePasswordLengthProgress(password);
    if (!length.meetsMinimumLength) {
        return `The password needs ${length.remainingCharacterCount} more characters (at least ${PASSWORD_MIN_LENGTH}).`;
    }
    if (typeof globalThis.zxcvbn !== 'function') return 'The strength check is still loading.';
    const strength = evaluatePasswordStrength(password, globalThis.zxcvbn);
    if (!strength.meetsScoreThreshold) return `Choose a stronger password: this one is ${strength.label.toLowerCase()}.`;
    if (screen.querySelector(CONFIRM_SELECTOR).value !== password) return 'The two passwords don\'t match.';
    return '';
}

// Each field gets the text as if typed, so Next and the meter follow.
function fillPassword(screen, password) {
    for (const selector of [PASSWORD_SELECTOR, CONFIRM_SELECTOR]) {
        const input = screen.querySelector(selector);
        input.value = password;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }
}

function passwordStep() {
    const field = (label, className) => `<label class="wizard-field"><span>${label}</span>
        <input type="password" class="wizard-input ${className}" autocomplete="new-password" maxlength="${PASSWORD_MAX_LENGTH}"></label>`;
    return makeStep({
        key: 'password', label: 'Password', title: 'A password for this vault',
        intro: 'With a password, your notes are encrypted and your AI key is kept. Write it down: MetaList can\'t recover a forgotten password.',
        nextLabel: NEXT, isAction: false, applies: ALWAYS,
        render: (choices) => toggledSectionHtml({
            choiceKey: 'protectsWithPassword', label: 'Protect this vault with a password', isOn: choices.protectsWithPassword,
            bodyHtml: `${field('Password', 'wizard-password')}${field('Confirm', 'wizard-password-confirm')}${strengthHtml()}
                <button type="button" class="secondary-btn wizard-generate">Generate Password…</button>`,
        }),
        wire: (screen, wizard) => {
            wireToggles(screen, wizard);
            const password = screen.querySelector(PASSWORD_SELECTOR);
            password.addEventListener('input', () => showStrength(screen));
            password.value = typed.password;
            screen.querySelector(CONFIRM_SELECTOR).value = typed.password;
            showStrength(screen);
            screen.querySelector('.wizard-generate').onclick = async () => {
                await wizard.services.openPasswordGenerator((generated) => fillPassword(screen, generated));
            };
            void loadPasswordStrengthEstimator().then(() => {
                if (!screen.isConnected) return;
                showStrength(screen);
                screen.dispatchEvent(new Event('input'));
            });
        },
        onChoice: null,
        onNext: async (wizard) => {
            let password = '';
            if (wizard.choices.protectsWithPassword) password = currentScreen(wizard).querySelector(PASSWORD_SELECTOR).value;
            remember('password', password);
            wizard.next();
        },
        missing: missingPassword,
    });
}

function currentScreen(wizard) {
    const screens = document.querySelectorAll(`#${wizard.modalElementId} .wizard-screen`);
    return screens[screens.length - 1];
}

// --- AI ---------------------------------------------------------------------------------

/**
 * The AI step's body: the providers MetaList offers as
 * cards, and the key of the one chosen, with its warning when it has one (as AI Agent
 * Settings shows them).
 */
function aiKeyHtml(choices) {
    const chosen = aiProvider(choices.aiProvider);
    const cards = AI_PROVIDERS.map((entry) => ({
        value: entry.provider, title: entry.label, badge: '', text: `A key from ${new URL(entry.billingUrl).host}`,
    }));
    let warning = '';
    if (Object.hasOwn(AI_KEY_WARNINGS, chosen.provider)) {
        const keyWarning = AI_KEY_WARNINGS[chosen.provider];
        warning = `<p class="wizard-note wizard-warning" title="${escapeHtml(keyWarning.tooltip)}">${escapeHtml(keyWarning.text)}</p>`;
    }
    return `
        ${choiceCardsHtml('aiProvider', chosen.provider, cards, 'grid')}
        <label class="wizard-field wizard-key-field"><span>${escapeHtml(chosen.label)} API key</span>
            <input type="password" class="wizard-input wizard-key-input" placeholder="Paste your API key" autocomplete="new-password" data-1p-ignore data-lpignore="true"></label>
        ${warning}`;
}

/** What an AI step with its key field still needs: the key ('' once typed); or untick to withoutIt. */
function missingKey(choices, screen, withoutIt) {
    if (screen.querySelector('.wizard-key-input').value.trim() !== '') return '';
    return `Paste your ${aiProvider(choices.aiProvider).label} API key, or untick the box to ${withoutIt}.`;
}

/** The AI step's body: "Set up an AI", ticked, over the providers and the key. */
function aiStepHtml(choices) {
    return toggledSectionHtml({ choiceKey: 'setsUpAi', label: 'Set up an AI', isOn: choices.setsUpAi, bodyHtml: aiKeyHtml(choices) });
}

function aiStep() {
    return makeStep({
        key: 'ai', label: 'AI', title: 'An AI for your notes',
        intro: 'An AI can answer questions about your notes and suggest tags. Pick the company whose key you have.',
        nextLabel: NEXT, isAction: false, applies: ALWAYS,
        render: (choices) => aiStepHtml(choices),
        wire: (screen, wizard) => {
            wireToggles(screen, wizard);
            // A key typed for another company is not this one's.
            if (typed.aiKeyProvider === wizard.choices.aiProvider) screen.querySelector(KEY_SELECTOR).value = typed.aiKey;
        },
        onChoice: null,
        // The key is checked here, saved once the vault has its password (Setting up).
        onNext: async (wizard) => {
            const { setsUpAi, aiProvider: provider } = wizard.choices;
            if (!setsUpAi) {
                wizard.next();
                return;
            }
            const apiKey = currentScreen(wizard).querySelector(KEY_SELECTOR).value.trim();
            const checked = await settleResult(async () => checkAiCredential(provider, apiKey));
            if (!checked.ok) {
                await showErrorDialogFor(checked.error, null);
                return;
            }
            remember('aiKey', apiKey);
            remember('aiKeyProvider', provider);
            wizard.next();
        },
        missing: (choices, screen) => (choices.setsUpAi ? missingKey(choices, screen, 'go without an AI') : ''),
    });
}

// --- Your notes, Summary, Setting up ----------------------------------------------------

const NOTES_SOURCES = [
    { value: 'obsidian', title: 'Obsidian vault', badge: '', text: 'Bring in a vault, its folders, links and attachments.' },
    { value: 'markdown', title: 'Markdown folder', badge: '', text: 'A folder of .md files from any app.' },
    { value: 'empty', title: 'Start empty', badge: '', text: 'Begin with a blank list.' },
];

function summaryLines(choices) {
    const lines = [choices.protectsWithPassword ? 'Your vault will be protected with a password.' : 'Your vault will have no password.'];
    lines.push(choices.setsUpAi ? `${aiProvider(choices.aiProvider).label} will be your AI.` : 'No AI will be set up.');
    if (choices.source === 'empty') lines.push('Your vault will start empty.');
    return lines;
}

// Setting up, in order: the password (this window stays logged in), the AI key, the import.
async function setUpVault(wizard, progress) {
    const choices = wizard.choices;
    if (choices.protectsWithPassword) {
        const text = 'Protecting your vault with a password…';
        progress.counted(0, PERCENT, text);
        await wizard.services.setPassword(typed.password, (percent) => progress.counted(percent, PERCENT, text));
    }
    if (choices.setsUpAi) {
        progress.working('Saving your AI key…');
        const entry = aiProvider(choices.aiProvider);
        await saveAiCredential(entry.provider, typed.aiKey);
        const current = wizard.services.getAiSettings();
        await wizard.services.saveAiSettings({ provider: entry.provider, model: entry.defaultModel, thinkingLevel: current.thinkingLevel });
    }
    forgetTypedSecrets();
    if (choices.source !== 'empty') await runImport(wizard, progress);
}

/** The new vault wizard's steps, in order. */
export function newVaultSteps() {
    // Importing once a source is picked (none is at first, as in the import wizard).
    const importing = (choices) => choices.source !== 'empty' && choices.source !== '';
    const withImport = importSteps({ withSourceStep: false, withSummaryAndRun: false })
        .map((step) => makeStep({ ...step, applies: (choices) => importing(choices) && step.applies(choices) }));
    return [
        vaultStep(),
        passwordStep(),
        aiStep(),
        makeStep({
            key: 'notes', label: 'Your notes', title: 'Bring in your notes?',
            intro: 'Already keeping notes somewhere? MetaList can bring them in now, or any time from the command palette.',
            nextLabel: NEXT, isAction: false, applies: ALWAYS,
            render: (choices) => choiceCardsHtml('source', choices.source, NOTES_SOURCES, 'grid'),
            wire: NOTHING_TO_WIRE, onChoice: null, onNext: null,
            missing: ({ source }) => (source === '' ? 'Choose where your notes are, or Start empty.' : ''),
        }),
        ...withImport,
        makeStep({
            key: 'vault-summary', label: 'Summary', title: 'Ready to set up your vault',
            intro: 'Here is what will happen. Nothing has changed yet.',
            nextLabel: NEXT, isAction: false, applies: ALWAYS,
            render: (choices) => `
                <ul class="wizard-list">${summaryLines(choices).map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ul>
                ${choices.source === 'empty' ? '' : `<h3 class="wizard-subtitle">Your notes</h3>
                <div class="wizard-preview"><p class="wizard-note">Reading your files…</p></div>`}`,
            wire: async (screen, wizard) => {
                if (wizard.choices.source !== 'empty') await fillImportPreview(screen, wizard, '.wizard-preview');
            },
            onChoice: null, onNext: null, missing: NOTHING_MISSING,
        }),
        runStep({ key: 'setting-up', label: 'Set up', title: 'Setting up your vault…', run: setUpVault }),
    ];
}
