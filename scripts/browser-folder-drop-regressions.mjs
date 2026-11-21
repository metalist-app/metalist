import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Files and folders dropped from the desktop (docs/ready-to-build/desktop-drops-into-folders.md).
// A test browser can't fake a dropped folder (its entry), so the folder's part starts where the
// drop hands over: the walkthrough opened with the folder's files as the browser read them.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
const FOLDER = 'Dropzone/';
const DROPPED_FOLDER = 'Droppedtrip';
const WIZARD_STEP_TIMEOUT_MS = 20000;
// The note that makes the folder dropped on.
const KEPT_FIRST_NOTES = 1;
const EARLIER_IMPORT_TAG = 'imported:source=files:at=2020-01-02T03:04';
// The note's own file and the one dropped while it is edited.
const TOKENS_AFTER_SECOND_DROP = 2;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function stepTitle(page) {
  return page.$eval('#import-wizard .wizard-screen:not(.is-leaving) .wizard-screen-title', node => node.textContent);
}

async function waitForStep(page, title) {
  await page.waitForFunction(expected => {
    const node = document.querySelector('#import-wizard .wizard-screen:not(.is-leaving) .wizard-screen-title');
    return node !== null && node.textContent === expected;
  }, {timeout: WIZARD_STEP_TIMEOUT_MS}, title);
  await pause(SETTLE_MS);
}

async function next(page) {
  await page.click('#import-wizard .wizard-footer .wizard-next');
}

// §1: files dropped on a folder come in as on the column, in that folder, the note left open no longer.
async function checkFilesOnAFolder(page) {
  const markedWithNoNoteOpen = await page.evaluate(folder => {
    const row = document.querySelector(`#virtual-folders [data-virtual-folder="${folder}"]`);
    const transfer = new DataTransfer();
    // Not a text file: a dropped .txt or .md asks first (files-shown-not-copied.md §5).
    transfer.items.add(new File(['dropped,on a folder'], 'folder-drop.csv', {type: 'text/csv'}));
    const box = row.getBoundingClientRect();
    const at = {clientX: box.left + box.width / 2, clientY: box.top + box.height / 2, bubbles: true, cancelable: true, dataTransfer: transfer};
    row.dispatchEvent(new DragEvent('dragover', at));
    const marked = row.classList.contains('is-drop-target');
    row.dispatchEvent(new DragEvent('drop', at));
    return marked;
  }, FOLDER);
  assert.equal(markedWithNoNoteOpen, true, 'files over a folder with no note open: that folder is marked');
  await page.waitForFunction(() => [...document.querySelectorAll('#notes-container > .note')]
    .some(note => note.textContent.includes('folder-drop.csv')), {timeout: WIZARD_STEP_TIMEOUT_MS});
  await idle(page);
  await pause(SETTLE_MS);
  const dropped = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const note = [...document.querySelectorAll('#notes-container > .note')].find(node => node.textContent.includes('folder-drop.csv'));
    return {id: note.dataset.noteId, isFirst: document.querySelector('#notes-container > .note') === note,
      folders: note.dataset.noteTags.split(/\s+/).filter(tag => tag.endsWith('/')), isEditing: mode.isEditing};
  });
  assert.deepEqual({isFirst: dropped.isFirst, folders: dropped.folders, isEditing: dropped.isEditing},
    {isFirst: true, folders: [FOLDER], isEditing: false}, 'files dropped on a folder: a new note at the top, in that folder, not left open');
  return dropped.id;
}

