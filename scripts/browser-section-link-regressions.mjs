import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Links to a place in a note, `[[note#words]]` (docs/ui/references.md, "Links to a place in a
// note"; agreed with the maintainer, 2026-11-21):
// - with no text of its own the link reads its note's first line, " > " and the words, each by
//   its first part;
// - following it opens the note's page with the words in view and marked, and no find bar; the
//   mark goes at the first wheel or key; words in a folded note are reached as find reaches them,
//   and the note folds back when the mark goes; words that are gone open the note at its top;
// - after `[[`, a note's name and `#`, the list offers that note's lines, narrowed by the letters
//   typed; choosing one writes the link; `![[` offers none.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
const LIST_WAIT_MS = 5000;
const FILLER_LINES = 40;
const TRIP = 'Sectionlink trip plan';
const CURRENT_MARK = 'metalist-find-current';
const OTHER_MARKS = 'metalist-find';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function makeNotes(page) {
  return page.evaluate(async (tripLine, fillerLines) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const filler = Array.from({length: fillerLines}, (_, index) => `<div>Filler line ${index + 1} of the trip</div>`).join('');
    const trip = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(trip.id, `<div>${tripLine}</div>${filler}<div>Day 3: Porto</div><div>Bridge walk at dusk</div>`, '');
    const folded = await NotesAPI.createChild(trip.id, '');
    await NotesAPI.saveNote(folded.id, '<div>Hidden stops</div><div>Secret harbour cafe</div>', '');
    await NotesAPI.collapseNote(folded.id);
    const long = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(long.id, '<div>galleries are confusing. the icons should be swapped</div><div>only some pdfs displayed? also, galleries do not show</div>', '');
    const host = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(host.id, [
      `<div>Sectionlink host</div>`,
      `<div>[[${trip.id}#Day 3]]</div>`,
      `<div>[[${trip.id}#bridge walk|the bridge]]</div>`,
      `<div>[[${trip.id}#No such words]]</div>`,
      `<div>[[${trip.id}#Secret harbour]]</div>`,
      `<div>[[${long.id}#only some pdfs displayed? also, galleries do not show]]</div>`,
    ].join(''), '');
    const typed = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(typed.id, '<div>Sectionlink typing</div>', '');
    return {trip: trip.id, folded: folded.id, long: long.id, host: host.id, typed: typed.id};
  }, TRIP, FILLER_LINES);
}

function linkSelector(ids, words) {
  return `.note[data-note-id="${ids.host}"] .note-reference-block[data-ref-section="${words}"] .note-reference-link`;
}

// What find has marked: the current match's words and whether they are wholly in the window,
// how many other marks there are, and whether the find bar shows.
function marked(page) {
  return page.evaluate((currentName, othersName) => {
    let ranges = [];
    if (CSS.highlights.has(currentName)) ranges = [...CSS.highlights.get(currentName)];
    let others = 0;
    if (CSS.highlights.has(othersName)) others = CSS.highlights.get(othersName).size;
    const bar = document.getElementById('find-in-list-bar');
    return {
      words: ranges.map(range => range.toString()),
      // Find brings a match below the window to its bottom edge: there Firefox gives the words'
      // bottom a fraction of a pixel past the edge (777..800.x of 800), so each edge is taken
      // to its whole pixel.
      inView: ranges.every((range) => {
        const box = range.getBoundingClientRect();
        return Math.round(box.top) >= 0 && Math.round(box.bottom) <= window.innerHeight;
      }),
      others,
      // Where the words are, for a failure's message.
      boxes: ranges.map((range) => {
        const box = range.getBoundingClientRect();
        return `${Math.round(box.top)}..${Math.round(box.bottom)} of ${window.innerHeight}`;
      }),
      isBarShown: bar !== null && !bar.hidden,
      scrollY: Math.round(window.scrollY),
    };
  }, CURRENT_MARK, OTHER_MARKS);
}

async function follow(page, ids, words) {
  await page.click(linkSelector(ids, words));
  await page.waitForSelector('#reference-view-chip-back', {visible: true});
  await idle(page);
}

async function back(page, ids) {
  await page.click('#reference-view-chip-back');
  await page.waitForSelector(`.note[data-note-id="${ids.host}"]`, {visible: true});
  await idle(page);
}

async function labels(page, ids) {
  const shown = await page.$$eval(`.note[data-note-id="${ids.host}"] .note-reference-link`, links => links.map(link => link.textContent.trim()));
  assert.deepEqual(shown, [
    `${TRIP} > Day 3`, 'the bridge', `${TRIP} > No such words`, `${TRIP} > Secret harbour`,
    'galleries are confusing > only some pdfs displayed?',
  ], 'each link reads its note then the words, by their first part, or its own text');
}

