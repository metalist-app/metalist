import { ApplicationState } from '../application-state.js';
import { WizardModal } from './wizard-modal.js';
import { importChoices, importSteps } from './import-wizard-steps.js';
import { forgetTypedSecrets, newVaultChoices, newVaultSteps } from './new-vault-steps.js';

// The two wizards (PLAN.md, phase 2): Import Notes, and Create Vault with the new vault's setup.

export class ImportWizard extends WizardModal {
    constructor(services) {
        super('importWizard', 'import-wizard', {
            title: 'Import Notes',
            steps: importSteps({ withSourceStep: true, withSummaryAndRun: true }),
            commitLabel: 'Import', services,
        });
        ApplicationState.own(this, 'ImportWizard', new.target === ImportWizard);
    }

    initialChoices() {
        return importChoices();
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
