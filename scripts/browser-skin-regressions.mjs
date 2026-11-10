import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { runThenCleanUp } from './suite-outcome.mjs';

// The Illuminated skin (docs/ui/skins.md), chosen under Theme: it takes over the page and goes
// without a trace. Run in Chrome and Firefox: Firefox draws ::first-letter differently.

const REQUESTS_QUIET_MS = 300;
const LONG_TAIL = '<div>Another line</div><div>Another line</div><div>Another line</div>';
const longNote = firstLine => `<div>${firstLine}</div>${LONG_TAIL}`;
const NOTE_TEXTS = ['Apple', 'The birch waits for you', 'Bay gypsy', 'Dahlia', 'Elm', 'Fern', 'Gorse', 'Holly', 'Ivy'];
const OLD_ENGLISH = 'Ye birch waits for thee';
const REAL_WORDS = NOTE_TEXTS[1];
const SWAPPED_NOTE = 1;
const FOLDED_NOTE = 2;
const FOLD_SETTLE_MS = 500;
const NOTES_PER_ORNAMENT = 4;
const INITIAL_SIZE_PX = 40;
const FOLDED_INITIAL_SIZE_PX = INITIAL_SIZE_PX;
const INITIAL_GAP_PX = 3;
const PIXEL_ROUNDING = 0.5;
const ORNAMENT_WIDTH_PX = 250;
const ORNAMENT_HEIGHT_PX = 78;
const ORNAMENT_GAP_PX = 10;
const ORNAMENTS_BY_NOTE = new Map([[3, 'ornament-01'], [7, 'ornament-05']]);
const SECOND_LETTER = 1;
const AFTER_THE_LETTER = 2;

async function applyPreference(page, key, value) {
  await page.evaluate(async ({key, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(key, value);
  }, {key, value});
}

async function createNotes(page) {
  // Long enough for a big letter, and bold, the tallest text a folded note shows.
  return page.evaluate(async notes => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // A new top-level note goes first, so the last one is made first.
    for (const html of [...notes].reverse()) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, '');
      ids.push(note.id);
    }
    return ids;
  }, NOTE_TEXTS.map(text => longNote(`<b>${text}</b>`)));
}

async function reloadApp(page) {
  // A reload that interrupts the font's download is reported as a page error by Firefox.
  await page.evaluate(() => document.fonts.ready);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// What the page shows for the skin; a note's letter offset is where its second letter starts.
function readPage(page) {
  return page.evaluate(({secondLetter, afterTheLetter}) => {
    const root = document.documentElement;
    const notes = [...document.querySelectorAll('#notes-container > .note')];
    const letterOffset = note => {
      const content = note.querySelector(':scope > .note-content');
      const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
      const range = document.createRange();
      range.setStart(text, secondLetter);
      range.setEnd(text, afterTheLetter);
      return range.getBoundingClientRect().left - content.getBoundingClientRect().left - parseFloat(getComputedStyle(content).paddingLeft);
    };
    return {
      skin: root.getAttribute('data-skin'),
      theme: root.getAttribute('data-theme'),
      pageCursor: getComputedStyle(root).cursor,
      buttonCursor: getComputedStyle(document.querySelector('button')).cursor,
      initials: notes.map(note => note.dataset.initial || null),
      texts: notes.map(note => note.querySelector(':scope > .note-content').firstElementChild.textContent.trim()),
      letterOffsets: notes.map(letterOffset),
      ornaments: notes.map(note => {
        const after = getComputedStyle(note, '::after');
        return {
          image: after.backgroundImage,
          width: parseFloat(after.width),
          height: parseFloat(after.height),
          marginBottom: parseFloat(getComputedStyle(note).marginBottom),
        };
      }),
      hasErrorOverlay: document.getElementById('fatal-error-overlay') !== null,
      noteFont: (() => {
        const style = getComputedStyle(notes[0].querySelector(':scope > .note-content'));
        return {family: style.fontFamily, size: style.fontSize};
      })(),
    };
  }, {secondLetter: SECOND_LETTER, afterTheLetter: AFTER_THE_LETTER});
}

function assertNear(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) <= PIXEL_ROUNDING, `${label}: ${actual} is not ${expected}`);
}

