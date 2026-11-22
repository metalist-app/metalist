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
// A folded gallery's pictures are small (64px columns, main.css); an open one's are 150px or more.
const FOLDED_TILE_LIMIT = 120;
// The folded row's own top margin (6px, main.css) and no more.
const FOLDED_ROW_GAP_LIMIT = 8;
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

// A click on a tile opens what it shows (the maintainer, 2026-11-21: clicking a tile did
// nothing): a file that is no picture, here a Markdown file drawn as a small page, opens in the
// viewer, and Escape closes it.
async function tileOpensItsFile(page, noteId) {
  await page.click(`.note[data-note-id="${noteId}"] .meta-gallery-tile`);
  await page.waitForSelector('.file-viewer-overlay', {visible: true});
  await idle(page);
  const shown = await page.$eval('.file-viewer-overlay', overlay => overlay.textContent);
  assert.ok(FILE_NAMES.some(name => shown.includes(name)), `the viewer shows the tile's file: ${shown.slice(0, 80)}`);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('.file-viewer-overlay') === null);
  await idle(page);
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

// A @gallery note inside an embed (the maintainer, 2026-11-19: "galleries don't show up in
// embeddings"; an embedded gallery showed its children as an outline, never the grid). An embed is
// a window onto its source, drawn as the list draws it. Holiday pictures (@gallery, a picture in
// each of its three child notes) is embedded twice: amid Trip report's text, and alone in a note
// that holds it. The agreed cases:
// 1. open: both embeds show the grid, the children hidden, as Holiday pictures does in the list;
// 2. folded (the embed's own arrow, shared with the source): the first line and one row of small
//    pictures, no captions, no switch;
// 3. the switch sits right under the arrow that folds the embed, and is the source's own choice:
//    flipped in an embed, it flips the other embed and the list;
// 4. a tile shows its picture full screen; Go to note is offered while the list shows the source
//    as a note of its own, and not otherwise;
// 5. a search that shows the holders and not the source leaves the embeds' grids whole.
const EMBED_TAG = 'gallery-embed-suite';
const PICTURE_COLORS = ['purple', 'orange', 'blue'];
const PICTURE_SIZE = {width: 300, height: 200};

async function makeEmbeddedGallery(page) {
  return page.evaluate(async ({colors, size, tag}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const picture = color => new Promise(done => {
      const canvas = document.createElement('canvas');
      canvas.width = size.width;
      canvas.height = size.height;
      const context = canvas.getContext('2d');
      context.fillStyle = color;
      context.fillRect(0, 0, size.width, size.height);
      canvas.toBlob(done, 'image/png');
    });
    const source = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(source.id, '<p>Holiday pictures</p>', '@gallery');
    const children = [];
    for (const color of colors) {
      const uploaded = await FilesAPI.uploadFile(new File([await picture(color)], `${color}.png`, {type: 'image/png'}));
      const child = await NotesAPI.createChild(source.id, '');
      await NotesAPI.saveNote(child.id, `<p>${color} ${uploaded.reference_token}</p>`, '');
      children.push(child.id);
    }
    const holder = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(holder.id, `<p>![[${source.id}]]</p>`, tag);
    const report = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(report.id, `<p>Trip report, with the pictures:</p><p>![[${source.id}]]</p><p>and text after.</p>`, tag);
    return {source: source.id, holder: holder.id, report: report.id, children};
  }, {colors: PICTURE_COLORS, size: PICTURE_SIZE, tag: EMBED_TAG});
}

