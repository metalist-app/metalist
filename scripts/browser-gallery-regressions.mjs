import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A @gallery note (docs/future-plans/gallery.md; the maintainer, 2026-11-18 and 19), with a
// heading for its first line and Markdown files in the notes under it:
// - each file is one tile, showing the top of the file as a small page that fits its square;
// - the fold arrow is beside the heading, at the same place whether the note shows its grid or
//   its outline;
// - the switch sits right under the fold arrow, on its axis, the same size, in both states, and
//   its label says what a click does.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
// Sub-pixel layout rounds each edge to a device pixel at most.
const PIXEL_ROUNDING = 0.5;
const FILE_NAMES = ['Addendum.md', 'Handoff.md', 'Advantages.md'];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function makeGallery(page, ownText) {
  return page.evaluate(async ({names, ownText}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const top = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(top.id, ownText, '@gallery=markdown');
    const ids = [top.id];
    for (const name of names) {
      const text = `# ${name}\n\n## Core constraint\n\nThe game should support **asynchronous** play.\n\n- one\n- two\n\n${'A long paragraph of the document. '.repeat(60)}\n`;
      const uploaded = await FilesAPI.uploadFile(new File([text], name, {type: 'text/markdown'}));
      const child = await NotesAPI.createChild(top.id, '');
      await NotesAPI.saveNote(child.id, `<p>${uploaded.reference_token}</p>`, '');
      ids.push(child.id);
    }
    return ids;
  }, {names: FILE_NAMES, ownText});
}

// A gallery note with no text of its own: the only text in it is inside its tiles (the pages of
// its Markdown files). That text is no line of the note: the fold arrow stays at the note's top,
// where the stylesheet puts it, in both states. It was lined up with the first tile's first line
// while the grid showed, a line too low (the maintainer, 2026-11-19, in Firefox).
async function arrowIgnoresTileText(page, noteId) {
  const read = () => page.evaluate(noteId => {
    const note = document.querySelector(`.note[data-note-id="${noteId}"]`);
    const arrow = note.querySelector(':scope > .note-collapse-toggle');
    return {
      isOutline: note.classList.contains('is-gallery-outline'), placed: arrow.style.top,
      fromNoteTop: arrow.getBoundingClientRect().top - note.getBoundingClientRect().top,
    };
  }, noteId);
  const grid = await read();
  assert.equal(grid.isOutline, false);
  assert.equal(grid.placed, '', 'grid: a tile\'s text is not the note\'s first line, so the arrow keeps the stylesheet\'s place');
  await page.click(`.note[data-note-id="${noteId}"] .meta-gallery-switch`);
  await page.waitForFunction(noteId => document.querySelector(`.note[data-note-id="${noteId}"]`).classList.contains('is-gallery-outline'), {}, noteId);
  await idle(page);
  const outline = await read();
  assertNear(outline.fromNoteTop, grid.fromNoteTop, 'the fold arrow is at the same height in both states');
  await page.click(`.note[data-note-id="${noteId}"] .meta-gallery-switch`);
  await page.waitForFunction(noteId => !document.querySelector(`.note[data-note-id="${noteId}"]`).classList.contains('is-gallery-outline'), {}, noteId);
  await idle(page);
}

function layout(page, noteId) {
  return page.evaluate(noteId => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom};
    };
    const note = document.querySelector(`.note[data-note-id="${noteId}"]`);
    const heading = note.querySelector(':scope > .note-content h1');
    const firstLetter = document.createRange();
    firstLetter.setStart(heading.firstChild, 0);
    firstLetter.setEnd(heading.firstChild, 1);
    const toggle = note.querySelector('.meta-gallery-switch');
    return {
      isOutline: note.classList.contains('is-gallery-outline'),
      letter: box({getBoundingClientRect: () => firstLetter.getClientRects()[0]}),
      arrow: box(note.querySelector(':scope > .note-collapse-toggle')),
      toggle: box(toggle),
      label: toggle.title,
      tiles: [...note.querySelectorAll('.meta-gallery-tile')].map(tile => ({
        picture: box(tile.querySelector('.meta-gallery-picture')),
        page: tile.querySelector('.meta-gallery-document') === null ? null : box(tile.querySelector('.meta-gallery-document')),
      })),
      gridChildren: note.querySelector('.meta-gallery-grid').children.length,
    };
  }, noteId);
}

