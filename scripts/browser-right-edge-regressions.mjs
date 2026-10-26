import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Everything on the right of the window stands beside the scrollbar, never over it, and
// covers no note (docs/ui/controls.md, "The right edge"; agreed 2026-10-25). The visible
// right edge is the scrollbar's inner edge when scrollbars always show, the window's edge
// when they overlay the page. Current Chrome (155 and later) places a fixed element's
// `right` from that edge, older Chrome from the window's: with always-visible scrollbars
// the buttons then moved 15 px over the notes and covered a note's robot.
//
// Every case runs in each layout: scrollbars always shown (the headless browsers' own) and
// overlaid (no strip: `scrollbar-width: none` lays the page out as overlay scrollbars do),
// windows 800 and 1280 px wide, the AI chat closed and open.

const WINDOW_WIDTHS = [800, 1280];
const WINDOW_HEIGHT = 800;
const SCROLLBARS = ['always', 'overlay'];
const NOTE_COUNT = 30;
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const SETTLE_MS = 400;
// docs/ui/controls.md: the buttons 10 px from the visible right edge, 9 px from the chat;
// floating messages 8 px left of the buttons; the reminder cards 18 px from the corner.
const BUTTONS_EDGE_PX = 10;
const BUTTONS_CHAT_EDGE_PX = 9;
const MESSAGES_GAP_PX = 8;
const REMINDER_EDGE_PX = 18;
const ROBOT_INSET_PX = 4;
// Browsers place boxes on a layout grid: 1/64 px in Chrome, 1/60 px in Firefox.
const LAYOUT_STEP_PX = 1 / 60;
// The find bar is placed by script in whole pixels.
const WHOLE_PIXEL_ROUNDING = 0.5;
const OVERLAY_STYLE_ID = 'right-edge-overlay-scrollbars';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await settle(page);
}

async function seedNotes(page) {
  return page.evaluate(async count => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (let index = 0; index < count; index += 1) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>Right edge note ${index} with a line long enough to reach the right side of the list</p>`, '');
      ids.push(note.id);
    }
    // Mid-list, so the page can scroll it level with the buttons.
    const robot = ids[Math.floor(count / 2)];
    await NotesAPI.addTagProposals(robot, {[robot]: ['travel']});
    return {ids, robot};
  }, NOTE_COUNT);
}

async function setScrollbars(page, kind) {
  await page.evaluate(({kind, id}) => {
    document.getElementById(id)?.remove();
    if (kind === 'overlay') {
      const style = document.createElement('style');
      style.id = id;
      style.textContent = 'html { scrollbar-width: none; }';
      document.head.appendChild(style);
    }
  }, {kind, id: OVERLAY_STYLE_ID});
  await settle(page);
}

async function setChat(page, isOpen) {
  const isShown = await page.evaluate(() => document.body.classList.contains('pref-show-ai-chat'));
  if (isShown !== isOpen) {
    await page.click('#chat-toggle-button');
    await page.waitForFunction(isOpen => document.body.classList.contains('pref-show-ai-chat') === isOpen, {}, isOpen);
    await idle(page);
  }
  // The chat's input takes the focus when it opens; the cases start from the list.
  await page.evaluate(() => document.activeElement?.blur());
}

// The robot level with the highest button below the search header, where a button could
// cover it (above that, notes pass under the header).
async function showRobotNote(page, robotId) {
  await page.evaluate(id => {
    const robot = document.querySelector(`.note[data-note-id="${id}"] .note-proposal-indicator`).getBoundingClientRect();
    const headerBottom = document.querySelector('.controls').getBoundingClientRect().bottom;
    const button = [...document.querySelectorAll('.global-controls > *')]
      .filter(element => element.getClientRects().length > 0)
      .map(element => element.getBoundingClientRect())
      .find(rect => rect.top >= headerBottom);
    window.scrollBy(0, (robot.top + robot.bottom) / 2 - (button.top + button.bottom) / 2);
  }, robotId);
  await idle(page);
}

// What the cases measure, in one look at the page.
async function measure(page, robotId) {
  return page.evaluate(id => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
    };
    const isShown = element => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
    const inWindow = rect => rect.bottom > 0 && rect.top < window.innerHeight;
    const buttons = [...document.querySelectorAll('.global-controls > *')].filter(isShown).map(box);
    const notes = [...document.querySelectorAll('#notes-container .note')].map(box).filter(inWindow);
    const robots = [...document.querySelectorAll('#notes-container .note-proposal-indicator')].filter(isShown).map(box).filter(inWindow);
    const panel = document.querySelector('.ai-chat-panel');
    return {
      // The page's layout width: documentElement.clientWidth reports the whole window in
      // current Chrome even while a scrollbar strip is reserved (scrollbar-gutter: stable).
      visibleRight: document.documentElement.offsetWidth,
      strip: window.innerWidth - document.documentElement.offsetWidth,
      clientHeight: document.documentElement.clientHeight,
      controls: box(document.querySelector('.global-controls')),
      buttons, notes, robots,
      panel: panel !== null && isShown(panel) ? box(panel) : null,
      robot: box(document.querySelector(`.note[data-note-id="${id}"] > .note-proposal-indicator`)),
      robotNote: (() => {
        const note = document.querySelector(`.note[data-note-id="${id}"]`);
        return {...box(note), borderTop: note.clientTop, borderRight: note.offsetWidth - note.clientWidth - note.clientLeft};
      })(),
    };
  }, robotId);
}

function assertNear(actual, expected, tolerance, message) {
  assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} instead of ${expected}`);
}