function assertSkinned(shown) {
  assert.equal(shown.skin, 'illuminated');
  assert.equal(shown.theme, 'light');
  assert.equal(shown.hasErrorOverlay, false);
  assert.match(shown.pageCursor, /cursor-quill/);
  assert.match(shown.buttonCursor, /cursor-hand/);
  shown.texts.forEach((text, index) => {
    const isOpening = index % NOTES_PER_ORNAMENT === 0;
    assert.equal(shown.initials[index], isOpening ? text[0] : null, `the letter of ${text}`);
    if (isOpening) assertNear(shown.letterOffsets[index], INITIAL_SIZE_PX + INITIAL_GAP_PX, `after the big ${text[0]}`);
    else assert.ok(shown.letterOffsets[index] < NO_LETTER_MAX_OFFSET_PX, `${text} has no big letter: ${shown.letterOffsets[index]}`);
  });
  shown.ornaments.forEach((ornament, index) => {
    const name = ORNAMENTS_BY_NOTE.get(index);
    if (name === undefined) {
      assert.equal(ornament.image, 'none', `no ornament after note ${index}`);
      return;
    }
    assert.match(ornament.image, new RegExp(`${name}\\.webp`));
    assert.equal(ornament.width, ORNAMENT_WIDTH_PX);
    assert.equal(ornament.height, ORNAMENT_HEIGHT_PX);
    assert.equal(ornament.marginBottom, ORNAMENT_HEIGHT_PX + ORNAMENT_GAP_PX + ORNAMENT_GAP_PX);
  });
}

function assertPlain(shown) {
  assert.equal(shown.skin, null);
  assert.equal(shown.theme, null);
  assert.equal(shown.hasErrorOverlay, false);
  assert.doesNotMatch(shown.pageCursor, /cursor-quill/);
  assert.doesNotMatch(shown.buttonCursor, /cursor-hand/);
  assert.deepEqual(shown.initials, shown.texts.map(() => null));
  assert.deepEqual(shown.ornaments.map(ornament => ornament.image), shown.texts.map(() => 'none'));
}

// Old English is only how a note is drawn: an edit and a save get the real words.
async function oldEnglishCases(page, plainFont) {
  const shown = await page.evaluate(async ({index, plainHtml}) => {
    const note = document.querySelectorAll('#notes-container > .note')[index];
    const content = note.querySelector(':scope > .note-content');
    await new Promise(resolve => requestAnimationFrame(resolve));
    const firstLine = () => content.firstElementChild.textContent.trim();
    const drawn = firstLine();
    const {sanitizeNoteHtmlForStorage} = await import('/static/js/modules/note-html-sanitizer.js');
    const stored = sanitizeNoteHtmlForStorage(content.innerHTML);
    const {DOMUtils} = await import('/static/js/modules/dom-utils.js');
    DOMUtils.setNoteEditable(note, true);
    const whileEditing = {
      text: firstLine(),
      spans: content.querySelectorAll('.olde-word').length,
      family: getComputedStyle(content).fontFamily,
      size: getComputedStyle(content).fontSize,
    };
    DOMUtils.setNoteEditable(note, false);
    return {drawn, stored, whileEditing};
  }, {index: SWAPPED_NOTE});
  assert.equal(shown.drawn, OLD_ENGLISH);
  assert.match(shown.stored, /The birch waits for you/);
  assert.doesNotMatch(shown.stored, /olde-word/);
  assert.deepEqual(shown.whileEditing, {text: REAL_WORDS, spans: 0, family: plainFont.family, size: plainFont.size});
  // A change in a note outside its text leaves no words to swap; that must pass without a fault.
  const hasFault = await page.evaluate(async index => {
    const nextFrame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const note = document.querySelectorAll('#notes-container > .note')[index];
    const marker = document.createElement('i');
    note.append(marker);
    await nextFrame();
    marker.remove();
    await nextFrame();
    return document.getElementById('fatal-error-overlay') !== null;
  }, SWAPPED_NOTE);
  assert.equal(hasFault, false);
  await reloadApp(page);
}