// How each of the three draws the gallery: the embed in Trip report, the embed its note holds,
// and Holiday pictures itself in the list (null when the list doesn't show it).
function embeddedLayout(page, ids) {
  return page.evaluate(ids => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, width: rect.width, height: rect.height, bottom: rect.bottom};
    };
    const isShown = element => element !== null && element.getClientRects().length > 0;
    const drawn = (gallery, arrow, children) => {
      const toggle = Array.from(gallery.querySelectorAll('.meta-gallery-switch')).at(-1);
      const tiles = Array.from(gallery.querySelectorAll('.meta-gallery-tile'));
      const firstLine = gallery.querySelector('.note-embed-gallery-first-line');
      return {
        isOutline: gallery.classList.contains('is-gallery-outline'),
        isGridShown: isShown(gallery.querySelector('.meta-gallery-grid')),
        areChildrenShown: isShown(children),
        tiles: tiles.map(tile => box(tile)),
        captionsShown: Array.from(gallery.querySelectorAll('.meta-gallery-caption')).filter(isShown).length,
        isSwitchShown: isShown(toggle),
        toggle: box(toggle), label: toggle.title,
        arrow: box(arrow),
        // The arrow's height in its own gallery: notes above it grow when they show an outline.
        arrowFromTop: arrow.getBoundingClientRect().top - gallery.getBoundingClientRect().top,
        firstLine: firstLine === null ? null : box(firstLine),
      };
    };
    const embedIn = noteId => document.querySelector(`.note[data-note-id="${noteId}"] .note-embed-gallery`);
    const report = embedIn(ids.report);
    const held = embedIn(ids.holder);
    const source = document.querySelector(`.note[data-note-id="${ids.source}"]`);
    return {
      report: drawn(report, report.querySelector(':scope > .note-embed-body > .note-embed-collapse-toggle'), report.querySelector(':scope > .note-embed-body > .note-embed-children')),
      // The note holding the embed folds it with its own arrow (docs/ui/references.md).
      held: drawn(held, document.querySelector(`.note[data-note-id="${ids.holder}"] > .note-collapse-toggle`), held.querySelector(':scope > .note-embed-body > .note-embed-children')),
      source: source === null ? null : drawn(source, source.querySelector(':scope > .note-collapse-toggle'), source.querySelector(':scope > .note-children')),
    };
  }, ids);
}

const EMBED_SWITCH = noteId => `.note[data-note-id="${noteId}"] .note-embed-gallery .meta-gallery-switch`;
const EMBED_TILE = noteId => `.note[data-note-id="${noteId}"] .note-embed-gallery .meta-gallery-tile`;

async function waitForOutline(page, ids, isOutline) {
  await page.waitForFunction((ids, isOutline) => [
    document.querySelector(`.note[data-note-id="${ids.report}"] .note-embed-gallery`),
    document.querySelector(`.note[data-note-id="${ids.holder}"] .note-embed-gallery`),
    document.querySelector(`.note[data-note-id="${ids.source}"]`),
  ].every(gallery => gallery.classList.contains('is-gallery-outline') === isOutline), {}, ids, isOutline);
  await idle(page);
}

async function waitForFolded(page, ids, isFolded) {
  await page.waitForFunction((ids, isFolded) => [ids.report, ids.holder].every(noteId => (
    document.querySelector(`.note[data-note-id="${noteId}"] .note-embed-gallery`).classList.contains('note-embed-collapsed') === isFolded
  )), {}, ids, isFolded);
  await idle(page);
}

async function picturesLoaded(page, ids) {
  await page.waitForFunction(ids => [ids.report, ids.holder].every(noteId => (
    Array.from(document.querySelectorAll(`.note[data-note-id="${noteId}"] .note-embed-gallery .meta-gallery-tile`))
      .every(tile => Array.from(tile.querySelectorAll('img')).some(image => image.complete && image.naturalWidth > 0))
  )), {}, ids);
}

async function embeddedGridAndSwitch(page, ids) {
  const grid = await embeddedLayout(page, ids);
  for (const [where, shown] of Object.entries(grid)) {
    assert.equal(shown.isOutline, false, `${where}: starts as its grid`);
    assert.equal(shown.isGridShown, true, `${where}: the grid shows`);
    assert.equal(shown.areChildrenShown, false, `${where}: the children are hidden while the grid shows`);
    assert.equal(shown.tiles.length, PICTURE_COLORS.length, `${where}: a tile for each picture`);
    assert.equal(shown.captionsShown, PICTURE_COLORS.length, `${where}: each tile has its caption`);
    assert.equal(shown.label, 'Show as outline');
    assertSwitchUnderArrow(shown, `${where}, grid`);
  }

  // Case 3: flipped in an embed, the choice is the source's, everywhere.
  await page.click(EMBED_SWITCH(ids.report));
  await waitForOutline(page, ids, true);
  const outline = await embeddedLayout(page, ids);
  for (const [where, shown] of Object.entries(outline)) {
    assert.equal(shown.isGridShown, false, `${where}: no grid as an outline`);
    assert.equal(shown.areChildrenShown, true, `${where}: the children show as an outline`);
    assert.equal(shown.label, 'Show as grid');
    assertSwitchUnderArrow(shown, `${where}, outline`);
    assertNear(shown.arrowFromTop, grid[where].arrowFromTop, `${where}: the fold arrow keeps its place in its note`);
  }
  await page.click(EMBED_SWITCH(ids.holder));
  await waitForOutline(page, ids, false);
}