function assertNear(actual, expected, what) {
  assert.ok(Math.abs(actual - expected) <= PIXEL_ROUNDING, `${what}: ${actual} should be ${expected}`);
}

function assertSwitchUnderArrow(shown, state) {
  assertNear(shown.toggle.left, shown.arrow.left, `${state}: the switch is on the fold arrow's axis`);
  assertNear(shown.toggle.top, shown.arrow.bottom, `${state}: the switch is right under the fold arrow`);
  assert.deepEqual([shown.toggle.width, shown.toggle.height], [shown.arrow.width, shown.arrow.height], `${state}: the switch is the arrow's size`);
}

function assertArrowBesideHeading(shown, state) {
  const arrowMiddle = shown.arrow.top + shown.arrow.height / 2;
  assert.ok(arrowMiddle > shown.letter.top && arrowMiddle < shown.letter.bottom,
    `${state}: the fold arrow (middle ${arrowMiddle}) is beside the heading's first line (${shown.letter.top} to ${shown.letter.bottom})`);
}

async function galleryCases(page, noteId) {
  const grid = await layout(page, noteId);
  assert.equal(grid.isOutline, false, 'a gallery starts as its grid');
  assert.equal(grid.label, 'Show as outline');
  assert.equal(grid.tiles.length, FILE_NAMES.length, 'each Markdown file is one tile');
  assert.equal(grid.gridChildren, FILE_NAMES.length, 'nothing of a file spills out as a tile of its own');
  for (const [index, tile] of grid.tiles.entries()) {
    assert.notEqual(tile.page, null, `tile ${index}: a Markdown file shows the top of the file`);
    assertNear(tile.picture.height, tile.picture.width, `tile ${index}: the picture is a square`);
    // Drawn at three times the square and shrunk to it: the page as shown fits the square.
    assertNear(tile.page.width, tile.picture.width, `tile ${index}: the page is as wide as its square`);
    assertNear(tile.page.left, tile.picture.left, `tile ${index}: the page starts at its square's left`);
    assertNear(tile.page.top, tile.picture.top, `tile ${index}: the page starts at its square's top`);
  }
  assertArrowBesideHeading(grid, 'grid');
  assertSwitchUnderArrow(grid, 'grid');

  await page.click(`.note[data-note-id="${noteId}"] .meta-gallery-switch`);
  await page.waitForFunction(noteId => document.querySelector(`.note[data-note-id="${noteId}"]`).classList.contains('is-gallery-outline'), {}, noteId);
  await idle(page);
  const outline = await layout(page, noteId);
  assert.equal(outline.label, 'Show as grid');
  assertArrowBesideHeading(outline, 'outline');
  assertSwitchUnderArrow(outline, 'outline');
  assertNear(outline.arrow.top - outline.letter.top, grid.arrow.top - grid.letter.top, 'the fold arrow keeps its height beside the heading in both states');
  assertNear(outline.arrow.left, grid.arrow.left, 'the fold arrow keeps its place across in both states');

  await page.click(`.note[data-note-id="${noteId}"] .meta-gallery-switch`);
  await page.waitForFunction(noteId => !document.querySelector(`.note[data-note-id="${noteId}"]`).classList.contains('is-gallery-outline'), {}, noteId);
  await idle(page);
}

export async function checkGallery(page) {
  await page.setViewport(WINDOW);
  const ids = await makeGallery(page, '<h1>Gallery suite: Centuries of Steel</h1>');
  const textless = await makeGallery(page, '');
  await runThenCleanUp('gallery', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await page.$eval(`.note[data-note-id="${ids[0]}"]`, note => note.scrollIntoView({block: 'center'}));
    await idle(page);
    await galleryCases(page, ids[0]);
    await page.$eval(`.note[data-note-id="${textless[0]}"]`, note => note.scrollIntoView({block: 'center'}));
    await idle(page);
    await arrowIgnoresTileText(page, textless[0]);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, [ids[0], textless[0]]);
    await idle(page);
  });
}