// A folded note's one line keeps the letters that hang below it (y, g), in the skin's script.
async function foldedDescenderCase(page) {
  const note = await page.evaluate(async ({index, settleMs}) => {
    const element = document.querySelectorAll('#notes-container > .note')[index];
    element.querySelector(':scope > .note-collapse-toggle').click();
    await new Promise(resolve => setTimeout(resolve, settleMs));
    const content = element.querySelector(':scope > .note-content');
    const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
    const range = document.createRange();
    range.selectNodeContents(text);
    const result = {
      isFolded: element.classList.contains('collapsed'),
      textBottom: range.getBoundingClientRect().bottom,
      contentBottom: content.getBoundingClientRect().bottom,
      font: getComputedStyle(text.parentElement).fontFamily.slice(0, 30),
    };
    element.querySelector(':scope > .note-collapse-toggle').click();
    await new Promise(resolve => setTimeout(resolve, settleMs));
    return result;
  }, {index: FOLDED_NOTE, settleMs: FOLD_SETTLE_MS});
  assert.equal(note.isFolded, true);
  assert.ok(note.textBottom <= note.contentBottom, `letters are cut at the fold: text ends ${note.textBottom}, the note at ${note.contentBottom} (${note.font})`);
}

// An opening note's letter is the same size open and folded.
async function foldedInitialCase(page) {
  const offsets = await page.evaluate(async ({settleMs, secondLetter, afterTheLetter}) => {
    const note = document.querySelector('#notes-container > .note');
    const toggle = () => note.querySelector(':scope > .note-collapse-toggle').click();
    const settle = () => new Promise(resolve => setTimeout(resolve, settleMs));
    const read = () => {
      const content = note.querySelector(':scope > .note-content');
      const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
      const range = document.createRange();
      range.setStart(text, secondLetter);
      range.setEnd(text, afterTheLetter);
      return {
        isFolded: note.classList.contains('collapsed'),
        initial: note.dataset.initial || null,
        offset: range.getBoundingClientRect().left - content.getBoundingClientRect().left - parseFloat(getComputedStyle(content).paddingLeft),
        height: content.getBoundingClientRect().height,
      };
    };
    const shown = [read()];
    for (let step = 0; step < 2; step += 1) {
      toggle();
      await settle();
      shown.push(read());
    }
    return shown;
  }, {settleMs: FOLD_SETTLE_MS, secondLetter: SECOND_LETTER, afterTheLetter: AFTER_THE_LETTER});
  assert.deepEqual(offsets.map(state => state.isFolded), [false, true, false]);
  for (const state of offsets) {
    if (state.isFolded) {
      assert.equal(state.initial, 'A');
      assertNear(state.offset, FOLDED_INITIAL_SIZE_PX + INITIAL_GAP_PX, 'the letter while folded');
      assert.ok(state.height < INITIAL_SIZE_PX * 2, `a folded note is one line tall: ${state.height}`);
    } else {
      assert.equal(state.initial, 'A');
      assertNear(state.offset, INITIAL_SIZE_PX + INITIAL_GAP_PX, 'the big letter while open');
    }
  }
}

// Every way a note's first line can be written gets the big letter, and an edited note has no
// room held for one.
const OPENING_SHAPES = [
  ['text ending in a line break', `Elm tree<br>${LONG_TAIL}`],
  ['two lines split by a line break', `Elm tree<br>A second line${LONG_TAIL}`],
  ['a paragraph', `<p>Elm tree</p><p>A second line</p>${LONG_TAIL}`],
  ['an empty line first', `<div><br></div><div>Elm tree</div>${LONG_TAIL}`],
  ['blocks inside blocks', `<div><div>Elm tree</div></div>${LONG_TAIL}`],
  ['a section', `<section>Elm tree</section>${LONG_TAIL}`],
  ['a block inside an inline', `<span><div>Elm tree</div></span>${LONG_TAIL}`],
  ['a list item', `<ul><li>Elm tree</li></ul>${LONG_TAIL}`],
  ['a quote', `<blockquote>Elm tree</blockquote>${LONG_TAIL}`],
];
const OPENING_NOTE = 4;
const NO_LETTER_MAX_OFFSET_PX = 20;
const BASELINE_ALLOWANCE_PX = 1.5;
// The painted letter ends this share of its tile above the tile's bottom edge, inside the frame.
const LETTER_INSET_SHARE = 0.2;
const SECOND_ROOT = 1;

