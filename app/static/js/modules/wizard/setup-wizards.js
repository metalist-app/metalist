import { ApplicationState } from '../application-state.js';
import { NotesAPI } from '../api-client.js';
import { WizardModal } from './wizard-modal.js';
import { importChoices, importSteps } from './import-wizard-steps.js';
import { forgetTypedSecrets, newVaultChoices, newVaultSteps } from './new-vault-steps.js';

// The two wizards (PLAN.md, phase 2): Import, and Create Vault with the new vault's setup.

export class ImportWizard extends WizardModal {
    constructor(services) {
        super('importWizard', 'import-wizard', {
            title: 'Import',
            steps: importSteps({ withSourceStep: true, withSummaryAndRun: true }),
            commitLabel: 'Import', services,
        });
        // Choices already made when it opens (a dropped bookmarks file: Browser bookmarks chosen,
        // its File step filled in; bookmark-import.md §5), or null for none.
        this._presetChoices = null;
        // The step it opens on: null for the first; dropped text files open at the Markdown
        // screen, the steps before it done when they were dropped (files-shown-not-copied.md §5).
        this._startStep = null;
        ApplicationState.own(this, 'ImportWizard', new.target === ImportWizard);
    }

    setStartStep(stepKey) {
        if (stepKey !== null && (typeof stepKey !== 'string' || stepKey === '')) {
            throw new Error('ImportWizard.setStartStep requires a step key or null');
        }
        if (this._startStep !== stepKey) {
            this._startStep = stepKey;
        }
    }

    startStepKey() {
        if (this._startStep === null) return super.startStepKey();
        return this._startStep;
    }

    setPresetChoices(presetChoices) {
        if (presetChoices !== null && typeof presetChoices !== 'object') {
            throw new Error('ImportWizard.setPresetChoices requires choices or null');
        }
        // Owned state refuses a change to the value it has.
        if (this._presetChoices !== presetChoices) {
            this._presetChoices = presetChoices;
        }
    }

    initialChoices() {
        if (this._presetChoices === null) return importChoices();
        return { ...importChoices(), ...this._presetChoices };
    }

    // A dropped folder's files copied to the server's holding folder go with the walkthrough,
    // cancelled or imported (docs/ready-to-build/desktop-drops-into-folders.md).
    onClose() {
        super.onClose();
        const uploadId = this.choices.uploadId;
        if (uploadId !== '') void NotesAPI.discardImportUpload(uploadId);
    }
}

// Create Vault, in the vault it is opened from, is the Vault step alone; the new vault opens
// straight into the rest, from Password on, Vault ticked (PLAN.md, phase 2).
export class NewVaultWizard extends WizardModal {
    constructor(services) {
        super('newVaultWizard', 'new-vault-wizard', {
            title: 'Create Vault', steps: newVaultSteps(), commitLabel: 'Set Up Vault', services,
        });
        // Whether this window goes on with a new vault's setup (from Password) or creates one.
        this._continuesSetup = false;
        ApplicationState.own(this, 'NewVaultWizard', new.target === NewVaultWizard);
    }

    setContinuesSetup(continuesSetup) {
        if (typeof continuesSetup !== 'boolean') {
            throw new Error('NewVaultWizard.setContinuesSetup requires a boolean');
        }
        // Owned state refuses a change to the value it has.
        if (this._continuesSetup !== continuesSetup) {
            this._continuesSetup = continuesSetup;
        }
    }

    startStepKey() {
        if (this._continuesSetup) return 'password';
        return 'vault';
    }

    // Create Vault's button is green too: it creates the vault.
    isCommitStep(step, index, actionIndex) {
        if (step.key === 'vault') return true;
        return super.isCommitStep(step, index, actionIndex);
    }

    initialChoices() {
        return newVaultChoices(importChoices());
    }

    onClose() {
        super.onClose();
        forgetTypedSecrets();
    }
}
