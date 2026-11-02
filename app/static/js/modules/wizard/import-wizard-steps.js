import { escapeHtml } from '../html-escape.js';
import { formatByteSize } from '../byte-sizes.js';
import { NotesAPI } from '../api-client.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { bookmarksFileChoices } from './bookmarks-file.js';

// The import wizard's steps (PLAN.md, phase 2), shared by the import wizard and the new
// vault wizard, which runs them after its own: the folder picked in the system's dialog,
// the choices, the server's preview of what the import will do, then the import itself.

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
const CHOICE_LAYOUTS = ['grid', 'stacked', 'compact', 'pair', 'quad'];
// A layout's classes: a pair is compact cards two across, a quad four across.
const LAYOUT_CLASSES = { grid: 'is-grid', stacked: 'is-stacked', compact: 'is-compact', pair: 'is-compact is-pair', quad: 'is-compact is-quad' };

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

/**
 * What the import will do, shown before it runs (the maintainer, 2026-10-31: the summary
 * comes before the import, which is the last step): what will come in, and what will appear
 * differently. The import's preview and the new vault's. How each kind of file comes in is
 * said outright: note data or file data, which back up differently (the maintainer, 2026-11-01).
 */
export function importPreviewHtml(preview, choices) {
    let into = '';
    if (preview.prefixFolder !== '') {
        into = `<p class="wizard-note">Everything goes into the folder <code>${escapeHtml(preview.prefixFolder)}</code>.</p>`;
    }
    const textNoteCount = preview.noteCount - preview.keptFileCount;
    let counts = [
        [preview.textFileCount, `Markdown files will become ${notesWord(textNoteCount)} (${preview.textFileCount} root ${preview.textFileCount === 1 ? 'note' : 'notes'})`],
        [preview.attachmentCount, 'images and files your notes show or link to will be stored as file data, shown where the notes show them'],
        [preview.keptFileCount, 'Canvas, Base and Excalidraw files will be stored as file data, each shown in a note of its own'],
    ];
    if (choices.source === FILES_SOURCE) {
        const otherFileCount = preview.keptFileCount - preview.keptImageCount;
        let otherFiles = 'files';
        if (preview.keptImageCount > NONE) otherFiles = 'other files';
        counts = [
            [preview.textFileCount, `text files will become ${notesWord(textNoteCount)} (${preview.textFileCount} root ${preview.textFileCount === 1 ? 'note' : 'notes'})`],
            [preview.keptImageCount, 'images will be stored as file data, each shown as its picture in a note of its own'],
            [otherFileCount, `${otherFiles} will be stored as file data, each shown as its card in a note of its own`],
            [preview.previewFileCount, 'files will get a preview where they have text: copied into a note under each, as note data'],
        ];
    }
    counts = [...counts, [preview.folderTagCount, 'tags will be added based on the folder structure']].filter(([count]) => count > NONE);
    let images = '';
    if (bringsInImages(choices) && choices.imagesAs === IMAGES_COMPRESSED) {
        images = `<p class="wizard-note">Images will be compressed: at most ${escapeHtml(choices.imageLongestSide)} pixels on the longest side, without location and camera data.</p>`;
    } else if (bringsInImages(choices)) {
        images = '<p class="wizard-note">Images will come in as they are.</p>';
    }
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
        // A folder of files: files over the per-file limit (folder-import-and-file-previews.md §3).
        [preview.overLimitCount, 'files', 'is over the size limit for a file and will be left out.',
            'are over the size limit for a file and will be left out.'],
    ].filter(([count]) => count > 0);
    let differencesHtml = '';
    if (differences.length > 0) {
        differencesHtml = `
                <h3 class="wizard-subtitle">What will appear differently</h3>
                <ul class="wizard-list">${differences.map(([count, what, restForOne, restForSeveral]) => `
                    <li><strong>${count} of your ${what}</strong> ${count === 1 ? restForOne : restForSeveral}</li>`).join('')}
                </ul>`;
    }
    return `${into}
                <div class="wizard-stats">${counts.map(([count, label]) => `
                    <span class="wizard-stat">${count}</span><span class="wizard-stat-label">${escapeHtml(label)}</span>`).join('')}
                </div>${images}${differencesHtml}`;
}

function notesWord(count) {
    return `${count} ${count === 1 ? 'note' : 'notes'}`;
}

/** The server's preview for the choices so far, drawn into the summary (summarySelector). */
export async function fillImportPreview(screen, wizard, summarySelector) {
    let html = '';
    if (wizard.choices.source === BOOKMARKS_SOURCE) {
        html = bookmarksPreviewHtml(await NotesAPI.previewBookmarkImport(bookmarksRequest(wizard.choices)));
    } else {
        html = importPreviewHtml(await NotesAPI.previewImport(importRequest(wizard.choices)), wizard.choices);
    }
    const summary = screen.querySelector(summarySelector);
    if (summary === null || !summary.isConnected) return;
    summary.innerHTML = html;
}

/**
 * The work's own screen, the last: its progress while run(wizard, progress) works; done, the
 * wizard closes on what it made (the maintainer, 2026-11-01: no screen saying it is done, the
 * imported notes show at once).
 */