async function readOpening(page) {
  return page.evaluate(({index, secondLetter, afterTheLetter}) => {
    const note = document.querySelectorAll('#notes-container > .note')[index];
    const content = note.querySelector(':scope > .note-content');
    const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
    const range = document.createRange();
    range.setStart(text, secondLetter);
    range.setEnd(text, afterTheLetter);
    return {
      noteId: note.dataset.noteId,
      // From the left of the block that holds the letter, whatever it is.
      offset: (() => {
        let host = text.parentElement;
        while (!['block', 'list-item', 'flow-root'].includes(getComputedStyle(host).display)) host = host.parentElement;
        return range.getBoundingClientRect().left - host.getBoundingClientRect().left - parseFloat(getComputedStyle(host).paddingLeft);
      })(),
    };
  }, {index: OPENING_NOTE, secondLetter: SECOND_LETTER, afterTheLetter: AFTER_THE_LETTER});
}

async function saveOpening(page, noteId, html) {
  await page.evaluate(async ({noteId, html}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(noteId, html, '');
  }, {noteId, html});
  await reloadApp(page);
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
}

async function openingShapeCases(page) {
  const {noteId} = await readOpening(page);
  const failures = [];
  // A note with a child, as the note that showed the bug had.
  const childId = await page.evaluate(async noteId => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const child = await NotesAPI.createChild(noteId, '');
    await NotesAPI.saveNote(child.id, '<div>A child</div>', '');
    return child.id;
  }, noteId);
  for (const [shape, html] of OPENING_SHAPES) {
    await saveOpening(page, noteId, html);
    const {offset} = await readOpening(page);
    if (Math.abs(offset - (INITIAL_SIZE_PX + INITIAL_GAP_PX)) > PIXEL_ROUNDING) failures.push(`${shape}: the second letter is at ${offset}`);
  }
  // Typed text with no block around it: Firefox lost its letter on a real fold and unfold.
  await saveOpening(page, noteId, `Elm tree${LONG_TAIL}`);
  for (const step of ['fold', 'unfold', 'fold', 'unfold']) {
    const box = await page.evaluate(index => {
      const note = document.querySelectorAll('#notes-container > .note')[index];
      note.scrollIntoView({block: 'center'});
      const {left, top, width, height} = note.querySelector(':scope > .note-collapse-toggle').getBoundingClientRect();
      return {x: left + width / 2, y: top + height / 2};
    }, OPENING_NOTE);
    await page.mouse.click(box.x, box.y);
    await new Promise(resolve => setTimeout(resolve, FOLD_SETTLE_MS));
    const {offset} = await readOpening(page);
    const expected = (step === 'fold' ? FOLDED_INITIAL_SIZE_PX : INITIAL_SIZE_PX) + INITIAL_GAP_PX;
    if (Math.abs(offset - expected) > PIXEL_ROUNDING) failures.push(`after a real ${step}: the second letter is at ${offset}, not ${expected}`);
  }
  // One line with a child, the note that showed the bug: the letter open and small folded.
  await saveOpening(page, noteId, '<div>Elm tree</div>');
  for (const step of ['open', 'fold', 'unfold']) {
    if (step !== 'open') {
      await page.evaluate(index => document.querySelectorAll('#notes-container > .note')[index].querySelector(':scope > .note-collapse-toggle').click(), OPENING_NOTE);
      await new Promise(resolve => setTimeout(resolve, FOLD_SETTLE_MS));
    }
    const {offset} = await readOpening(page);
    const expected = (step === 'fold' ? FOLDED_INITIAL_SIZE_PX : INITIAL_SIZE_PX) + INITIAL_GAP_PX;
    if (Math.abs(offset - expected) > PIXEL_ROUNDING) failures.push(`one line with a child, ${step}: the second letter is at ${offset}, not ${expected}`);
  }
  await page.evaluate(async childId => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNote(childId);
  }, childId);
  await saveOpening(page, noteId, longNote(`<b>${NOTE_TEXTS[OPENING_NOTE]}</b>`));
  const editedHold = await page.evaluate(async index => {
    const note = document.querySelectorAll('#notes-container > .note')[index];
    const {DOMUtils} = await import('/static/js/modules/dom-utils.js');
    DOMUtils.setNoteEditable(note, true);
    const minHeight = getComputedStyle(note.querySelector(':scope > .note-content')).minHeight;
    DOMUtils.setNoteEditable(note, false);
    return minHeight;
  }, OPENING_NOTE);
  if (parseFloat(editedHold) >= INITIAL_SIZE_PX) failures.push(`an edited note holds room for the letter: ${editedHold}`);
  await saveOpening(page, noteId, '<div>Elm tree</div>');
  const oneLine = await readOpening(page);
  if (Math.abs(oneLine.offset - (INITIAL_SIZE_PX + INITIAL_GAP_PX)) > PIXEL_ROUNDING) failures.push(`a one-line note has no big letter: ${oneLine.offset}`);
  await saveOpening(page, noteId, longNote(`<b>${NOTE_TEXTS[OPENING_NOTE]}</b>`));
  assert.deepEqual(failures, []);
}

