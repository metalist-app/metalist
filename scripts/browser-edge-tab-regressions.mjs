import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The pull tabs (the maintainer, 2026-11-02; docs/ui/controls.md): the virtual folders' on the
// left edge, the AI chat's on the right, at the window's bottom (its middle until the maintainer
// moved them, 2026-11-02), as far up as ≡ is down from the top, each its icon above an arrow
// pointing the way a click moves its panel; a click shows or hides the panel as View > Show does.
//   1. closed, a tab sits on the window's edge; open, on its panel's edge; both at the window's
//      bottom, the arrow pointing the way a click moves the panel; the notices at the bottom
//      right keep clear of the chat's tab, with the chat open or closed
//   2. a click shows the tree and says a click will hide it; another hides it again
//   3. the tree is a full-height panel at the left
//   4. a reload keeps the tree shown, the tab saying so (the tree had stayed hidden until the
//      next view refresh: the choice was read after the first view was drawn)
//   5. at 900px and narrower, where the tree can't show, its tab doesn't either
//   6. the tabs hide while a note is open full screen
//   7. at the narrowest width the tree shows, no tab covers a note, the panels shown or hidden
// With the AI chat open too (the maintainer, 2026-11-02: the column started right of the tree but
// kept its width, running under the chat and the floating buttons):
//   8. the column starts right of the tree's tab exactly where it does without the chat, and ends
//      before the floating buttons beside the chat; the notes narrow to fit
//   9. the chat keeps a third of the window while the notes have 480px beside the tree, narrowing
//      to its 280px least first
//  10. where even that doesn't fit, the tree and its tab hide (the chat stays), the column as
//      with the chat alone
//  11. the chat alone is as it was
// The tree's width and the space beside it (the maintainer, 2026-11-02):
//  13. the notes keep the same margin from both panels' edges, to the pixel (the maintainer,
//      2026-11-02): 48px, where ≡, ↑ and ↓ fit beside the chat; the open tabs are mirror images,
//      each outside its panel and rounded on the side facing the notes
//  14. dragging the panel's right edge sets the tree's width, live; the column and the tab follow
//  15. no narrower than 160px; no wider than leaves the notes 480px
//  16. ← and → on the handle change it by 24px, Home sets the least, End the most
//  17. the width is remembered across reloads
//  18. the cut-off beside the chat follows the width: a 160px tree shows beside the chat in a
//      window too narrow for a 240px one
//  12. releasing the chat's width handle where it was pressed saves nothing and fails nothing (it
//      saved the width it already had, which the preferences refuse: FATAL "Redundant state change:
//      preference pref.ai.chat_width", the maintainer, 2026-11-02)

const WINDOW = {width: 1440, height: 900};
// The widest window where the tree hides, and the narrowest where it shows (main.css).
const TREE_HIDDEN_WIDTH = 900;
const TREE_SHOWN_WIDTH = 901;
const REQUESTS_QUIET_MS = 300;
const FIXTURE_TAG = 'foldersbuttonfixture';
// The tabs: --edge-tab-width; the tree's panel, --side-rail-edge + --virtual-folders-width.
const TAB_WIDTH_PX = 28;
const EDGE_PX = 10;
const TREE_WIDTH_PX = 240;
const TREE_PANEL_PX = EDGE_PX + TREE_WIDTH_PX;
// --virtual-folders-gap: from the tree's edge to the notes, as from the notes to the chat's edge
// (--app-min-visible-gutter: 10px + ≡'s 30px + 8px).
const GAP_PX = 48;
const ROUNDED_RIGHT = '0px 10px 10px 0px';
const ROUNDED_LEFT = '10px 0px 0px 10px';
const EQUAL_GAPS_WIDTH = 1100;
// The tree's width: its least, the keyboard's step, and where it is remembered.
const TREE_LEAST_PX = 160;
const KEY_STEP_PX = 24;
const WIDTH_KEY = 'metalist.virtual_folders.width';
const DRAGGED_PX = 60;
const QUARTERS = 4;
// The notices' gap from what is beside them (.app-notice-stack, 18px from the corner before).
const NOTICE_GAP_PX = 18;
const CLOSED_TOWARD_LEFT = '‹';
const OPENS_TOWARD_RIGHT = '›';
// The chat's share of the window, its least width, and what the notes keep beside it (main.css:
// --ai-chat-width, the clamp in --ai-chat-effective-width, --ai-chat-min-notes-width).
const CHAT_SHARE = 33.333 / 100;
const CHAT_LEAST_PX = 280;
const NOTES_LEAST_PX = 480;
// The tree and its tab beside it: --side-rail-edge + --virtual-folders-width + --virtual-folders-gap.
const TREE_ROOM_PX = TREE_PANEL_PX + GAP_PX;
// The narrowest window where the tree shows beside the chat, and the widest where it can't.
const BESIDE_CHAT_WIDTH = TREE_ROOM_PX + NOTES_LEAST_PX + CHAT_LEAST_PX;
const BELOW_CHAT_WIDTH = BESIDE_CHAT_WIDTH - 1;
// What a note keeps from the floating buttons, at least.
const BUTTON_SPACE_PX = 8;
const WIDTHS_BESIDE_CHAT = [2000, 1440, 1100, BESIDE_CHAT_WIDTH];
// Browsers lay out in sixty-fourths (Chrome) or sixtieths (Firefox) of a pixel.
const SAME_PX = 1 / 60;

