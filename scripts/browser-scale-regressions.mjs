import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {join, resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {waitForAppIdle, waitForAppQuiet} from './browser-app-idle.mjs';

// The `scale` suite (PLAN.md, scale testing, part 3): MetaList on a large vault, in a real
// browser, against the server's own AI. 0.26.0 froze on a real vault three ways that 4,488 unit
// tests and 83 browser suites on a handful of notes could not see: an import of 1,127 files
// passed a 15 s watchdog and was called stuck; an AI question with an empty search box put a
// whole vault's reading on the request loop and held the server for minutes; Stop left that
// reading running. This suite runs each at the reporter's scale, with a budget on every step.
//
// The server starts on a vault scripts/generate_large_vault.py wrote (SCALE_NOTE_COUNT notes;
// every tenth starts with "Harbor"), with a folder of SCALE_IMPORT_FILE_COUNT Markdown files
// beside it, the scripted AI (tests/fixtures/scripted-ai/search-view.json: one search of the
// view, then an answer) and the operating system's folder dialog answered with that folder
// (METALIST_TEST_PICK_FOLDER). prepareScaleVault writes all that before browser-smoke.mjs
// starts the server.
//
// Budgets are generous with respect to the failures they catch (a freeze is minutes against
// a normal second), so a slow CI machine cannot fail a good build while a regression still
// cannot pass. Each measured step prints its time against its budget. A stall of the
// request loop fails the run as well (browser-loop-stalls.mjs), whatever the budgets say.

export const SCALE_NOTE_COUNT = 100_000;
export const SCALE_IMPORT_FILE_COUNT = 1_200;
// The same seed every run: the vault, its root count and its Harbor notes are the same.
const GENERATED_VAULT_SEED = 1;
const SCRIPTED_AI_SCRIPT = 'tests/fixtures/scripted-ai/search-view.json';
// generate_large_vault.py's IMPORT_FILES_FOLDER, its SEARCH_WORD, and a folder tag it gives notes.
// In the list's search box a bare word is a tag and a text search is quoted
// (docs/ui/search-semantics.md), so the word is searched as "Harbor" and the tag as Journal/.
const IMPORT_FILES_FOLDER = 'import-files';
const SEARCH_WORD = 'Harbor';
const TEXT_SEARCH = `"${SEARCH_WORD}"`;
const TAG_SEARCH = 'Journal/';
// The generator's last line: "Wrote 100,000 notes (37,203 at the top) to ... in 3.1 s".
const ROOT_COUNT_LINE = /^Wrote [\d,]+ notes \(([\d,]+) at the top\)/m;
const MS_PER_SECOND = 1000;
const REQUESTS_QUIET_MS = 300;
const POLL_MS = 50;

// Budgets (ms). Normal times from the first local run are in the comments.
// The wizard's preview reads every file (a second locally).
const PREVIEW_BUDGET_MS = 60_000;
// The import writes 1,200 notes and files; 0.26.0 called it stuck at 15 s.
const IMPORT_BUDGET_MS = 180_000;
// The question: one search of 100,000 notes by the agent, then the answer (10 s locally).
// 0.26.0 held the server for minutes.
const ANSWER_BUDGET_MS = 120_000;
// Typing in the list's search box while the AI reads the vault: the list follows. A text
// search of 100,000 notes took the server 2.5 s locally while the agent's thread shared
// the CPU, and the step 4 to 8 s with other work on the machine (PLAN.md guessed 3 s);
// a freeze is minutes, with the request never answered.
const LIST_FILTER_BUDGET_MS = 20_000;
// Stop during the agent's search: Send is back.
const STOP_BUDGET_MS = 1_000;
// How long after Send the list is typed in (the agent is reading the vault), and Stop is
// pressed (the scripted question is answered in about 4 s locally; the vault's reading is
// under way well before that).
const TYPE_AFTER_SEND_MS = 1_000;
const STOP_AFTER_SEND_MS = 300;
// The list: a band of roots moves when the bottom is reached (the poll runs every 800 ms),
// a tree collapses and expands, a tag search filters and clears.
const BAND_MOVE_BUDGET_MS = 5_000;
const SCROLL_PAGES = 5;
const COLLAPSE_BUDGET_MS = 3_000;
const TAG_SEARCH_BUDGET_MS = 5_000;
// The wizard goes from the folder to the summary in a few Nexts (Markdown; Images when there are any).
const MOST_WIZARD_NEXTS = 4;

const WIZARD = '#import-wizard';
const WIZARD_TITLE = `${WIZARD} .wizard-screen:not(.is-leaving) .wizard-screen-title`;
const NEXT = `${WIZARD} .wizard-next`;
const CHAT_INPUT = '#ai-chat-input';
const CHAT_SEND = '#ai-chat-send';
const SEARCH_INPUT = '#search-input';
const QUESTION = 'Which notes mention the harbor?';
const ANSWER = 'Done searching: the notes about the harbor are listed above.';

/**
 * The vault, the import folder and the environment the scale server needs, written before the
 * server starts (it loads the vault as it starts). Returns the vault's root count, from the
 * generator's own report.
 */
export function prepareScaleVault({python, directory, env, noteCount, fileCount}) {
  assert(Number.isInteger(noteCount) && noteCount > 0, 'prepareScaleVault needs a note count');
  assert(Number.isInteger(fileCount) && fileCount > 0, 'prepareScaleVault needs a file count');
  const generated = spawnSync(python, ['scripts/generate_large_vault.py', '--notes', String(noteCount), '--data-dir', directory,
    '--seed', String(GENERATED_VAULT_SEED), '--files', String(fileCount)], {env, encoding: 'utf-8'});
  assert.equal(generated.status, 0, `Generating the vault failed: ${generated.stderr}`);
  const rootCountMatch = ROOT_COUNT_LINE.exec(generated.stdout);
  assert(rootCountMatch !== null, `The generator did not report the root count: ${generated.stdout}`);
  env.METALIST_SCRIPTED_AI = resolve(SCRIPTED_AI_SCRIPT);
  env.METALIST_TEST_PICK_FOLDER = join(directory, IMPORT_FILES_FOLDER);
  return Number(rootCountMatch[1].replaceAll(',', ''));
}

function seconds(ms) {
  return `${(ms / MS_PER_SECOND).toFixed(1)} s`;
}

// Runs step, checks it took no longer than budgetMs, and prints what it took. A wait inside
// the step that gives up names the step too.
async function timed(label, budgetMs, step) {
  const startedAt = performance.now();
  try {
    await step();
  } catch (error) { // shockharness: ignore[EXC001] reason="the step's own error is rethrown with the step named"
    throw new Error(`${label}: not within its budget of ${seconds(budgetMs)}: ${error.message}`, {cause: error});
  }
  const tookMs = performance.now() - startedAt;
  console.log(`scale: ${label} in ${seconds(tookMs)} (budget ${seconds(budgetMs)})`);
  assert(tookMs <= budgetMs, `${label} took ${seconds(tookMs)}, over its budget of ${seconds(budgetMs)}`);
}

async function noFatalOverlay(page, when) {
  assert.equal(await page.$('#fatal-error-overlay'), null, `a fatal error was shown ${when}`);
}

// A value of the page's ModeContext (searchQuery, rootCountTotal, searchRootCountTotal).
async function modeContextValue(page, name) {
  return page.evaluate(async name => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode[name];
  }, name);
}

