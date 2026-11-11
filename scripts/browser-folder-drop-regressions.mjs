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
  await page.evaluate(folder => {
    const row = document.querySelector(`#virtual-folders [data-virtual-folder="${folder}"]`);
    const transfer = new DataTransfer();
    // Not a text file: a dropped .txt or .md asks first (files-shown-not-copied.md §5).
    transfer.items.add(new File(['dropped,on a folder'], 'folder-drop.csv', {type: 'text/csv'}));
    const box = row.getBoundingClientRect();
    const at = {clientX: box.left + box.width / 2, clientY: box.top + box.height / 2, bubbles: true, cancelable: true, dataTransfer: transfer};
    row.dispatchEvent(new DragEvent('dragover', at));
    row.dispatchEvent(new DragEvent('drop', at));
  }, FOLDER);
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
    created.push(await checkFilesOnAFolder(page));
    created.push(...await checkFolderOnAFolder(page));
    await checkWhereEachDropEnds(page, created, contexts);
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
