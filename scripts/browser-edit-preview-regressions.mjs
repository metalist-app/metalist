import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Previews while editing (docs/ui/content-formatting.md, "Previews while editing"; agreed
// 2026-10-29): with the caret inside a formula of the note being edited, a panel 6 px below
// the caret's line shows it drawn, its left edge at the caret, following the caret; above the
// line near the window's bottom. Nothing outside a formula, with only its opening delimiter,
// or for a formula that looks as typed. Broken mid-typing, the last good drawing fades to a
// ghost (0.25) and a pause shows "Invalid LaTeX"; a command not finished shows as typed after
// the pause. The panel never moves the note's text. Escape hides it until the caret leaves the
// formula; scrolling hides it; a selection shows none; Previews While Editing off shows none.
// The note's text never holds the caret mark.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// Longer than the wait after typing (150 ms) and the answer: no panel by then means none.
const NO_PANEL_WAIT_MS = 600;
// Longer than the pause after which a broken formula shows why (1.5 s).
const BROKEN_PAUSE_WAIT_MS = 2500;
const PANEL_WAIT_MS = 2000;
// Between the caret's line and the panel (paste-format-offer-service.js, CARD_GAP_PX).
const GAP_PX = 6;
// The panel's place is rounded to whole pixels.
const ROUNDING_PX = 0.5;
const GHOST_OPACITY = '0.25';
const FULL_OPACITY = '1';
const FILLER_NOTES = 30;
const PANEL = '.edit-preview';
// What marks the caret in the note sent for a preview (edit-preview-service.js).
const CARET_MARK = '\ufdd0';

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

async function pause(milliseconds) {
  await new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function seedNotes(page) {
  return page.evaluate(async fillerCount => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const fillers = [];
    for (let index = 0; index < fillerCount; index += 1) fillers.push(await make(`<div>Filler note ${index}</div>`, ''));
    const formulas = await make([
      'A half: $$\\frac{1}{2}$$ done.',
      'Plain $$x$$ here.',
      // Last: a $$ with no $$ after it anywhere opens nothing.
      'Only an opening $$\\frac{1}{2} and no closing one.',
    ].map(line => `<div>${line}</div>`).join(''), '@markdown');
    return {fillers, formulas};
  }, FILLER_NOTES);
}

const contentOf = id => `.note[data-note-id="${id}"] > .note-content`;

async function enterEditing(page, id) {
  await page.evaluate(selector => document.querySelector(selector).scrollIntoView({block: 'start'}), contentOf(id));
  await settle(page);
  await page.click(contentOf(id));
  await idle(page);
  await page.waitForSelector(`.note.editing[data-note-id="${id}"]`);
}

// Puts the caret `after` characters past the start of `needle` in the note being edited.
async function placeCaret(page, needle, after) {
  await page.evaluate(({needle, after}) => {
    const content = document.querySelector('.note.editing > .note-content');
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      const start = text.data.indexOf(needle);
      if (start === -1) continue;
      const range = document.createRange();
      range.setStart(text, start + after);
      range.collapse(true);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      return;
    }
    throw new Error(`no text ${needle}`);
  }, {needle, after});
}

// The panel, the caret's line and every note's box, measured in one frame.
async function measure(page) {
  return page.evaluate(selector => {
    const panel = document.querySelector(selector);
    const caret = getSelection().getRangeAt(0).getClientRects()[0];
    const boxes = [...document.querySelectorAll('.note, .note-content')].map(element => {
      const box = element.getBoundingClientRect();
      return [box.left, box.top, box.width, box.height].join(',');
    }).join('|');
    if (panel === null) return {panel: null, caret: {left: caret.left, top: caret.top, bottom: caret.bottom}, boxes};
    const box = panel.getBoundingClientRect();
    return {
      panel: {
        left: box.left, top: box.top, bottom: box.bottom, height: box.height,
        opacity: getComputedStyle(panel).opacity, text: panel.textContent, html: panel.innerHTML,
        hasFraction: panel.querySelector('math mfrac') !== null, hasError: panel.classList.contains('edit-preview-has-error'),
      },
      caret: {left: caret.left, top: caret.top, bottom: caret.bottom},
      boxes,
    };
  }, PANEL);
}