const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

// R2, R4: nothing in a note lies under a button; R3, and beside the chat when it shows.
function checkButtons(layout, label, isChatOpen) {
  assert(layout.buttons.length > 0, `${label}: the buttons show`);
  for (const button of layout.buttons) {
    for (const note of layout.notes) {
      assert(!overlaps(button, note), `${label}: a button covers a note (button ${button.left}-${button.right}, note to ${note.right})`);
    }
    for (const robot of layout.robots) {
      assert(!overlaps(button, robot), `${label}: a button covers a robot (button ${button.left}-${button.right}, robot ${robot.left}-${robot.right})`);
    }
  }
  if (isChatOpen) {
    assert.notEqual(layout.panel, null, `${label}: the chat shows`);
    assertNear(layout.controls.right, layout.panel.left - BUTTONS_CHAT_EDGE_PX, LAYOUT_STEP_PX, `${label}: the buttons stand ${BUTTONS_CHAT_EDGE_PX} px from the chat`);
    assertNear(layout.panel.right, layout.visibleRight, LAYOUT_STEP_PX, `${label}: the chat ends at the visible right edge`);
    return;
  }
  assertNear(layout.controls.right, layout.visibleRight - BUTTONS_EDGE_PX, LAYOUT_STEP_PX, `${label}: the buttons stand ${BUTTONS_EDGE_PX} px from the visible right edge`);
}

// C1: the robot in its note's top-right corner, 4 px inside the border, wholly in the note
// (docs/ui/tag-bar.md; agreed 2026-10-25).
function checkRobotCorner(layout, label) {
  const {robot, robotNote: note} = layout;
  assertNear(robot.right, note.right - note.borderRight - ROBOT_INSET_PX, LAYOUT_STEP_PX, `${label}: the robot's right edge is ${ROBOT_INSET_PX} px inside the note's border`);
  assertNear(robot.top, note.top + note.borderTop + ROBOT_INSET_PX, LAYOUT_STEP_PX, `${label}: the robot's top is ${ROBOT_INSET_PX} px inside the note's border`);
  assert(robot.left >= note.left && robot.bottom <= note.bottom, `${label}: the robot lies wholly in its note`);
}

// R1: pressing the robot opens its note with the caret hidden.
async function checkRobotPress(page, robotId, label) {
  await page.click(`.note[data-note-id="${robotId}"] .note-proposal-indicator`);
  await pause(SETTLE_MS);
  await idle(page);
  const state = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {id: mode.currentNoteId, hidden: mode.isCaretHidden};
  });
  await page.keyboard.press('Escape');
  await idle(page);
  assert.deepEqual(state, {id: robotId, hidden: true}, `${label}: pressing the robot opens its note with the caret hidden`);
}

