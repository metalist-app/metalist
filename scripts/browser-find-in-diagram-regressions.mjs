import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Find (Cmd+F) in Mermaid diagrams (docs/ui/find.md, "Diagrams"; the cases agreed 2026-11-02).
// A diagram is stored as its code and drawn by the browser; find treats it as one stop whose
// code holds the words, on the server and the page alike:
//   1. words in its labels: one stop, in its place; every label holding them lightly marked,
//      the first the current match
//   2. words only in its code: one stop, the diagram outlined as the current match
//   3. the drawing's hidden style text: never found
//   4. a diagram not drawn (invalid, showing its code): the same one stop; the "Invalid Mermaid
//      diagram" badge is never found
//   5. several labels holding the words: still one stop
//   6. a diagram in a folded note: the note opens for this view, as for any match
// Where typing starts (agreed 2026-11-02): an outlined diagram counts as on screen when any part
// of it shows below the find bar (its top edge had decided, so a diagram in plain view whose top
// was behind the bar was skipped and find started on the next note):
//   7. at the top of the list, the first diagram's top behind the bar: find starts on it, nothing
//      scrolls
//   8. only the diagram's bottom shows below the bar: find starts on it, nothing scrolls
//   9. the whole diagram above the bar's bottom: find starts on the next match, nothing scrolls
// And the server never counts more in a note than the page shows (it counted the code's words
// and the page the drawing's, so find stopped on words that were not there).

const WINDOW = {width: 1100, height: 1400};
const REQUESTS_QUIET_MS = 300;
const TYPING_SETTLE_MS = 500;
const SETTLE_MS = 400;
const DRAWN_WAIT_MS = 8000;
const FIXTURE_TAG = 'finddiagramfixture';
const CURRENT_HIGHLIGHT = 'metalist-find-current';
const MARK_HIGHLIGHT = 'metalist-find';
const DRAWN = ['graph TD', '  idea1[Idea] --> Draft', '  Draft --> Review', '  Review -->|changes| Draft', '  Review --> final[Final Draft]'];
const BROKEN = ['graph TD', '  A --> ((( broken'];
const FOLDED = ['Folded diagram holder', 'a second line', '```mermaid', 'graph TD', '  Harbor --> Dock', '```'];
// Below the fixture's notes, so the list scrolls far enough for cases 8 and 9.
const SPACER_LINES = Array.from({length: 60}, (_, index) => `spacer row ${index + 1}`);
// Short enough that the list scrolls; the diagram cases scroll it to exact places.
const SCROLLING_WINDOW = {width: 1100, height: 700};
// How much of the diagram shows below the find bar in case 8, and how far above it it ends in 9.
const SLIVER_PX = 30;
const ABOVE_PX = 10;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function search(page, text) {
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

async function seedNotes(page) {
  return page.evaluate(async ({tag, drawn, broken, folded, spacer}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const lines = list => list.map(line => `<div>${line}</div>`).join('');
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    // createNote puts each note at the top: made bottom-up, they read top-down.
    const spacerNote = await make(lines(spacer), tag);
    const foldedNote = await make(lines(folded), `${tag} @markdown`);
    const brokenNote = await make(lines(broken), `${tag} @mermaid`);
    const drawnNote = await make(lines(drawn), `${tag} @mermaid`);
    await NotesAPI.setCollapsedBulk([drawnNote, brokenNote, spacerNote], false);
    await NotesAPI.setCollapsedBulk([foldedNote], true);
    return {drawn: drawnNote, broken: brokenNote, folded: foldedNote, spacer: spacerNote};
  }, {tag: FIXTURE_TAG, drawn: DRAWN, broken: BROKEN, folded: FOLDED, spacer: SPACER_LINES});
}

async function openFind(page) {
  await page.keyboard.down('Control');
  await page.keyboard.press('f');
  await page.keyboard.up('Control');
  await page.waitForSelector('#find-in-list-bar:not([hidden])');
}

async function typeFind(page, text) {
  await clickAndSelectAll(page, '#find-in-list-input');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(text);
  await pause(TYPING_SETTLE_MS);
  await idle(page);
  await pause(SETTLE_MS);
}

// The bar's count, the current match and where it is, and the marks inside each diagram.
function state(page, ids) {
  return page.evaluate(({ids, currentName, markName}) => {
    const current = CSS.highlights.get(currentName);
    let currentText = null;
    let currentIn = null;
    if (current !== undefined && current.size > 0) {
      const range = [...current][0];
      currentText = range.toString();
      const holder = range.startContainer.parentElement.closest('.meta-mermaid-diagram, .meta-mermaid-source');
      if (holder === null) {
        // In the note's own text, outside any diagram.
        currentIn = 'text';
      } else {
        currentIn = holder.className.split(' ')[0];
      }
    }
    const marks = CSS.highlights.get(markName);
    const marksIn = id => {
      const note = document.querySelector(`.note[data-note-id="${id}"]`);
      if (marks === undefined || note === null) return [];
      return [...marks].filter(range => note.contains(range.startContainer)).map(range => range.toString());
    };
    const outlined = [...document.querySelectorAll('.is-find-current')].map(element => element.closest('.note').dataset.noteId);
    const folded = document.querySelector(`.note[data-note-id="${ids.folded}"]`);
    return {
      count: document.getElementById('find-in-list-count').textContent,
      currentText, currentIn, outlined,
      drawnMarks: marksIn(ids.drawn), brokenMarks: marksIn(ids.broken),
      foldedOpen: folded !== null && !folded.classList.contains('collapsed'),
    };
  }, {ids, currentName: CURRENT_HIGHLIGHT, markName: MARK_HIGHLIGHT});
}

// What the server counts in each note shown open, against what the page can show there.
function countsOverPage(page, text) {
  return page.evaluate(async text => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const {ModeContextInstance: context} = await import('/static/js/modules/mode-manager/mode-context.js');
    const answer = await NotesAPI.findInList({
      tabId: context.activeTabId, search: context.getExecutedSearchQuery(), isUntaggedView: context.isUntaggedView,
      text, fromRootIndex: 0, direction: 'forward',
    });
    return answer.matches.map(match => ({noteId: match.noteId, contentCount: match.contentCount}));
  }, text);
}