async function embeddedFoldedRow(page, ids) {
  await page.click(`.note[data-note-id="${ids.report}"] .note-embed-gallery > .note-embed-body > .note-embed-collapse-toggle`);
  await waitForFolded(page, ids, true);
  const folded = await embeddedLayout(page, ids);
  for (const [where, shown] of Object.entries(folded)) {
    assert.equal(shown.isGridShown, true, `${where}, folded: the row of pictures shows`);
    assert.equal(shown.tiles.length, PICTURE_COLORS.length);
    for (const tile of shown.tiles) {
      assert.equal(tile.top, shown.tiles[0].top, `${where}, folded: the pictures are one row`);
      assert.ok(tile.height > 0 && tile.height < FOLDED_TILE_LIMIT, `${where}, folded: small pictures (${tile.height})`);
    }
    assert.equal(shown.captionsShown, 0, `${where}, folded: no captions`);
    assert.equal(shown.isSwitchShown, false, `${where}, folded: no switch`);
  }
  for (const where of ['report', 'held']) {
    const shown = folded[where];
    assert.ok(shown.firstLine.height > 0, `${where}, folded: the first line shows`);
    assert.ok(shown.firstLine.bottom <= shown.tiles[0].top, `${where}, folded: the row is under the first line`);
    assert.ok(shown.tiles[0].top - shown.firstLine.bottom <= FOLDED_ROW_GAP_LIMIT,
      `${where}, folded: the row sits right under the line (${shown.tiles[0].top - shown.firstLine.bottom})`);
  }
  await page.click(`.note[data-note-id="${ids.report}"] .note-embed-gallery > .note-embed-body > .note-embed-collapse-toggle`);
  await waitForFolded(page, ids, false);
}

function goToNoteShown(page) {
  return page.evaluate(() => {
    const overlay = document.querySelector('.image-zoom-overlay.is-gallery');
    if (overlay === null) return null;
    return overlay.querySelector('.image-zoom-go-to-note').getClientRects().length > 0;
  });
}

async function embeddedFullScreen(page, ids, {isSourceListed}) {
  await picturesLoaded(page, ids);
  await page.click(EMBED_TILE(ids.report));
  await page.waitForSelector('.image-zoom-overlay.is-gallery');
  assert.equal(await goToNoteShown(page), isSourceListed,
    isSourceListed ? 'Go to note is offered while the list shows the source' : 'no Go to note when the list does not show the source');
  assert.deepEqual(await page.$eval('.image-zoom-overlay', overlay => [
    overlay.querySelector('.image-zoom-previous').disabled, overlay.querySelector('.image-zoom-next').disabled,
  ]), [true, false], 'the first picture, with the embed\'s others after it');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('.image-zoom-overlay') === null);
}

async function searchFor(page, text) {
  await page.focus('#search-input');
  await page.evaluate(() => document.getElementById('search-input').select());
  await page.keyboard.press('Backspace');
  if (text !== '') await page.keyboard.type(text);
  await page.waitForFunction(async expected => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return ModeContextInstance.getExecutedSearchQuery() === expected;
  }, {}, text);
  await page.evaluate(() => document.getElementById('search-input').blur());
  await idle(page);
}

async function embeddedUnderSearch(page, ids) {
  await searchFor(page, EMBED_TAG);
  const searched = await embeddedLayout(page, ids);
  assert.equal(searched.source, null, 'the search shows the holders, not Holiday pictures');
  for (const where of ['report', 'held']) {
    assert.equal(searched[where].tiles.length, PICTURE_COLORS.length, `${where}: a search leaves the embed's grid whole`);
    assert.equal(searched[where].isGridShown, true);
  }
  await embeddedFullScreen(page, ids, {isSourceListed: false});
  await searchFor(page, '');
}

async function checkEmbeddedGallery(page) {
  const ids = await makeEmbeddedGallery(page);
  await runThenCleanUp('gallery in an embed', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await page.$eval(`.note[data-note-id="${ids.report}"]`, note => note.scrollIntoView({block: 'start'}));
    await idle(page);
    await embeddedGridAndSwitch(page, ids);
    await embeddedFoldedRow(page, ids);
    await embeddedFullScreen(page, ids, {isSourceListed: true});
    await embeddedUnderSearch(page, ids);
  }, async () => {
    await page.keyboard.press('Escape');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, [ids.report, ids.holder, ids.source]);
    await idle(page);
  });
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
    await tileOpensItsFile(page, ids[0]);
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
  await checkEmbeddedGallery(page);
}
