import { escapeHtml } from '../html-escape.js';
import { AI_KEY_WARNINGS, AI_PROVIDERS, aiProvider } from '../ai-chat/ai-providers.js';
import { AiApiError, saveAiCredential } from '../ai-chat/ai-chat-api.js';
import { NotesAPI } from '../api-client.js';
import { rethrowUnexpectedError } from '../expected-errors.js';
import { showErrorDialogFor } from '../modals/error-dialog.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { suggestTagsForImport } from '../import-tag-suggestions.js';

// The import wizard's steps (PLAN.md, phase 2), shared by the import wizard and the new
// vault wizard, which runs them after its own: the folder picked in the system's dialog,
// the choices, the server's preview of what the import will do, then the import itself and
// the AI's tags.

const PERCENT = 100;
// The split sample's notes: one new to the mode fades in, the others move to their place.
const SAMPLE_FADE_IN_MS = 300;
const SAMPLE_MOVE_MS = 380;
const SAMPLE_MOVE_EASING = 'cubic-bezier(0.4, 0, 0.2, 1)';
const STEP_FIELDS = ['key', 'label', 'title', 'intro', 'nextLabel', 'isAction', 'applies', 'render', 'wire', 'onChoice', 'onNext', 'missing'];
const NEXT = 'Next';
const ALWAYS = () => true;
const NOTHING_TO_WIRE = () => {};
export const NOTHING_MISSING = () => '';

/**
 * The AI step's body (the import's, and the new vault's): the providers MetaList offers as
 * cards, and the key of the one chosen, with its warning when it has one (as AI Agent
 * Settings shows them).
 */
