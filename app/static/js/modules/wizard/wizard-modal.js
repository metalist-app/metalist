import { ApplicationState } from '../application-state.js';
import { BaseModal } from '../modals/base-modal.js';
import { escapeHtml } from '../html-escape.js';
import { showErrorDialog } from '../modals/error-dialog.js';

// The frame of the setup and import wizards (PLAN.md, phase 2): a full-window page with a
// progress bar naming every step, one screen at a time sliding left on Next and right on
// Back (the reference views' slide: 250 ms; a 120 ms fade with Reduce Motion; nothing with
// Animated Transitions off), and Back and the main button. Every step is gone through: there
// is no skipping ahead (the maintainer, 2026-10-31).
//
// A step: { key, label (in the progress bar), title, intro (HTML, '' for none), nextLabel,
// isAction, applies(choices), render(choices, wizard) -> HTML, wire(screen, wizard),
// onChoice, onNext, missing(choices, screen) }. missing says what the step still needs
// ('' once it is done): until then Next is greyed out, and pressing it says so. Its choices are buttons with data-choice-key and data-choice-value;
// pressing one sets that choice and draws the screen again in place, unless the step's
// onChoice(screen, key, value, wizard) (null for none) does it itself, as the split preview
// does. onNext(wizard) (null for none) replaces Next's going on. The step with isAction runs
// the work (wizard.next() when done), and the steps after it have no Back.

const SLIDE_DURATION_MS = 250;
const SLIDE_EASING = 'cubic-bezier(0.4, 0, 0.2, 1)';
const REDUCED_MOTION_FADE_MS = 120;
const FORWARD = 1;
const BACKWARD = -1;
const FULL_SHIFT_PERCENT = 100;
const LAST_OFFSET = 1;

function isMotionEnabled() {
    return document.body.classList.contains('pref-animated-transitions');
}

function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function progressHtml(steps, currentIndex) {
    const items = steps.map((step, index) => {
        let stateClass = '';
        if (index < currentIndex) stateClass = ' is-done';
        if (index === currentIndex) stateClass = ' is-current';
        const current = index === currentIndex ? ' aria-current="step"' : '';
        return `<li class="wizard-progress-step${stateClass}"${current}>
                <span class="wizard-progress-dot" aria-hidden="true"></span>
                <span class="wizard-progress-label">${escapeHtml(step.label)}</span>
            </li>`;
    }).join('');
    // On a narrow screen the steps' names give way to one line naming the current step.
    const caption = `Step ${currentIndex + 1} of ${steps.length} · ${escapeHtml(steps[currentIndex].label)}`;
    return `<ol class="wizard-progress" style="--wizard-step-count:${steps.length}">${items}</ol>
        <p class="wizard-progress-caption">${caption}</p>`;
}

// Whether the step at index comes before the action (there may be none: a new vault started empty).
function isStepBefore(index, actionIndex) {
    if (actionIndex < 0) return true;
    return index < actionIndex;
}

export class WizardModal extends BaseModal {
    // services: what the steps need from the app ({ getAiSettings, saveAiSettings, afterImport }).
    constructor(modalName, modalElementId, { title, steps, commitLabel, services }) {
        super(modalName, modalElementId);
        if (typeof title !== 'string' || !Array.isArray(steps) || steps.length === 0 || typeof commitLabel !== 'string') {
            throw new Error('WizardModal requires a title, steps and the label of the button that starts the work');
        }
        for (const service of ['getAiSettings', 'saveAiSettings', 'afterImport']) {
            if (typeof services[service] !== 'function') {
                throw new Error(`WizardModal requires the ${service} service`);
            }
        }
        this.services = services;
        this._wizardTitle = title;
        this._wizardSteps = steps;
        // On whichever step comes last before the work, as which one that is depends on the
        // choices (no AI, no AI tags step).
        this._commitLabel = commitLabel;
        ApplicationState.own(this, 'WizardModal', new.target === WizardModal);
    }

    // The choices a run starts from: every question's default (subclasses).
    initialChoices() {
        throw new Error(`${this.modalName} must give its initial choices`);
    }

    getInitialModalState() {
        return { stepKey: this._wizardSteps[0].key, choices: this.initialChoices() };
    }

    shouldCloseOnClickOutside() {
        return false;
    }

    get choices() {
        return this.getModalState().choices;
    }

    // The steps this run goes through, given the choices so far.
    visibleSteps() {
        const choices = this.choices;
        return this._wizardSteps.filter((step) => step.applies(choices));
    }

    _currentIndex() {
        const index = this.visibleSteps().findIndex((step) => step.key === this.getModalState().stepKey);
        if (index < 0) {
            throw new Error(`${this.modalName}: step ${this.getModalState().stepKey} is not in this run`);
        }
        return index;
    }

