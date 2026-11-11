import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { openSortMenu } from './browser-sort-menu-regressions.mjs';

// The File size order (docs/ui/command-palette.md, Sort Order): offered only with Notes with
// Files on, what it ranks by, and the sizes it shows.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 700;
const WIDE = {width: 1440, height: 900};
const NO_MARGIN = {width: 900, height: 900};
const KIB = 1024;
// The distance CSS puts a total from its note.
const TOTAL_MARGIN_PX = 8;
// Enough plain notes above the sized ones that their place in Normal order is far down the page.
const PLAIN_NOTES = 40;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

// Largest total first; created in this order, so Normal order (newest first) lists them reversed.
const SIZED_NOTES = ['Huge zip', 'Big picture', 'Trip', 'Used twice', 'Small pdf'];

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function seed(page) {
  return page.evaluate(async ({kib, plainNotes}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const upload = async (name, type, kilobytes) => {
      const file = new File([new Uint8Array(kilobytes * kib).fill(7)], name, {type});
      return (await FilesAPI.uploadFile(file)).file_id;
    };
    const ids = [];
    const note = async (parentId, text) => {
      let created;
      if (parentId === null) created = await NotesAPI.createNote(null, '');
      else created = await NotesAPI.createChild(parentId, '');
      await NotesAPI.saveNote(created.id, `<div>${text}</div>`, '');
      if (parentId === null) ids.push(created.id);
      return created.id;
    };
    await note(null, `Huge zip [[${await upload('huge.zip', 'application/zip', 900)}]] [[${await upload('tiny.png', 'image/png', 1)}]]`);
    await note(null, `Big picture [[${await upload('big.png', 'image/png', 300)}]]`);
    const trip = await note(null, `Trip [[${await upload('trip.pdf', 'application/pdf', 100)}]]`);
    await note(trip, `Trip child [[${await upload('trip-child.pdf', 'application/pdf', 150)}]]`);
    const twice = await upload('twice.pdf', 'application/pdf', 200);
    const usedTwice = await note(null, `Used twice [[${twice}]]`);
    await note(usedTwice, `Used twice child [[${twice}]]`);
    await note(null, `Small pdf [[${await upload('small.pdf', 'application/pdf', 2)}]]`);
    for (let index = 0; index < plainNotes; index += 1) await note(null, `Plain ${index}`);
    return ids;
  }, {kib: KIB, plainNotes: PLAIN_NOTES});
}

async function setFilter(page, kind) {
  await page.evaluate(async kind => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setFileFilter(kind);
  }, kind);
  await idle(page);
}

function shownNotes(page) {
  return page.evaluate(names => [...document.querySelectorAll('#notes-container > .note')].flatMap(root => {
    const name = root.querySelector('.note-content').innerText.split('\n')[0].trim();
    const total = root.querySelector(':scope > .note-file-total');
    return names.includes(name) ? [[name, total === null ? null : total.textContent]] : [];
  }), SIZED_NOTES);
}

function cardSizes(page) {
  return page.$$eval('[data-file-size]', headers => headers.map(header => [
    header.querySelector('.note-file-reference-name').textContent, header.getAttribute('data-file-size'),
  ]));
}

function chipText(page, id) {
  return page.$eval(`#${id}`, chip => {
    const label = chip.querySelector('.search-input-chip-label');
    return getComputedStyle(chip).display === 'none' ? '' : label.textContent.trim();
  });
}

async function sortMenuLabels(page) {
  await openSortMenu(page);
  const labels = await page.$$eval('#context-submenu .context-menu-item', items => items.map(item => item.textContent.trim()));
  return labels;
}

async function closeMenu(page) {
  await page.keyboard.press('Escape');
  await page.waitForSelector('#context-menu.is-visible', {hidden: true});
}

async function pickFromSortMenu(page, label) {
  await openSortMenu(page);
  const items = await page.$$('#context-submenu .context-menu-item');
  const texts = await Promise.all(items.map(item => item.evaluate(node => node.textContent.trim())));
  await items[texts.findIndex(text => text.endsWith(label))].click();
  await idle(page);
}