async function screenTitle(page) {
  return page.$eval(WIZARD_TITLE, title => title.textContent.trim());
}

async function clickNext(page) {
  const before = await screenTitle(page);
  await page.click(NEXT);
  await page.waitForFunction((selector, before) => {
    const title = document.querySelector(selector);
    return title !== null && title.textContent.trim() !== before;
  }, {}, WIZARD_TITLE, before);
}

// The list shows the search `text`: it has run, nothing is loading, and its roots are on
// the page (when it has any).
async function waitForSearchShown(page, text, budgetMs) {
  await page.waitForFunction(async text => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    if (mode.getExecutedSearchQuery() !== text || mode.isLoading) return false;
    const total = text === '' ? mode.rootCountTotal : mode.searchRootCountTotal;
    return total === 0 || document.querySelector('#notes-container > .note[data-note-id]') !== null;
  }, {timeout: budgetMs, polling: POLL_MS}, text);
  await waitForAppIdle(page);
}

// What the list shows, for a failure's message.
async function listState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const container = document.getElementById('notes-container');
    return `search ${JSON.stringify(mode.getExecutedSearchQuery())}, ${mode.searchRootCountTotal} search roots of ${mode.rootCountTotal}, `
      + `count shown "${document.getElementById('search-results-count').textContent}", ${container.children.length} elements in the list: `
      + container.innerHTML.slice(0, 300);
  });
}