    currentStep() {
        return this.visibleSteps()[this._currentIndex()];
    }

    /** Set one choice; nothing happens when it already has that value. */
    choose(key, value) {
        this.chooseMany({ [key]: value });
    }

    /** Set several choices at once; nothing happens when they already have those values. */
    chooseMany(updates) {
        const choices = this.choices;
        if (Object.entries(updates).every(([key, value]) => choices[key] === value)) return;
        this.updateModalState({ choices: { ...choices, ...updates } });
    }

    showModalElement() {
        let modalElement = document.getElementById(this.modalElementId);
        if (!modalElement) {
            modalElement = document.createElement('div');
            modalElement.id = this.modalElementId;
            modalElement.className = 'modal wizard-modal';
            document.body.appendChild(modalElement);
        }
        const step = this.currentStep();
        modalElement.innerHTML = `
            <div class="modal-content wizard" role="dialog" aria-modal="true" aria-label="${escapeHtml(this._wizardTitle)}">
                <header class="wizard-header">
                    <span class="wizard-title">${escapeHtml(this._wizardTitle)}</span>
                    <div class="wizard-progress-holder">${progressHtml(this.visibleSteps(), this._currentIndex())}</div>
                </header>
                <div class="wizard-viewport">
                    <section class="wizard-screen">${this._screenHtml(step)}</section>
                </div>
                <footer class="wizard-footer"></footer>
            </div>`;
        modalElement.style.display = 'block';
        const screen = modalElement.querySelector('.wizard-screen');
        this._wireScreen(screen, step);
        this._renderFooter();
        this._focusScreen(screen);
    }

    _screenHtml(step) {
        let intro = '';
        if (step.intro !== '') intro = `<p class="wizard-intro">${step.intro}</p>`;
        return `
            <div class="wizard-screen-inner">
                <h2 class="wizard-screen-title">${escapeHtml(step.title)}</h2>
                ${intro}
                <div class="wizard-body">${step.render(this.choices, this)}</div>
            </div>`;
    }

    _wireScreen(screen, step) {
        for (const button of screen.querySelectorAll('[data-choice-key]')) {
            button.onclick = () => {
                const key = button.dataset.choiceKey;
                const value = button.dataset.choiceValue;
                this.choose(key, value);
                if (step.onChoice !== null) {
                    step.onChoice(screen, key, value, this);
                } else {
                    this.redrawScreen();
                }
            };
        }
        step.wire(screen, this);
        // Typing a key or ticking a box can finish the step (or undo that): Next follows.
        screen.oninput = () => this._refreshNext();
        screen.onchange = () => this._refreshNext();
    }

    // The screen being shown: the last one, as a leaving one goes before it.
    _currentScreen() {
        const screens = this._element().querySelectorAll('.wizard-screen');
        return screens[screens.length - LAST_OFFSET];
    }

    _missing() {
        return this.currentStep().missing(this.choices, this._currentScreen());
    }

    // Next greyed out while the step still needs something.
    _refreshNext() {
        if (this.currentStep().isAction === true) return;
        const isIncomplete = this._missing() !== '';
        const next = this._element().querySelector('.wizard-footer .wizard-next');
        next.classList.toggle('is-incomplete', isIncomplete);
        next.setAttribute('aria-disabled', String(isIncomplete));
    }

    /** Draw the current screen again in place (a choice changed), and the bar and footer. */
    redrawScreen() {
        const screen = this._element().querySelector('.wizard-screen:not(.is-leaving)');
        const step = this.currentStep();
        screen.innerHTML = this._screenHtml(step);
        this._wireScreen(screen, step);
        this._renderProgress();
        this._renderFooter();
        // The pressed choice was drawn again; focus stays in the wizard, where Enter goes on.
        this._focusNext();
    }

    /**
     * The work (the last step) is done: its screen says so (title, and intro as HTML), its
     * mark in the progress bar is ticked, and Done closes the wizard.
     */
    finishAction({ title, introHtml }) {
        if (!this.isOpen) return;
        const element = this._element();
        const screen = element.querySelector('.wizard-screen:not(.is-leaving)');
        screen.querySelector('.wizard-screen-title').textContent = title;
        const intro = document.createElement('p');
        intro.className = 'wizard-intro';
        intro.innerHTML = introHtml;
        screen.querySelector('.wizard-screen-title').after(intro);
        const current = element.querySelector('.wizard-progress-step.is-current');
        current.classList.remove('is-current');
        current.classList.add('is-done');
        const footer = element.querySelector('.wizard-footer');
        footer.innerHTML = `
            <span class="wizard-footer-space"></span>
            <button type="button" class="primary-btn wizard-next" data-modal-enter-action>Done</button>`;
        footer.querySelector('.wizard-next').onclick = () => this.close();
        this._focusNext();
    }