export function aiKeyHtml(choices) {
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
        ${choiceCardsHtml('aiProvider', chosen.provider, cards)}
        <label class="wizard-field wizard-key-field"><span>${escapeHtml(chosen.label)} API key</span>
            <input type="password" class="wizard-input wizard-key-input" placeholder="Paste your API key" autocomplete="new-password" data-1p-ignore data-lpignore="true"></label>
        ${warning}`;
}

/**
 * A step's yes or no, at its top (the maintainer, 2026-10-31: unticking it is the obvious
 * way to skip): ticked, the step's fields under it; unticked, they fold away and can't be
 * reached. The choice is choiceKey's (true or false).
 */
export function toggledSectionHtml({ choiceKey, label, isOn, bodyHtml }) {
    return `
        <label class="wizard-toggle wizard-toggle-lead">
            <input type="checkbox" data-wizard-toggle="${escapeHtml(choiceKey)}"${isOn ? ' checked' : ''} data-wizard-focus> ${escapeHtml(label)}
        </label>
        <div class="wizard-toggled${isOn ? '' : ' is-off'}"${isOn ? '' : ' inert'}><div class="wizard-toggled-inner">${bodyHtml}</div></div>`;
}

/** Ticking or unticking a step's yes or no folds its fields in or out, in place. */
export function wireToggles(screen, wizard) {
    for (const box of screen.querySelectorAll('[data-wizard-toggle]')) {
        box.onchange = () => {
            wizard.choose(box.dataset.wizardToggle, box.checked);
            const section = box.closest('.wizard-body').querySelector('.wizard-toggled');
            section.classList.toggle('is-off', !box.checked);
            section.inert = !box.checked;
        };
    }
}

/** What an AI step with its key field still needs: the key ('' once typed); or untick to withoutIt. */
export function missingKey(choices, screen, withoutIt) {
    if (screen.querySelector('.wizard-key-input').value.trim() !== '') return '';
    return `Paste your ${aiProvider(choices.aiProvider).label} API key, or untick the box to ${withoutIt}.`;
}

/** The AI step's body: "Set up an AI", ticked, over the providers and the key. */
export function aiStepHtml(choices) {
    return toggledSectionHtml({ choiceKey: 'setsUpAi', label: 'Set up an AI', isOn: choices.setsUpAi, bodyHtml: aiKeyHtml(choices) });
}

/**
 * What the import will do, shown before it runs (the maintainer, 2026-10-31: the summary
 * comes before the import, which is the last step): what will come in, and what will appear
 * differently. The import's preview and the new vault's.
 */
export function importPreviewHtml(preview) {
    const counts = [
        [preview.fileCount, `files will become ${preview.noteCount} notes (${preview.rootNoteCount} root notes), after a note with the import report`],
        [preview.attachmentCount, 'attachments will come with them'],
        [preview.folderTagCount, 'tags will be added based on the folder structure'],
    ].filter(([count]) => count > 0);
    // [count, what, the rest for one, the rest for several]
    const differences = [
        [preview.filesWithCommentsCount, 'files with comments', '(<code>%%…%%</code>) will show them as visible text.',
            '(<code>%%…%%</code>) will show them as visible text.'],
        [preview.blockIdCount, 'block IDs', '(<code>^abc123</code>) will be hidden; links to it will still lead to its note.',
            '(<code>^abc123</code>) will be hidden; links to them will still lead to their notes.'],
        [preview.calloutCount, 'callouts', 'will become a quote with its title in bold.', 'will become quotes with their title in bold.'],
        [preview.missingLinkCount, 'links', 'leads to a note that isn\'t in the folder; it will stay as written.',
            'lead to notes that aren\'t in the folder; they will stay as written.'],
        [preview.unreadableFileCount, 'files', 'isn\'t UTF-8 text and will be left out.', 'aren\'t UTF-8 text and will be left out.'],
        [preview.unusedAttachmentCount, 'attachments', 'isn\'t linked from any note and will be left out.',
            'aren\'t linked from any note and will be left out.'],
    ].filter(([count]) => count > 0);
    let differencesHtml = '';
    if (differences.length > 0) {
        differencesHtml = `
                <h3 class="wizard-subtitle">What will appear differently</h3>
                <ul class="wizard-list">${differences.map(([count, what, restForOne, restForSeveral]) => `
                    <li><strong>${count} of your ${what}</strong> ${count === 1 ? restForOne : restForSeveral}</li>`).join('')}
                </ul>`;
    }
    return `
                <div class="wizard-stats">${counts.map(([count, label]) => `
                    <span class="wizard-stat">${count}</span><span class="wizard-stat-label">${escapeHtml(label)}</span>`).join('')}
                </div>${differencesHtml}`;
}

/** The server's preview for the choices so far, drawn into the summary (summarySelector). */
export async function fillImportPreview(screen, wizard, summarySelector) {
    const { source, folderPath, split, content } = wizard.choices;
    const preview = await NotesAPI.previewImport(source, folderPath, split, content);
    const summary = screen.querySelector(summarySelector);
    if (summary === null || !summary.isConnected) return;
    summary.innerHTML = importPreviewHtml(preview);
}

/**
 * The work's own screen, the last: its progress while run(screen, wizard, progress) works,
 * then, done, its title and text (what run resolves to: { title, introHtml }) say so and
 * Done closes the wizard.
 */
export function runStep({ key, label, title, run }) {
    return makeStep({
        key, label, title, intro: '', nextLabel: NEXT, isAction: true, applies: ALWAYS,
        render: () => `
            <div class="wizard-import-progress is-indeterminate"><div class="wizard-progress-fill"></div></div>
            <p class="wizard-import-count"></p>`,
        wire: async (screen, wizard) => {
            const finished = await run(wizard, progressReporter(screen));
            // Done: the screen says so; the bar and its line have nothing left to show.
            screen.querySelector('.wizard-import-progress').remove();
            screen.querySelector('.wizard-import-count').remove();
            wizard.finishAction(finished);
        },
        onChoice: null, onNext: null, missing: NOTHING_MISSING,
    });
}

// The run screen's progress: a moving bar and a line while the length is unknown
// (working(text)), a filling one once it is (counted(done, total, text)).
function progressReporter(screen) {
    const bar = screen.querySelector('.wizard-import-progress');
    const fill = screen.querySelector('.wizard-progress-fill');
    const label = screen.querySelector('.wizard-import-count');
    return {
        working(text) {
            bar.classList.add('is-indeterminate');
            label.textContent = text;
        },
        counted(done, total, text) {
            bar.classList.remove('is-indeterminate');
            fill.style.width = `${(done / total) * PERCENT}%`;
            label.textContent = text;
        },
    };
}

/**
 * The import with the wizard's choices, then the AI's tags when chosen; what the last screen
 * says once done. Used by the import wizard and by the new vault wizard's setup.
 */
export async function runImport(wizard, progress) {
    const { source, folderPath, split, content, aiTags } = wizard.choices;
    progress.working('Importing your files…');
    let result = null;
    await CommandGate.run('importWizard.import', async () => {
        result = await NotesAPI.importFolder(source, folderPath, split, content);
        if (!Number.isInteger(result.noteCount) || !Array.isArray(result.fileNoteIds) || !Array.isArray(result.folderTags)
            || typeof result.sourceTag !== 'string') {
            throw new Error('The import answered without its notes');
        }
        // Behind the wizard, a new search context of the imported notes: there when it closes.
        await wizard.services.afterImport(result.sourceTag);
    });
    const lines = [`${result.noteCount} notes came in. The import report is the first note in your list: what came in, and what didn't.`];
    if (aiTags && result.fileNoteIds.length > 0) {
        progress.working('Asking the AI for tags…');
        const tagged = await suggestTagsForImport({
            fileNoteIds: result.fileNoteIds, folderTags: result.folderTags, sourceTag: result.sourceTag,
            settings: wizard.services.getAiSettings(),
            // The files go in as few requests as fit: the bar fills as each answers.
            onProgress: (done, total) => progress.counted(done, total, 'Asking the AI for tags…'),
        });
        lines.push(`The AI suggested tags for ${tagged.proposedNoteCount} notes; they show as 🤖 on each.`);
        if (tagged.failure !== '') {
            lines.push(`It stopped early: ${tagged.failure}`);
        }
    }
    return { title: 'Your notes are in', introHtml: lines.map(escapeHtml).join(' ') };
}