// What a browser's scrollbar takes from the window (none where scrollbars overlay the page).
function scrollbarWidth(page) {
  return page.evaluate(() => window.innerWidth - document.documentElement.clientWidth);
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// The tree shows in folder contexts (docs/ready-to-build/virtual-folders.md, "Folder contexts"): after the
// reload, the folders tab opens or closes it.
async function reloadWithFolders(page, isShown) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const isOn = await page.evaluate(() => document.body.classList.contains('virtual-folders-on'));
  if (isOn === isShown) return;
  await page.click('#virtual-folders-button');
  await idle(page);
}

function layout(page) {
  return page.evaluate(() => {
    const box = id => {
      const element = document.getElementById(id);
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height,
        isShown: getComputedStyle(element).display !== 'none' && !element.hidden,
        arrow: element.querySelector('.edge-tab-arrow') === null ? null
          : getComputedStyle(element.querySelector('.edge-tab-arrow'), '::before').content.replaceAll('"', ''),
      };
    };
    const button = document.getElementById('virtual-folders-button');
    const tree = document.getElementById('virtual-folders');
    const chat = document.querySelector('.ai-chat-panel');
    return {
      folders: box('virtual-folders-button'), chatTab: box('chat-toggle-button'),
      // The edge fixed things are placed against: the window, less the scrollbar's reserved strip.
      fixedRight: document.querySelector('.global-controls').getBoundingClientRect().right
        + parseFloat(getComputedStyle(document.querySelector('.global-controls')).right),
      windowHeight: window.innerHeight,
      menuTop: document.getElementById('menu-button').getBoundingClientRect().top,
      // The notices' column (app-notice-stack.js): where its right edge is placed.
      noticesRight: document.querySelector('.app-notice-stack') === null ? null
        : document.querySelector('.global-controls').getBoundingClientRect().right
          + parseFloat(getComputedStyle(document.querySelector('.global-controls')).right)
          - parseFloat(getComputedStyle(document.querySelector('.app-notice-stack')).right),
      tree: tree === null ? null : box('virtual-folders'),
      chat: getComputedStyle(chat).display === 'none' ? null : chat.getBoundingClientRect().toJSON(),
      title: button.title, label: button.getAttribute('aria-label'), pressed: button.getAttribute('aria-pressed'),
      notes: [...document.querySelectorAll('.note-content')].map(note => note.getBoundingClientRect().toJSON()),
    };
  });
}

async function withChat(page, isOpen) {
  const isShown = await page.evaluate(() => document.body.classList.contains('pref-show-ai-chat'));
  if (isShown !== isOpen) {
    await page.click('#chat-toggle-button');
    await page.waitForFunction(isOpen => document.body.classList.contains('pref-show-ai-chat') === isOpen, {}, isOpen);
  }
  await idle(page);
}

// Where the column, the notes, the floating buttons and the chat are.
function columnLayout(page) {
  return page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
    const shown = selector => {
      const element = document.querySelector(selector);
      return element !== null && getComputedStyle(element).display !== 'none' && !element.hidden;
    };
    const notes = [...document.querySelectorAll('.note-content')].map(note => note.getBoundingClientRect().toJSON());
    return {
      windowWidth: window.innerWidth,
      bar: rect('.controls'), menu: rect('#menu-button'), chat: shown('.ai-chat-panel') ? rect('.ai-chat-panel') : null,
      treeShown: shown('#virtual-folders'), buttonShown: shown('#virtual-folders-button'), chatTabShown: shown('#chat-toggle-button'),
      notesLeft: Math.min(...notes.map(note => note.left)), notesRight: Math.max(...notes.map(note => note.right)),
    };
  });
}

