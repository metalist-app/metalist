import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import {clickAndSelectAll} from './browser-select-field.mjs';

// Reference pages (docs/ready-to-build/reference-cards.md, §1, §2 and §10). Following a reference,
// an embed's reference icon or an AI answer's references turns to a page: the column slides as one
// piece, left going deeper and right coming back; the search box fades out and the black bar shows
// arrows in its middle, only those that can act (◀ always, ⏮ from the second page, ▶ after going
// back), each kept in its place. ◀ or Escape goes back a page, ⏮ to the search, ▶ forward again,
// each to the exact place left. A page shows its linked notes as roots. Each search context keeps
// its page: its row reads `refview > Source note`, choosing it returns there, and a reload brings it
// back. Deleting the linked note closes the page. Sort orders and Untagged show as chips inside the
// input. One check per agreed case, positions compared exactly. Notes are put in place with the
// mouse wheel, as a person scrolls.

const SETTLE_MS = 300;
// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
const SEARCH = 'refview';
const FILLERS_ABOVE = 10;
const FILLERS_BELOW = 14;
const TARGET_CHILDREN = 24;
// The target's child that links on to the second target, far enough down to need a scroll.
const LINKING_CHILD_INDEX = 16;
// Where a note is brought on screen, with the wheel, before a reference is followed from it.
const NOTE_TOP_BEFORE_FOLLOWING_PX = 320;
const TARGET_TITLE = 'Reference view target whose first line runs long enough that a chip would cut it short';
const SECOND_TITLE = 'Second reference target';
const THIRD_TITLE = 'Third reference target';
// The target's child that links to the target itself.
const SELF_LINKING_CHILD_INDEX = 2;
const SOURCE_LABEL = 'Source note';
// The target's child linking to the third target: a link on the target's page other than the first.
const THIRD_LINKING_CHILD_INDEX = 18;
// The target's child a link elsewhere points at: a page of a note that has a parent.
const LINKED_CHILD_INDEX = 6;
const DOOMED_TITLE = 'Reference target deleted while its page is open';
const SLIDE_MS = 250;
const REDUCED_MOTION_FADE_MS = 120;
// Firefox lays out at 1/60 px (Chrome at 1/64); centers computed from two boxes can
// differ by one layout unit and no more.
const LAYOUT_UNIT_PX = 1 / 60;
// The sort and Untagged chips end this far inside the input's right edge (main.css).
const INPUT_CHIPS_INSET_PX = 4;
// The input's own right padding, before the chips' width is added (main.css).
const INPUT_RIGHT_PADDING_PX = 12;
const HALF = 0.5;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function createNotes(page) {
  return page.evaluate(async ({search, fillersAbove, fillersBelow, targetChildren, linkingChildIndex, selfLinkingChildIndex,
    thirdLinkingChildIndex, linkedChildIndex, targetTitle, secondTitle, thirdTitle, doomedTitle}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {fillers: [], children: []};
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    // createNote(null, '') inserts at the top, so the list is built bottom-up.
    for (let index = fillersBelow; index >= 1; index -= 1) {
      ids.fillers.push(await make(`<p>Reference view filler below ${index}</p><p>second line</p><p>third line</p>`, search));
    }
    ids.second = await make(`<p>${secondTitle}</p><p>its second line</p>`, 'refother');
    ids.target = await make(`<p>${targetTitle}</p><p>the target's second line</p>`, search);
    for (let index = 1; index <= targetChildren; index += 1) {
      const child = await NotesAPI.createChild(ids.target, '');
      let html = `<p>Target child ${index}</p><p>second line</p><p>third line</p>`;
      if (index === linkingChildIndex) html = `<p>Target child ${index} links to [[${ids.second}]] in its text</p><p>more</p>`;
      if (index === selfLinkingChildIndex) html = `<p>Target child ${index} links to [[${ids.target}]], its parent</p><p>more</p>`;
      await NotesAPI.saveNote(child.id, html, '');
      ids.children.push(child.id);
      if (index === linkingChildIndex) ids.linkingChild = child.id;
      if (index === selfLinkingChildIndex) ids.selfLinkingChild = child.id;
    }
    // The second note links back to the target and on to a third, which links back too.
    ids.third = await make(`<p>${thirdTitle}</p><p>back to [[${ids.target}]]</p>`, 'refother');
    await NotesAPI.saveNote(ids.second, `<p>${secondTitle}</p><p>back to [[${ids.target}]], on to [[${ids.third}]]</p>`, 'refother');
    ids.thirdLinkingChild = ids.children[thirdLinkingChildIndex - 1];
    await NotesAPI.saveNote(ids.thirdLinkingChild, `<p>Target child ${thirdLinkingChildIndex} links to [[${ids.third}]]</p>`, '');
    ids.linkedChild = ids.children[linkedChildIndex - 1];
    ids.doomed = await make(`<p>${doomedTitle}</p><p>its second line</p>`, 'refother');
    ids.doomHolder = await make(`<p>Links to [[${ids.doomed}]], which gets deleted</p>`, search);
    ids.childHolder = await make(`<p>Links to [[${ids.linkedChild}]], a child</p>`, search);
    ids.holder = await make(`<p>Holder links to [[${ids.target}]] in its text</p><p>second line</p>`, search);
    for (let index = fillersAbove; index >= 1; index -= 1) {
      ids.fillers.push(await make(`<p>Reference view filler above ${index}</p><p>second line</p><p>third line</p>`, search));
    }
    return ids;
  }, {search: SEARCH, fillersAbove: FILLERS_ABOVE, fillersBelow: FILLERS_BELOW, targetChildren: TARGET_CHILDREN,
    linkingChildIndex: LINKING_CHILD_INDEX, selfLinkingChildIndex: SELF_LINKING_CHILD_INDEX,
    thirdLinkingChildIndex: THIRD_LINKING_CHILD_INDEX, linkedChildIndex: LINKED_CHILD_INDEX, targetTitle: TARGET_TITLE,
    secondTitle: SECOND_TITLE, thirdTitle: THIRD_TITLE, doomedTitle: DOOMED_TITLE});
}

