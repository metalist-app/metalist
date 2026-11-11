import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { runThenCleanUp } from './suite-outcome.mjs';

// A folded note whose first line is a Mermaid diagram shows the whole diagram small, the size of
// a folded Excalidraw drawing (docs/ui/content-formatting.md; cases agreed 2026-11-09). A diagram
// further down leaves the note's first line of text, and an invalid diagram its first source line.

const REQUESTS_QUIET_MS = 300;
const FOLD_SETTLE_MS = 500;
const THUMBNAIL_WIDTH_EM = 7.5;
const THUMBNAIL_HEIGHT_EM = 4.5;
const ONE_LINE_EM = 1.6;
// The frame's 2 px padding and 1 px border, on each side.
const FRAME_INSET_PX = 3;
const PIXEL_ROUNDING = 0.5;
// Illuminated has no panel behind a diagram: it sits on the bare parchment (2a518557, skins/illuminated.css).
const THEME_BACKGROUNDS = [['system', 'rgb(255, 255, 255)'], ['dark', 'rgb(14, 14, 14)'], ['illuminated', 'rgba(0, 0, 0, 0)']];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const lines = (...texts) => texts.map(text => `<div>${text}</div>`).join('');
const DIAGRAM = ['graph TD', 'A --&gt; B'];

const NOTES = {
  whole: [lines(...DIAGRAM), '@mermaid'],
  regionFirst: [lines(`((${DIAGRAM[0]}`, `${DIAGRAM[1]}))`, 'After'), '((@mermaid))'],
  fenceFirst: [lines('```mermaid', ...DIAGRAM, '```', 'After'), '@markdown'],
  regionLater: [lines('Before', `((${DIAGRAM[0]}`, `${DIAGRAM[1]}))`), '((@mermaid))'],
  invalid: [lines('not a diagram at all', 'second line'), '@mermaid'],
  linked: [lines(...DIAGRAM), '@mermaid'],
};
const DRAWN_NOTES = ['whole', 'regionFirst', 'fenceFirst', 'regionLater', 'linked'];
const THUMBNAIL_NOTES = ['whole', 'regionFirst', 'fenceFirst', 'linked'];

async function createNotes(page) {
  return page.evaluate(async notes => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = {};
    for (const [name, [html, tags]] of Object.entries(notes)) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      ids[name] = note.id;
    }
    // A note that links to it gives the note a backlink badge, and its drawing a wrapper.
    const linker = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(linker.id, `<div>[[${ids.linked}]]</div>`, '');
    ids.linker = linker.id;
    return ids;
  }, NOTES);
}

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function waitForDrawings(page, ids) {
  await page.waitForFunction(ids => ids.every(id => document.querySelector(`.note[data-note-id="${id}"] [data-mermaid-state="rendered"] svg`) !== null), {}, DRAWN_NOTES.map(name => ids[name]));
}

async function applyPreference(page, key, value) {
  await page.evaluate(async ({key, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(key, value);
  }, {key, value});
}

async function toggleFold(page, noteId) {
  await page.evaluate(id => {
    const note = document.querySelector(`.note[data-note-id="${id}"]`);
    note.scrollIntoView({block: 'center'});
    note.querySelector(':scope > .note-collapse-toggle').click();
  }, noteId);
  await pause(FOLD_SETTLE_MS);
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

function readNote(page, noteId) {
  return page.evaluate(id => {
    const note = document.querySelector(`.note[data-note-id="${id}"]`);
    const content = note.querySelector(':scope > .note-content');
    const diagram = content.querySelector('.meta-mermaid-diagram');
    const svg = diagram === null ? null : diagram.querySelector('svg');
    const box = element => {
      if (element === null) return null;
      const {top, left, width, height, bottom} = element.getBoundingClientRect();
      return {top, left, width, height, bottom};
    };
    return {
      isFolded: note.classList.contains('collapsed'),
      // Read only where there is a diagram (its frame's size).
      em: diagram === null ? null : parseFloat(getComputedStyle(diagram).fontSize),
      contentEm: parseFloat(getComputedStyle(content).fontSize),
      content: box(content),
      diagram: box(diagram),
      svg: box(svg),
      background: diagram === null ? null : getComputedStyle(diagram).backgroundColor,
      text: content.textContent.trim(),
      html: content.innerHTML.slice(0, 220),
      sourceTop: (() => {
        const code = content.querySelector('code');
        return code === null ? null : code.getBoundingClientRect().top;
      })(),
      textLeft: content.getBoundingClientRect().left + parseFloat(getComputedStyle(content).paddingLeft),
    };
  }, noteId);
}

function assertNear(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) <= PIXEL_ROUNDING, `${label}: ${actual} is not ${expected}`);
}