// Every type the notes hold, most files first (4 PDFs, 2 pictures, a zip), the standard ones even with none.
async function openFileTypeMenu(page) {
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  await page.mouse.click(width - 2, 180, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible');
  const buttons = await page.$$('#context-menu .context-menu-item');
  const labels = await Promise.all(buttons.map(button => button.evaluate(node => node.textContent)));
  await buttons[labels.findIndex(label => label.startsWith('Notes with Files'))].click();
  await page.waitForSelector('#context-submenu.is-visible');
  return page.$$('#context-submenu .context-menu-item');
}

async function checkFileTypeMenu(page) {
  const items = await openFileTypeMenu(page);
  const labels = await Promise.all(items.map(item => item.evaluate(node => node.textContent.trim())));
  assert.deepEqual(labels, ['✓All Notes', 'Any File', 'PDFs', 'Images', 'ZIP Files', 'Markdown Files']);
  await items[labels.indexOf('ZIP Files')].click();
  await idle(page);
  assert.equal(await chipText(page, 'file-filter-indicator'), 'With ZIP files');
  assert.deepEqual((await shownNotes(page)).map(([name]) => name), ['Huge zip'], 'only the note with the zip');
  await pickFromSortMenu(page, 'File Size');
  assert.deepEqual((await cardSizes(page)).map(([name]) => name), ['huge.zip'], 'the File size order counts the zip alone');
  await pickFromSortMenu(page, 'Normal');
  const again = await openFileTypeMenu(page);
  const ticked = await Promise.all(again.map(item => item.evaluate(node => node.textContent.trim())));
  assert.equal(ticked[labels.indexOf('ZIP Files')], '✓ZIP Files');
  await closeMenu(page);
  await setFilter(page, 'none');
}

async function checkOffered(page) {
  assert.equal((await sortMenuLabels(page)).some(label => label.endsWith('File Size')), false, 'no filter: no File Size');
  await closeMenu(page);
  await setFilter(page, 'any');
  assert.equal((await sortMenuLabels(page)).some(label => label.endsWith('File Size')), true, 'with the filter: File Size');
  await closeMenu(page);
}

async function checkOrderAndPills(page) {
  await pickFromSortMenu(page, 'File Size');
  assert.equal(await chipText(page, 'root-sort-indicator'), 'File size');
  assert.deepEqual(await shownNotes(page), [
    ['Huge zip', '901.0 KB'], ['Big picture', '300.0 KB'], ['Trip', '250.0 KB'], ['Used twice', '200.0 KB'], ['Small pdf', '2.0 KB'],
  ]);
  assert.deepEqual(await cardSizes(page), [
    ['huge.zip', '900.0 KB'], ['tiny.png', '1.0 KB'], ['big.png', '300.0 KB'], ['trip.pdf', '100.0 KB'],
    ['trip-child.pdf', '150.0 KB'], ['twice.pdf', '200.0 KB'], ['twice.pdf', '200.0 KB'], ['small.pdf', '2.0 KB'],
  ]);

  await pickFromSortMenu(page, 'Reverse Order');
  assert.equal(await chipText(page, 'root-sort-indicator'), 'File size ↑');
  assert.deepEqual((await shownNotes(page)).map(([name]) => name), [...SIZED_NOTES].reverse());
  await pickFromSortMenu(page, 'Reverse Order');
}

async function checkOnlyTheFiltersFilesCount(page) {
  await setFilter(page, 'image');
  assert.deepEqual(await shownNotes(page), [['Big picture', '300.0 KB'], ['Huge zip', '1.0 KB']]);
  assert.deepEqual(await cardSizes(page), [['big.png', '300.0 KB'], ['tiny.png', '1.0 KB']]);
  await setFilter(page, 'any');
}

function totalPlacement(page) {
  return page.evaluate(() => {
    const note = document.querySelector('#notes-container > .note');
    const content = note.querySelector(':scope > .note-content').getBoundingClientRect();
    const total = note.querySelector(':scope > .note-file-total > span').getBoundingClientRect();
    const box = note.getBoundingClientRect();
    return {
      isInNote: document.getElementById('notes-container').classList.contains('file-totals-in-note'),
      gapToNote: total.left - box.right, rightInside: total.right <= box.right, aboveContent: total.bottom <= content.top,
    };
  });
}

async function checkTotalPlacement(page) {
  const inMargin = await totalPlacement(page);
  assert.equal(inMargin.isInNote, false);
  assert.equal(inMargin.gapToNote, TOTAL_MARGIN_PX);
  await page.setViewport(NO_MARGIN);
  await idle(page);
  const inNote = await totalPlacement(page);
  assert.deepEqual([inNote.isInNote, inNote.rightInside, inNote.aboveContent], [true, true, true]);
  await page.setViewport(WIDE);
  await idle(page);
  assert.equal((await totalPlacement(page)).isInNote, false, 'with the margin back, the totals go back to it');
}

async function checkSizesAreNotNoteText(page) {
  const facts = await page.evaluate(() => ({
    noteText: [...document.querySelectorAll('#notes-container .note-content')].some(content => content.innerText.includes(' KB')),
    selectable: getComputedStyle(document.querySelector('.note-file-total > span')).userSelect,
  }));
  assert.deepEqual(facts, {noteText: false, selectable: 'none'});
}

async function checkPillsSurviveEditingAndCollapse(page, firstNoteId) {
  const countPills = () => page.evaluate(() => [
    document.querySelectorAll('.note-file-total').length, document.querySelectorAll('[data-file-size]').length,
  ]);
  const before = await countPills();
  const title = await page.evaluate(() => {
    const rect = document.querySelector('#notes-container > .note .note-content').getBoundingClientRect();
    return {x: rect.left + 30, y: rect.top + 10};
  });
  await page.mouse.click(title.x, title.y);
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.isEditing;
  });
  // A key pressed while the note is still opening is dropped.
  await idle(page);
  await page.keyboard.press('Escape');
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return !state.isEditing;
  });
  await idle(page);
  assert.deepEqual(await countPills(), before, 'editing a note keeps the pills');

  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.collapseNote(id);
  }, firstNoteId);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  assert.deepEqual(await countPills(), before, 'a reload and a collapsed note keep the pills');
  // Stretched, the title would push the size to the far side of the card.
  assert.equal(await page.$eval('.note.collapsed [data-file-size] .note-file-reference-title', title => getComputedStyle(title).flexGrow), '0');
}