async function followedWordsAreMarkedUntilTheNextMove(page, ids) {
  await follow(page, ids, 'Day 3');
  const first = await marked(page);
  assert.deepEqual({words: first.words, inView: first.inView ? true : `${first.boxes.join(', ')}, scrolled ${first.scrollY}`, others: first.others, isBarShown: first.isBarShown},
    {words: ['Day 3'], inView: true, others: 0, isBarShown: false},
    `the words are in view and marked alone, with no find bar (words at ${first.boxes.join(', ')}, scrolled ${first.scrollY})`);
  assert.ok((await marked(page)).scrollY > 0, 'the page moved to bring the words into view');
  await page.mouse.move(WINDOW.width / 2, WINDOW.height / 2);
  await page.mouse.wheel({deltaY: 40});
  await idle(page);
  assert.deepEqual((await marked(page)).words, [], 'the mark goes at the first wheel');
  await back(page, ids);

  // Capitals are ignored, and a key press takes the mark away too.
  await follow(page, ids, 'bridge walk');
  assert.deepEqual((await marked(page)).words, ['Bridge walk']);
  await page.keyboard.press('Shift');
  await idle(page);
  assert.deepEqual((await marked(page)).words, [], 'the mark goes at the first key');
  await back(page, ids);
}

async function wordsThatAreGoneOpenTheNoteAtItsTop(page, ids) {
  await follow(page, ids, 'No such words');
  const shown = await marked(page);
  assert.deepEqual({words: shown.words, scrollY: shown.scrollY, isBarShown: shown.isBarShown},
    {words: [], scrollY: 0, isBarShown: false}, 'words that are gone: the note at its top, nothing marked');
  assert.equal(await page.$('.error-overlay, #error-overlay'), null, 'and no error');
  await back(page, ids);
}

function isFoldedShown(page, ids) {
  return page.$eval(`.note[data-note-id="${ids.folded}"]`, note => note.classList.contains('collapsed'));
}

async function wordsInAFoldedNoteAreReachedAndItFoldsBack(page, ids) {
  await follow(page, ids, 'Secret harbour');
  const shown = await marked(page);
  assert.deepEqual({words: shown.words, inView: shown.inView}, {words: ['Secret harbour'], inView: true},
    'words in a folded note are shown and marked');
  await page.keyboard.press('Shift');
  await idle(page);
  assert.deepEqual((await marked(page)).words, []);
  assert.equal(await isFoldedShown(page, ids), true, 'the note find opened is folded again once the mark goes');
  await back(page, ids);
}

function listRows(page) {
  return page.$$eval('.reference-suggestions .reference-suggestion', rows => rows.map(row => row.textContent));
}

async function theListOffersANotesLines(page, ids) {
  const content = `.note[data-note-id="${ids.typed}"] > .note-content`;
  await page.click(content);
  await page.waitForFunction(selector => document.querySelector(selector).isContentEditable, {}, content);
  await page.keyboard.press('End');
  await page.keyboard.type(` [[${TRIP}#`);
  await page.waitForSelector('.reference-suggestions .reference-suggestion-line', {timeout: LIST_WAIT_MS});
  assert.ok((await listRows(page)).every(row => row.endsWith(TRIP)), 'after # every row is a line of that note');
  await page.keyboard.type('por');
  await page.waitForFunction(() => document.querySelectorAll('.reference-suggestions .reference-suggestion').length === 1, {timeout: LIST_WAIT_MS});
  assert.deepEqual(await listRows(page), [`Day 3: Porto${TRIP}`], 'letters after the # narrow the lines');
  await page.keyboard.press('Enter');
  await pause(SETTLE_MS);
  assert.equal(await page.$eval(content, node => node.innerText.trim()), `Sectionlink typing [[${ids.trip}#Day 3: Porto]]`,
    'choosing a line writes the link and closes it');
  // An embed shows its whole note: `![[` offers no lines.
  await page.keyboard.type(` ![[${TRIP}#`);
  await pause(LIST_WAIT_MS / 2);
  assert.deepEqual(await listRows(page), [], 'an embed is offered no lines');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await idle(page);
}

export async function checkSectionLinks(page) {
  await page.setViewport(WINDOW);
  const ids = await makeNotes(page);
  await runThenCleanUp('section links', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    await labels(page, ids);
    await followedWordsAreMarkedUntilTheNextMove(page, ids);
    await wordsThatAreGoneOpenTheNoteAtItsTop(page, ids);
    await wordsInAFoldedNoteAreReachedAndItFoldsBack(page, ids);
    await theListOffersANotesLines(page, ids);
  }, async () => {
    await page.evaluate(async noteIds => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of noteIds) await NotesAPI.deleteNote(id);
    }, [ids.host, ids.typed, ids.long, ids.trip]);
    await idle(page);
  });
}