// Whether the preview comes to meet `condition` within PANEL_WAIT_MS, checked every frame.
async function becomes(page, condition, value) {
  return page.evaluate(({condition, value, selector, timeout}) => new Promise(resolve => {
    const panel = () => document.querySelector(selector);
    const checks = {
      shown: () => panel() !== null,
      hidden: () => panel() === null,
      opacity: () => panel() !== null && getComputedStyle(panel()).opacity === value,
      fraction: () => panel() !== null && panel().querySelector('math mfrac') !== null,
      movedFrom: () => panel() !== null && Math.abs(panel().getBoundingClientRect().left - value) > 1,
    };
    const started = performance.now();
    const step = () => {
      if (checks[condition]()) {
        resolve(true);
        return;
      }
      if (performance.now() - started > timeout) {
        resolve(false);
        return;
      }
      requestAnimationFrame(step);
    };
    step();
  }), {condition, value, selector: PANEL, timeout: PANEL_WAIT_MS});
}

async function waitForPanel(page, label) {
  assert.ok(await becomes(page, 'shown', null), `${label}: a preview`);
  await settle(page);
}

async function assertNoPanel(page, label) {
  await pause(NO_PANEL_WAIT_MS);
  assert.equal(await page.$(PANEL), null, `${label}: no preview`);
}

function assertBelowCaret(measured, label) {
  assert.notEqual(measured.panel, null, `${label}: a preview`);
  assert.ok(Math.abs(measured.panel.left - measured.caret.left) <= ROUNDING_PX,
    `${label}: its left edge at the caret (${measured.panel.left}, caret ${measured.caret.left})`);
  assert.ok(Math.abs(measured.panel.top - (measured.caret.bottom + GAP_PX)) <= ROUNDING_PX,
    `${label}: ${GAP_PX} px below the caret's line (${measured.panel.top}, line bottom ${measured.caret.bottom})`);
}

async function shownBelowAndFollowing(page) {
  await placeCaret(page, 'done', 1);
  await assertNoPanel(page, 'caret in plain text');
  const before = await measure(page);
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'caret in \\frac{1}{2}');
  const shown = await measure(page);
  assertBelowCaret(shown, 'caret in \\frac{1}{2}');
  assert.equal(shown.panel.hasFraction, true, 'the fraction is drawn');
  assert.equal(shown.panel.opacity, FULL_OPACITY, 'at full strength');
  assert.equal(shown.boxes, before.boxes, 'no note moved when the preview appeared');
  await placeCaret(page, '\\frac', 1);
  assert.ok(await becomes(page, 'movedFrom', shown.panel.left), 'the preview follows the caret');
  await settle(page);
  assertBelowCaret(await measure(page), 'caret moved within the formula');
}

async function nothingOutsideAFormula(page) {
  await placeCaret(page, 'A half', 2);
  await assertNoPanel(page, 'caret before the formula');
  await placeCaret(page, '$$ done', 1);
  await assertNoPanel(page, 'caret between the closing $$');
  await placeCaret(page, 'and no closing', 4);
  await assertNoPanel(page, 'only an opening $$');
  await placeCaret(page, '$$x$$', 3);
  await assertNoPanel(page, '$$x$$ looks as typed');
}

async function brokenFormulaFades(page) {
  await placeCaret(page, '{1}{2}', 6);
  await waitForPanel(page, 'before typing');
  const good = await measure(page);
  await page.keyboard.type('^');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'broken: the last good drawing fades to the ghost');
  const faded = await measure(page);
  assert.equal(faded.panel.html, good.panel.html, 'broken: the last good drawing stays');
  assert.equal(faded.panel.hasError, false, 'broken: no reason while typing');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const paused = await measure(page);
  assert.deepEqual([paused.panel.text, paused.panel.hasError, paused.panel.opacity], ['Invalid LaTeX', true, FULL_OPACITY],
    'broken after a pause: why');
  await page.keyboard.press('Backspace');
  assert.ok(await becomes(page, 'fraction', null), 'fixed: the fraction is drawn again');
  await settle(page);
  const fixed = await measure(page);
  assert.deepEqual([fixed.panel.opacity, fixed.panel.hasError], [FULL_OPACITY, false], 'fixed: back at full strength');

  await page.keyboard.type(' + \\fra');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'a command not finished: the last good drawing fades');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const unknown = await measure(page);
  assert.equal(unknown.panel.opacity, FULL_OPACITY, 'a command not finished, after a pause: full strength');
  assert.ok(unknown.panel.html.includes('<mi>\\fra</mi>') && unknown.panel.hasFraction,
    `a command not finished, after a pause: drawn as the note draws it (${unknown.panel.html})`);
  for (let index = 0; index < ' + \\fra'.length; index += 1) await page.keyboard.press('Backspace');
  await idle(page);
}