/** A step with every field given (wizard-modal.js says what each does). */
export function makeStep(fields) {
    for (const field of STEP_FIELDS) {
        if (!Object.hasOwn(fields, field)) {
            throw new Error(`Wizard step ${fields.key} is missing ${field}`);
        }
    }
    return Object.freeze(fields);
}

export function choiceCardsHtml(key, chosen, cards) {
    return `<div class="wizard-choices">${cards.map((card) => `
        <button type="button" class="wizard-choice${card.value === chosen ? ' is-chosen' : ''}"
            data-choice-key="${escapeHtml(key)}" data-choice-value="${escapeHtml(card.value)}" aria-pressed="${card.value === chosen}">
            <span class="wizard-choice-title">${escapeHtml(card.title)}</span>
            ${card.badge ? `<span class="wizard-choice-badge">${escapeHtml(card.badge)}</span>` : ''}
            <span class="wizard-choice-text">${escapeHtml(card.text)}</span>
        </button>`).join('')}</div>`;
}

const SOURCES = [
    { value: 'obsidian', title: 'Obsidian vault', badge: 'One-way',
        text: 'Your notes, text, links and files come back out of MetaList as standard Markdown; features only Obsidian has may not.' },
    { value: 'markdown', title: 'Markdown folder', badge: 'One-way',
        text: 'A folder of .md files from any app. Your notes, text, links and files come back out as standard Markdown.' },
];

// The built-in sample the split modes are shown on, as units of text with their kind.
const SAMPLE = [
    { id: 'title', kind: 'heading', text: 'Trip to Lisbon' },
    { id: 'p1', kind: 'paragraph', text: 'Three days, mostly on foot.' },
    { id: 'p2', kind: 'paragraph', text: 'Book the ferry a day ahead.' },
    { id: 'l1', kind: 'item', text: 'Pastéis de Belém' },
    { id: 'l2', kind: 'item', text: 'Tram 28' },
    { id: 'h2', kind: 'heading', text: 'Day 1' },
    { id: 'p3', kind: 'paragraph', text: 'Alfama in the morning, before the heat.' },
];

// Each mode's notes: [unit ids in the note, children].
const SPLIT_TREES = {
    none: [[['title', 'p1', 'p2', 'l1', 'l2', 'h2', 'p3'], []]],
    'headings-and-lists': [[['title'], [
        [['p1', 'p2'], [[['l1'], []], [['l2'], []]]],
        [['h2'], [[['p3'], []]]],
    ]]],
    paragraphs: [[['title'], [
        [['p1'], []],
        [['p2'], [[['l1'], []], [['l2'], []]]],
        [['h2'], [[['p3'], []]]],
    ]]],
};

const SPLITS = [
    { value: 'paragraphs', title: 'Headings, lists and paragraphs',
        text: 'Every paragraph can be moved, tagged or linked on its own. A quoted search finds one paragraph at a time.' },
    { value: 'headings-and-lists', title: 'Headings and lists',
        text: 'Sections and list items stand alone; a run of paragraphs stays together, reading as it did.' },
    { value: 'none', title: 'No splitting',
        text: 'Each file is one note and comes back out exactly. Its sections can\'t be folded, tagged or moved on their own.' },
];