// While a note is being edited, files let go on a folder in the tree go into that note, not into
// the folder (the maintainer, 2026-11-19).
async function checkFilesOnAFolderWhileEditing(page, noteId) {
  const contentSelector = `#notes-container > .note[data-note-id="${noteId}"] > .note-content`;
  await page.click(contentSelector);
  await page.waitForFunction(selector => document.querySelector(selector).getAttribute('contenteditable') === 'true', {}, contentSelector);
  await idle(page);
  const rootsBefore = await page.$$eval('#notes-container > .note', notes => notes.length);
  const markedWhileEditing = await page.evaluate(folder => {
    const row = document.querySelector(`#virtual-folders [data-virtual-folder="${folder}"]`);
    const transfer = new DataTransfer();
    transfer.items.add(new File(['dropped,while editing'], 'while-editing.csv', {type: 'text/csv'}));
    const box = row.getBoundingClientRect();
    const at = {clientX: box.left + box.width / 2, clientY: box.top + box.height / 2, bubbles: true, cancelable: true, dataTransfer: transfer};
    row.dispatchEvent(new DragEvent('dragover', at));
    const marked = document.querySelectorAll('#virtual-folders .is-drop-target').length;
    row.dispatchEvent(new DragEvent('drop', at));
    return marked;
  }, FOLDER);
  assert.equal(markedWhileEditing, 0, 'files over a folder while a note is edited: no folder is marked');
  await page.waitForFunction((selector, expected) => [...document.querySelector(selector).innerText.matchAll(/\[\[[0-9a-f-]{36}\]\]/g)].length === expected,
    {timeout: WIZARD_STEP_TIMEOUT_MS}, contentSelector, TOKENS_AFTER_SECOND_DROP);
  await idle(page);
  assert.equal(await page.$$eval('#notes-container > .note', notes => notes.length), rootsBefore,
    'files on a folder while a note is edited: no new note');
  await page.keyboard.press('Escape');
  await idle(page);
}

// A folder dropped alone, through the walkthrough to its end. prefixText: what the folder field is
// changed to on its screen, null to leave it. Returns the holding folder's id.
async function importDroppedFolder(page, {name, into, prefixText, files}) {
  await page.evaluate(async ({name, into, files}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const file = ([path, text]) => ({path, size: new Blob([text]).size, file: new File([text], path.split('/').pop())});
    await CommandPalette.openImportWizardWithDroppedFolder({name, files: files.map(file)}, into);
  }, {name, into, files});
  // As for a dropped bookmarks file: Source first, with Any folder chosen.
  await waitForStep(page, 'What are you importing?');
  assert.equal(await page.$eval('#import-wizard [data-choice-key="source"].is-chosen', node => node.dataset.choiceValue), 'files',
    'Any folder is chosen');
  await next(page);
  await waitForStep(page, 'Choose the folder');
  assert.equal(await page.$eval('#import-wizard .wizard-folder-name', node => node.textContent), name, 'the dropped folder is chosen');
  assert.equal(await page.$eval('#import-wizard [data-wizard-prefix]', node => node.value), `${into}${name}`,
    'it goes into the folder it was dropped on, under its own name');
  if (prefixText !== null) {
    await page.$eval('#import-wizard [data-wizard-prefix]', (node, text) => {
      node.value = text;
      node.dispatchEvent(new Event('input', {bubbles: true}));
    }, prefixText);
    await pause(SETTLE_MS);
  }
  await next(page);
  await waitForStep(page, 'What should be imported?');
  await page.waitForSelector('#import-wizard .wizard-kinds');
  await next(page);
  // Copying runs by itself and goes on when done.
  await waitForStep(page, 'How should your Markdown files come in?');
  const uploadId = await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    return CommandPalette._importWizard.choices.uploadId;
  });
  assert.notEqual(uploadId, '', 'the ticked files were copied to a holding folder');
  for (;;) {
    const title = await stepTitle(page);
    if (title === 'Ready to import') break;
    await next(page);
    await page.waitForFunction(previous => {
      const node = document.querySelector('#import-wizard .wizard-screen:not(.is-leaving) .wizard-screen-title');
      return node !== null && node.textContent !== previous;
    }, {timeout: WIZARD_STEP_TIMEOUT_MS}, title);
    await pause(SETTLE_MS);
  }
  await page.waitForFunction(() => !document.querySelector('#import-wizard .wizard-preview').textContent.includes('Reading'),
    {timeout: WIZARD_STEP_TIMEOUT_MS});
  await next(page);
  await page.waitForFunction(() => document.getElementById('import-wizard') === null
    || getComputedStyle(document.getElementById('import-wizard')).display === 'none', {timeout: WIZARD_STEP_TIMEOUT_MS});
  await idle(page);
  await pause(SETTLE_MS);
  return uploadId;
}

// What the window shows: the context, whether the tree shows, the folders chosen, the search, and the notes listed.
async function shownNow(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {chosenVirtualFolders, isVirtualFoldersShown} = await import('/static/js/modules/mode-manager/services/virtual-folders-service.js');
    const notes = [...document.querySelectorAll('#notes-container > .note')];
    return {
      tabId: mode.activeTabId, contextCount: mode.tabOrder.length, treeShown: isVirtualFoldersShown(),
      folders: [...chosenVirtualFolders()], search: mode.searchQuery, scrollY: window.scrollY,
      noteIds: notes.map(note => note.dataset.noteId), noteTexts: notes.map(note => note.textContent),
    };
  });
}