function expectedChatWidth(windowWidth, besideTree) {
  const leftOfChat = besideTree ? TREE_ROOM_PX + NOTES_LEAST_PX : NOTES_LEAST_PX;
  return Math.max(CHAT_LEAST_PX, Math.min(windowWidth * CHAT_SHARE, windowWidth - leftOfChat));
}

function assertClearOfChat(seen, label) {
  assert.ok(seen.notesRight <= seen.menu.left - BUTTON_SPACE_PX, `${label}: notes end at ${seen.notesRight}, ≡ starts at ${seen.menu.left}`);
  assert.ok(seen.bar.right <= seen.menu.left - BUTTON_SPACE_PX, `${label}: the search bar ends at ${seen.bar.right}, ≡ starts at ${seen.menu.left}`);
  assert.ok(seen.menu.right <= seen.chat.left, `${label}: ≡ ends at ${seen.menu.right}, the chat starts at ${seen.chat.left}`);
}

async function besideTheChat(page) {
  const scrollbar = await scrollbarWidth(page);
  for (const pageWidth of WIDTHS_BESIDE_CHAT) {
    const width = pageWidth + scrollbar;
    await page.setViewport({...WINDOW, width});
    await withChat(page, false);
    const alone = await columnLayout(page);
    await withChat(page, true);
    const seen = await columnLayout(page);
    const label = `${width}px`;
    assert.equal(seen.treeShown, true, `${label}: the tree shows`);
    assert.equal(seen.buttonShown, true, `${label}: its tab shows`);
    // 8: where it starts without the chat, to the pixel; ends clear of the buttons.
    assert.equal(seen.bar.left, alone.bar.left, `${label}: the search bar starts where it does without the chat`);
    assert.equal(seen.notesLeft, alone.notesLeft, `${label}: the notes start where they do without the chat`);
    assertClearOfChat(seen, label);
    // 9: the chat's width.
    const chatWidth = expectedChatWidth(seen.windowWidth, true);
    assert.ok(Math.abs(seen.chat.width - chatWidth) < SAME_PX, `${label}: the chat is ${seen.chat.width}px, expected ${chatWidth}px`);
  }
}

async function treeHidesBelowTheChat(page) {
  await page.setViewport({...WINDOW, width: BELOW_CHAT_WIDTH + await scrollbarWidth(page)});
  await withChat(page, true);
  const seen = await columnLayout(page);
  const label = `${BELOW_CHAT_WIDTH}px`;
  assert.equal(seen.treeShown, false, `${label}: the tree hides`);
  assert.equal(seen.buttonShown, false, `${label}: its tab hides`);
  assert.equal(seen.chatTabShown, true, `${label}: the chat's tab stays`);
  assertClearOfChat(seen, label);
  const chatWidth = expectedChatWidth(seen.windowWidth, false);
  assert.ok(Math.abs(seen.chat.width - chatWidth) < SAME_PX, `${label}: the chat is ${seen.chat.width}px, expected ${chatWidth}px`);
}

async function chatAloneAsItWas(page) {
  await page.setViewport(WINDOW);
  await reloadWithFolders(page, false);
  await withChat(page, true);
  const seen = await columnLayout(page);
  assertClearOfChat(seen, 'chat alone');
  const chatWidth = expectedChatWidth(seen.windowWidth, false);
  assert.ok(Math.abs(seen.chat.width - chatWidth) < SAME_PX, `chat alone: the chat is ${seen.chat.width}px, expected ${chatWidth}px`);
  await withChat(page, false);
}

async function releasingTheHandleInPlace(page) {
  await page.setViewport(WINDOW);
  await withChat(page, true);
  const errors = [];
  const onError = error => errors.push(String(error));
  const onConsole = message => {
    if (message.type() === 'error' && message.text().includes('Redundant state change')) errors.push(message.text());
  };
  page.on('pageerror', onError);
  page.on('console', onConsole);
  const handle = await page.$eval('#ai-chat-resizer', element => {
    const rect = element.getBoundingClientRect();
    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
  });
  for (let press = 0; press < 2; press++) {
    await page.mouse.move(handle.x, handle.y);
    await page.mouse.down();
    await page.mouse.up();
    await idle(page);
  }
  page.off('pageerror', onError);
  page.off('console', onConsole);
  await withChat(page, false);
  assert.deepEqual(errors, []);
}