// Records, in the page, every reference transition the moment it plays: the column
// animations, the bar's state and the input's text. Survives reloads.
async function installTransitionRecorder(page) {
  const recorder = () => {
    window.__referenceTransitions = [];
    const record = () => {
      const state = document.documentElement.dataset.referenceTransition;
      if (state === undefined) return;
      // A slide's keyframes move (transform); a Reduce Motion fade's change opacity.
      const describeFrame = frame => (Object.hasOwn(frame, 'transform')
        ? {transform: frame.transform} : {opacity: Number(frame.opacity)});
      const describe = element => element.getAnimations()
        .filter(animation => animation.constructor.name === 'Animation')
        .map(animation => ({
          keyframes: animation.effect.getKeyframes().map(describeFrame),
          duration: animation.effect.getTiming().duration,
        }));
      const row = document.querySelector('.controls .search-input-row');
      // Without motion there is no copy of the old column, and nothing slides.
      const ghost = document.querySelector('.reference-slide-ghost');
      const ghostAnimations = [];
      if (ghost !== null) ghostAnimations.push(...describe(ghost));
      // How far the still copy draws each note on screen from where the live column drew
      // it, the moment the copy covers the column (agreed 2026-10-31: it was 2 px lower).
      const ghostOffsets = [];
      if (state === 'pending' && ghost !== null) {
        const liveNotes = [...document.querySelectorAll('#notes-container .note')];
        const copies = [...ghost.querySelectorAll('.note')];
        liveNotes.forEach((note, index) => {
          const live = note.getBoundingClientRect();
          if (live.bottom < 0 || live.top > window.innerHeight) return;
          const copy = copies[index].getBoundingClientRect();
          ghostOffsets.push({top: copy.top - live.top, left: copy.left - live.left});
        });
      }
      window.__referenceTransitions.push({
        state,
        ghost: ghostAnimations,
        hasGhost: ghost !== null,
        ghostOffsets,
        column: describe(document.getElementById('notes-container')),
        isChipAnimating: row.classList.contains('is-chip-animating'),
        isChipShown: document.getElementById('reference-source-indicator').classList.contains('is-shown'),
        inputValue: document.getElementById('search-input').value,
        windowWidth: window.innerWidth,
      });
    };
    new MutationObserver(record).observe(document, {
      attributes: true, subtree: true, attributeFilter: ['data-reference-transition'],
    });
  };
  await page.evaluateOnNewDocument(recorder);
  await page.evaluate(recorder);
}

async function transitionCount(page) {
  return page.evaluate(() => window.__referenceTransitions.length);
}

// Runs the action, waits for the reference transition it starts to finish, and returns
// what was recorded as it played.
async function navigate(page, action) {
  const before = await transitionCount(page);
  await action();
  await page.waitForFunction(count => window.__referenceTransitions.length > count
      && document.documentElement.dataset.referenceTransition === undefined
      && document.querySelector('.reference-slide-ghost') === null,
  {}, before);
  await idle(page);
  const records = await page.evaluate(count => window.__referenceTransitions.slice(count), before);
  const playing = records.filter(record => record.state === 'playing');
  assert.equal(playing.length, 1, 'one transition played');
  expectCopyInPlace(records.filter(record => record.state === 'pending'));
  return playing[0];
}

// Before it slides, the still copy of the column shows every note exactly where the live
// column showed it: going deeper and coming back, scrolled or not.
function expectCopyInPlace(pending) {
  assert.equal(pending.length, 1, 'one transition began');
  // Without motion (or with Reduce Motion's fade) there is no copy.
  if (!pending[0].hasGhost) return;
  assert.ok(pending[0].ghostOffsets.length > 0, 'the copy covers notes on screen');
  for (const offset of pending[0].ghostOffsets) {
    expectSameSpot(offset.top, 0, 'the still copy shows each note at its height');
    expectSameSpot(offset.left, 0, 'the still copy shows each note at its side');
  }
}

function expectSlide(record, direction, label) {
  const width = record.windowWidth;
  const outgoing = direction === 'forward' ? -width : width;
  assert.deepEqual(record.ghost, [{keyframes: [{transform: 'translateX(0px)'}, {transform: `translateX(${outgoing}px)`}],
    duration: SLIDE_MS}], `${label}: the old column slides ${direction === 'forward' ? 'left' : 'right'} as one piece`);
  assert.deepEqual(record.column, [{keyframes: [{transform: `translateX(${-outgoing}px)`}, {transform: 'translateX(0px)'}],
    duration: SLIDE_MS}], `${label}: the new column slides in from the ${direction === 'forward' ? 'right' : 'left'}`);
}

