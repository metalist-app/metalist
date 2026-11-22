import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A copied note's diagrams are its own (docs/ui/excalidraw.md, "Copies"; the maintainer,
// 2026-11-22: "if I copy a note that has a diagram in it, just make a new identical diagram").
// "Combat design" shows the diagram "Battle flow"; "Logistics" shows none.
// 1. Copy Note on "Combat design", then Paste Sibling Note on "Logistics": the pasted note
//    shows a diagram of its own, drawn as the original, and "Combat design" keeps its own.
// 2. A note that was cut and pasted goes on with the diagram it had.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
// A new file's content revision (file_storage.py): its previews are stored for it.
const FIRST_REVISION = 1;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function makeNotes(page) {
  return page.evaluate(async (firstRevision) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const scene = JSON.stringify({type: 'excalidraw', version: 2, elements: [], appState: {}, files: {}});
    const uploaded = await FilesAPI.uploadFile(new File([scene], 'Battle flow.excalidraw', {type: 'application/vnd.excalidraw+json'}));
    // Drawn: a diagram shows as its picture once its previews are stored.
    const drawing = fill => `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120" viewBox="0 0 300 120"><rect x="10" y="10" width="280" height="100" fill="${fill}"/></svg>`;
    await FilesAPI.storeFilePreviews(uploaded.file_id, {light: drawing('#ffe9a8'), dark: drawing('#334455')}, firstRevision);
    const combat = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(combat.id, `<div>Combat design</div><div>${uploaded.reference_token}</div>`, '');
    const logistics = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(logistics.id, '<div>Logistics</div>', '');
    return {combat: combat.id, logistics: logistics.id, diagram: uploaded.file_id};
  }, FIRST_REVISION);
}

// The diagrams a note's own text shows, in order.
function diagramsOf(page, noteId) {
  return page.$$eval(`#notes-container .note[data-note-id="${noteId}"] > .note-content .note-reference-file-excalidraw`,
    references => references.map(reference => reference.dataset.refNoteId));
}

// Right-click a note's first line and choose an item of its menu, in its `group` submenu when
// the menu has that group ('' for an item of the menu itself).
async function chooseFromNoteMenu(page, noteId, group, label) {
  const line = await page.waitForSelector(`#notes-container .note[data-note-id="${noteId}"] > .note-content > div`, {visible: true});
  const box = await line.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible');
  await pause(SETTLE_MS);
  const choose = async (selector, wanted) => {
    for (const entry of await page.$$(selector)) {
      if (await entry.$eval('.context-menu-item-label', found => found.textContent) === wanted) {
        await entry.click();
        await pause(SETTLE_MS);
        return true;
      }
    }
    return false;
  };
  const menuItems = '.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item';
  if (group !== '' && await choose(menuItems, group)) {
    assert.equal(await choose('.context-menu-submenu.is-visible .context-menu-item', label), true, `${group} has no ${label}`);
  } else {
    assert.equal(await choose(menuItems, label), true, `the note menu has no ${label}`);
  }
  await idle(page);
}

async function aPastedCopyGetsItsOwnDiagram(page, ids) {
  const before = await page.$$eval('#notes-container > .note', notes => notes.map(note => note.dataset.noteId));
  await chooseFromNoteMenu(page, ids.combat, '', 'Copy Note');
  await chooseFromNoteMenu(page, ids.logistics, 'Paste', 'Paste Sibling Note');
  // The pasted note is left edited, where a diagram shows as its reference: back to reading it.
  await page.keyboard.press('Escape');
  await idle(page);
  const after = await page.$$eval('#notes-container > .note', notes => notes.map(note => note.dataset.noteId));
  const pasted = after.filter(noteId => !before.includes(noteId));
  assert.equal(pasted.length, 1, 'one note was pasted');
  const [copyId] = pasted;
  const own = await diagramsOf(page, copyId);
  const pastedText = await page.$eval(`#notes-container .note[data-note-id="${copyId}"] > .note-content`, content => content.innerHTML);
  assert.equal(own.length, 1, `the pasted note shows one diagram: ${pastedText}`);
  assert.notEqual(own[0], ids.diagram, 'it is a diagram of its own');
  assert.deepEqual(await diagramsOf(page, ids.combat), [ids.diagram], '"Combat design" keeps its diagram');
  // Identical: drawn as the original, its picture showing without opening the editor.
  await page.waitForSelector(`#notes-container .note[data-note-id="${copyId}"] [data-ref-note-id="${own[0]}"] img:not([hidden])`, {visible: true});
  return {copyId, diagram: own[0]};
}

async function aCutNoteKeepsItsDiagram(page, ids, copy) {
  // Cut: copied, deleted, then pasted.
  const movedId = await page.evaluate(async ({copyId, logistics}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.copyNote(copyId);
    await NotesAPI.deleteNote(copyId);
    return (await NotesAPI.pasteNoteSibling(logistics)).id;
  }, {copyId: copy.copyId, logistics: ids.logistics});
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  assert.deepEqual(await diagramsOf(page, movedId), [copy.diagram], 'the cut note goes on with the diagram it had');
  return movedId;
}

export async function checkDiagramCopies(page) {
  await page.setViewport(WINDOW);
  const ids = await makeNotes(page);
  // The pasted note still there: the copy, then (the cut having deleted it) the note pasted after.
  let pasted = [];
  await runThenCleanUp('diagram copies', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    const copy = await aPastedCopyGetsItsOwnDiagram(page, ids);
    pasted = [copy.copyId];
    pasted = [await aCutNoteKeepsItsDiagram(page, ids, copy)];
  }, async () => {
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, [...pasted, ids.combat, ids.logistics]);
    await idle(page);
  });
}