    _focusNext() {
        const next = this._element().querySelector('.wizard-next');
        if (next instanceof HTMLElement) next.focus({ preventScroll: true });
    }

    _element() {
        const element = document.getElementById(this.modalElementId);
        if (!(element instanceof HTMLElement)) {
            throw new Error(`Wizard element missing: ${this.modalElementId}`);
        }
        return element;
    }

    _renderProgress() {
        this._element().querySelector('.wizard-progress-holder').innerHTML = progressHtml(this.visibleSteps(), this._currentIndex());
    }

    _actionIndex() {
        return this.visibleSteps().findIndex((step) => step.isAction === true);
    }

    _renderFooter() {
        const steps = this.visibleSteps();
        const index = this._currentIndex();
        const step = steps[index];
        const actionIndex = this._actionIndex();
        const isBeforeAction = isStepBefore(index, actionIndex);
        const canGoBack = index > 0 && isBeforeAction;
        // The button that starts the work (Import) stands out: it is the one that commits.
        let commitClass = '';
        let nextLabel = step.nextLabel;
        if (index + 1 === actionIndex) {
            commitClass = ' is-commit';
            nextLabel = this._commitLabel;
        }
        const footer = this._element().querySelector('.wizard-footer');
        if (step.isAction === true) {
            footer.innerHTML = '';
            return;
        }
        footer.innerHTML = `
            <button type="button" class="secondary-btn wizard-back"${canGoBack ? '' : ' hidden'}>Back</button>
            <span class="wizard-footer-space"></span>
            <button type="button" class="primary-btn wizard-next${commitClass}" data-modal-enter-action>${escapeHtml(nextLabel)}</button>`;
        footer.querySelector('.wizard-back').onclick = () => this.back();
        footer.querySelector('.wizard-next').onclick = async () => {
            const missing = this._missing();
            if (missing !== '') {
                await showErrorDialog([{ text: missing, fieldId: null }]);
                return;
            }
            if (step.onNext !== null) {
                await step.onNext(this);
                return;
            }
            this.next();
        };
        this._refreshNext();
    }

    next() {
        const index = this._currentIndex();
        if (index === this.visibleSteps().length - LAST_OFFSET) {
            this.close();
            return;
        }
        this._goTo(index + 1, FORWARD);
    }

    back() {
        const index = this._currentIndex();
        if (index === 0) return;
        this._goTo(index - 1, BACKWARD);
    }

    // Slide to the step at index (of the visible steps): the screen leaves towards the side
    // it came from going back, the new one comes in from the other.
    _goTo(index, direction) {
        const step = this.visibleSteps()[index];
        this.updateModalState({ stepKey: step.key });
        const viewport = this._element().querySelector('.wizard-viewport');
        const leaving = viewport.querySelector('.wizard-screen:not(.is-leaving)');
        const entering = document.createElement('section');
        entering.className = 'wizard-screen';
        entering.innerHTML = this._screenHtml(step);
        viewport.append(entering);
        this._wireScreen(entering, step);
        this._renderProgress();
        this._renderFooter();
        this._focusScreen(entering);
        // A page nobody sees runs no animations: nothing would finish the slide.
        if (!isMotionEnabled() || document.hidden) {
            leaving.remove();
            return;
        }
        if (prefersReducedMotion()) {
            leaving.remove();
            entering.animate([{ opacity: 0 }, { opacity: 1 }], { duration: REDUCED_MOTION_FADE_MS, easing: 'linear' });
            return;
        }
        leaving.classList.add('is-leaving');
        const leaveTo = -direction * FULL_SHIFT_PERCENT;
        const enterFrom = direction * FULL_SHIFT_PERCENT;
        const leave = leaving.animate(
            [{ transform: 'translateX(0)' }, { transform: `translateX(${leaveTo}%)` }],
            { duration: SLIDE_DURATION_MS, easing: SLIDE_EASING, fill: 'forwards' },
        );
        leave.onfinish = () => leaving.remove();
        leave.oncancel = () => leaving.remove();
        entering.animate(
            [{ transform: `translateX(${enterFrom}%)` }, { transform: 'translateX(0)' }],
            { duration: SLIDE_DURATION_MS, easing: SLIDE_EASING },
        );
    }

    _focusScreen(screen) {
        const target = screen.querySelector('[data-wizard-focus]');
        if (target instanceof HTMLElement) {
            target.focus({ preventScroll: true });
            return;
        }
        this._focusNext();
    }
}