async function chooseTreeFolder(page, folder) {
  await page.evaluate(async folder => {
    const {chooseFolder} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await chooseFolder(folder, false);
  }, folder);
  await idle(page);
}

async function typeSearch(page, text) {
  // What is there goes first: the new search replaces it.
  await page.$eval('#search-input', input => {
    input.value = '';
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await page.click('#search-input');
  await page.keyboard.type(text);
  await page.keyboard.press('Enter');
  await idle(page);
  await pause(SETTLE_MS);
}

// An import's tag goes down to the minute: the imports before this one, made in the same minute,
// go first, so a search of its tag can show that it lists this one's notes and no others.
async function deleteEarlierImports(page, created) {
  const earlier = created.splice(KEPT_FIRST_NOTES);
  await page.evaluate(async ids => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of ids) await NotesAPI.deleteNote(id);
  }, earlier);
  await idle(page);
}

function filesOf(name) {
  return [['plan.md', `# Plan of ${name}\n\nA line of the plan.\n`], [`notes/todo-of-${name}.txt`, `Todo of ${name}`]];
}

function assertOnlyItsNotes(shown, imported, label) {
  assert.equal(shown.noteTexts.length, 2, `${label}: only the import's notes are listed, got ${shown.noteTexts.length}`);
  assert.ok(shown.noteTexts.every(text => text.includes(`of ${imported}`)), `${label}: the notes listed are ${imported}'s: ${JSON.stringify(shown.noteTexts)}`);
}

// Cases 1, 2, 3 and 6: a new folder with the tree showing is chosen, its search, and shows from its top.
function assertItsNewFolder(page, shown, before, folder, imported, label) {
  assert.deepEqual({folders: shown.folders, search: shown.search, tabId: shown.tabId, contextCount: shown.contextCount, scrollY: shown.scrollY},
    {folders: [folder], search: folder, tabId: before.tabId, contextCount: before.contextCount, scrollY: 0}, `${label}: its new folder is chosen in the same context`);
  assertOnlyItsNotes(shown, imported, label);
  return page.$eval(`#virtual-folders .virtual-folder.is-filtered > [data-virtual-folder="${folder}"]`, row => row.getBoundingClientRect().height > 0);
}

// Cases 4, 5 and 7: a new search context on this import's tag; the one dropped in stays.
function assertItsOwnSearch(shown, before, imported, label) {
  assert.equal(shown.contextCount, before.contextCount + 1, `${label}: one new search context`);
  assert.notEqual(shown.tabId, before.tabId, `${label}: the new context is the one shown`);
  assert.equal(shown.treeShown, before.treeShown, `${label}: the tree as it was`);
  assert.match(shown.search, /^imported:source=files/, `${label}: it searches the import's tag`);
  assertOnlyItsNotes(shown, imported, label);
}

// §2 and §4, and where each drop ends (the maintainer, 2026-11-09): a folder dropped opens the
// walkthrough on Any folder, its files listed before any is sent, then copied, then imported.
async function checkFolderOnAFolder(page) {
  const created = [];
  const before = await shownNow(page);
  const uploadId = await importDroppedFolder(page, {name: DROPPED_FOLDER, into: FOLDER, prefixText: null,
    files: [...filesOf(DROPPED_FOLDER), ['.DS_Store', 'x']]});
  const shown = await shownNow(page);
  created.push(...shown.noteIds);
  assert.ok(await assertItsNewFolder(page, shown, before, `${FOLDER}${DROPPED_FOLDER}/`, DROPPED_FOLDER, 'dropped on a folder in the tree'), 'the new folder shows open in the tree');
  // Discarding it again is refused as gone (app/services/import_uploads.py _upload_folder).
  const discard = await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {settleResult} = await import('/static/js/modules/async-result.js');
    const outcome = await settleResult(() => NotesAPI.discardImportUpload(id));
    return {isDiscarded: outcome.ok, refusal: outcome.ok ? null : `${outcome.error.name}: ${outcome.error.message}`};
  }, uploadId);
  assert.deepEqual(discard, {isDiscarded: false, refusal: 'ServerInputRejectedError: That upload is gone. Drop the folder again.'},
    'the holding folder went with the walkthrough');
  return created;
}