function expectSameSpot(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) <= LAYOUT_UNIT_PX, `${label}: ${actual} is ${expected}`);
}

// Types the search and lets it run; never Enter, which on a search already run adds a note.
async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  await page.keyboard.type(query);
  await idle(page);
}

async function notePlace(page, noteId) {
  return page.evaluate(noteId => {
    const note = document.querySelector(`#notes-container .note[data-note-id="${noteId}"]`);
    return {scrollY: window.scrollY, top: note.getBoundingClientRect().top};
  }, noteId);
}

// Brings the note near the given height with the mouse wheel, as a person scrolls,
// and returns exactly where it ended up.
async function wheelNoteTo(page, noteId, top) {
  const {top: current} = await notePlace(page, noteId);
  const viewport = page.viewport();
  await page.mouse.move(viewport.width * HALF, viewport.height * HALF);
  await page.mouse.wheel({deltaY: Math.round(current - top)});
  await page.waitForFunction(() => new Promise(resolve => {
    const y = window.scrollY;
    requestAnimationFrame(() => requestAnimationFrame(() => resolve(window.scrollY === y)));
  }));
  await idle(page);
  return notePlace(page, noteId);
}

async function clickReferenceLink(page, holderId, targetId) {
  await page.click(`#notes-container .note[data-note-id="${holderId}"] > .note-content `
    + `.note-reference-link[data-ref-note-id="${targetId}"] .note-reference-link-title`);
}

// The bar, the column and the view as they are now.
async function barState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {isViewingReferenceSource} = await import('/static/js/modules/mode-manager/services/reference-source-navigation-service.js');
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, right: rect.right, width: rect.width, height: rect.height,
        centerX: rect.left + rect.width / 2, centerY: rect.top + rect.height / 2};
    };
    // An arrow shows when it can act; one that can't keeps its place, hidden.
    const arrow = id => {
      const element = document.getElementById(id);
      return {
        shown: !element.classList.contains('is-unavailable') && getComputedStyle(element).visibility === 'visible'
          && getComputedStyle(element).display !== 'none',
        title: element.getAttribute('title'),
        box: box(element),
      };
    };
    const chip = document.getElementById('reference-source-indicator');
    const label = document.getElementById('reference-source-indicator-label');
    const input = document.getElementById('search-input');
    const row = document.querySelector('.controls .search-input-row');
    const column = document.getElementById('notes-container');
    const roots = [...column.children].filter(node => node.matches('.note[data-note-id]'))
      .map(node => node.dataset.noteId);
    return {
      isReferenceView: isViewingReferenceSource(),
      searchQuery: mode.searchQuery,
      tabCount: mode.tabOrder.length,
      activeTabId: mode.activeTabId,
      chipShown: chip.classList.contains('is-shown'),
      chipVisibility: getComputedStyle(chip).visibility,
      chipOpacity: getComputedStyle(chip).opacity,
      // The page's kind, read by screen readers; not drawn (a fixed-width slot keeps the arrows' places).
      label: label.textContent,
      labelWidth: label.getBoundingClientRect().width,
      toSearch: arrow('reference-source-indicator-clear'),
      back: arrow('reference-view-chip-back'),
      forward: arrow('reference-view-chip-forward'),
      inputValue: input.value,
      inputOpacity: getComputedStyle(input).opacity,
      inputVisibility: getComputedStyle(input).visibility,
      inputFocused: document.activeElement === input,
      input: box(input),
      row: box(row),
      rowAnimating: row.classList.contains('is-chip-animating'),
      column: box(column),
      columnTransform: getComputedStyle(column).transform,
      columnVisibility: getComputedStyle(column).visibility,
      ghosts: document.querySelectorAll('.reference-slide-ghost').length,
      isSliding: document.documentElement.classList.contains('reference-sliding'),
      roots,
      greyBars: column.querySelectorAll('.note.search-redacted, .note[data-search-redacted="true"]').length,
      scrollY: window.scrollY,
    };
  });
}

function expectSettled(state, label) {
  assert.equal(state.ghosts, 0, `${label}: the old column's copy is gone`);
  assert.equal(state.isSliding, false, `${label}: the page no longer clips the slide`);
  assert.equal(state.columnTransform, 'none', `${label}: the column is back in place`);
  assert.equal(state.columnVisibility, 'visible', `${label}: the column is visible`);
  assert.equal(state.rowAnimating, false, `${label}: the bar is no longer animating`);
}

// Where the arrows sit on the first page: every later page has them at exactly these places.
let arrowPlaces = null;