function assertThumbnail(shown, label) {
  assert.equal(shown.isFolded, true, `${label} is folded`);
  assert.notEqual(shown.diagram, null, `${label} has no diagram: ${shown.html}`);
  assertNear(shown.diagram.width, THUMBNAIL_WIDTH_EM * shown.em, `${label} frame width`);
  assertNear(shown.diagram.height, THUMBNAIL_HEIGHT_EM * shown.em, `${label} frame height`);
  assertNear(shown.diagram.left, shown.textLeft, `${label} frame at the left`);
  assertNear(shown.content.height, shown.diagram.height, `${label} note is as tall as its thumbnail`);
  assertNear(shown.svg.width, shown.diagram.width - FRAME_INSET_PX - FRAME_INSET_PX, `${label} drawing width`);
  assertNear(shown.svg.height, shown.diagram.height - FRAME_INSET_PX - FRAME_INSET_PX, `${label} drawing height`);
}

function assertOneLine(shown, expectedStart, label) {
  assert.equal(shown.isFolded, true, `${label} is folded`);
  assert.ok(shown.content.height <= ONE_LINE_EM * shown.contentEm + PIXEL_ROUNDING, `${label} is one line (${shown.content.height})`);
  assert.ok(shown.text.includes(expectedStart), `${label} shows ${expectedStart}: ${shown.text}`);
}

async function foldCases(page, ids) {
  const failures = [];
  const attempt = async (name, run) => {
    try {
      await run();
    } catch (error) {
      // A suite reports every failing case together, then fails below; anything else ends it.
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${name}: ${error.message}`);
    }
  };
  await reloadApp(page);
  await waitForDrawings(page, ids);
  const unfolded = {};
  for (const name of DRAWN_NOTES) unfolded[name] = await readNote(page, ids[name]);

  for (const name of THUMBNAIL_NOTES) {
    await attempt(`${name}: a thumbnail of the whole diagram`, async () => {
      await toggleFold(page, ids[name]);
      assertThumbnail(await readNote(page, ids[name]), name);
    });
  }
  await attempt('a diagram further down leaves the first line of text', async () => {
    await toggleFold(page, ids.regionLater);
    const shown = await readNote(page, ids.regionLater);
    assertOneLine(shown, 'Before', 'regionLater');
    assert.equal(shown.diagram, null, `the diagram is not drawn: ${shown.html}`);
  });
  await attempt('an invalid diagram shows its first source line', async () => {
    await toggleFold(page, ids.invalid);
    const shown = await readNote(page, ids.invalid);
    assertOneLine(shown, 'not a diagram at all', 'invalid');
    assert.ok(shown.sourceTop !== null && shown.sourceTop < shown.content.bottom, `the source's first line is in sight (${shown.sourceTop}, ${shown.content.bottom})`);
  });
  for (const [theme, background] of THEME_BACKGROUNDS) {
    await attempt(`${theme}: the same thumbnail on the theme's background`, async () => {
      if (theme !== 'system') await applyPreference(page, 'pref.theme', theme);
      await pause(FOLD_SETTLE_MS);
      const shown = await readNote(page, ids.whole);
      assertThumbnail(shown, theme);
      assert.equal(shown.background, background);
    });
  }
  await applyPreference(page, 'pref.theme', 'system');
  await pause(FOLD_SETTLE_MS);
  for (const name of DRAWN_NOTES) {
    await attempt(`${name}: unfolding gives the full diagram back`, async () => {
      await toggleFold(page, ids[name]);
      const shown = await readNote(page, ids[name]);
      assert.equal(shown.isFolded, false);
      for (const [element, size] of [['diagram', 'width'], ['diagram', 'height'], ['svg', 'width'], ['svg', 'height']]) {
        assertNear(shown[element][size], unfolded[name][element][size], `${name} ${element} ${size}`);
      }
    });
  }
  assert.deepEqual(failures, []);
}

export async function checkMermaidFold(page) {
  await applyPreference(page, 'pref.animated_transitions', false);
  const ids = await createNotes(page);
  await runThenCleanUp('mermaid fold', () => foldCases(page, ids), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, Object.values(ids));
    await applyPreference(page, 'pref.animated_transitions', true);
  });
}