// The list's own count decides the letters and ornaments, not where the page's window starts.
async function shiftedWindowCase(page) {
  const marks = await page.evaluate(async () => {
    const {ModeContextInstance: ModeContext} = await import('/static/js/modules/mode-manager/mode-context.js');
    const container = document.getElementById('notes-container');
    const settle = async () => {
      const marker = document.createElement('i');
      container.append(marker);
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      marker.remove();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    };
    const window = ModeContext._tabRootWindows[ModeContext._activeTabId];
    window.start = 1;
    await settle();
    const notes = [...container.querySelectorAll(':scope > .note')];
    const shown = {initials: notes.map(note => note.dataset.initial || null), ornaments: notes.map(note => note.dataset.ornament || null)};
    window.start = 0;
    await settle();
    return shown;
  });
  assert.deepEqual(marks.initials.map((value, index) => (value === null ? null : index)).filter(index => index !== null), [3, 7]);
  assert.deepEqual(marks.ornaments, [null, null, '0', null, null, null, '1', null, null]);
}

// Arrows take turns red and blue among the notes that have one: a note with no arrow takes no turn.
async function arrowColourCase(page) {
  const noteId = await page.evaluate(() => document.querySelectorAll('#notes-container > .note')[1].dataset.noteId);
  await saveOneLine(page, noteId, `<div>${NOTE_TEXTS[SECOND_ROOT]}</div>`);
  const colours = await page.evaluate(() => [...document.querySelectorAll('#notes-container > .note')]
    .filter(note => note.dataset.canCollapse === 'true')
    .map(note => getComputedStyle(note.querySelector(':scope > .note-collapse-toggle')).color));
  await saveOneLine(page, noteId, longNote(`<b>${NOTE_TEXTS[SECOND_ROOT]}</b>`));
  assert.ok(colours.length > 2, `there are arrows to compare: ${colours.length}`);
  colours.slice(1).forEach((colour, index) => assert.notEqual(colour, colours[index], `arrows ${index} and ${index + 1} are the same colour`));
}

async function saveOneLine(page, noteId, html) {
  await page.evaluate(async ({noteId, html}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(noteId, html, '');
  }, {noteId, html});
  await reloadApp(page);
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
}

// The text after the letter stands level with the bottom of the painted letter, open and folded.
async function letterBaselineCase(page) {
  const gaps = await page.evaluate(async ({settleMs, letterSize, foldedSize, letterInsetShare}) => {
    const note = document.querySelector('#notes-container > .note');
    const measure = size => {
      const content = note.querySelector(':scope > .note-content');
      const text = document.createTreeWalker(content, NodeFilter.SHOW_TEXT).nextNode();
      const box = (start, end) => {
        const range = document.createRange();
        range.setStart(text, start);
        range.setEnd(text, end);
        return range.getBoundingClientRect();
      };
      const canvas = document.createElement('canvas').getContext('2d');
      const style = getComputedStyle(text.parentElement);
      canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const descent = canvas.measureText('x').fontBoundingBoxDescent;
      const baseline = box(1, 2).bottom - descent;
      const letter = box(0, 1);
      return Math.abs((letter.top + letter.bottom) / 2 + size / 2 - size * letterInsetShare - baseline);
    };
    const toggle = note.querySelector(':scope > .note-collapse-toggle');
    const open = measure(letterSize);
    toggle.click();
    await new Promise(resolve => setTimeout(resolve, settleMs));
    const folded = measure(foldedSize);
    toggle.click();
    await new Promise(resolve => setTimeout(resolve, settleMs));
    return {open, folded};
  }, {settleMs: FOLD_SETTLE_MS, letterSize: INITIAL_SIZE_PX, foldedSize: FOLDED_INITIAL_SIZE_PX, letterInsetShare: LETTER_INSET_SHARE});
  assert.ok(gaps.open <= BASELINE_ALLOWANCE_PX, `open: the letter's bottom is ${gaps.open} px from the text's baseline`);
  assert.ok(gaps.folded <= BASELINE_ALLOWANCE_PX, `folded: the letter's bottom is ${gaps.folded} px from the text's baseline`);
}