// A reference page's bar: only the arrows that can act (⏮ from the second page, ▶ after going
// back), each in its place, the gap between ◀ and ▶ on the bar's middle; no search shown.
function expectReferenceBar(state, expected, label) {
  assert.equal(state.isReferenceView, true, `${label}: a reference page`);
  assert.equal(state.chipShown, true, `${label}: the arrows show`);
  assert.equal(state.chipVisibility, 'visible', `${label}: the arrows are visible`);
  assert.equal(state.chipOpacity, '1', `${label}: the arrows have faded in`);
  assert.equal(state.label, expected.kind, `${label}: the page's kind, for screen readers`);
  assert.ok(state.labelWidth <= 1, `${label}: no words between the arrows`);
  assert.equal(state.back.shown, true, `${label}: ◀ shows on every page`);
  assert.equal(state.toSearch.shown, expected.depth > 1, `${label}: ⏮ ${expected.depth > 1 ? 'shows' : 'hides'} on page ${expected.depth}`);
  assert.equal(state.forward.shown, expected.hasForward, `${label}: ▶ ${expected.hasForward ? 'shows after going back' : 'hides'}`);
  assert.deepEqual([state.toSearch.title, state.back.title, state.forward.title], ['Back to your search', 'Back', 'Forward'],
    `${label}: each arrow says where it goes`);
  expectSameSpot((state.back.box.right + state.forward.box.left) / 2, state.row.centerX,
    `${label}: the gap between ◀ and ▶ is on the bar's middle`);
  const places = {toSearch: state.toSearch.box.left, back: state.back.box.left, forward: state.forward.box.left};
  if (arrowPlaces === null) arrowPlaces = places;
  for (const name of Object.keys(places)) {
    expectSameSpot(places[name], arrowPlaces[name], `${label}: the ${name} arrow keeps its place`);
  }
  assert.equal(state.inputOpacity, '0', `${label}: the search input is faded out`);
  assert.equal(state.inputVisibility, 'hidden', `${label}: the search input takes no clicks`);
  assert.equal(state.inputValue, '', `${label}: the hidden input is empty, never a note ID`);
  assert.equal(state.greyBars, 0, `${label}: no grey bars for notes beside the linked ones`);
  expectSettled(state, label);
}

const SOURCE_PAGE = {kind: SOURCE_LABEL, depth: 1, hasForward: false};

function expectSearchBar(state, query, label) {
  assert.equal(state.isReferenceView, false, `${label}: back at the search`);
  assert.equal(state.searchQuery, query, `${label}: the search is the one the user typed`);
  assert.equal(state.chipShown, false, `${label}: no arrows`);
  assert.equal(state.chipVisibility, 'hidden', `${label}: the arrows are gone`);
  assert.equal(state.inputValue, query, `${label}: the input shows the search`);
  assert.equal(state.inputOpacity, '1', `${label}: the input has faded back in`);
  assert.equal(state.inputVisibility, 'visible', `${label}: the input is visible`);
  expectSettled(state, label);
}

async function setAnimatedTransitions(page, isOn) {
  await page.evaluate(async isOn => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.animated_transitions', isOn);
  }, isOn);
}

async function setSortMode(page, sortMode) {
  await page.evaluate(async sortMode => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setSortMode(sortMode);
  }, sortMode);
  await idle(page);
}

async function setUntagged(page, isUntagged) {
  await page.evaluate(async isUntagged => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.setIsUntaggedView(isUntagged);
  }, isUntagged);
  await idle(page);
}

// Stands in for an AI answer's references (an AI provider is not set up in tests):
// the same markup the answer renders, fixed at the window's bottom left.
async function addAiReference(page, id, html) {
  await page.evaluate(({id, html}) => {
    document.getElementById(id)?.remove();
    const holder = document.createElement('div');
    holder.id = id;
    holder.className = 'ai-chat-message-content';
    holder.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:20000;background:#fff;padding:4px';
    holder.innerHTML = html;
    document.body.append(holder);
  }, {id, html});
}

// The list of search contexts, as it lists them: a context on a page names the page's kind.
async function contextRows(page) {
  return page.evaluate(async () => {
    const {updateSearchContextsList} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    updateSearchContextsList();
    return [...document.querySelectorAll('#search-contexts-list .tab-context-item')].map(item => ({
      tabId: item.dataset.tabId,
      label: item.querySelector('.tab-context-query').textContent,
      isActive: item.classList.contains('is-active'),
    }));
  });
}

// Whether the context's row offers − (close): the only context listed never does (it offered it
// while on a page, counting the pages' hidden tabs, and closed the page instead; 2026-11-14).
async function rowOffersClose(page, tabId) {
  await contextRows(page);
  return page.$eval(`#search-contexts-list .tab-context-item[data-tab-id="${tabId}"] .delete-context`,
    button => !button.classList.contains('is-hidden'));
}

async function clickContextRow(page, tabId) {
  const zone = await (await page.$('#tab-hover-zone')).boundingBox();
  await page.mouse.move(zone.x + zone.width * HALF, zone.y + zone.height * HALF);
  const item = `#search-contexts-list .tab-context-item[data-tab-id="${tabId}"] .tab-context-query`;
  await page.waitForSelector(item, {visible: true});
  await pause(SETTLE_MS);
  await page.click(item);
  await idle(page);
}