async function labelsAreOneStop(page, ids) {
  await typeFind(page, 'draft');
  const shown = await state(page, ids);
  assert.equal(shown.count, '1 of 1', '1, 5: the diagram is one stop, however many labels hold the words');
  assert.equal(shown.currentText, 'Draft', '1: the first label holding them is the current match');
  assert.equal(shown.currentIn, 'meta-mermaid-diagram', '1: in the drawing');
  assert.deepEqual(shown.drawnMarks.sort(), ['Draft', 'Draft'], '1: every label holding them is marked (Draft, Final Draft)');
  assert.deepEqual(shown.outlined, [], '1: no outline when a label shows the words');
}

async function codeOnlyIsOneStop(page, ids) {
  await typeFind(page, 'idea1');
  const shown = await state(page, ids);
  assert.equal(shown.count, '1 of 1', '2: words only in the code are one stop');
  assert.equal(shown.currentText, null, '2: nothing inside the drawing is marked current');
  assert.deepEqual(shown.outlined, [ids.drawn], '2: the diagram is outlined instead');
}

async function styleIsNoText(page, ids) {
  for (const text of ['fill', 'font-family', 'stroke']) {
    await typeFind(page, text);
    const shown = await state(page, ids);
    assert.equal(shown.count, 'No matches', `3: the drawing's style text is never found (${text})`);
    assert.deepEqual(shown.drawnMarks, [], `3: nor marked (${text})`);
  }
}

async function brokenIsOneStop(page, ids) {
  await typeFind(page, 'broken');
  const shown = await state(page, ids);
  assert.equal(shown.count, '1 of 1', '4: a diagram showing its code is one stop');
  assert.equal(shown.currentText, 'broken', '4: its words marked in the code');
  assert.equal(shown.currentIn, 'meta-mermaid-source', '4: in the code shown');
  await typeFind(page, 'invalid mermaid');
  assert.equal((await state(page, ids)).count, 'No matches', '4: the badge is never found');
}

async function foldedOpens(page, ids) {
  await typeFind(page, 'harbor');
  await page.waitForFunction(id => document.querySelector(`.note[data-note-id="${id}"] .meta-mermaid-diagram`) !== null,
    {timeout: DRAWN_WAIT_MS}, ids.folded);
  await idle(page);
  await pause(SETTLE_MS);
  const shown = await state(page, ids);
  assert.equal(shown.count, '1 of 1', '6: one stop');
  assert.equal(shown.foldedOpen, true, '6: the folded note opens for this view');
  assert.equal(shown.currentText, 'Harbor', '6: its label is the current match');
}

async function serverNeverCountsMore(page, ids) {
  const over = [];
  for (const text of ['draft', 'graph', 'td', 'idea', 'review', 'changes', 'fill', 'font', 'e', 'a', 'r', '-->']) {
    for (const match of await countsOverPage(page, text)) {
      const shown = await page.evaluate(async ({noteId, text}) => {
        const note = document.querySelector(`.note[data-note-id="${noteId}"]`);
        if (note === null || note.classList.contains('collapsed')) return null;
        const {pageStopCount} = await import('/static/js/modules/mode-manager/services/find-in-list-service.js');
        return pageStopCount(note, text);
      }, {noteId: match.noteId, text});
      if (shown !== null && match.contentCount > shown) over.push(`${text}: server ${match.contentCount}, page ${shown}`);
    }
  }
  assert.deepEqual(over, [], 'the server never counts more in a note than the page shows');
}