const CONTENTS = [
    { value: 'rich', title: 'Rich text', badge: '',
        text: 'MetaList\'s own formatting: bold, links, headings and lists drawn as you edit.' },
    { value: 'markdown', title: 'Markdown', badge: '',
        text: 'The text as written in your files, marks and all, in notes tagged @markdown; drawn when you aren\'t editing.' },
];

// One note of the sample as it shows while edited: Markdown's marks are there in both
// modes, hidden in rich text, so switching slides them in or out (main.css).
function mark(text) {
    return `<span class="wizard-md-mark">${escapeHtml(text)}</span>`;
}

const WRITE_SAMPLE_HTML = `
    <div class="wizard-sample-note wizard-write-note">
        <div class="wizard-write-line is-heading">${mark('# ')}Trip to Lisbon</div>
        <div class="wizard-write-line">Book the ${mark('**')}<span class="wizard-md-strong">ferry</span>${mark('**')} a day ahead.</div>
        <div class="wizard-write-line">Walk ${mark('*')}<span class="wizard-md-em">slowly</span>${mark('*')} up to the castle.</div>
        <div class="wizard-write-line is-item"><span class="wizard-rich-bullet">•&nbsp;</span>${mark('- ')}Pastéis de Belém</div>
        <div class="wizard-write-line is-item"><span class="wizard-rich-bullet">•&nbsp;</span>${mark('- ')}Tram 28</div>
        <div class="wizard-write-line">Ride ${mark('[')}<span class="wizard-md-link">the yellow tram</span>${mark('](https://carris.pt)')} at dawn.</div>
    </div>
    <div class="wizard-write-tag"><span>@markdown</span></div>`;

function unitHtml(unit) {
    return `<span class="wizard-sample-unit is-${unit.kind}" data-unit="${unit.id}">${escapeHtml(unit.text)}</span>`;
}

function sampleTreeHtml(nodes) {
    return nodes.map(([unitIds, children]) => {
        const units = unitIds.map((id) => unitHtml(SAMPLE.find((unit) => unit.id === id))).join('');
        const childHtml = children.length > 0 ? `<div class="wizard-sample-children">${sampleTreeHtml(children)}</div>` : '';
        return `<div class="wizard-sample-note" data-note-key="${unitIds[0]}"><div class="wizard-sample-text">${units}</div>${childHtml}</div>`;
    }).join('');
}

// What a sample line or note is followed by across a switch: its unit, or its first unit's note.
function flipKey(element) {
    if (Object.hasOwn(element.dataset, 'unit')) {
        return element.dataset.unit;
    }
    return `note:${element.dataset.noteKey}`;
}