// B1: the reminder cards 18 px from the visible right edge and the bottom.
async function checkReminderCorner(page, layout, label) {
  const corner = await page.evaluate(() => {
    let container = document.getElementById('reminder-surface');
    const isOurs = container === null;
    if (isOurs) {
      container = document.createElement('div');
      container.id = 'reminder-surface';
      container.className = 'reminder-surface';
      container.innerHTML = '<div class="reminder-surface-item">Right edge card</div>';
      document.body.appendChild(container);
    }
    const rect = container.getBoundingClientRect();
    if (isOurs) container.remove();
    return {right: rect.right, bottom: rect.bottom};
  });
  assertNear(corner.right, layout.visibleRight - REMINDER_EDGE_PX, LAYOUT_STEP_PX, `${label}: the reminder cards stand ${REMINDER_EDGE_PX} px from the visible right edge`);
  assertNear(corner.bottom, layout.clientHeight - REMINDER_EDGE_PX, LAYOUT_STEP_PX, `${label}: the reminder cards stand ${REMINDER_EDGE_PX} px from the bottom`);
}

// B2: floating messages just left of the buttons, never over the scrollbar.
async function checkFloatingMessage(page, layout, label) {
  const card = await page.evaluate(async () => {
    const {FloatingMessages} = await import('/static/js/modules/floating-messages.js');
    FloatingMessages.show({text: 'Right edge message', type: 'info', detail: '', isClosable: true, isLasting: true, key: 'right-edge'});
    const stack = document.querySelector('.floating-messages').getBoundingClientRect();
    FloatingMessages.dismissAll();
    return {right: stack.right};
  });
  assertNear(card.right, layout.controls.left - MESSAGES_GAP_PX, LAYOUT_STEP_PX, `${label}: the floating messages stand ${MESSAGES_GAP_PX} px left of the buttons`);
  assert(card.right <= layout.visibleRight, `${label}: the floating messages stay off the scrollbar`);
}

// F1: the find bar's right edge lines up with the search controls'.
async function checkFindBar(page, label) {
  await page.keyboard.down('Control');
  await page.keyboard.press('f');
  await page.keyboard.up('Control');
  await page.waitForSelector('#find-in-list-bar:not([hidden])');
  await settle(page);
  const edges = await page.evaluate(() => ({
    bar: document.getElementById('find-in-list-bar').getBoundingClientRect().right,
    controls: document.querySelector('.controls').getBoundingClientRect().right,
  }));
  await page.keyboard.press('Escape');
  await page.waitForSelector('#find-in-list-bar', {hidden: true});
  await idle(page);
  assertNear(edges.bar, edges.controls, WHOLE_PIXEL_ROUNDING, `${label}: the find bar lines up with the search controls`);
}

async function layoutCases(page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(error.message);
    }
  };
  for (const width of WINDOW_WIDTHS) {
    await page.setViewport({width, height: WINDOW_HEIGHT});
    for (const scrollbars of SCROLLBARS) {
      await setScrollbars(page, scrollbars);
      for (const isChatOpen of [false, true]) {
        await setChat(page, isChatOpen);
        await showRobotNote(page, ids.robot);
        const label = `${width} px, scrollbars ${scrollbars}, chat ${isChatOpen ? 'open' : 'closed'}`;
        const layout = await measure(page, ids.robot);
        assert(layout.buttons.some(button => layout.robot.top <= (button.top + button.bottom) / 2
          && (button.top + button.bottom) / 2 <= layout.robot.bottom), `${label}: the robot is level with a button`);
        if (scrollbars === 'always') {
          assert(layout.strip > 0, `${label}: this browser shows no scrollbar strip, so the case tests nothing`);
        } else {
          assert.equal(layout.strip, 0, `${label}: overlay scrollbars leave no strip`);
        }
        await attempt(label, () => checkButtons(layout, label, isChatOpen));
        await attempt(label, () => checkRobotCorner(layout, label));
        await attempt(label, () => checkRobotPress(page, ids.robot, label));
        await attempt(label, () => checkReminderCorner(page, layout, label));
        await attempt(label, () => checkFloatingMessage(page, layout, label));
        await attempt(label, () => checkFindBar(page, label));
      }
    }
  }
  assert.deepEqual(failures, []);
}

export async function checkRightEdge(page) {
  const viewport = page.viewport();
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('right edge', () => layoutCases(page, ids), async () => {
    await setScrollbars(page, 'always');
    await setChat(page, false);
    await page.setViewport(viewport);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids.ids);
  });
}