// Types `text` over whatever the list's search box holds ('' clears it) and times the list
// showing it.
async function searchShown(page, text, budgetMs) {
  await page.click(SEARCH_INPUT);
  await page.evaluate(selector => document.querySelector(selector).select(), SEARCH_INPUT);
  if (text === '') {
    await page.keyboard.press('Backspace');
  } else {
    await page.keyboard.type(text);
  }
  await timed(`the list showing the search "${text}"`, budgetMs, () => waitForSearchShown(page, text, budgetMs));
}

async function rootsOnPage(page) {
  return page.$$eval('#notes-container > .note[data-note-id]', notes => notes.map(note => note.dataset.noteId));
}

async function sendText(page) {
  return page.$eval(CHAT_SEND, button => `${button.textContent.trim()}${button.disabled ? ' (disabled)' : ''}`);
}

async function chatIsBusy(page) {
  return page.evaluate(async () => {
    const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
    return AiChatPanel._isBusy;
  });
}

// --- The import of a folder of Markdown files -------------------------------------------------

async function checkImport(page) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.openImportWizard();
  });
  await page.waitForSelector(`${WIZARD} .wizard-choice[data-choice-value="markdown"]`, {visible: true});
  await page.click(`${WIZARD} .wizard-choice[data-choice-value="markdown"]`);
  await clickNext(page);
  assert.equal(await screenTitle(page), 'Choose the folder');
  // The operating system's dialog, answered by the server with the generated folder.
  await page.click(`${WIZARD} .wizard-choose-folder`);
  await page.waitForSelector(`${WIZARD} .wizard-folder-chosen.is-chosen`);
  const counts = await page.$eval(`${WIZARD} .wizard-folder-counts`, element => element.textContent.trim());
  assert.equal(counts, `${SCALE_IMPORT_FILE_COUNT} Markdown files`);
  for (let next = 0; next < MOST_WIZARD_NEXTS && await screenTitle(page) !== 'Ready to import'; next += 1) {
    await clickNext(page);
  }
  assert.equal(await screenTitle(page), 'Ready to import');
  await timed('the import preview', PREVIEW_BUDGET_MS, () => page.waitForFunction(selector => {
    const preview = document.querySelector(`${selector} .wizard-preview`);
    return preview !== null && !preview.textContent.includes('Reading your files…');
  }, {timeout: PREVIEW_BUDGET_MS, polling: POLL_MS}, WIZARD));
  // "1200 Markdown files will become 3600 notes (1200 root notes)", the count in its own element.
  const preview = await page.$eval(`${WIZARD} .wizard-preview`, element => element.textContent.replace(/\s+/g, ' '));
  assert.match(preview, new RegExp(`${SCALE_IMPORT_FILE_COUNT} ?Markdown files will become \\d+ notes \\(${SCALE_IMPORT_FILE_COUNT} root notes\\)`));
  // Import: the wizard closes on what it made, a search context of the imported notes open.
  await page.click(NEXT);
  await timed(`the import of ${SCALE_IMPORT_FILE_COUNT.toLocaleString('en-US')} files`, IMPORT_BUDGET_MS, async () => {
    await page.waitForFunction(selector => {
      const wizard = document.querySelector(selector);
      return wizard === null || wizard.offsetParent === null;
    }, {timeout: IMPORT_BUDGET_MS, polling: POLL_MS}, WIZARD);
    await waitForAppIdle(page);
  });
  await noFatalOverlay(page, 'during the import');
  const searchQuery = await modeContextValue(page, 'searchQuery');
  // The import's source tag: "imported:source=markdown:at=2026-11-07T10:01".
  assert(searchQuery.startsWith('imported:source=markdown:'), `the imported notes' search context is open, searching their tag: ${JSON.stringify(searchQuery)}`);
  await waitForSearchShown(page, searchQuery, IMPORT_BUDGET_MS);
  assert.equal(await modeContextValue(page, 'searchRootCountTotal'), SCALE_IMPORT_FILE_COUNT,
    'each imported file is a root note of the new search context');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// --- The AI with an empty search box ------------------------------------------------------------

