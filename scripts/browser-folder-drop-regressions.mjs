import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Files and folders dropped from the desktop (docs/ready-to-build/desktop-drops-into-folders.md).
// A test browser can't fake a dropped folder (its entry), so the folder's part starts where the
// drop hands over: the walkthrough opened with the folder's files as the browser read them.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
const SHOWN_KEY = 'metalist.virtual_folders.shown';
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
const FOLDER = 'Dropzone/';
const DROPPED_FOLDER = 'Droppedtrip';
const WIZARD_STEP_TIMEOUT_MS = 20000;
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

// §2 and §4: a folder dropped on a folder opens the walkthrough on Any folder, the folder in,
// its files listed before any is sent, then copied, then imported under the target.
async function checkFolderOnAFolder(page) {
  await page.evaluate(async ({name, folder}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const file = (path, text) => ({path, size: new Blob([text]).size, file: new File([text], path.split('/').pop())});
    await CommandPalette.openImportWizardWithDroppedFolder({
      name, files: [file('plan.md', '# Dropped plan\n\nA line of the plan.\n'), file('notes/todo.txt', 'Dropped todo'), file('.DS_Store', 'x')],
    }, folder);
  }, {name: DROPPED_FOLDER, folder: FOLDER});
  // As for a dropped bookmarks file: Source first, with Any folder chosen.
  await waitForStep(page, 'What are you importing?');
  assert.equal(await page.$eval('#import-wizard [data-choice-key="source"].is-chosen', node => node.dataset.choiceValue), 'files',
    'Any folder is chosen');
  await next(page);
  await waitForStep(page, 'Choose the folder');
  assert.equal(await page.$eval('#import-wizard .wizard-folder-name', node => node.textContent), DROPPED_FOLDER, 'the dropped folder is chosen');
  assert.equal(await page.$eval('#import-wizard [data-wizard-prefix]', node => node.value), `${FOLDER}${DROPPED_FOLDER}`,
    'it goes into the folder it was dropped on, under its own name');
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
  const imported = await page.evaluate(() => [...document.querySelectorAll('#notes-container > .note')]
    .filter(note => ['Dropped plan', 'Dropped todo', 'todo.txt'].some(text => note.textContent.includes(text)))
    .map(note => ({id: note.dataset.noteId, folders: note.dataset.noteTags.split(/\s+/).filter(tag => tag.endsWith('/'))})));
  assert.equal(imported.length, 2, 'the plan and the text file came in; the hidden file did not');
  for (const note of imported) {
    assert.ok(note.folders.every(tag => tag.startsWith(`${FOLDER}${DROPPED_FOLDER}/`)) && note.folders.length > 0,
      `imported under the target: ${note.folders}`);
  }
  // Discarding it again is refused as gone (app/services/import_uploads.py _upload_folder).
  const discard = await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {settleResult} = await import('/static/js/modules/async-result.js');
    const outcome = await settleResult(() => NotesAPI.discardImportUpload(id));
    return {isDiscarded: outcome.ok, refusal: outcome.ok ? null : `${outcome.error.name}: ${outcome.error.message}`};
  }, uploadId);
  assert.deepEqual(discard, {isDiscarded: false, refusal: 'ServerInputRejectedError: That upload is gone. Drop the folder again.'},
    'the holding folder went with the walkthrough');
  return imported.map(note => note.id);
}

export async function checkFolderDrops(page) {
  const folderNoteId = await page.evaluate(async folder => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>Folder drop target</p>', folder);
    return note.id;
  }, FOLDER);
  await page.setViewport(WINDOW);
  await page.evaluate(key => window.localStorage.setItem(key, 'true'), SHOWN_KEY);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const created = [folderNoteId];
  await runThenCleanUp('folder drops', async () => {
    await page.waitForSelector(`#virtual-folders [data-virtual-folder="${FOLDER}"]`, {visible: true});
    created.push(await checkFilesOnAFolder(page));
    created.push(...await checkFolderOnAFolder(page));
  }, async () => {
    await page.evaluate(async ({ids, key}) => {
      window.localStorage.setItem(key, 'false');
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, {ids: created, key: SHOWN_KEY});
  });
}