// The find bar's bottom and the drawn diagram's top and bottom, on the screen.
function diagramAndBar(page, ids) {
  return page.evaluate(id => {
    const diagram = document.querySelector(`.note[data-note-id="${id}"] .meta-mermaid-diagram`).getBoundingClientRect();
    const bar = document.getElementById('find-in-list-bar').getBoundingClientRect();
    return {diagramTop: diagram.top, diagramBottom: diagram.bottom, barBottom: bar.bottom, barLeft: bar.left, diagramRight: diagram.right, scrollY: window.scrollY};
  }, ids.drawn);
}

// Find emptied, the list scrolled to scrollY, then the text typed: where find starts.
async function startAt(page, ids, scrollY, text) {
  await typeFind(page, '');
  await page.evaluate(y => window.scrollTo(0, y), scrollY);
  await idle(page);
  const before = await diagramAndBar(page, ids);
  assert.equal(before.scrollY, scrollY, 'the list scrolls to the place the case needs');
  await page.focus('#find-in-list-input');
  await page.keyboard.type(text);
  await pause(TYPING_SETTLE_MS);
  await idle(page);
  await pause(SETTLE_MS);
  return {before, after: await diagramAndBar(page, ids), shown: await state(page, ids)};
}

async function startsOnADiagramBehindTheBar(page, ids) {
  await page.setViewport(SCROLLING_WINDOW);
  await idle(page);
  const top = await startAt(page, ids, 0, 'graph');
  assert.ok(top.before.diagramTop < top.before.barBottom && top.before.diagramRight > top.before.barLeft,
    '7: the case holds: the diagram\'s top is behind the find bar');
  assert.equal(top.shown.count, '1 of 3', '7: find starts on the diagram whose top is behind the bar');
  assert.deepEqual(top.shown.outlined, [ids.drawn], '7: it is outlined');
  assert.equal(top.shown.foldedOpen, false, '7: the folded note stays folded');
  assert.deepEqual([top.after.scrollY, top.after.diagramTop], [0, top.before.diagramTop], '7: nothing scrolls');

  // Only its bottom shows below the bar.
  const sliverY = Math.round(top.before.diagramBottom - top.before.barBottom - SLIVER_PX);
  const sliver = await startAt(page, ids, sliverY, 'graph');
  assert.ok(sliver.before.diagramBottom > sliver.before.barBottom, '8: the case holds: some of the diagram shows below the bar');
  assert.equal(sliver.shown.count, '1 of 3', '8: find starts on the diagram');
  assert.deepEqual(sliver.shown.outlined, [ids.drawn], '8: it is outlined');
  assert.deepEqual([sliver.after.scrollY, sliver.after.diagramTop], [sliverY, sliver.before.diagramTop], '8: nothing scrolls');

  // All of it above the bar's bottom.
  const aboveY = Math.round(top.before.diagramBottom - top.before.barBottom + ABOVE_PX);
  const above = await startAt(page, ids, aboveY, 'graph');
  assert.ok(above.before.diagramBottom < above.before.barBottom, '9: the case holds: none of the diagram shows below the bar');
  assert.equal(above.shown.count, '2 of 3', '9: find starts on the next match');
  assert.equal(above.shown.currentText, 'graph', '9: in the broken diagram\'s code');
  assert.deepEqual(above.shown.outlined, [], '9: the diagram is not outlined');
  assert.equal(above.after.scrollY, aboveY, '9: nothing scrolls');
  await page.setViewport(WINDOW);
  await idle(page);
}

export async function checkFindInDiagrams(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  await runThenCleanUp('find in diagrams', async () => {
    await search(page, FIXTURE_TAG);
    await page.waitForSelector(`.note[data-note-id="${ids.drawn}"] .meta-mermaid-diagram[data-mermaid-state="rendered"]`, {timeout: DRAWN_WAIT_MS});
    await page.waitForSelector(`.note[data-note-id="${ids.broken}"] code[data-mermaid-state="invalid"]`, {timeout: DRAWN_WAIT_MS});
    await idle(page);
    await attempt('server and page agree', () => serverNeverCountsMore(page, ids));
    await openFind(page);
    await attempt('1, 5 labels', () => labelsAreOneStop(page, ids));
    await attempt('2 code only', () => codeOnlyIsOneStop(page, ids));
    await attempt('3 style text', () => styleIsNoText(page, ids));
    await attempt('4 a diagram showing its code', () => brokenIsOneStop(page, ids));
    await attempt('6 a folded note', () => foldedOpens(page, ids));
    await attempt('7-9 where typing starts', () => startsOnADiagramBehindTheBar(page, ids));
    assert.deepEqual(failures, []);
  }, async () => {
    await page.keyboard.press('Escape');
    await search(page, '');
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of Object.values(ids)) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
