import { ApplicationState } from '../application-state.js';
import { WizardModal } from './wizard-modal.js';
import {
    NOTHING_MISSING, aiStepHtml, choiceCardsHtml, fillImportPreview, importChoices, importSteps, makeStep, missingKey,
    runImport, runStep, toggledSectionHtml, wireToggles,
} from './import-wizard-steps.js';
import { importSource } from '../import-sources.js';

// The two wizards (PLAN.md, phase 2). The import wizard is wired to the import; the new vault
// wizard's password and AI steps are not applied yet (its import is).

const NEXT = 'Next';
const NOTHING_TO_WIRE = () => {};

export class ImportWizard extends WizardModal {
    constructor(services) {
        super('importWizard', 'import-wizard', {
            title: 'Import Notes',
            steps: importSteps({ withSourceStep: true, offersKey: true, withSummaryAndRun: true }),
            commitLabel: 'Import', services,
        });
        // The source the next run starts on (openFor).
        this._startSource = 'obsidian';
        ApplicationState.own(this, 'ImportWizard', new.target === ImportWizard);
    }

    /** Open on sourceKey's choice (a new vault set up to import from it). */
    async openFor(sourceKey) {
        importSource(sourceKey);
        // Owned state refuses a change to the value it has.
        if (this._startSource !== sourceKey) {
            this._startSource = sourceKey;
        }
        await this.open();
    }

    initialChoices() {
        return importChoices(this._startSource);
    }
}

const NOTES_SOURCES = [
    { value: 'obsidian', title: 'Obsidian vault', badge: '', text: 'Bring in a vault, its folders, links and attachments.' },
    { value: 'markdown', title: 'Markdown folder', badge: '', text: 'A folder of .md files from any app.' },
    { value: 'empty', title: 'Start empty', badge: '', text: 'Begin with a blank list.' },
];

function newVaultSteps() {
    const importing = (choices) => choices.source !== 'empty';
    const withImport = importSteps({ withSourceStep: false, offersKey: false, withSummaryAndRun: false })
        .map((step) => makeStep({ ...step, applies: (choices) => importing(choices) && step.applies(choices) }));
    return [
        makeStep({
            key: 'password', label: 'Password', title: 'A password for this vault',
            intro: 'With a password, your notes are encrypted and an AI key is remembered. MetaList can\'t recover a forgotten password.',
            nextLabel: NEXT, isAction: false, applies: () => true,
            render: (choices) => toggledSectionHtml({
                choiceKey: 'protectsWithPassword', label: 'Protect this vault with a password', isOn: choices.protectsWithPassword,
                bodyHtml: `
                    <label class="wizard-field"><span>Password</span>
                        <input type="password" class="wizard-input" autocomplete="new-password"></label>
                    <label class="wizard-field"><span>Confirm</span>
                        <input type="password" class="wizard-input" autocomplete="new-password"></label>
                    <button type="button" class="secondary-btn wizard-generate">Generate Password…</button>
                    <p class="wizard-note">Setting one keeps you logged in.</p>`,
            }),
            wire: wireToggles, onChoice: null, onNext: null,
            missing: (choices, screen) => {
                if (!choices.protectsWithPassword) return '';
                const [password, confirmation] = [...screen.querySelectorAll('input[type="password"]')].map((input) => input.value);
                if (password === '') return 'Type a password, or untick the box to go without one.';
                if (password !== confirmation) return 'The two passwords don\'t match.';
                return '';
            },
        }),
        makeStep({
            key: 'ai', label: 'AI', title: 'An AI for your notes',
            intro: 'An AI can answer questions about your notes and suggest tags. Pick the company whose key you have.',
            nextLabel: NEXT, isAction: false, applies: () => true,
            render: (choices) => aiStepHtml(choices),
            wire: wireToggles, onChoice: null, onNext: null,
            missing: (choices, screen) => (choices.setsUpAi ? missingKey(choices, screen, 'go without an AI') : ''),
        }),
        makeStep({
            key: 'notes', label: 'Your notes', title: 'Bring in your notes?',
            intro: 'Already keeping notes somewhere? MetaList can bring them in now, or any time from the command palette.',
            nextLabel: NEXT, isAction: false, applies: () => true,
            render: (choices) => choiceCardsHtml('source', choices.source, NOTES_SOURCES),
            wire: NOTHING_TO_WIRE, onChoice: null, onNext: null, missing: NOTHING_MISSING,
        }),
        ...withImport,
        makeStep({
            key: 'vault-summary', label: 'Summary', title: 'Ready to set up your vault',
            intro: 'Here is what will happen. Nothing has changed yet.',
            nextLabel: NEXT, isAction: false, applies: () => true,
            render: (choices) => `
                <ul class="wizard-list">
                    <li>${choices.protectsWithPassword ? 'Your vault will be protected with a password.' : 'Your vault will have no password.'}</li>
                    <li>${choices.setsUpAi ? 'An AI will be set up.' : 'No AI will be set up.'}</li>
                    ${choices.source === 'empty' ? '<li>Your vault will start empty.</li>' : ''}
                </ul>
                ${choices.source === 'empty' ? '' : `<h3 class="wizard-subtitle">Your notes</h3>
                <div class="wizard-preview"><p class="wizard-note">Reading your files…</p></div>`}`,
            wire: async (screen, wizard) => {
                if (wizard.choices.source !== 'empty') await fillImportPreview(screen, wizard, '.wizard-preview');
            },
            onChoice: null, onNext: null, missing: NOTHING_MISSING,
        }),
        runStep({
            key: 'setting-up', label: 'Set up', title: 'Setting up your vault…',
            run: async (wizard, progress) => {
                if (wizard.choices.source !== 'empty') {
                    const imported = await runImport(wizard, progress);
                    return { title: 'Your vault is ready', introHtml: imported.introHtml };
                }
                return { title: 'Your vault is ready', introHtml: '' };
            },
        }),
    ];
}

export class NewVaultWizard extends WizardModal {
    constructor(services) {
        super('newVaultWizard', 'new-vault-wizard', {
            title: 'Set Up Your Vault', steps: newVaultSteps(), commitLabel: 'Set Up Vault', services,
        });
        ApplicationState.own(this, 'NewVaultWizard', new.target === NewVaultWizard);
    }

    initialChoices() {
        return importChoices('empty');
    }
}