// The panel, the handle on its edge, the search bar and the tab.
function treeLayout(page) {
  return page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
    return {
      tree: rect('#virtual-folders'), handle: rect('.virtual-folders-resizer'), bar: rect('.controls'),
      tab: rect('#virtual-folders-button'), pageWidth: document.documentElement.clientWidth,
      treeShown: getComputedStyle(document.getElementById('virtual-folders')).display !== 'none',
    };
  });
}

async function dragHandleTo(page, x) {
  const seen = await treeLayout(page);
  // Above the tab, which sits on the edge at the window's bottom.
  const y = seen.handle.top + seen.handle.height / QUARTERS;
  await page.mouse.move(seen.handle.left + seen.handle.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(x, y, {steps: 5});
  await page.mouse.up();
  await idle(page);
}

function mostTreeWidth(pageWidth) {
  return pageWidth - EDGE_PX - GAP_PX - NOTES_LEAST_PX;
}

async function columnBesideTheTree(page) {
  await page.setViewport(WINDOW);
  await reloadWithFolders(page, true);
  const seen = await treeLayout(page);
  assert.equal(seen.bar.left, seen.tree.right + GAP_PX, 'the notes start 48px from the panel');
  // Narrowed between the tree and the chat, the same gap on both sides.
  await page.setViewport({...WINDOW, width: EQUAL_GAPS_WIDTH});
  await withChat(page, true);
  // The notes' bordered boxes, not their text inside.
  const boxes = await page.$$eval('#notes-container > .note', notes => notes.map(note => note.getBoundingClientRect().toJSON()));
  const tree = await treeLayout(page);
  const chat = await page.$eval('.ai-chat-panel', element => element.getBoundingClientRect().toJSON());
  const radii = await page.evaluate(() => ['virtual-folders-button', 'chat-toggle-button'].map(id => {
    const style = getComputedStyle(document.getElementById(id));
    return [style.borderTopLeftRadius, style.borderTopRightRadius, style.borderBottomRightRadius, style.borderBottomLeftRadius].join(' ');
  }));
  await withChat(page, false);
  await page.setViewport(WINDOW);
  assert.ok(boxes.length > 0, 'top-level notes are shown');
  assert.equal(Math.min(...boxes.map(box => box.left)) - tree.tree.right, GAP_PX, 'from the tree\'s edge to the notes');
  assert.equal(chat.left - Math.max(...boxes.map(box => box.right)), GAP_PX, 'from the notes to the chat\'s edge');
  assert.deepEqual(radii, [ROUNDED_RIGHT, ROUNDED_LEFT], 'the open tabs are mirror images');
}

async function dragsTheWidth(page) {
  await page.setViewport(WINDOW);
  await reloadWithFolders(page, true);
  const before = await treeLayout(page);
  assert.equal(before.handle.left + before.handle.width / 2, before.tree.right, 'the handle is on the panel\'s right edge');
  await dragHandleTo(page, before.tree.right + DRAGGED_PX);
  let seen = await treeLayout(page);
  assert.equal(seen.tree.width, TREE_PANEL_PX + DRAGGED_PX);
  assert.equal(seen.bar.left, before.bar.left + DRAGGED_PX, 'the column follows');
  assert.equal(seen.tab.left, seen.tree.right, 'the tab follows, outside the panel');
  // 17: remembered.
  await reloadWithFolders(page, true);
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, TREE_PANEL_PX + DRAGGED_PX, 'the width is remembered');
  // 15: the limits.
  await dragHandleTo(page, EDGE_PX);
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + TREE_LEAST_PX, 'no narrower than 160px');
  await dragHandleTo(page, seen.pageWidth - EDGE_PX);
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + mostTreeWidth(seen.pageWidth), 'no wider than leaves the notes 480px');
}

async function keysSetTheWidth(page) {
  await page.setViewport(WINDOW);
  await reloadWithFolders(page, true);
  await page.focus('.virtual-folders-resizer');
  await page.keyboard.press('Home');
  let seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + TREE_LEAST_PX, 'Home: the least');
  await page.keyboard.press('ArrowRight');
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + TREE_LEAST_PX + KEY_STEP_PX, '→: 24px wider');
  await page.keyboard.press('ArrowLeft');
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + TREE_LEAST_PX, '←: 24px narrower');
  await page.keyboard.press('End');
  seen = await treeLayout(page);
  assert.equal(seen.tree.width, EDGE_PX + mostTreeWidth(seen.pageWidth), 'End: the most');
}