// Reported 2026-11-09: the list held on to the note that had been on top, far down the new order.
async function checkEndingTheFilterStartsAtTheTop(page) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await idle(page);
  await page.click('#file-filter-indicator-clear');
  await idle(page);
  const facts = await page.evaluate(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {
      sortMode: state.activeTabSortMode, scrollY: window.scrollY,
      totals: document.querySelectorAll('.note-file-total').length, cards: document.querySelectorAll('[data-file-size]').length,
    };
  });
  assert.deepEqual(facts, {sortMode: 'normal', scrollY: 0, totals: 0, cards: 0});
  assert.equal(await chipText(page, 'root-sort-indicator'), '');
}

async function checkLeavingTheOrderStartsAtTheTop(page) {
  await setFilter(page, 'any');
  await pickFromSortMenu(page, 'File Size');
  await page.evaluate(() => window.scrollTo(0, 0));
  await idle(page);
  await page.click('#root-sort-indicator-clear');
  await idle(page);
  assert.equal(await page.evaluate(() => window.scrollY), 0, 'its chip goes back to Normal, at the top');
  assert.equal(await page.evaluate(() => document.querySelectorAll('.note-file-total').length), 0);
}

export async function checkFileSizeSort(page) {
  const originalViewport = page.viewport();
  await page.setViewport(WIDE);
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const ids = await seed(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('file size sort', async () => {
    await checkFileTypeMenu(page);
    await checkOffered(page);
    await checkOrderAndPills(page);
    await checkOnlyTheFiltersFilesCount(page);
    await checkTotalPlacement(page);
    await checkSizesAreNotNoteText(page);
    await checkEndingTheFilterStartsAtTheTop(page);
    await checkLeavingTheOrderStartsAtTheTop(page);
    await setFilter(page, 'any');
    await pickFromSortMenu(page, 'File Size');
    await checkPillsSurviveEditingAndCollapse(page, ids[0]);
  }, async () => {
    await page.evaluate(async ids => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await CommandPalette.setFileFilter('none');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
    await page.setViewport(originalViewport);
  });
}