// Switching modes moves each note and line of the sample from where it was to where it goes
// (splitting apart or joining); the screen around it stays still.
function animateSample(preview, splitMode) {
    const before = new Map();
    for (const element of preview.querySelectorAll('[data-unit], [data-note-key]')) {
        before.set(flipKey(element), element.getBoundingClientRect());
    }
    preview.innerHTML = sampleTreeHtml(SPLIT_TREES[splitMode]);
    if (!document.body.classList.contains('pref-animated-transitions') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    for (const element of preview.querySelectorAll('[data-unit], [data-note-key]')) {
        const key = flipKey(element);
        const after = element.getBoundingClientRect();
        if (!before.has(key)) {
            element.animate([{ opacity: 0 }, { opacity: 1 }], { duration: SAMPLE_FADE_IN_MS, easing: 'ease-out' });
            continue;
        }
        const was = before.get(key);
        element.animate([
            { transform: `translate(${was.left - after.left}px, ${was.top - after.top}px)` },
            { transform: 'translate(0, 0)' },
        ], { duration: SAMPLE_MOVE_MS, easing: SAMPLE_MOVE_EASING });
    }
}

// Where a folder path's last part starts (the folder dialog gives the operating system's
// separators).
const PATH_SEPARATORS_RE = /[\\/]+/;

function folderName(folderPath) {
    const parts = folderPath.split(PATH_SEPARATORS_RE).filter((part) => part !== '');
    return parts[parts.length - 1];
}

async function chooseFolder(wizard) {
    const picked = await NotesAPI.pickImportFolder(wizard.choices.source, wizard.services.getAiSettings().provider);
    if (typeof picked.selected !== 'boolean' || typeof picked.folderPath !== 'string'
        || !Number.isInteger(picked.markdownFileCount) || typeof picked.canSuggestTags !== 'boolean') {
        throw new Error('Import folder pick response malformed');
    }
    if (!picked.selected) return;
    wizard.chooseMany({
        folderPath: picked.folderPath, folderName: folderName(picked.folderPath),
        markdownFileCount: picked.markdownFileCount, aiReady: picked.canSuggestTags,
    });
    wizard.redrawScreen();
}

// With no AI set up, a ticked "Have an AI suggest tags" saves the key typed (as AI Agent
// Settings does) and makes its provider the one the chat and the tags use.
async function saveTypedAiKey(wizard) {
    const { aiProvider: provider } = wizard.choices;
    const entry = aiProvider(provider);
    const input = document.querySelector(`#${wizard.modalElementId} .wizard-screen:not(.is-leaving) .wizard-key-input`);
    const apiKey = input.value.trim();
    let failure = null;
    try {
        await saveAiCredential(provider, apiKey);
    } catch (error) {
        rethrowUnexpectedError(error);
        if (!(error instanceof AiApiError)) {
            throw error;
        }
        failure = error;
    }
    if (failure !== null) {
        await showErrorDialogFor(failure, null);
        return false;
    }
    const current = wizard.services.getAiSettings();
    await wizard.services.saveAiSettings({ provider, model: entry.defaultModel, thinkingLevel: current.thinkingLevel });
    wizard.choose('aiReady', true);
    return true;
}

/**
 * The import's steps. withSourceStep: the import wizard asks where from; the new vault
 * wizard has asked already. offersKey: with no AI set up, the AI tags step takes a key (the
 * import wizard); the new vault wizard has just asked, so its AI tags step shows only when an
 * AI was set up there. withSummaryAndRun: the import's own preview and run end it; the new
 * vault wizard ends with its own, for the whole setup.
 */
export function importSteps({ withSourceStep, offersKey, withSummaryAndRun }) {
    return [
        makeStep({
            key: 'source', label: 'Source', title: 'Where are your notes?',
            intro: 'Pick what your notes are in.',
            nextLabel: NEXT, isAction: false, applies: () => withSourceStep,
            render: (choices) => choiceCardsHtml('source', choices.source, SOURCES),
            wire: NOTHING_TO_WIRE, onChoice: null, onNext: null, missing: NOTHING_MISSING,
        }),
        makeStep({
            key: 'folder', label: 'Folder', title: 'Choose the folder',
            intro: 'Every Markdown file in it becomes a note, tagged with the folder it was in and with the tags written in the file.',
            nextLabel: NEXT, isAction: false, applies: ALWAYS,
            render: (choices) => {
                let chosen = '<div class="wizard-folder-chosen is-empty">No folder chosen yet</div>';
                if (choices.folderPath !== '') {
                    chosen = `<div class="wizard-folder-chosen" title="${escapeHtml(choices.folderPath)}">
                        <span class="wizard-folder-name">${escapeHtml(choices.folderName)}</span>
                        <span class="wizard-folder-counts">${choices.markdownFileCount} Markdown files</span></div>`;
                }
                return `${chosen}<button type="button" class="secondary-btn wizard-choose-folder" data-wizard-focus>Choose Folder…</button>`;
            },
            wire: (screen, wizard) => {
                screen.querySelector('.wizard-choose-folder').onclick = async () => chooseFolder(wizard);
            },
            onChoice: null, onNext: null,
            missing: ({ folderPath, markdownFileCount }) => {
                if (folderPath === '') return 'Choose the folder your notes are in first.';
                if (markdownFileCount === 0) return 'That folder holds no Markdown files. Choose another.';
                return '';
            },
        }),
        makeStep({
            key: 'split', label: 'Split', title: 'How should each file become notes?',
            intro: 'Shown on a sample: this is exactly how the notes will look in MetaList.',
            nextLabel: NEXT, isAction: false, applies: ALWAYS,
            render: (choices) => `
                <div class="wizard-split">
                    ${choiceCardsHtml('split', choices.split, SPLITS)}
                    <div class="wizard-sample" aria-label="Sample">${sampleTreeHtml(SPLIT_TREES[choices.split])}</div>
                </div>`,
            wire: NOTHING_TO_WIRE,
            onChoice: (screen, key, value) => {
                for (const card of screen.querySelectorAll('.wizard-choice')) {
                    const isChosen = card.dataset.choiceValue === value;
                    card.classList.toggle('is-chosen', isChosen);
                    card.setAttribute('aria-pressed', String(isChosen));
                }
                animateSample(screen.querySelector('.wizard-sample'), value);
            },
            onNext: null, missing: NOTHING_MISSING,
        }),
        makeStep({
            key: 'content', label: 'Write as', title: 'Rich text or Markdown?',
            intro: 'Rich text is MetaList\'s own formatting, edited as you see it. Markdown keeps the text as written, in notes tagged <code>@markdown</code>.',
            nextLabel: NEXT, isAction: false, applies: ALWAYS,
            render: (choices) => `
                <div class="wizard-split">
                    ${choiceCardsHtml('content', choices.content, CONTENTS)}
                    <div>
                        <span class="wizard-caption">While you edit a note</span>
                        <div class="wizard-sample wizard-write-sample is-${escapeHtml(choices.content)}" aria-label="Sample">${WRITE_SAMPLE_HTML}</div>
                    </div>
                </div>`,
            wire: NOTHING_TO_WIRE,
            // The sample changes in place: Markdown's marks slide in as the formatting falls
            // away (CSS transitions on the sample's class), and back.
            onChoice: (screen, key, value) => {
                for (const card of screen.querySelectorAll('.wizard-choice')) {
                    const isChosen = card.dataset.choiceValue === value;
                    card.classList.toggle('is-chosen', isChosen);
                    card.setAttribute('aria-pressed', String(isChosen));
                }
                const sample = screen.querySelector('.wizard-write-sample');
                for (const content of CONTENTS) {
                    sample.classList.toggle(`is-${content.value}`, content.value === value);
                }
            },
            onNext: null, missing: NOTHING_MISSING,
        }),
        // One step for the AI's tags (the maintainer, 2026-10-31). With no AI set up, its yes
        // opens the providers and the key; in the new vault wizard, which has just asked, it
        // shows only when an AI was set up, and is the yes alone.
        makeStep({
            key: 'ai-tags', label: 'AI tags', title: 'Let an AI suggest tags?',
            intro: 'An AI can suggest tags for every imported note. They show as 🤖 on each note, and you decide which to keep; nothing is tagged until you do. Folder tags are never suggested.',
            nextLabel: NEXT, isAction: false,
            applies: (choices) => offersKey || choices.setsUpAi,
            render: (choices) => {
                const takesKey = offersKey && !choices.aiReady;
                const label = `Have ${takesKey ? 'an' : 'the'} AI suggest tags for the ${choices.markdownFileCount} files`;
                let bodyHtml = '';
                if (takesKey) bodyHtml = aiKeyHtml(choices);
                return toggledSectionHtml({ choiceKey: 'aiTags', label, isOn: choices.aiTags, bodyHtml });
            },
            wire: wireToggles, onChoice: null,
            onNext: async (wizard) => {
                const { aiTags, aiReady } = wizard.choices;
                if (aiTags && offersKey && !aiReady && !(await saveTypedAiKey(wizard))) return;
                wizard.next();
            },
            missing: (choices, screen) => {
                if (!choices.aiTags || !offersKey || choices.aiReady) return '';
                return missingKey(choices, screen, 'import without the AI');
            },
        }),
        makeStep({
            key: 'summary', label: 'Summary', title: 'Ready to import',
            intro: 'Here is what the import will do. Nothing has changed yet.',
            nextLabel: NEXT, isAction: false, applies: () => withSummaryAndRun,
            render: () => '<div class="wizard-preview"><p class="wizard-note">Reading your files…</p></div>',
            wire: async (screen, wizard) => fillImportPreview(screen, wizard, '.wizard-preview'),
            onChoice: null, onNext: null, missing: NOTHING_MISSING,
        }),
        ...(withSummaryAndRun ? [runStep({ key: 'importing', label: 'Import', title: 'Importing…', run: runImport })] : []),
    ];
}

export function importChoices(source) {
    return {
        source, folderPath: '', folderName: '', markdownFileCount: 0, split: 'paragraphs', content: 'rich',
        protectsWithPassword: true, setsUpAi: true, aiProvider: AI_PROVIDERS[0].provider, aiReady: false, aiTags: false,
    };
}