async function cutOffFollowsTheWidth(page) {
  const narrowRoom = EDGE_PX + TREE_LEAST_PX + GAP_PX + NOTES_LEAST_PX + CHAT_LEAST_PX;
  const scrollbar = await scrollbarWidth(page);
  await page.setViewport({...WINDOW, width: narrowRoom + scrollbar});
  await reloadWithFolders(page, true);
  await page.focus('.virtual-folders-resizer');
  await page.keyboard.press('Home');
  await withChat(page, true);
  assert.equal((await treeLayout(page)).treeShown, true, `${narrowRoom}px: a 160px tree shows beside the chat`);
  await page.setViewport({...WINDOW, width: narrowRoom + scrollbar - 1});
  await idle(page);
  assert.equal((await treeLayout(page)).treeShown, false, `${narrowRoom - 1}px: it doesn't fit`);
  await withChat(page, false);
}

function overlaps(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

// As far up from the window's bottom as ≡ is down from its top.
function assertBottom(tab, seen, label) {
  const fromBottom = seen.windowHeight - tab.bottom;
  assert.ok(Math.abs(fromBottom - seen.menuTop) < SAME_PX,
    `${label}: ${fromBottom}px from the window's bottom, as ≡ is ${seen.menuTop}px from its top`);
}

// The notices' column ends a notice's gap (18px) short of the chat's tab.
function assertNoticesClear(seen, label) {
  const expected = seen.chatTab.left - NOTICE_GAP_PX;
  assert.ok(Math.abs(seen.noticesRight - expected) < SAME_PX,
    `${label}: the notices end at ${seen.noticesRight}, ${NOTICE_GAP_PX}px left of the chat's tab is ${expected}`);
}

// 1, 3: where each tab sits, closed and open, and which way its arrow points.
async function tabsOnTheirEdges(page) {
  // The notices' column, made as the first notice makes it.
  await page.evaluate(async () => {
    const {appNoticeStack} = await import('/static/js/modules/app-notice-stack.js');
    appNoticeStack();
  });
  await withChat(page, false);
  let seen = await layout(page);
  assert.equal(seen.tree.isShown, false);
  assert.equal(seen.folders.left, 0, 'the closed folders tab is on the window\'s left edge');
  assert.equal(seen.folders.width, TAB_WIDTH_PX);
  assert.equal(seen.folders.arrow, OPENS_TOWARD_RIGHT);
  assertBottom(seen.folders, seen, 'the closed folders tab');
  assert.equal(seen.chatTab.right, seen.fixedRight, 'the closed chat tab is on the window\'s right edge');
  assert.equal(seen.chatTab.arrow, CLOSED_TOWARD_LEFT);
  assertBottom(seen.chatTab, seen, 'the closed chat tab');
  assertNoticesClear(seen, 'chat closed');
  await page.click('#virtual-folders-button');
  await withChat(page, true);
  seen = await layout(page);
  assert.deepEqual([seen.tree.left, seen.tree.top, seen.tree.width, seen.tree.height], [0, 0, TREE_PANEL_PX, seen.windowHeight],
    'the tree is a full-height panel at the left');
  // 13: outside the panel, on its right edge, as the chat's is outside the chat.
  assert.equal(seen.folders.left, seen.tree.right, 'the open folders tab is on the tree\'s right edge, outside it');
  assert.equal(seen.folders.arrow, CLOSED_TOWARD_LEFT);
  assertBottom(seen.folders, seen, 'the open folders tab');
  assert.equal(seen.chatTab.right, seen.chat.left, 'the open chat tab is on the chat\'s left edge');
  assert.equal(seen.chatTab.arrow, OPENS_TOWARD_RIGHT);
  assertBottom(seen.chatTab, seen, 'the open chat tab');
  assertNoticesClear(seen, 'chat open');
  await withChat(page, false);
  await page.click('#virtual-folders-button');
  await idle(page);
}

async function clickToggles(page) {
  let seen = await layout(page);
  assert.equal(seen.tree.isShown, false);
  assert.deepEqual([seen.title, seen.label, seen.pressed], ['Show virtual folders', 'Show virtual folders', 'false']);
  await page.click('#virtual-folders-button');
  await idle(page);
  seen = await layout(page);
  assert.equal(seen.tree.isShown, true);
  assert.deepEqual([seen.title, seen.label, seen.pressed], ['Hide virtual folders', 'Hide virtual folders', 'true']);
  await page.click('#virtual-folders-button');
  await idle(page);
  seen = await layout(page);
  assert.equal(seen.tree.isShown, false);
  assert.equal(seen.title, 'Show virtual folders');
}

async function reloadKeepsShown(page) {
  await reloadWithFolders(page, true);
  const seen = await layout(page);
  assert.equal(seen.tree.isShown, true, 'the tree shows after a reload that remembers it shown');
  assert.equal(seen.title, 'Hide virtual folders');
}

async function hiddenWhereTreeCannotShow(page) {
  await page.setViewport({...WINDOW, width: TREE_HIDDEN_WIDTH});
  await idle(page);
  assert.equal((await layout(page)).folders.isShown, false);
  await page.setViewport({...WINDOW, width: TREE_SHOWN_WIDTH});
  await idle(page);
  assert.equal((await layout(page)).folders.isShown, true);
}

async function coversNoNote(page) {
  await page.setViewport({...WINDOW, width: TREE_SHOWN_WIDTH});
  for (const isShown of [false, true]) {
    await reloadWithFolders(page, isShown);
    const seen = await layout(page);
    for (const [name, tab] of [['folders', seen.folders], ['chat', seen.chatTab]]) {
      const covered = seen.notes.filter(note => overlaps(tab, note));
      assert.deepEqual(covered, [], `folders ${isShown ? 'shown' : 'hidden'}: the ${name} tab covers a note`);
    }
  }
}

async function hiddenInFullScreen(page, noteId) {
  await page.evaluate(async id => {
    const {openNoteFullscreen} = await import('/static/js/modules/mode-manager/services/note-fullscreen-service.js');
    await openNoteFullscreen(id);
  }, noteId);
  await idle(page);
  const covered = await layout(page);
  assert.deepEqual([covered.folders.isShown, covered.chatTab.isShown], [false, false]);
  await page.keyboard.press('Escape');
  await idle(page);
  const back = await layout(page);
  assert.deepEqual([back.folders.isShown, back.chatTab.isShown], [true, true]);
}

export async function checkEdgeTabs(page) {
  await page.setViewport(WINDOW);
  const noteId = await page.evaluate(async tag => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<div>Folders button fixture</div>', tag);
    return note.id;
  }, FIXTURE_TAG);
  const hadWidth = await page.evaluate(key => window.localStorage.getItem(key), WIDTH_KEY);
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  await runThenCleanUp('edge tabs', async () => {
    await reloadWithFolders(page, false);
    await attempt('1, 3 the tabs on their edges', () => tabsOnTheirEdges(page));
    await attempt('2 a click shows and hides', () => clickToggles(page));
    await attempt('4 a reload keeps it shown', () => reloadKeepsShown(page));
    await attempt('5 hidden where the tree is', () => hiddenWhereTreeCannotShow(page));
    await page.setViewport(WINDOW);
    await attempt('6 hidden in full screen', () => hiddenInFullScreen(page, noteId));
    await attempt('7 covers no note', () => coversNoNote(page));
    await attempt('11 the chat alone', () => chatAloneAsItWas(page));
    await reloadWithFolders(page, true);
    await attempt('8, 9 beside the chat', () => besideTheChat(page));
    await attempt('10 below the chat', () => treeHidesBelowTheChat(page));
    await attempt('12 the chat handle released in place', () => releasingTheHandleInPlace(page));
    await attempt('13 the column beside the tree', () => columnBesideTheTree(page));
    await attempt('14, 15, 17 dragging the width', () => dragsTheWidth(page));
    await attempt('16 the keys', () => keysSetTheWidth(page));
    await attempt('18 the cut-off follows the width', () => cutOffFollowsTheWidth(page));
    assert.deepEqual(failures, []);
  }, async () => {
    await page.setViewport(WINDOW);
    await withChat(page, false);
    await reloadWithFolders(page, false);
    await page.evaluate(async ({id, widthKey, hadWidth}) => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.deleteNote(id);
      if (hadWidth === null) window.localStorage.removeItem(widthKey);
      else window.localStorage.setItem(widthKey, hadWidth);
    }, {id: noteId, widthKey: WIDTH_KEY, hadWidth});
  });
}