async function checkWhereEachDropEnds(page, created, contexts) {
  // 1: on `/`, or the column with no folder chosen.
  await chooseTreeFolder(page, '');
  let before = await shownNow(page);
  await importDroppedFolder(page, {name: 'Droppedtop', into: '', prefixText: null, files: filesOf('Droppedtop')});
  let shown = await shownNow(page);
  created.push(...shown.noteIds);
  assert.ok(await assertItsNewFolder(page, shown, before, 'Droppedtop/', 'Droppedtop', 'dropped on the top'), 'shown in the tree');

  // 2: on the column while a folder is chosen: a folder of its own name, at the top of the tree.
  await chooseTreeFolder(page, FOLDER);
  before = await shownNow(page);
  await importDroppedFolder(page, {name: 'Droppedcolumn', into: '', prefixText: null, files: filesOf('Droppedcolumn')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  assert.ok(await assertItsNewFolder(page, shown, before, 'Droppedcolumn/', 'Droppedcolumn', 'dropped on the column in a folder'), 'shown in the tree');

  // 6: a search typed: replaced by the new folder, as clicking the folder replaces it.
  await chooseTreeFolder(page, '');
  await typeSearch(page, 'drop');
  before = await shownNow(page);
  assert.equal(before.search, 'drop', 'the search is typed');
  await importDroppedFolder(page, {name: 'Droppedsearch', into: '', prefixText: null, files: filesOf('Droppedsearch')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  assert.ok(await assertItsNewFolder(page, shown, before, 'Droppedsearch/', 'Droppedsearch', 'dropped with a search typed'), 'shown in the tree');

  // 4: the walkthrough's folder name emptied: no folder to choose.
  await deleteEarlierImports(page, created);
  await chooseTreeFolder(page, '');
  before = await shownNow(page);
  await importDroppedFolder(page, {name: 'Droppedblank', into: '', prefixText: '', files: filesOf('Droppedblank')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  contexts.push(shown.tabId);
  assertItsOwnSearch(shown, before, 'Droppedblank', 'no folder name');

  // 5: added to a folder that holds notes already: only the new ones listed.
  await deleteEarlierImports(page, created);
  created.push(await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>Already in the folder</p>', 'Droppedexisting/');
    return note.id;
  }));
  await idle(page);
  before = await shownNow(page);
  assert.equal(before.treeShown, true, 'the tree shown');
  await importDroppedFolder(page, {name: 'Droppedagain', into: '', prefixText: 'Droppedexisting', files: filesOf('Droppedagain')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  contexts.push(shown.tabId);
  assertItsOwnSearch(shown, before, 'Droppedagain', 'added to an existing folder');

  // 7: the tree hidden, a search whose words the imported notes don't match.
  await deleteEarlierImports(page, created);
  await page.click('#virtual-folders-button');
  await idle(page);
  await typeSearch(page, 'zzznothing');
  before = await shownNow(page);
  assert.equal(before.treeShown, false, 'the tree hidden');
  await importDroppedFolder(page, {name: 'Droppedplain', into: '', prefixText: null, files: filesOf('Droppedplain')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  contexts.push(shown.tabId);
  assertItsOwnSearch(shown, before, 'Droppedplain', 'dropped in a plain search');

  // 7, again: the plain search is an earlier import's, as after dropping one folder then another.
  await deleteEarlierImports(page, created);
  created.push(await page.evaluate(async tag => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>From an earlier import</p>', tag);
    return note.id;
  }, EARLIER_IMPORT_TAG));
  await typeSearch(page, EARLIER_IMPORT_TAG);
  before = await shownNow(page);
  assert.equal(before.search, EARLIER_IMPORT_TAG, "the earlier import's search");
  await importDroppedFolder(page, {name: 'Droppedsecond', into: '', prefixText: null, files: filesOf('Droppedsecond')});
  shown = await shownNow(page);
  created.push(...shown.noteIds);
  contexts.push(shown.tabId);
  assertItsOwnSearch(shown, before, 'Droppedsecond', "dropped in an earlier import's search");
}

// --- Importing a folder again, and Changed since (import-export-launch.md §5, "Importing again") ---

const AGAIN_FOLDER = 'Droppedagain';
// A file last changed long before the day Changed since names, and that day.
const LONG_AGO = Date.UTC(2025, 10, 1, 12);
const CHANGED_SINCE = '2026-01-01';
const NOTHING_TO_BRING_IN = 'Every file is as it was when you imported it.';

// The folder dropped alone and walked to its Summary. files: [path, text, last changed (ms)].
// changedSince: the day typed on the Folder screen, '' to leave it empty. Returns what the
// checklist offered and what the Summary says of an earlier import ('' when it says nothing).
async function walkToSummary(page, {files, changedSince}) {
  await page.evaluate(async ({name, files}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const file = ([path, text, lastModified]) => ({
      path, size: new Blob([text]).size, file: new File([text], path.split('/').pop(), {lastModified}),
    });
    await CommandPalette.openImportWizardWithDroppedFolder({name, files: files.map(file)}, '');
  }, {name: AGAIN_FOLDER, files});
  await waitForStep(page, 'What are you importing?');
  await next(page);
  await waitForStep(page, 'Choose the folder');
  if (changedSince !== '') {
    await page.$eval('#import-wizard [data-wizard-changed-since]', (node, day) => {
      node.value = day;
      node.dispatchEvent(new Event('change', {bubbles: true}));
    }, changedSince);
  }
  // The folder's name is checked before Next goes on.
  await page.waitForFunction(() => !document.querySelector('#import-wizard .wizard-footer .wizard-next').classList.contains('is-incomplete'),
    {timeout: WIZARD_STEP_TIMEOUT_MS});
  await next(page);
  await waitForStep(page, 'What should be imported?');
  await page.waitForSelector('#import-wizard .wizard-kinds');
  const offered = await page.$$eval('#import-wizard .wizard-kind-count', counts => counts.map(count => count.textContent).join(', '));
  for (;;) {
    const title = await stepTitle(page);
    if (title === 'Ready to import') break;
    // Copying goes on by itself.
    if (title !== 'Copying your files') await next(page);
    await page.waitForFunction(previous => {
      const node = document.querySelector('#import-wizard .wizard-screen:not(.is-leaving) .wizard-screen-title');
      return node !== null && node.textContent !== previous;
    }, {timeout: WIZARD_STEP_TIMEOUT_MS}, title);
    await pause(SETTLE_MS);
  }
  await page.waitForSelector('#import-wizard .wizard-preview-counts', {timeout: WIZARD_STEP_TIMEOUT_MS});
  await pause(SETTLE_MS);
  const before = await page.$eval('#import-wizard .wizard-again', node => node.innerText.replace(/\s+/g, ' ').trim());
  return {offered, before};
}

async function importFromSummary(page) {
  await next(page);
  await page.waitForFunction(() => document.getElementById('import-wizard') === null
    || getComputedStyle(document.getElementById('import-wizard')).display === 'none', {timeout: WIZARD_STEP_TIMEOUT_MS});
  await idle(page);
  await pause(SETTLE_MS);
}

async function chooseOnSummary(page, value) {
  await page.click(`#import-wizard input[name="wizard-earlier-notes"][value="${value}"]`);
  await idle(page);
  await pause(SETTLE_MS);
}

// The notes of the folder, as the list shows them with the folder chosen: [id, text] each.
async function notesOfAgainFolder(page) {
  await chooseTreeFolder(page, `${AGAIN_FOLDER}/`);
  await pause(SETTLE_MS);
  const shown = await shownNow(page);
  return shown.noteIds.map((id, index) => [id, shown.noteTexts[index]]);
}

async function checkAFolderDroppedAgain(page, created, contexts) {
  const contextsBefore = (await shownNow(page)).contextCount;
  const now = Date.now();
  // First: only the file changed since the day comes in, and nothing came in before.
  const first = await walkToSummary(page, {
    files: [['alpha.md', 'Alpha one\n', now], ['beta.md', 'Beta one\n', LONG_AGO]], changedSince: CHANGED_SINCE,
  });
  assert.deepEqual(first, {offered: '1 file', before: ''}, 'Changed since: one of the two files is offered, and nothing came in before');
  await importFromSummary(page);
  const afterFirst = await notesOfAgainFolder(page);
  created.push(...afterFirst.map(([id]) => id));
  assert.equal(afterFirst.length, 1, 'Changed since: one file came in');
  assert.match(afterFirst[0][1], /Alpha one/, 'Changed since: the file changed since the day');
  const [alphaId] = afterFirst[0];

  // Again, alpha changed: the Summary says so, Keep both chosen; Replace puts alpha's new notes
  // in its old note's place and brings in beta, which never came in.
  const second = await walkToSummary(page, {
    files: [['alpha.md', 'Alpha two\n', now], ['beta.md', 'Beta one\n', LONG_AGO]], changedSince: '',
  });
  assert.equal(second.offered, '2 files', 'no day: both files are offered');
  assert.match(second.before, new RegExp(`^${AGAIN_FOLDER} was imported before \\(.+\\)\\. 1 file changed since\\. Keep both Replace the old notes$`),
    'the Summary says the folder came in before and asks');
  assert.equal(await page.$eval('#import-wizard input[name="wizard-earlier-notes"]:checked', node => node.value), 'keep',
    'Keep both is chosen at first');
  await chooseOnSummary(page, 'replace');
  await importFromSummary(page);
  const afterSecond = await notesOfAgainFolder(page);
  created.push(...afterSecond.map(([id]) => id).filter(id => !created.includes(id)));
  assert.deepEqual(afterSecond.map(([, text]) => /Alpha two/.test(text) ? 'alpha two' : /Beta one/.test(text) ? 'beta' : text).toSorted(),
    ['alpha two', 'beta'], 'Replace: alpha as it is now, and beta, each once');
  assert.equal(afterSecond.find(([, text]) => /Alpha two/.test(text))[0], alphaId, 'Replace: alpha keeps its note');

  // Again with nothing changed, Replace has nothing to bring in: said so, and Import waits.
  const third = await walkToSummary(page, {
    files: [['alpha.md', 'Alpha two\n', now], ['beta.md', 'Beta one\n', LONG_AGO]], changedSince: '',
  });
  assert.match(third.before, /No file changed since\./, 'nothing changed since');
  await chooseOnSummary(page, 'replace');
  assert.deepEqual(await page.evaluate(() => ({
    said: document.querySelector('#import-wizard .wizard-preview-counts').innerText.trim(),
    isWaiting: document.querySelector('#import-wizard .wizard-footer .wizard-next').classList.contains('is-incomplete'),
  })), {said: NOTHING_TO_BRING_IN, isWaiting: true}, 'Replace with nothing changed');
  await page.keyboard.press('Escape');
  await idle(page);
  await pause(SETTLE_MS);
  assert.equal((await notesOfAgainFolder(page)).length, afterSecond.length, 'nothing came in');
  // The search contexts the imports opened go with the suite's others.
  const order = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return [...mode.tabOrder];
  });
  contexts.push(...order.slice(contextsBefore).filter(tabId => !contexts.includes(tabId)));
}

export async function checkFolderDrops(page) {
  const folderNoteId = await page.evaluate(async folder => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>Folder drop target</p>', folder);
    return note.id;
  }, FOLDER);
  await page.setViewport(WINDOW);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  // The folders tab shows the tree (docs/ready-to-build/folders-tab-and-multiple-folders.md §1).
  await page.click('#virtual-folders-button');
  await idle(page);
  const created = [folderNoteId];
  const contexts = [];
  await runThenCleanUp('folder drops', async () => {
    await page.waitForSelector(`#virtual-folders [data-virtual-folder="${FOLDER}"]`, {visible: true});
    const droppedOnFolderId = await checkFilesOnAFolder(page);
    created.push(droppedOnFolderId);
    await checkFilesOnAFolderWhileEditing(page, droppedOnFolderId);
    created.push(...await checkFolderOnAFolder(page));
    await checkWhereEachDropEnds(page, created, contexts);
    await checkAFolderDroppedAgain(page, created, contexts);
  }, async () => {
    // The search contexts the drops opened go with their −, as a person deletes them: deleted behind
    // the page's back, its next save of the scroll would name them and be refused.
    for (const tabId of contexts) await deleteFromList(page, tabId);
    await page.evaluate(async ids => {
      // Hides the tree again.
      if (document.body.classList.contains('virtual-folders-on')) document.getElementById('virtual-folders-button').click();
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, created);
  });
}

async function deleteFromList(page, tabId) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width / 2, zone.y + zone.height / 2);
  const minus = `#search-contexts-list .delete-context[data-delete-tab-id="${tabId}"]`;
  await page.waitForSelector(minus, {visible: true});
  await pause(SETTLE_MS);
  await page.click(minus);
  await idle(page);
  await pause(SETTLE_MS);
}