// §10 case 1: a reference followed from the search, landing where it always has, the linked
// note the page's one root.
async function checkFollowFromSearch(page, ids) {
  await setAnimatedTransitions(page, false);
  const stillLeft = await wheelNoteTo(page, ids.holder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await clickReferenceLink(page, ids.holder, ids.target);
  await page.waitForFunction(() => document.getElementById('reference-source-indicator').classList.contains('is-shown'));
  await idle(page);
  const stillLanding = await notePlace(page, ids.target);
  await page.click('#reference-view-chip-back');
  await page.waitForFunction(() => !document.getElementById('reference-source-indicator').classList.contains('is-shown'));
  await idle(page);
  assert.deepEqual(await notePlace(page, ids.holder), stillLeft, 'with no motion, ◀ returns to the exact place');
  await setAnimatedTransitions(page, true);

  const left = await wheelNoteTo(page, ids.holder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  const before = await barState(page);
  const played = await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  expectSlide(played, 'forward', 'follow from the search');
  assert.equal(played.isChipShown, true, 'follow from the search: the arrows appear with the slide');
  assert.equal(played.inputValue, SEARCH, 'follow from the search: the input fades out with its text');
  const after = await barState(page);
  expectReferenceBar(after, SOURCE_PAGE, 'follow from the search');
  assert.deepEqual(after.roots, [ids.target], 'the page shows the linked note as its root');
  assert.deepEqual(await notePlace(page, ids.target), stillLanding, 'the target lands where it always has');
  assert.equal(after.column.left, before.column.left, 'the column ends where it was, side to side');
  return left;
}

// ◀ from the first page: back to the search, where the user left it.
async function checkBackToSearch(page, ids, left, label) {
  const played = await navigate(page, () => page.click('#reference-view-chip-back'));
  expectSlide(played, 'back', label);
  assert.equal(played.inputValue, SEARCH, `${label}: the input fades in with its text`);
  const after = await barState(page);
  expectSearchBar(after, SEARCH, label);
  assert.deepEqual(await notePlace(page, ids.holder), left, `${label}: the search is at the exact place the user left it`);
  return after;
}

// A link to a note that has a parent: the page shows that note as a root, with nothing above it.
async function checkLinkedChildIsARoot(page, ids) {
  const left = await wheelNoteTo(page, ids.childHolder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await navigate(page, () => clickReferenceLink(page, ids.childHolder, ids.linkedChild));
  const shown = await barState(page);
  expectReferenceBar(shown, SOURCE_PAGE, 'a link to a child');
  assert.deepEqual(shown.roots, [ids.linkedChild], 'a linked child is the page\'s root, without its parent');
  await navigate(page, () => page.click('#reference-view-chip-back'));
  assert.deepEqual(await notePlace(page, ids.childHolder), left, 'back where the link was followed');
}

// §10 cases 2–6: deeper, back (◀ and Escape), forward (▶), a new link drops the way forward,
// and ⏮ from two pages down.
async function checkPath(page, ids) {
  const left = await wheelNoteTo(page, ids.holder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  const searchTabs = (await barState(page)).tabCount;
  await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  const atLink = await wheelNoteTo(page, ids.linkingChild, NOTE_TOP_BEFORE_FOLLOWING_PX);
  assert.ok(atLink.scrollY > 0, 'the linking child is far enough down to need a scroll');

  // Case 2: following again slides left once more; ⏮ appears.
  const deeper = await navigate(page, () => clickReferenceLink(page, ids.linkingChild, ids.second));
  expectSlide(deeper, 'forward', 'follow again');
  const second = await barState(page);
  expectReferenceBar(second, {...SOURCE_PAGE, depth: 2}, 'follow again');
  assert.deepEqual(second.roots, [ids.second], 'the second page shows the second target');
  const secondLeft = await wheelNoteTo(page, ids.second, NOTE_TOP_BEFORE_FOLLOWING_PX);

  // Case 3: ◀ goes back one page, to the exact place; ▶ appears.
  const backed = await navigate(page, () => page.click('#reference-view-chip-back'));
  expectSlide(backed, 'back', '◀');
  expectReferenceBar(await barState(page), {...SOURCE_PAGE, hasForward: true}, '◀');
  assert.deepEqual(await notePlace(page, ids.linkingChild), atLink, '◀: exactly where the user left the first page');

  // Case 5: ▶ goes forward to the page come back from, as it was left; then nothing is forward.
  const forward = await navigate(page, () => page.click('#reference-view-chip-forward'));
  expectSlide(forward, 'forward', '▶');
  expectReferenceBar(await barState(page), {...SOURCE_PAGE, depth: 2}, '▶');
  assert.deepEqual(await notePlace(page, ids.second), secondLeft, '▶: exactly where the user left the second page');

  // Case 3: Escape (not editing, no dialog) goes back too.
  const escaped = await navigate(page, () => page.keyboard.press('Escape'));
  expectSlide(escaped, 'back', 'Escape');
  expectReferenceBar(await barState(page), {...SOURCE_PAGE, hasForward: true}, 'Escape');
  assert.deepEqual(await notePlace(page, ids.linkingChild), atLink, 'Escape: exactly where the user left the first page');

  // Case 6: following another reference drops what was forward.
  await wheelNoteTo(page, ids.thirdLinkingChild, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await navigate(page, () => clickReferenceLink(page, ids.thirdLinkingChild, ids.third));
  const third = await barState(page);
  expectReferenceBar(third, {...SOURCE_PAGE, depth: 2}, 'a new link after going back');
  assert.deepEqual(third.roots, [ids.third], 'the new link\'s page');

  // Case 4: ⏮ from two pages down goes straight back to the search, in one slide.
  const played = await navigate(page, () => page.click('#reference-source-indicator-clear'));
  expectSlide(played, 'back', '⏮');
  const after = await barState(page);
  expectSearchBar(after, SEARCH, '⏮ from two pages down');
  assert.deepEqual(await notePlace(page, ids.holder), left, '⏮: the search is at the exact place the user left it');
  assert.equal(after.tabCount, searchTabs, '⏮ closes every page it leaves');
}

// Case 7: following a reference already on the path goes back to its page, and the pages after
// it become forward; a reference to the page shown does nothing.
async function checkReturnAlongPath(page, ids) {
  const searchTabs = (await barState(page)).tabCount;
  await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  const atLink = await wheelNoteTo(page, ids.linkingChild, NOTE_TOP_BEFORE_FOLLOWING_PX);
  const expectBackAtTarget = async (played, label) => {
    expectSlide(played, 'back', label);
    const bar = await barState(page);
    expectReferenceBar(bar, {...SOURCE_PAGE, hasForward: true}, label);
    assert.deepEqual(bar.roots, [ids.target], `${label}: the target's page`);
    assert.equal(bar.tabCount, searchTabs + 1, `${label}: no new tab, the pages after the target's closed`);
    assert.deepEqual(await notePlace(page, ids.linkingChild), atLink, `${label}: exactly where the user left the target's page`);
  };

  await navigate(page, () => clickReferenceLink(page, ids.linkingChild, ids.second));
  await expectBackAtTarget(await navigate(page, () => clickReferenceLink(page, ids.second, ids.target)), 'a link back one page');
  const forward = await navigate(page, () => page.click('#reference-view-chip-forward'));
  expectSlide(forward, 'forward', '▶ after a link back');
  assert.deepEqual((await barState(page)).roots, [ids.second], '▶ returns to the page the link back left');

  await navigate(page, () => clickReferenceLink(page, ids.second, ids.third));
  assert.equal((await barState(page)).tabCount, searchTabs + 3, 'a note not on the path opens a page');
  await expectBackAtTarget(await navigate(page, () => clickReferenceLink(page, ids.third, ids.target)), 'a link back two pages');

  const before = await transitionCount(page);
  await clickReferenceLink(page, ids.selfLinkingChild, ids.target);
  await idle(page);
  assert.equal(await transitionCount(page), before, 'a link to the page shown does nothing');
  assert.equal((await barState(page)).tabCount, searchTabs + 1, 'a link to the page shown opens no tab');

  await navigate(page, () => page.click('#reference-view-chip-back'));
  assert.equal((await barState(page)).tabCount, searchTabs, '◀ from the first page closes the path');
}

// Case 8: an AI answer's references, then one of them; the same again does nothing.
async function checkAiReferences(page, ids) {
  const left = await wheelNoteTo(page, ids.holder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await addAiReference(page, 'test-ai-open-all',
    `<a href="#" class="ai-chat-open-all-references" data-ref-query="${ids.target} OR ${ids.second}">Open all references</a>`);
  const opened = await navigate(page, () => page.click('#test-ai-open-all .ai-chat-open-all-references'));
  expectSlide(opened, 'forward', 'Show all references');
  const references = await barState(page);
  expectReferenceBar(references, {...SOURCE_PAGE, kind: 'All references'}, 'Show all references');
  assert.deepEqual(references.roots.toSorted(), [ids.target, ids.second].toSorted(), 'both cited notes are shown, as roots');

  const transitionsBefore = await transitionCount(page);
  await page.click('#test-ai-open-all .ai-chat-open-all-references');
  await idle(page);
  const again = await barState(page);
  assert.equal(await transitionCount(page), transitionsBefore, 'the references already shown: no transition');
  assert.deepEqual({tab: again.activeTabId, tabs: again.tabCount, roots: again.roots},
    {tab: references.activeTabId, tabs: references.tabCount, roots: references.roots}, 'the references already shown: nothing changes');

  await addAiReference(page, 'test-ai-reference',
    `<ul><li data-ref-query="${ids.second}"><a href="#" class="note-reference-link"><span>AI reference</span></a></li></ul>`);
  const replaced = await navigate(page, () => page.click('#test-ai-reference .note-reference-link'));
  expectSlide(replaced, 'forward', 'one AI reference');
  const after = await barState(page);
  expectReferenceBar(after, {...SOURCE_PAGE, kind: 'Reference'}, 'one AI reference');
  assert.equal(after.tabCount, references.tabCount, 'one AI reference adds no page');
  assert.deepEqual(after.roots, [ids.second], 'the reference replaced the page');
  await page.evaluate(() => {
    document.getElementById('test-ai-open-all').remove();
    document.getElementById('test-ai-reference').remove();
  });
  await checkBackToSearch(page, ids, left, '◀ from AI references');
}

// With Reduce Motion, a quick fade instead of the slide.
async function checkReducedMotion(page, ids) {
  const left = await wheelNoteTo(page, ids.holder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await setReducedMotion(page, true);
  const played = await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  const fade = [{keyframes: [{opacity: 1}, {opacity: 0}], duration: REDUCED_MOTION_FADE_MS}];
  assert.deepEqual(played.ghost, fade, 'reduce motion: the old column fades out');
  assert.deepEqual(played.column, [{keyframes: [{opacity: 0}, {opacity: 1}], duration: REDUCED_MOTION_FADE_MS}],
    'reduce motion: the new column fades in, without moving');
  expectReferenceBar(await barState(page), SOURCE_PAGE, 'reduce motion');
  const closed = await navigate(page, () => page.click('#reference-view-chip-back'));
  assert.deepEqual(closed.ghost, fade, 'reduce motion: ◀ fades too');
  expectSearchBar(await barState(page), SEARCH, 'reduce motion: back at the search');
  assert.deepEqual(await notePlace(page, ids.holder), left, 'reduce motion: the search is where the user left it');
  await setReducedMotion(page, false);
}

// Cases 10 and 11, and each search context keeping its page (rule 9): a reload brings the page
// and its path back (not what was forward); the context's row names the page; choosing another
// context and coming back returns to the page, ▶ kept; no transition plays for any of it.
async function checkContextsKeepTheirPage(page, ids) {
  const searchTabId = (await barState(page)).activeTabId;
  await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  await wheelNoteTo(page, ids.linkingChild, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await navigate(page, () => clickReferenceLink(page, ids.linkingChild, ids.second));
  await navigate(page, () => page.click('#reference-view-chip-back'));
  const onPage = await barState(page);
  const pagePlace = await notePlace(page, ids.linkingChild);
  let rows = await contextRows(page);
  assert.deepEqual(rows, [{tabId: searchTabId, label: `${SEARCH} > ${SOURCE_LABEL}`, isActive: true}],
    'the context\'s row names its page; the page has no row of its own');
  assert.ok(rows.every(row => !/[0-9a-f]{8}-[0-9a-f]{4}/i.test(row.label)), 'no row is named by a note ID');
  assert.equal(await rowOffersClose(page, searchTabId), false, 'the only context, on a page, offers no −');

  // Another context, and back: the page as it was left, ▶ kept.
  await page.evaluate(async () => {
    const {openSearchInNewSearchContext} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await openSearchInNewSearchContext('refother', 'test');
  });
  await idle(page);
  rows = await contextRows(page);
  assert.deepEqual(rows.map(row => [row.label, row.isActive]), [[`${SEARCH} > ${SOURCE_LABEL}`, false], ['refother', true]],
    'the other context is in use; the first keeps its page');
  const otherTabId = rows[1].tabId;
  await clickContextRow(page, searchTabId);
  const back = await barState(page);
  expectReferenceBar(back, {...SOURCE_PAGE, hasForward: true}, 'choosing the context again');
  assert.equal(back.activeTabId, onPage.activeTabId, 'the same page');
  assert.deepEqual(await notePlace(page, ids.linkingChild), pagePlace, 'the page as it was left');

  // A reload: the page and its path come back; what was forward does not.
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  assert.deepEqual(await page.evaluate(() => window.__referenceTransitions), [], 'a reload plays no transition');
  expectReferenceBar(await barState(page), SOURCE_PAGE, 'after a reload');
  assert.equal(await page.evaluate(() => sessionStorage.getItem('metalist_reference_navigation_stack')), null,
    'no page is kept in the window: the server keeps them with the tabs');
  await clickContextRow(page, otherTabId);
  await clickContextRow(page, searchTabId);
  assert.deepEqual(await page.evaluate(() => window.__referenceTransitions), [], 'choosing contexts plays no transition');
  expectReferenceBar(await barState(page), SOURCE_PAGE, 'chosen again after a reload');

  // Done with the other context; ◀ back to the search, whose row is plain again.
  await page.hover('#tab-hover-zone');
  await page.waitForSelector(`#search-contexts-list .tab-context-item[data-tab-id="${otherTabId}"] .delete-context`, {visible: true});
  await page.click(`#search-contexts-list .tab-context-item[data-tab-id="${otherTabId}"] .delete-context`);
  await idle(page);
  await navigate(page, () => page.click('#reference-view-chip-back'));
  assert.deepEqual(await contextRows(page), [{tabId: searchTabId, label: SEARCH, isActive: true}], 'back at the search, the row is plain');
}

// Tab on a page goes back to the search, ready to type.
async function checkTabToTheSearch(page, ids) {
  await navigate(page, () => clickReferenceLink(page, ids.holder, ids.target));
  await navigate(page, () => page.keyboard.press('Tab'));
  const after = await barState(page);
  expectSearchBar(after, SEARCH, 'Tab');
  assert.equal(after.inputFocused, true, 'Tab: the search input has the focus');
  await page.evaluate(() => document.getElementById('search-input').blur());
  await idle(page);
}

// Rule 10: deleting the note a page shows closes the page: its context shows its search, where
// the user left it, and its row is plain.
async function checkDeletingTheLinkedNote(page, ids) {
  const left = await wheelNoteTo(page, ids.doomHolder, NOTE_TOP_BEFORE_FOLLOWING_PX);
  await navigate(page, () => clickReferenceLink(page, ids.doomHolder, ids.doomed));
  expectReferenceBar(await barState(page), SOURCE_PAGE, 'the page of the note to delete');
  await page.evaluate(async doomed => {
    const {deleteNoteOutsideEdit} = await import('/static/js/modules/mode-manager/actions/note-actions.js');
    await deleteNoteOutsideEdit(doomed);
  }, ids.doomed);
  await page.waitForFunction(() => !document.getElementById('reference-source-indicator').classList.contains('is-shown'));
  await idle(page);
  expectSearchBar(await barState(page), SEARCH, 'the linked note deleted');
  assert.deepEqual(await notePlace(page, ids.doomHolder), left, 'the search is where the user left it');
  const rows = await contextRows(page);
  assert.deepEqual(rows.map(row => row.label), [SEARCH], 'the context\'s row is plain again');
}

// Reduce Motion on or off. Chrome emulates the media feature. Puppeteer cannot in
// Firefox, so there the page's own question, matchMedia('(prefers-reduced-motion:
// reduce)'), which is how MetaList asks, gets that answer.
async function setReducedMotion(page, reduce) {
  if (process.env.BROWSER_TEST_BROWSER === 'chrome') {
    await page.emulateMediaFeatures([{name: 'prefers-reduced-motion', value: reduce ? 'reduce' : 'no-preference'}]);
    return;
  }
  await page.evaluate(reduce => {
    const query = '(prefers-reduced-motion: reduce)';
    if (window.__realMatchMedia === undefined) window.__realMatchMedia = window.matchMedia.bind(window);
    window.matchMedia = text => {
      const answer = window.__realMatchMedia(text);
      if (text !== query) return answer;
      return Object.defineProperties(Object.create(answer), {matches: {value: reduce}, media: {value: query}});
    };
  }, reduce);
}

async function inputChipsState(page) {
  return page.evaluate(() => {
    const chip = id => {
      const element = document.getElementById(id);
      const rect = element.getBoundingClientRect();
      return {
        shown: element.classList.contains('is-shown'),
        animating: element.classList.contains('is-growing') || element.classList.contains('is-leaving'),
        label: element.querySelector('.search-input-chip-label').textContent,
        title: element.querySelector('.search-input-chip-label').getAttribute('title'),
        left: rect.left, right: rect.right,
      };
    };
    const input = document.getElementById('search-input');
    const chips = document.querySelector('.controls .search-input-chips');
    return {
      untagged: chip('untagged-view-indicator'),
      sort: chip('root-sort-indicator'),
      inputRight: input.getBoundingClientRect().right,
      inputPaddingRight: getComputedStyle(input).paddingRight,
      chipsLeft: chips.getBoundingClientRect().left,
      chipsWidth: chips.offsetWidth,
    };
  });
}

// Sort orders (Reverse Order too) and Untagged: chips at the right end inside the input.
async function checkInputChips(page) {
  await setSortMode(page, 'alphabetical');
  let chips = await inputChipsState(page);
  assert.equal(chips.sort.shown, true, 'a sort order shows its chip');
  assert.deepEqual([chips.sort.label, chips.sort.title], ['A–Z', 'Sorted alphabetically'], 'short label, full name as tooltip');
  expectSameSpot(chips.sort.right, chips.inputRight - INPUT_CHIPS_INSET_PX, 'the chip ends just inside the input\'s right edge');
  assert.equal(chips.inputPaddingRight, `${INPUT_RIGHT_PADDING_PX + chips.chipsWidth}px`, 'the typed text stops before the chips');

  await setSortMode(page, 'alphabetical-reversed');
  chips = await inputChipsState(page);
  assert.deepEqual([chips.sort.label, chips.sort.title], ['Z–A', 'Sorted alphabetically, Z to A'], 'Reverse Order shows Z–A');
  await setSortMode(page, 'created-reversed');
  chips = await inputChipsState(page);
  assert.deepEqual([chips.sort.label, chips.sort.title], ['Created ↑', 'Sorted by datetime created, oldest first'],
    'a reversed date order starts from the oldest');

  await setUntagged(page, true);
  chips = await inputChipsState(page);
  assert.equal(chips.untagged.shown, true, 'Untagged shows its chip');
  assert.ok(chips.untagged.right <= chips.sort.left, 'Untagged comes first, before the sort');
  assert.equal(chips.inputPaddingRight, `${INPUT_RIGHT_PADDING_PX + chips.chipsWidth}px`, 'the text stops before both chips');

  // A reload shows the chips as they are, without growing them in.
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  chips = await inputChipsState(page);
  assert.deepEqual([chips.sort.shown, chips.sort.animating], [true, false], 'after a reload the sort chip is simply there');
  assert.deepEqual([chips.untagged.shown, chips.untagged.animating], [true, false], 'and so is the Untagged chip: the tab keeps it');

  // × on the sort chip returns to Normal, not reversed.
  await page.click('#root-sort-indicator-clear');
  await idle(page);
  assert.equal(await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.activeTabSortMode;
  }), 'normal', '× ends the sort order and its direction');

  // Typing a new search keeps the sort, which stays until its × ends it (the maintainer,
  // 2026-11-02, docs/ui/state-handling.md); Untagged still ends.
  await setSortMode(page, 'alphabetical');
  await searchFor(page, SEARCH);
  chips = await inputChipsState(page);
  assert.deepEqual([chips.sort.shown, chips.untagged.shown], [true, false], 'a new search keeps the sort and ends Untagged');
  assert.equal(await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.activeTabSortMode;
  }), 'alphabetical', 'a new search runs in the tab\'s sort');
  await page.click('#root-sort-indicator-clear');
  await idle(page);
}

export async function checkReferenceViews(page) {
  const ids = await createNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await installTransitionRecorder(page);
  await runThenCleanUp('reference pages', async () => {
    await searchFor(page, SEARCH);
    const left = await checkFollowFromSearch(page, ids);
    await checkBackToSearch(page, ids, left, '◀ from the first page');
    await checkLinkedChildIsARoot(page, ids);
    await checkPath(page, ids);
    await checkReturnAlongPath(page, ids);
    await checkAiReferences(page, ids);
    await checkReducedMotion(page, ids);
    await checkContextsKeepTheirPage(page, ids);
    await checkTabToTheSearch(page, ids);
    await checkDeletingTheLinkedNote(page, ids);
    await checkInputChips(page);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      const present = [ids.holder, ids.childHolder, ids.doomHolder, ids.target, ids.second, ids.third, ...ids.fillers];
      for (const id of present) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