// Struck-out words are scribbled over rather than ruled through.
async function scribbleCase(page) {
  const shown = await page.evaluate(() => {
    const content = document.querySelector('#notes-container > .note > .note-content');
    const struck = document.createElement('s');
    struck.textContent = 'struck';
    content.append(struck);
    const style = getComputedStyle(struck);
    const result = {line: style.textDecorationLine, image: style.backgroundImage};
    struck.remove();
    return result;
  });
  assert.equal(shown.line, 'none');
  assert.match(shown.image, /scribble\.svg/);
}

// The script is MetaList's own font, loaded from MetaList, whatever the system has installed.
async function scriptFontCase(page) {
  const font = await page.evaluate(async () => {
    await document.fonts.ready;
    return {
      family: getComputedStyle(document.querySelector('#notes-container > .note > .note-content')).fontFamily,
      isLoaded: [...document.fonts].some(face => face.family.replaceAll('"', '') === 'Eagle Lake' && face.status === 'loaded'),
    };
  });
  assert.match(font.family, /^"?Eagle Lake"?,/);
  assert.equal(font.isLoaded, true);
}

// A root note's text is never smaller than its children's: the skin scales the size the
// Note Layout setting chose, and doesn't replace it for the children alone.
async function rootSizeCase(page) {
  const parentId = await page.evaluate(() => document.querySelector('#notes-container > .note').dataset.noteId);
  const childId = await page.evaluate(async parentId => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const child = await NotesAPI.createChild(parentId, '');
    await NotesAPI.saveNote(child.id, '<div>A child</div>', '');
    return child.id;
  }, parentId);
  await reloadApp(page);
  const sizes = await page.evaluate(({parentId, childId}) => {
    const sizeOf = id => parseFloat(getComputedStyle(document.querySelector(`.note[data-note-id="${id}"] > .note-content`)).fontSize);
    const original = document.body.dataset.topLevelNoteSize;
    const read = setting => {
      document.body.dataset.topLevelNoteSize = setting;
      return {root: sizeOf(parentId), child: sizeOf(childId)};
    };
    const result = {same: read('same'), larger: read('larger')};
    document.body.dataset.topLevelNoteSize = original;
    return result;
  }, {parentId, childId});
  await page.evaluate(async childId => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNote(childId);
  }, childId);
  await reloadApp(page);
  assert.equal(sizes.same.root, sizes.same.child, `same size: root ${sizes.same.root}, child ${sizes.same.child}`);
  assert.ok(sizes.larger.root > sizes.larger.child, `larger: root ${sizes.larger.root}, child ${sizes.larger.child}`);
}

async function skinCases(page) {
  await reloadApp(page);
  const before = await readPage(page);
  assert.deepEqual(before.texts, NOTE_TEXTS);
  assertPlain(before);

  await applyPreference(page, 'pref.theme', 'illuminated');
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
  assertSkinned(await readPage(page));

  await reloadApp(page);
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') !== null);
  assertSkinned(await readPage(page));

  await rootSizeCase(page);
  await scriptFontCase(page);
  await scribbleCase(page);
  await arrowColourCase(page);
  await shiftedWindowCase(page);
  await openingShapeCases(page);
  await letterBaselineCase(page);
  await foldedInitialCase(page);
  await foldedDescenderCase(page);
  await oldEnglishCases(page, before.noteFont);

  await applyPreference(page, 'pref.theme', 'system');
  await page.waitForFunction(() => document.querySelector('#notes-container > .note[data-initial]') === null);
  const after = await readPage(page);
  assertPlain(after);
  assert.equal(after.texts[SWAPPED_NOTE], REAL_WORDS);
}

export async function checkSkin(page) {
  await applyPreference(page, 'pref.animated_transitions', false);
  const ids = await createNotes(page);
  await runThenCleanUp('skin', () => skinCases(page), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
    if (await page.evaluate(() => document.documentElement.getAttribute('data-skin') !== null)) await applyPreference(page, 'pref.theme', 'system');
    await applyPreference(page, 'pref.animated_transitions', true);
  });
}