export function runStep({ key, label, title, run }) {
    return makeStep({
        key, label, title, intro: '', nextLabel: NEXT, isAction: true, applies: ALWAYS,
        render: () => `
            <div class="wizard-import-progress is-indeterminate"><div class="wizard-progress-fill"></div></div>
            <p class="wizard-import-count"></p>`,
        wire: async (screen, wizard) => {
            await run(wizard, progressReporter(screen));
            if (wizard.isOpen) wizard.close();
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
 * The import with the wizard's choices, its notes then shown in a new search context. Used by
 * the import wizard and by the new vault wizard's setup.
 */
export async function runImport(wizard, progress) {
    const isBookmarks = wizard.choices.source === BOOKMARKS_SOURCE;
    progress.working(isBookmarks ? 'Importing your bookmarks…' : 'Importing your files…');
    let result = null;
    await CommandGate.run('importWizard.import', async () => {
        if (isBookmarks) {
            result = await NotesAPI.importBookmarks({ ...bookmarksRequest(wizard.choices), addToExisting: wizard.choices.addToExisting });
        } else {
            result = await NotesAPI.importFolder(importRequest(wizard.choices));
        }
        if (!Number.isInteger(result.noteCount) || typeof result.sourceTag !== 'string') {
            throw new Error('The import answered without its notes');
        }
        // Behind the wizard, a new search context of the imported notes: there when it closes.
        await wizard.services.afterImport(result.sourceTag);
    });
}

// The wizard's choices as the import and its preview take them.
function importRequest(choices) {
    return {
        source: choices.source, folderPath: choices.folderPath,
        splitMode: turnsMarkdownIntoNotes(choices) ? choices.split : WHOLE_FILES, contentFormat: choices.content,
        prefixFolder: choices.prefixText, addToExisting: choices.addToExisting,
        compressesImages: bringsInImages(choices) && choices.imagesAs === IMAGES_COMPRESSED,
        imageLongestSide: Number(choices.imageLongestSide),
        ...fileSelection(choices),
    };
}

// A folder of files' checklist as the import takes it: the kinds unticked, and the files
// ticked against their kind (left out of a ticked kind, brought in from an unticked one).
function fileSelection(choices) {
    if (choices.source !== FILES_SOURCE) {
        return { excludedGroups: [], excludedFiles: [], includedFiles: [], keepsMarkdownAsFiles: false, previewKinds: [] };
    }
    const groupOfPath = new Map(choices.scan.groups.flatMap((group) => group.files.map(([path]) => [path, group.key])));
    const excludedFiles = choices.fileExceptions.filter((path) => isTicked(choices, groupOfPath.get(path)));
    const includedFiles = choices.fileExceptions.filter((path) => !isTicked(choices, groupOfPath.get(path)));
    return {
        excludedGroups: choices.excludedGroups, excludedFiles, includedFiles,
        keepsMarkdownAsFiles: choices.markdownAs === MARKDOWN_AS_FILES,
        previewKinds: choices.previewKinds,
    };
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

// The choices as cards: side by side ('grid'), one under another ('stacked': a list that
// grows, as the import's sources will), or small and one under another ('compact': two sets
// of choices on one screen), or two small cards side by side ('pair'). A card's badge and
// text show when it has them.
export function choiceCardsHtml(key, chosen, cards, layout) {
    if (!CHOICE_LAYOUTS.includes(layout)) {
        throw new Error(`choiceCardsHtml requires a layout: ${CHOICE_LAYOUTS.join(' or ')}`);
    }
    return `<div class="wizard-choices ${LAYOUT_CLASSES[layout]}">${cards.map((card) => `
        <button type="button" class="wizard-choice${card.value === chosen ? ' is-chosen' : ''}"
            data-choice-key="${escapeHtml(key)}" data-choice-value="${escapeHtml(card.value)}" aria-pressed="${card.value === chosen}">
            <span class="wizard-choice-check" aria-hidden="true">✓</span>
            <span class="wizard-choice-title">${escapeHtml(card.title)}</span>
            ${card.badge ? `<span class="wizard-choice-badge">${escapeHtml(card.badge)}</span>` : ''}
            ${card.text ? `<span class="wizard-choice-text">${escapeHtml(card.text)}</span>` : ''}
        </button>`).join('')}</div>`;
}

// The sources, by name alone (the maintainer, 2026-11-01): more will come. The wizard says
// nothing about a source until it is picked (the maintainer, 2026-11-01: an import may be any
// folder); then the folder step says what that source brings in (folderIntro) and counts
// what it reads (fileWord).
const SOURCES = [
    { value: 'obsidian', title: 'Obsidian vault', badge: '', text: '',
        folderIntro: 'Choose the vault\'s folder. Each Markdown file in it becomes a note, with its folder, its tags, its links and the files it shows.',
        fileWord: 'Markdown files' },
    { value: 'markdown', title: 'Markdown folder', badge: '', text: '',
        folderIntro: 'Choose the folder. Each Markdown file in it becomes a note, tagged with the folder it was in.',
        fileWord: 'Markdown files' },
    { value: 'files', title: 'Any folder', badge: '', text: '',
        folderIntro: 'Choose any folder. Each file in it becomes a note: Markdown and text files with their text, every other file as its card or picture.',
        fileWord: 'files' },
    // A browser's bookmarks export: a file, not a folder (docs/ready-to-build/bookmark-import.md).
    { value: 'bookmarks', title: 'Browser bookmarks', badge: '', text: '',
        folderIntro: 'Choose the bookmarks file your browser exported. Each bookmark becomes a note, in its folder.',
        fileWord: 'bookmarks' },
];
const BOOKMARKS_SOURCE = 'bookmarks';
// A folder of any files (folder-import-and-file-previews.md): its checklist, and Split and
// Write as only for the text files it brings in.
const FILES_SOURCE = 'files';
const TEXT_GROUP = 'text';
// A file as one note: what text files are when no Markdown file asks how to split.
const WHOLE_FILES = 'none';

// Images: kept as they are (chosen at first) or compressed (folder-import-and-file-previews.md,
// Images compressed; the maintainer, 2026-11-01). The endings compression shrinks:
// image_compression.py's COMPRESSIBLE_SUFFIXES.
const IMAGES_ORIGINALS = 'originals';
const IMAGES_COMPRESSED = 'compressed';
const COMPRESSIBLE_IMAGE_RE = /\.(jpe?g|png|webp|tiff?|bmp)$/i;
const IMAGES_AS = [
    { value: IMAGES_ORIGINALS, title: 'Keep originals', badge: '', text: 'Each image as it is.' },
    { value: IMAGES_COMPRESSED, title: 'Compress', badge: '', text: 'Smaller, without location and camera data.' },
];
// The longest side a compressed image keeps (image_compression.py's IMAGE_LONGEST_SIDES), each
// card with about what the images come to (the maintainer, 2026-11-01: pick by sharpness,
// see the size); 2560, sharp full-screen, at first.
const IMAGE_LONGEST_SIDES = ['1280', '1920', '2560', '3840'];
const FIRST_IMAGE_LONGEST_SIDE = '2560';
// Previews (folder-import-and-file-previews.md: a file's text copied into a note under it,
// note data beside the file data): one row per kind, file_text_preview.py's
// IMPORT_PREVIEW_KINDS; none ticked at first (the maintainer, 2026-11-01: they come in numbers,
// and a preview copies the whole file). A PDF has no row: its text is to be searchable with the
// file instead ("Searchable file text").
const PREVIEW_KINDS = [
    { key: 'code', label: 'Code' },
    { key: 'html', label: 'Web pages' },
    { key: 'data', label: 'CSV and JSON' },
];
const FIRST_PREVIEW_KINDS = [];

function sourceOf(choices) {
    const source = SOURCES.find((candidate) => candidate.value === choices.source);
    if (source === undefined) {
        throw new Error(`Unknown import source ${choices.source}`);
    }
    return source;
}

// One note of the sample as it shows while edited: Markdown's marks are there in both
// formats, hidden in rich text, so switching slides them in or out (main.css).
function mark(text) {
    return `<span class="wizard-md-mark">${escapeHtml(text)}</span>`;
}

const BULLET = '<span class="wizard-rich-bullet">•&nbsp;</span>';

// The built-in sample both Markdown choices are shown on (the maintainer, 2026-11-01: one
// screen, the sample following both): units of text with their kind, written in Markdown.
const SAMPLE = [
    { id: 'title', kind: 'heading', html: `${mark('# ')}Trip to Lisbon` },
    { id: 'p1', kind: 'paragraph', html: `Three days, mostly ${mark('*')}<span class="wizard-md-em">on foot</span>${mark('*')}.` },
    { id: 'p2', kind: 'paragraph', html: `Book the ${mark('**')}<span class="wizard-md-strong">ferry</span>${mark('**')} a day ahead.` },
    { id: 'l1', kind: 'item', html: `${BULLET}${mark('- ')}Pastéis de Belém` },
    { id: 'l2', kind: 'item', html: `${BULLET}${mark('- ')}Tram 28` },
    { id: 'h2', kind: 'heading', html: `${mark('## ')}Day 1` },
    { id: 'p3', kind: 'paragraph', html: `Ride ${mark('[')}<span class="wizard-md-link">the yellow tram</span>${mark('](https://carris.pt)')} at dawn.` },
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

// The choices, short (the maintainer, 2026-11-01: both on one screen).
const SPLITS = [
    { value: 'paragraphs', title: 'Headings, lists and paragraphs', badge: 'Recommended', text: 'Every paragraph its own note.' },
    { value: 'headings-and-lists', title: 'Headings and lists', badge: '', text: 'Paragraphs stay together.' },
    { value: 'none', title: 'No splitting', badge: '', text: 'One note per file.' },
];

// A folder of files' Markdown: notes, or kept as files (the maintainer, 2026-11-01: one
// choice for all of them; READMEs and docs are often not notes).
const MARKDOWN_AS_NOTES = 'notes';
const MARKDOWN_AS_FILES = 'files';
const MARKDOWN_AS = [
    { value: MARKDOWN_AS_NOTES, title: 'Turn into notes', badge: 'Recommended', text: 'Split and written as below.' },
    { value: MARKDOWN_AS_FILES, title: 'Keep as files', badge: '', text: 'File cards, unchanged.' },
];

const CONTENTS = [
    { value: 'rich', title: 'Rich text', badge: 'Recommended', text: 'Formatting drawn as you edit.' },
    { value: 'markdown', title: 'Markdown', badge: '', text: 'As written, tagged @markdown.' },
];

function unitHtml(unit) {
    return `<span class="wizard-sample-unit is-${unit.kind}" data-unit="${unit.id}">${unit.html}</span>`;
}

// Markdown kept as files: the sample is a file's card, as the list shows it.
const FILE_CARD_SAMPLE_HTML = `
    <div class="wizard-sample" aria-label="Sample">
        <div class="wizard-sample-note wizard-sample-file"><span class="wizard-sample-badge">.MD</span><span class="wizard-sample-file-name">Trip to Lisbon.md</span></div>
    </div>`;

// Whether the Markdown files are split and written as chosen (not kept as files).
function turnsMarkdownIntoNotes(choices) {
    return bringsInMarkdown(choices) && !(choices.source === FILES_SOURCE && choices.markdownAs === MARKDOWN_AS_FILES);
}

// The Markdown screen's left side: a folder of files first asks notes or files; notes then
// asks how to split and write them.
function markdownChoicesHtml(choices) {
    let asWhat = '';
    if (choices.source === FILES_SOURCE) {
        asWhat = `
            <h3 class="wizard-choice-group">Markdown files</h3>
            ${choiceCardsHtml('markdownAs', choices.markdownAs, MARKDOWN_AS, 'pair')}`;
    }
    if (!turnsMarkdownIntoNotes(choices)) return asWhat;
    return `${asWhat}
        <h3 class="wizard-choice-group">Split each file</h3>
        ${choiceCardsHtml('split', choices.split, SPLITS, 'compact')}
        <h3 class="wizard-choice-group">Write as</h3>
        ${choiceCardsHtml('content', choices.content, CONTENTS, 'pair')}`;
}

// The sample with both choices: notes as split, written as chosen; Markdown's tag under it.
function sampleHtml(choices) {
    if (!turnsMarkdownIntoNotes(choices)) return FILE_CARD_SAMPLE_HTML;
    return `
        <div class="wizard-sample wizard-write-sample is-${escapeHtml(choices.content)}" aria-label="Sample">
            <div class="wizard-sample-tree">${sampleTreeHtml(SPLIT_TREES[choices.split])}</div>
            <div class="wizard-write-tag"><span>@markdown</span></div>
        </div>`;
}

function markChosenCards(screen, key, value) {
    for (const card of screen.querySelectorAll(`.wizard-choice[data-choice-key="${CSS.escape(key)}"]`)) {
        const isChosen = card.dataset.choiceValue === value;
        card.classList.toggle('is-chosen', isChosen);
        card.setAttribute('aria-pressed', String(isChosen));
    }
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
    const picked = await NotesAPI.pickImportFolder(wizard.choices.source);
    if (typeof picked.selected !== 'boolean' || typeof picked.folderPath !== 'string'
        || !Number.isInteger(picked.fileCount) || !Number.isInteger(picked.imageCount)) {
        throw new Error('Import folder pick response malformed');
    }
    if (!picked.selected) return;
    const name = folderName(picked.folderPath);
    // The folder the notes go into starts as the vault's name (import-prefix-folder.md §2).
    wizard.chooseMany({
        folderPath: picked.folderPath, folderName: name, fileCount: picked.fileCount, imageCount: picked.imageCount, prefixText: name,
        // A new folder is read again for the checklist.
        scan: null,
    });
    wizard.redrawScreen();
}

// --- A browser's bookmarks export (docs/ready-to-build/bookmark-import.md) ---------------

function countedWord(count, one, several) {
    return `${count.toLocaleString()} ${count === SINGLE ? one : several}`;
}

// The File screen: the export chosen (its name, how many bookmarks in how many folders) or
// why it can't be imported, and the folder the notes go into (Bookmarks at first).
function bookmarksFileHtml(choices) {
    let chosen = '<div class="wizard-folder-chosen is-empty" role="button" tabindex="0" title="Choose File…">No file chosen yet</div>';
    let below = '';
    if (choices.bookmarksFileName !== '' && choices.bookmarksProblem !== '') {
        chosen = `<div class="wizard-folder-chosen is-empty" role="button" tabindex="0" title="Choose File…">${escapeHtml(choices.bookmarksFileName)}</div>`;
        below = `<p class="wizard-note is-problem">${escapeHtml(choices.bookmarksProblem)}</p>`;
    } else if (choices.bookmarksFileName !== '') {
        const counts = `${countedWord(choices.bookmarkCount, 'bookmark', 'bookmarks')} in ${countedWord(choices.bookmarkFolderCount, 'folder', 'folders')}`;
        chosen = `<div class="wizard-folder-chosen is-chosen" role="button" tabindex="0" title="Choose File…">
            <span class="wizard-choice-check" aria-hidden="true">✓</span>
            <span class="wizard-folder-name">${escapeHtml(choices.bookmarksFileName)}</span>
            <span class="wizard-folder-counts">${escapeHtml(counts)}</span></div>`;
        below = prefixFieldHtml(choices);
    }
    return `<p class="wizard-intro">${escapeHtml(sourceOf(choices).folderIntro)}</p>
        ${chosen}<button type="button" class="secondary-btn wizard-choose-folder" data-wizard-focus>Choose File…</button>${below}`;
}

// The browser's own file picker: the file is read in the browser and sent, so this works on
// every deployment (bookmark-import.md, Decided).
function chooseBookmarksFile(wizard) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.html,.htm,text/html';
    input.onchange = async () => {
        if (input.files === null || input.files.length === NONE) return;
        wizard.chooseMany({ ...await bookmarksFileChoices(input.files[0]), prefixCheckedFor: null });
        wizard.redrawScreen();
    };
    input.click();
}

function bookmarksRequest(choices) {
    return { fileText: choices.bookmarksText, prefixFolder: choices.prefixText };
}

// The Summary: how many bookmarks come in, the folder tags, the folder it all goes into, and
// what is left out (not a website address), listed under an arrow.
function bookmarksPreviewHtml(preview) {
    let into = '';
    if (preview.prefixFolder !== '') {
        into = `<p class="wizard-note">Everything goes into the folder <code>${escapeHtml(preview.prefixFolder)}</code>.</p>`;
    }
    const counts = [
        [preview.bookmarkCount, 'bookmarks will become notes, each its title linked to its page'],
        [preview.folderTagCount, 'tags will be added based on the bookmark folders'],
    ].filter(([count]) => count > NONE);
    let leftOut = '';
    if (preview.leftOut.length > NONE) {
        const items = preview.leftOut.map(([title, why]) => `
            <li class="wizard-kind-file"><span class="wizard-kind-file-name">${escapeHtml(title)}</span>
                <span class="wizard-kind-size">${escapeHtml(why)}</span></li>`).join('');
        leftOut = `
            <h3 class="wizard-subtitle">Left out</h3>
            <details class="wizard-left-out">
                <summary><span class="wizard-kind-arrow" aria-hidden="true"></span>${escapeHtml(countedWord(preview.leftOut.length, 'bookmark isn\'t', 'bookmarks aren\'t'))} a website address</summary>
                <ul class="wizard-kind-files">${items}</ul>
            </details>`;
    }
    return `${into}
        <div class="wizard-stats">${counts.map(([count, label]) => `
            <span class="wizard-stat">${count}</span><span class="wizard-stat-label">${escapeHtml(label)}</span>`).join('')}
        </div>${leftOut}`;
}

// --- The folder the notes go into (docs/ready-to-build/import-prefix-folder.md) -----------

function prefixFieldHtml(choices) {
    return `
        <label class="wizard-field wizard-into-field"><span>Folder as it will appear in MetaList</span>
            <input type="text" class="wizard-input" data-wizard-prefix value="${escapeHtml(choices.prefixText)}"
                autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"></label>
        <div class="wizard-prefix-status">${prefixStatusHtml(choices)}</div>`;
}

function wirePrefixField(screen, wizard) {
    const input = screen.querySelector('[data-wizard-prefix]');
    if (input === null) return;
    input.addEventListener('input', () => {
        wizard.choose('prefixText', input.value);
        void checkPrefix(screen, wizard);
    });
    wirePrefixStatus(screen.querySelector('.wizard-prefix-status'), wizard);
    if (wizard.choices.prefixCheckedFor !== wizard.choices.prefixText) void checkPrefix(screen, wizard);
}

// What the typed name makes, as the server last said: the folder (cleaned as folder names
// are), whether it exists, and what is wrong with the name; prefixCheckedFor is the text it
// was said for, so an answer for older text is dropped.
function prefixStatusHtml(choices) {
    if (choices.prefixText.trim() === '') {
        return '<p class="wizard-note">No folder: your folders stay at the top.</p>';
    }
    if (choices.prefixCheckedFor !== choices.prefixText) return '<p class="wizard-note">&nbsp;</p>';
    if (choices.prefixProblem !== '') return `<p class="wizard-note is-problem">${escapeHtml(choices.prefixProblem)}</p>`;
    const folder = `<code>${escapeHtml(choices.prefixFolder)}</code>`;
    if (!choices.prefixExists) return `<p class="wizard-note">The notes go into ${folder}.</p>`;
    return `
        <p class="wizard-note">${folder} already exists.</p>
        <label class="wizard-toggle"><input type="checkbox" data-wizard-add-existing${choices.addToExisting ? ' checked' : ''}> Add the notes to it</label>`;
}

async function checkPrefix(screen, wizard) {
    const typed = wizard.choices.prefixText;
    const answer = await NotesAPI.checkImportPrefixFolder(typed);
    if (typeof answer.folder !== 'string' || typeof answer.exists !== 'boolean' || typeof answer.problem !== 'string') {
        throw new Error('Import folder check answered malformed');
    }
    // Typed on since: the answer is for older text.
    if (wizard.choices.prefixText !== typed) return;
    wizard.chooseMany({
        prefixCheckedFor: typed, prefixFolder: answer.folder, prefixExists: answer.exists, prefixProblem: answer.problem,
    });
    const status = screen.querySelector('.wizard-prefix-status');
    if (status === null || !status.isConnected) return;
    status.innerHTML = prefixStatusHtml(wizard.choices);
    wirePrefixStatus(status, wizard);
    // Next follows the answer (the wizard listens for input).
    screen.dispatchEvent(new Event('input'));
}

function wirePrefixStatus(status, wizard) {
    const box = status.querySelector('[data-wizard-add-existing]');
    if (box !== null) box.onchange = () => wizard.choose('addToExisting', box.checked);
}

// --- What comes in, for a folder of files (folder-import-and-file-previews.md §3) --------

async function scanFolder(wizard) {
    const scan = await NotesAPI.scanImportFolder(wizard.choices.folderPath);
    if (!Array.isArray(scan.groups) || !Number.isInteger(scan.freeBytes) || !Number.isInteger(scan.maxFileBytes)) {
        throw new Error('Import folder scan answered malformed');
    }
    // The smart defaults: the junk kinds start unticked; the user decides.
    const excludedGroups = scan.groups.filter((group) => group.isSkippedByDefault).map((group) => group.key);
    wizard.chooseMany({ scan, excludedGroups, fileExceptions: [] });
    wizard.redrawScreen();
}

function isTicked(choices, key) {
    return !choices.excludedGroups.includes(key);
}

// A file is ticked as its kind is, unless it was ticked against it (fileExceptions); one over
// the size limit never comes in.
function isFileTicked(choices, flipped, groupKey, path, isOverLimit) {
    if (isOverLimit) return false;
    return isTicked(choices, groupKey) !== flipped.has(path);
}

// The files that will come in: [group key, path, size] of each.
function tickedFiles(choices) {
    const flipped = new Set(choices.fileExceptions);
    return choices.scan.groups.flatMap((group) => group.files
        .filter(([path, , isOverLimit]) => isFileTicked(choices, flipped, group.key, path, isOverLimit))
        .map(([path, size, , previewKind]) => [group.key, path, size, previewKind]));
}

function tickedBytes(choices) {
    return tickedFiles(choices).reduce((total, [, , size]) => total + size, NONE);
}

// A kind some of whose files were ticked against it shows its box as a dash.
function isKindMixed(choices, group) {
    const flipped = new Set(choices.fileExceptions);
    return group.files.some(([path]) => flipped.has(path));
}

const NONE = 0;
const SINGLE = 1;

function filesWord(count) {
    return count === SINGLE ? 'file' : 'files';
}

// A bar's length, out of the largest (the bars compare kinds with each other).
function barPercent(bytes, largest) {
    if (largest === NONE) return NONE;
    return Math.max((bytes / largest) * PERCENT, MIN_BAR_PERCENT);
}

const MIN_BAR_PERCENT = 1;

function checklistHtml(choices) {
    if (choices.scan === null) return '<p class="wizard-note">Reading the folder…</p>';
    const { groups, freeBytes, maxFileBytes } = choices.scan;
    const largest = largestKindBytes(choices);
    const rows = groups.map((group) => {
        let over = '';
        if (group.overLimitCount > NONE) {
            // Red only for going over a limit, never for being large (§3).
            over = `<span class="wizard-kind-over">${group.overLimitCount} ${filesWord(group.overLimitCount)} over ${escapeHtml(formatByteSize(maxFileBytes))}, left out</span>`;
        }
        const isOpen = choices.openKinds.includes(group.key);
        const boxId = `wizard-kind-${group.key}`;
        const mixed = isKindMixed(choices, group) ? ' data-wizard-mixed' : '';
        return `
            <div class="wizard-kind-group" data-wizard-kind-group="${escapeHtml(group.key)}">
                <div class="wizard-kind">
                    <button type="button" class="wizard-kind-arrow" data-wizard-kind-open="${escapeHtml(group.key)}"
                        aria-expanded="${isOpen}" title="Show its files">${isOpen ? '▾' : '▸'}</button>
                    <input type="checkbox" id="${boxId}" data-wizard-kind="${escapeHtml(group.key)}"${isTicked(choices, group.key) ? ' checked' : ''}${mixed}>
                    <label class="wizard-kind-label" for="${boxId}">${escapeHtml(group.label)}${over}</label>
                    <span class="wizard-kind-count">${group.fileCount.toLocaleString()} ${filesWord(group.fileCount)}</span>
                    <span class="wizard-kind-size">${escapeHtml(formatByteSize(group.bytes))}</span>
                    ${kindBarHtml(choices, group, largest)}
                </div>
                ${isOpen ? kindFilesHtml(group, choices) : ''}
            </div>`;
    }).join('');
    return `
        <div class="wizard-kinds">${rows}</div>
        <div class="wizard-total">${totalHtml(choices)}</div>`;
}

// A kind's bar, as long as its size beside the largest: green for what will be imported,
// grey for what won't (the maintainer, 2026-11-01), both when its files are mixed.
function kindBarHtml(choices, group, largest) {
    const flipped = new Set(choices.fileExceptions);
    const importedBytes = group.files
        .filter(([path, , isOverLimit]) => isFileTicked(choices, flipped, group.key, path, isOverLimit))
        .reduce((total, [, size]) => total + size, NONE);
    const whole = barPercent(group.bytes, largest);
    let imported = NONE;
    if (group.bytes > NONE) imported = (importedBytes / group.bytes) * whole;
    return `<span class="wizard-kind-bar" data-wizard-kind-bar><span class="is-imported" style="width:${imported}%"></span><span class="is-left-out" style="width:${whole - imported}%"></span></span>`;
}

function largestKindBytes(choices) {
    return choices.scan.groups.reduce((most, group) => Math.max(most, group.bytes), NONE);
}

// What is ticked against the space left: red only when it won't fit (§3).
function totalHtml(choices) {
    const { freeBytes } = choices.scan;
    const ticked = tickedBytes(choices);
    const isOver = ticked > freeBytes;
    let width = PERCENT;
    if (freeBytes > NONE) width = Math.min((ticked / freeBytes) * PERCENT, PERCENT);
    return `
            <span class="wizard-total-text${isOver ? ' is-over' : ''}">${escapeHtml(formatByteSize(ticked))} ticked, ${escapeHtml(formatByteSize(freeBytes))} free</span>
            <span class="wizard-kind-bar${isOver ? ' is-over' : ''}"><span class="is-imported" style="width:${width}%"></span></span>`;
}

// A checkbox's dash (some of a kind's files ticked against it) is set on the element, not in HTML.
function markMixedKinds(screen) {
    for (const box of screen.querySelectorAll('[data-wizard-kind]')) {
        box.indeterminate = box.hasAttribute('data-wizard-mixed');
    }
}

// A file ticked or unticked against its kind: its box is already changed; the kind's dash,
// the total and Next follow in place, the open lists staying where they are. Split and
// Write as come or go with the text ticked, which draws the screen again.
function tickFile(screen, wizard, box) {
    const path = box.dataset.wizardFile;
    const hadText = bringsInMarkdown(wizard.choices);
    const exceptions = wizard.choices.fileExceptions.filter((flipped) => flipped !== path);
    const isAgainstKind = box.checked !== isTicked(wizard.choices, box.dataset.wizardFileKind);
    wizard.choose('fileExceptions', isAgainstKind ? [...exceptions, path] : exceptions);
    if (bringsInMarkdown(wizard.choices) !== hadText) {
        wizard.redrawScreen();
        return;
    }
    const groupElement = box.closest('[data-wizard-kind-group]');
    const group = wizard.choices.scan.groups.find((candidate) => candidate.key === box.dataset.wizardFileKind);
    groupElement.querySelector('[data-wizard-kind]').indeterminate = isKindMixed(wizard.choices, group);
    groupElement.querySelector('[data-wizard-kind-bar]').outerHTML = kindBarHtml(wizard.choices, group, largestKindBytes(wizard.choices));
    screen.querySelector('.wizard-total').innerHTML = totalHtml(wizard.choices);
}

// A kind opened to show its files (the maintainer, 2026-11-01: to see which file is left
// out, by name): each file's folder and name, its size, the largest first; one over the
// limit says so in red. Built only when opened: a kind can hold thousands.
function kindFilesHtml(group, choices) {
    const { maxFileBytes } = choices.scan;
    const flipped = new Set(choices.fileExceptions);
    const items = group.files.map(([path, size, isOverLimit]) => {
        const cut = path.lastIndexOf('/');
        const folder = cut === -1 ? '' : path.slice(0, cut + 1);
        const name = path.slice(cut + 1);
        let over = '';
        if (isOverLimit) over = `<span class="wizard-kind-over">over ${escapeHtml(formatByteSize(maxFileBytes))}, left out</span>`;
        // Each file ticked as its kind is unless ticked against it (the maintainer, 2026-11-01).
        const isChecked = isFileTicked(choices, flipped, group.key, path, isOverLimit);
        return `
            <li class="wizard-kind-file" title="${escapeHtml(path)}">
                <label class="wizard-kind-file-path">
                    <input type="checkbox" data-wizard-file="${escapeHtml(path)}" data-wizard-file-kind="${escapeHtml(group.key)}"${isChecked ? ' checked' : ''}${isOverLimit ? ' disabled' : ''}>
                    <span class="wizard-kind-file-name"><span class="wizard-kind-file-folder">${escapeHtml(folder)}</span>${escapeHtml(name)}${over}</span>
                </label>
                <span class="wizard-kind-size">${escapeHtml(formatByteSize(size))}</span>
            </li>`;
    }).join('');
    return `<ul class="wizard-kind-files">${items}</ul>`;
}

// Open or close a kind's files in place: the rows around it stay where they are.
function toggleKindFiles(screen, wizard, key) {
    const groupElement = screen.querySelector(`[data-wizard-kind-group="${CSS.escape(key)}"]`);
    const arrow = groupElement.querySelector('[data-wizard-kind-open]');
    const isOpen = wizard.choices.openKinds.includes(key);
    if (isOpen) {
        wizard.choose('openKinds', wizard.choices.openKinds.filter((open) => open !== key));
        groupElement.querySelector('.wizard-kind-files').remove();
    } else {
        wizard.choose('openKinds', [...wizard.choices.openKinds, key]);
        const group = wizard.choices.scan.groups.find((candidate) => candidate.key === key);
        groupElement.insertAdjacentHTML('beforeend', kindFilesHtml(group, wizard.choices));
    }
    arrow.textContent = isOpen ? '▸' : '▾';
    arrow.setAttribute('aria-expanded', String(!isOpen));
}

function checklistProblem(choices) {
    if (choices.scan === null) return 'Reading the folder…';
    if (tickedFiles(choices).length === NONE) return 'Tick at least one file.';
    if (tickedBytes(choices) > choices.scan.freeBytes) return 'The ticked files won\'t fit in the space left. Untick some.';
    return '';
}

// Split and Write as are about Markdown: asked only when Markdown files come in (the
// maintainer, 2026-11-01). Without them, a folder of files' text files come in whole.
const MARKDOWN_FILE_RE = /\.(md|markdown)$/i;

function bringsInMarkdown(choices) {
    if (choices.source === BOOKMARKS_SOURCE) return false;
    if (choices.source !== FILES_SOURCE) return true;
    if (choices.scan === null) return false;
    return tickedFiles(choices).some(([groupKey, path]) => groupKey === TEXT_GROUP && MARKDOWN_FILE_RE.test(path));
}

// The Images screen shows only when images compression shrinks come in: a folder of files'
// ticked ones, a vault's or Markdown folder's (its estimate then counts the ones notes show).
function bringsInImages(choices) {
    if (choices.source !== FILES_SOURCE) return choices.imageCount > NONE;
    if (choices.scan === null) return false;
    return tickedFiles(choices).some(([, path]) => COMPRESSIBLE_IMAGE_RE.test(path));
}

// How many images and their size now, and about their size at each longest side: asked of
// the server for the choices so far, kept while they stay the same (picking a card draws the
// screen again).
function hasImageEstimate(choices) {
    return choices.imageEstimate !== null && choices.imageEstimate.request === imageEstimateRequestKey(choices);
}

function imageEstimateHtml(choices) {
    if (!hasImageEstimate(choices)) return '<p class="wizard-intro">Measuring the images…</p>';
    const { imageCount, imageBytes } = choices.imageEstimate.estimate;
    return `<p class="wizard-intro">${imageCount} ${imageCount === 1 ? 'image' : 'images'}, ${escapeHtml(formatByteSize(imageBytes))} now</p>`;
}

// Compressing: the longest side, each card with about what the images come to at it.
function imageSizesHtml(choices) {
    if (choices.imagesAs !== IMAGES_COMPRESSED) return '';
    const cards = IMAGE_LONGEST_SIDES.map((side) => ({ value: side, title: `${side} px`, badge: '', text: imageSizeText(choices, side) }));
    return `
        <h3 class="wizard-choice-group">Longest side</h3>
        ${choiceCardsHtml('imageLongestSide', choices.imageLongestSide, cards, 'quad')}`;
}

function imageSizeText(choices, side) {
    if (!hasImageEstimate(choices)) return '…';
    return `about ${formatByteSize(choices.imageEstimate.estimate.compressedBytes[side])}`;
}

// The estimate is the same whatever is chosen on this screen.
function imageEstimateRequestKey(choices) {
    return JSON.stringify({ ...importRequest(choices), compressesImages: false, imageLongestSide: Number(FIRST_IMAGE_LONGEST_SIDE) });
}

async function estimateImages(screen, wizard) {
    const request = imageEstimateRequestKey(wizard.choices);
    if (wizard.choices.imageEstimate !== null && wizard.choices.imageEstimate.request === request) return;
    const estimate = await NotesAPI.estimateImportImages(JSON.parse(request));
    if (!Number.isInteger(estimate.imageCount) || !Number.isInteger(estimate.imageBytes)
        || IMAGE_LONGEST_SIDES.some((side) => !Number.isInteger(estimate.compressedBytes[side]))) {
        throw new Error('Import image estimate answered malformed');
    }
    wizard.choose('imageEstimate', { request, estimate });
    const line = screen.querySelector('.wizard-image-estimate');
    if (line === null || !line.isConnected) return;
    line.innerHTML = imageEstimateHtml(wizard.choices);
    // The cards on screen take their sizes in place: drawn again, they would lose their clicks.
    for (const card of screen.querySelectorAll('[data-choice-key="imageLongestSide"]')) {
        card.querySelector('.wizard-choice-text').textContent = imageSizeText(wizard.choices, card.dataset.choiceValue);
    }
}

// The Previews screen shows only when ticked files can get a preview (the scan says which).
function bringsInPreviews(choices) {
    if (choices.source !== FILES_SOURCE || choices.scan === null) return false;
    return tickedFiles(choices).some(([, , , previewKind]) => previewKind !== '');
}

// The ticked files that can get a preview, counted by kind.
function previewFileCounts(choices) {
    const counts = new Map();
    for (const [, , , previewKind] of tickedFiles(choices)) {
        if (previewKind === '') continue;
        if (!counts.has(previewKind)) counts.set(previewKind, NONE);
        counts.set(previewKind, counts.get(previewKind) + 1);
    }
    return counts;
}

function previewEstimateRequestKey(choices) {
    return JSON.stringify({
        ...importRequest(choices), previewKinds: [], compressesImages: false, imageLongestSide: Number(FIRST_IMAGE_LONGEST_SIDE),
    });
}

function hasPreviewEstimate(choices) {
    return choices.previewEstimate !== null && choices.previewEstimate.request === previewEstimateRequestKey(choices);
}

// A kind's files and about how much note data their previews add ('…' until measured).
function previewSizeText(choices, kind, fileCount) {
    const files = `${fileCount} ${fileCount === 1 ? 'file' : 'files'}`;
    if (!hasPreviewEstimate(choices)) return `${files}, …`;
    const measured = choices.previewEstimate.estimate.kinds.find((candidate) => candidate.key === kind);
    if (measured === undefined) return files;
    return `${files}, about ${formatByteSize(measured.noteBytes)} of note data`;
}

function previewRowsHtml(choices) {
    const counts = previewFileCounts(choices);
    return PREVIEW_KINDS.filter(({ key }) => counts.has(key)).map(({ key, label }) => `
        <label class="wizard-preview-kind">
            <input type="checkbox" data-wizard-preview-kind="${escapeHtml(key)}"${choices.previewKinds.includes(key) ? ' checked' : ''}>
            <span class="wizard-preview-kind-name">${escapeHtml(label)}</span>
            <span class="wizard-preview-kind-size" data-wizard-preview-size="${escapeHtml(key)}">${escapeHtml(previewSizeText(choices, key, counts.get(key)))}</span>
        </label>`).join('');
}

async function estimatePreviews(screen, wizard) {
    const request = previewEstimateRequestKey(wizard.choices);
    if (hasPreviewEstimate(wizard.choices)) return;
    const estimate = await NotesAPI.estimateImportPreviews(JSON.parse(request));
    if (!Array.isArray(estimate.kinds) || estimate.kinds.some((kind) => typeof kind.key !== 'string' || !Number.isInteger(kind.noteBytes))) {
        throw new Error('Import preview estimate answered malformed');
    }
    wizard.choose('previewEstimate', { request, estimate });
    // The rows on screen take their sizes in place: drawn again, their boxes would lose their handlers.
    const counts = previewFileCounts(wizard.choices);
    for (const size of screen.querySelectorAll('[data-wizard-preview-size]')) {
        const kind = size.dataset.wizardPreviewSize;
        size.textContent = previewSizeText(wizard.choices, kind, counts.get(kind));
    }
}

function prefixProblem(choices) {
    if (choices.prefixText.trim() === '') return '';
    if (choices.prefixCheckedFor !== choices.prefixText) return 'Checking the folder name…';
    if (choices.prefixProblem !== '') return choices.prefixProblem;
    if (choices.prefixExists && !choices.addToExisting) return 'That folder already exists: tick Add the notes to it, or choose another name.';
    return '';
}

/**
 * The import's steps (no AI in them: the maintainer, 2026-11-01). withSourceStep: the import
 * wizard asks where from; the new vault wizard has asked already. withSummaryAndRun: the
 * import's own preview and run end it; the new vault wizard ends with its own, for the
 * whole setup.
 */
export function importSteps({ withSourceStep, withSummaryAndRun }) {
    return [
        makeStep({
            key: 'source', label: 'Source', title: 'What are you importing?',
            intro: '',
            nextLabel: NEXT, isAction: false, applies: () => withSourceStep,
            render: (choices) => choiceCardsHtml('source', choices.source, SOURCES, 'stacked'),
            wire: NOTHING_TO_WIRE, onChoice: null, onNext: null,
            // None is chosen for you (the maintainer, 2026-11-01).
            missing: ({ source }) => (source === '' ? 'Choose what you are importing.' : ''),
        }),
        makeStep({
            key: 'folder', label: 'Folder', title: 'Choose the folder',
            intro: '',
            nextLabel: NEXT, isAction: false, applies: (choices) => choices.source !== BOOKMARKS_SOURCE,
            // The folder to import and the folder it goes into in MetaList, on one screen (the
            // maintainer, 2026-11-01): the second starts as the first's name.
            render: (choices) => {
                const source = sourceOf(choices);
                // The card opens the folder dialog too, as Choose Folder… does (the maintainer, 2026-11-01).
                let chosen = '<div class="wizard-folder-chosen is-empty" role="button" tabindex="0" title="Choose Folder…">No folder chosen yet</div>';
                let into = '';
                if (choices.folderPath !== '') {
                    // Chosen: drawn as a chosen card is, with its check (the maintainer, 2026-11-01).
                    chosen = `<div class="wizard-folder-chosen is-chosen" role="button" tabindex="0" title="${escapeHtml(choices.folderPath)}">
                        <span class="wizard-choice-check" aria-hidden="true">✓</span>
                        <span class="wizard-folder-name">${escapeHtml(choices.folderName)}</span>
                        <span class="wizard-folder-counts">${choices.fileCount} ${escapeHtml(source.fileWord)}</span></div>`;
                    into = prefixFieldHtml(choices);
                }
                return `<p class="wizard-intro">${escapeHtml(source.folderIntro)}</p>
                    ${chosen}<button type="button" class="secondary-btn wizard-choose-folder" data-wizard-focus>Choose Folder…</button>${into}`;
            },
            wire: (screen, wizard) => {
                screen.querySelector('.wizard-choose-folder').onclick = async () => chooseFolder(wizard);
                const card = screen.querySelector('.wizard-folder-chosen');
                card.onclick = async () => chooseFolder(wizard);
                card.onkeydown = (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    void chooseFolder(wizard);
                };
                wirePrefixField(screen, wizard);
            },
            onChoice: null, onNext: null,
            missing: (choices) => {
                if (choices.folderPath === '') return 'Choose the folder first.';
                if (choices.fileCount === 0) return 'That folder holds nothing this import reads. Choose another.';
                return prefixProblem(choices);
            },
        }),
        makeStep({
            key: 'bookmarksFile', label: 'File', title: 'Choose the bookmarks file',
            intro: '',
            nextLabel: NEXT, isAction: false, applies: (choices) => choices.source === BOOKMARKS_SOURCE,
            render: (choices) => bookmarksFileHtml(choices),
            wire: (screen, wizard) => {
                screen.querySelector('.wizard-choose-folder').onclick = () => chooseBookmarksFile(wizard);
                const card = screen.querySelector('.wizard-folder-chosen');
                card.onclick = () => chooseBookmarksFile(wizard);
                card.onkeydown = (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    chooseBookmarksFile(wizard);
                };
                wirePrefixField(screen, wizard);
            },
            onChoice: null, onNext: null,
            missing: (choices) => {
                if (choices.bookmarksFileName === '') return 'Choose the bookmarks file first.';
                if (choices.bookmarksProblem !== '') return choices.bookmarksProblem;
                return prefixProblem(choices);
            },
        }),
        makeStep({
            key: 'kinds', label: 'Files', title: 'What should be imported?',
            intro: 'Everything in the folder, by kind of file, largest first. Untick what you don\'t want; nothing is copied yet.',
            nextLabel: NEXT, isAction: false, applies: (choices) => choices.source === FILES_SOURCE,
            render: (choices) => checklistHtml(choices),
            wire: (screen, wizard) => {
                if (wizard.choices.scan === null) {
                    void scanFolder(wizard);
                    return;
                }
                for (const arrow of screen.querySelectorAll('[data-wizard-kind-open]')) {
                    arrow.onclick = () => toggleKindFiles(screen, wizard, arrow.dataset.wizardKindOpen);
                }
                markMixedKinds(screen);
                for (const box of screen.querySelectorAll('[data-wizard-kind]')) {
                    // A kind's box sets all its files again: the ones ticked against it follow it.
                    box.onchange = () => {
                        const key = box.dataset.wizardKind;
                        const group = wizard.choices.scan.groups.find((candidate) => candidate.key === key);
                        const paths = new Set(group.files.map(([path]) => path));
                        const others = wizard.choices.excludedGroups.filter((excluded) => excluded !== key);
                        wizard.chooseMany({
                            excludedGroups: box.checked ? others : [...others, key],
                            fileExceptions: wizard.choices.fileExceptions.filter((path) => !paths.has(path)),
                        });
                        wizard.redrawScreen();
                    };
                }
                // The files' boxes, in lists opened later too.
                screen.querySelector('.wizard-kinds').onchange = (event) => {
                    if (event.target instanceof HTMLInputElement && event.target.hasAttribute('data-wizard-file')) {
                        tickFile(screen, wizard, event.target);
                    }
                };
            },
            onChoice: null, onNext: null, missing: checklistProblem,
        }),
        makeStep({
            key: 'markdown', label: 'Markdown', title: 'How should your Markdown files come in?',
            intro: 'Shown on a sample: this is exactly how the notes will look in MetaList.',
            nextLabel: NEXT, isAction: false, applies: bringsInMarkdown,
            render: (choices) => `
                <div class="wizard-split is-choices-wide">
                    <div>${markdownChoicesHtml(choices)}</div>
                    <div>
                        <span class="wizard-caption">${turnsMarkdownIntoNotes(choices) ? 'A Markdown file\'s notes, while you edit them' : 'A Markdown file, as it will show'}</span>
                        ${sampleHtml(choices)}
                    </div>
                </div>`,
            wire: NOTHING_TO_WIRE,
            // The sample follows both choices in place: a split moves its notes, the format
            // slides Markdown's marks in or out (CSS transitions on the sample's class).
            onChoice: (screen, key, value, wizard) => {
                // Notes or files changes what the screen asks: drawn again.
                if (key === 'markdownAs') {
                    wizard.redrawScreen();
                    return;
                }
                markChosenCards(screen, key, value);
                const sample = screen.querySelector('.wizard-write-sample');
                if (key === 'split') {
                    animateSample(sample.querySelector('.wizard-sample-tree'), value);
                    return;
                }
                for (const content of CONTENTS) {
                    sample.classList.toggle(`is-${content.value}`, content.value === value);
                }
            },
            onNext: null, missing: NOTHING_MISSING,
        }),
        makeStep({
            key: 'images', label: 'Images', title: 'Should images be compressed?',
            intro: '',
            nextLabel: NEXT, isAction: false, applies: bringsInImages,
            render: (choices) => `
                <div class="wizard-image-estimate">${imageEstimateHtml(choices)}</div>
                ${choiceCardsHtml('imagesAs', choices.imagesAs, IMAGES_AS, 'pair')}
                <div class="wizard-image-sizes">${imageSizesHtml(choices)}</div>`,
            wire: (screen, wizard) => {
                void estimateImages(screen, wizard);
            },
            // Compress or not shows or hides the sizes: drawn again.
            onChoice: (screen, key, value, wizard) => {
                if (key === 'imagesAs') {
                    wizard.redrawScreen();
                    return;
                }
                markChosenCards(screen, key, value);
            },
            onNext: null, missing: NOTHING_MISSING,
        }),
        makeStep({
            key: 'previews', label: 'Previews', title: 'Which files should get a preview?',
            intro: 'A preview copies a file\'s text into a note under it, so search finds it. It is stored as note data, beside the file.',
            nextLabel: NEXT, isAction: false, applies: bringsInPreviews,
            render: (choices) => `<div class="wizard-preview-kinds">${previewRowsHtml(choices)}</div>`,
            wire: (screen, wizard) => {
                for (const box of screen.querySelectorAll('[data-wizard-preview-kind]')) {
                    box.onchange = () => {
                        const kind = box.dataset.wizardPreviewKind;
                        const others = wizard.choices.previewKinds.filter((ticked) => ticked !== kind);
                        wizard.choose('previewKinds', box.checked ? [...others, kind] : others);
                    };
                }
                void estimatePreviews(screen, wizard);
            },
            onChoice: null, onNext: null, missing: NOTHING_MISSING,
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

// A run's choices: no source yet (the person picks one), Split and Write as on the recommended.
export function importChoices() {
    return {
        source: '', folderPath: '', folderName: '', fileCount: 0, split: 'paragraphs', content: 'rich',
        // A folder of files: what the server read of it ({ groups, freeBytes, maxFileBytes }, null
        // until read) and the kinds unticked in its checklist.
        scan: null, excludedGroups: [],
        // The kinds opened to show their files, and the files ticked against their kind.
        openKinds: [], fileExceptions: [],
        // A folder of files' Markdown files: turned into notes (recommended) or kept as files.
        markdownAs: MARKDOWN_AS_NOTES,
        // Images: kept as they are unless compressed (chosen at first: the maintainer,
        // 2026-11-01); how many compression would shrink in the folder; and the server's
        // estimate ({ request, estimate }, null until asked) for the choices it was asked for.
        imagesAs: IMAGES_ORIGINALS, imageLongestSide: FIRST_IMAGE_LONGEST_SIDE, imageCount: 0, imageEstimate: null,
        // A folder of files: the kinds of file that get a preview, and the server's estimate of
        // their note data ({ request, estimate }, null until asked).
        previewKinds: [...FIRST_PREVIEW_KINDS], previewEstimate: null,
        // The folder the notes go into, as typed (the vault's name once a folder is chosen), and
        // what the server last said of it (prefixStatusHtml); adding to an existing one is ticked.
        prefixText: '', prefixCheckedFor: null, prefixFolder: '', prefixExists: false, prefixProblem: '', addToExisting: true,
        // A bookmarks export (bookmarks-file.js): its name, its text, its counts, and the
        // sentence saying it isn't one ('' when it is).
        bookmarksFileName: '', bookmarksText: '', bookmarkCount: 0, bookmarkFolderCount: 0, bookmarksProblem: '',
    };
}