async function showChat(page) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.show_ai_chat', true);
  });
  // Models loaded (the scripted AI stands in for the provider): Send is ready.
  await page.waitForFunction(selector => {
    const send = document.querySelector(selector);
    return send !== null && !send.disabled && send.textContent.trim() === 'Send';
  }, {}, CHAT_SEND);
}

async function ask(page) {
  await page.click(CHAT_INPUT);
  await page.type(CHAT_INPUT, QUESTION);
  await page.click(CHAT_SEND);
  await page.waitForFunction(async () => (await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js')).AiChatPanel._isBusy);
}

async function checkQuestionWithEmptySearch(page) {
  // The whole vault in view: the AI's scope is every note.
  await searchShown(page, '', TAG_SEARCH_BUDGET_MS);
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await showChat(page);
  const askedAt = performance.now();
  await ask(page);
  // A second in, the person goes on working: the list follows their search while the AI reads.
  await delay(TYPE_AFTER_SEND_MS);
  await searchShown(page, TEXT_SEARCH, LIST_FILTER_BUDGET_MS);
  const shown = await page.$$eval('#notes-container > .note[data-note-id] > .note-content', contents => contents.map(content => content.textContent));
  // A root shows when it or a note under it holds the word.
  assert(shown.length > 0 && shown.some(text => text.includes(SEARCH_WORD)),
    `the filtered list shows Harbor notes: ${shown.slice(0, 3).join(' | ')}; ${await listState(page)}`);
  assert((await modeContextValue(page, 'searchRootCountTotal')) > 0, `the search matched roots: ${await listState(page)}`);
  await noFatalOverlay(page, 'while the AI read the vault');
  // The answer, from the script, once the agent has searched the view and read what it found.
  const answerBudgetLeftMs = ANSWER_BUDGET_MS - (performance.now() - askedAt);
  await timed('the AI answering with the whole vault in view', ANSWER_BUDGET_MS, async () => {
    await page.waitForFunction(async () => !(await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js')).AiChatPanel._isBusy,
      {timeout: Math.max(answerBudgetLeftMs, POLL_MS), polling: POLL_MS});
  });
  const chat = await page.$eval('#ai-chat-messages', messages => messages.textContent);
  assert(chat.includes(ANSWER), `the script's answer is in the chat: ${chat.slice(-400)}`);
  await noFatalOverlay(page, 'after the AI answered');
}

// --- Stop during the agent's search --------------------------------------------------------------

async function checkStopDuringSearch(page) {
  await searchShown(page, '', TAG_SEARCH_BUDGET_MS);
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await ask(page);
  await delay(STOP_AFTER_SEND_MS);
  assert.equal(await sendText(page), 'Stop', 'the agent is still at work when Stop is pressed');
  await page.click(CHAT_SEND);
  await timed('Send back after Stop', STOP_BUDGET_MS, () => page.waitForFunction(selector => {
    const send = document.querySelector(selector);
    return send !== null && !send.disabled && send.textContent.trim() === 'Send';
  }, {timeout: STOP_BUDGET_MS, polling: POLL_MS}, CHAT_SEND));
  assert.equal(await chatIsBusy(page), false);
  // The server dropped the stopped reading: the list answers as before.
  await searchShown(page, TEXT_SEARCH, LIST_FILTER_BUDGET_MS);
  await noFatalOverlay(page, 'after Stop');
}

// --- The list itself ------------------------------------------------------------------------------

async function checkList(page) {
  await searchShown(page, '', TAG_SEARCH_BUDGET_MS);
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  // Scrolling to the bottom of the loaded roots: the band of loaded roots moves down each time.
  for (let scrolled = 0; scrolled < SCROLL_PAGES; scrolled += 1) {
    const before = await rootsOnPage(page);
    assert(before.length > 0, 'the list shows roots');
    await page.evaluate(() => window.scrollTo(0, document.scrollingElement.scrollHeight));
    await timed(`the band of roots moving down (${scrolled + 1} of ${SCROLL_PAGES})`, BAND_MOVE_BUDGET_MS, async () => {
      await page.waitForFunction(lastBefore => {
        const roots = document.querySelectorAll('#notes-container > .note[data-note-id]');
        return roots.length > 0 && roots[roots.length - 1].dataset.noteId !== lastBefore;
      }, {timeout: BAND_MOVE_BUDGET_MS, polling: POLL_MS}, before[before.length - 1]);
      await waitForAppIdle(page);
    });
  }
  // A tree collapses and expands.
  const treeId = await page.evaluate(() => {
    const tree = document.querySelector('#notes-container > .note[data-note-id]:has(> .note-collapse-toggle)');
    return tree === null ? null : tree.dataset.noteId;
  });
  assert(treeId !== null, 'a root with children is on the page');
  const arrow = `.note[data-note-id="${treeId}"] > .note-collapse-toggle`;
  await page.evaluate(selector => document.querySelector(selector).scrollIntoView({block: 'center'}), arrow);
  // The band of roots may follow the scroll: a click while the list loads is ignored.
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  const childrenShown = async () => page.$eval(`.note[data-note-id="${treeId}"]`, note => note.querySelectorAll('.note').length > 0
    && [...note.querySelectorAll('.note')].some(child => child.offsetParent !== null));
  const wasExpanded = await childrenShown();
  for (const [label, expected] of [['collapsing a tree', !wasExpanded], ['expanding it again', wasExpanded]]) {
    await waitForAppQuiet(page, REQUESTS_QUIET_MS);
    await page.click(arrow);
    const clickedAt = performance.now();
    await timed(label, COLLAPSE_BUDGET_MS, async () => {
      await page.waitForFunction(async (selector, expected) => {
        const note = document.querySelector(selector);
        const shown = note.querySelectorAll('.note').length > 0 && [...note.querySelectorAll('.note')].some(child => child.offsetParent !== null);
        return shown === expected;
      }, {timeout: COLLAPSE_BUDGET_MS, polling: POLL_MS}, `.note[data-note-id="${treeId}"]`, expected);
      console.log(`scale: ${label}: the children ${expected ? 'shown' : 'hidden'} after ${seconds(performance.now() - clickedAt)}`);
      await waitForAppIdle(page);
    });
  }
  // A tag search and back to everything.
  await searchShown(page, TAG_SEARCH, TAG_SEARCH_BUDGET_MS);
  assert((await modeContextValue(page, 'searchRootCountTotal')) > 0, 'the folder tag matches notes');
  await searchShown(page, '', TAG_SEARCH_BUDGET_MS);
  await noFatalOverlay(page, 'using the list');
}

export async function checkScale(page, {rootCount}) {
  assert(Number.isInteger(rootCount) && rootCount > 0, 'checkScale needs the vault\'s root count');
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  assert.equal(await modeContextValue(page, 'rootCountTotal'), rootCount, 'the generated vault is in view');
  await checkImport(page);
  await checkQuestionWithEmptySearch(page);
  await checkStopDuringSearch(page);
  await checkList(page);
}