async function escapeHidesIt(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before Escape');
  const before = await measure(page);
  await page.keyboard.press('Escape');
  await settle(page);
  const after = await measure(page);
  assert.equal(after.panel, null, 'Escape hides the preview');
  assert.equal(after.boxes, before.boxes, 'no note moved when it was hidden');
  assert.notEqual(await page.$('.note.editing'), null, 'Escape leaves editing alone');
  await page.keyboard.press('ArrowLeft');
  await assertNoPanel(page, 'after Escape, inside the same formula');
  await placeCaret(page, 'done', 1);
  await assertNoPanel(page, 'after Escape, outside the formula');
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'back in the formula after Escape');
}

async function aboveNearTheBottom(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before the window shrinks');
  const below = await measure(page);
  const height = Math.floor(below.caret.bottom + GAP_PX + below.panel.height);
  await page.setViewport({width: WINDOW.width, height});
  try {
    await settle(page);
    await placeCaret(page, '{1}{2}', 3);
    await waitForPanel(page, 'near the window\'s bottom');
    const above = await measure(page);
    assert.ok(Math.abs(above.panel.bottom - (above.caret.top - GAP_PX)) <= ROUNDING_PX,
      `near the window's bottom: ${GAP_PX} px above the caret's line (${above.panel.bottom}, line top ${above.caret.top})`);
  } finally {
    await page.setViewport(WINDOW);
    await settle(page);
  }
}

async function scrollSelectionAndSetting(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before scrolling');
  await page.mouse.wheel({deltaY: 1});
  assert.ok(await becomes(page, 'hidden', null), 'scrolling hides the preview');
  await placeCaret(page, '{1}{2}', 3);
  await waitForPanel(page, 'a caret move after scrolling');

  await page.evaluate(() => {
    const content = document.querySelector('.note.editing > .note-content');
    const text = [...content.querySelectorAll('div')][0].firstChild;
    const start = text.data.indexOf('{1}');
    const range = document.createRange();
    range.setStart(text, start);
    range.setEnd(text, start + 3);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
  });
  await assertNoPanel(page, 'a selection in the formula');

  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.edit_previews', false);
  });
  try {
    await placeCaret(page, '{1}{2}', 4);
    await assertNoPanel(page, 'Previews While Editing off');
  } finally {
    await page.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.applyPreference('pref.edit_previews', true);
    });
  }
  await placeCaret(page, '{1}{2}', 3);
  await waitForPanel(page, 'Previews While Editing on again');
}

async function previewCases(page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  await enterEditing(page, ids.formulas);
  const textBefore = await page.$eval('.note.editing > .note-content', content => content.innerHTML);
  await attempt('1 below the caret, following it, moving no note', () => shownBelowAndFollowing(page));
  await attempt('2 nothing outside a formula', () => nothingOutsideAFormula(page));
  await attempt('3 broken mid-typing: the last good drawing fades, a pause shows why', () => brokenFormulaFades(page));
  await attempt('4 Escape hides it until the caret leaves the formula', () => escapeHidesIt(page));
  await attempt('5 above the line near the window\'s bottom', () => aboveNearTheBottom(page));
  await attempt('6 scrolling, a selection and the setting', () => scrollSelectionAndSetting(page));
  await attempt('7 the note\'s text never holds the caret mark', async () => {
    const textAfter = await page.$eval('.note.editing > .note-content', content => content.innerHTML);
    assert.equal(textAfter, textBefore, 'the edited text is as it was');
    assert.equal(textAfter.includes(CARET_MARK), false, 'no caret mark in the editor');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await idle(page);
    // The note as shown again, drawn from what was saved.
    const shown = await page.$eval(`.note[data-note-id="${ids.formulas}"]`, note => note.innerHTML);
    assert.equal(await page.$('.note.editing'), null, 'editing ended');
    assert.equal(shown.includes(CARET_MARK), false, 'no caret mark saved');
  });
  assert.deepEqual(failures, []);
}

export async function checkEditPreviews(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('edit previews', () => previewCases(page, ids), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.formulas, ...ids.fillers]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
