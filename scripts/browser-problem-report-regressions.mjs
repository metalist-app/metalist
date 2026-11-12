import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Problem reports (docs/ready-to-build/error-reports.md, section 8): Report a Problem… with a
// typed sentence, Export Report… on the red error, Export Problem Reports…, and a report made
// with no vault open (the login page's). Every saved file is read back: no word of a note, tag
// or typing may be in it, and it carries how busy the computer was. Downloads are caught in
// the page, not saved (as browser-export-print-regressions.mjs does), so Chrome and Firefox
// run the same checks.

const REQUESTS_QUIET_MS = 300;
const PALETTE = '/static/js/modules/command-palette/command-palette-controller.js';
const DESCRIPTION = 'it froze when I added a tag';
const MAX_DESCRIPTION = 300;
const SHAPED_DESCRIPTION = 'xx xxxxx xxxx X xxxxx x xxx';
// The user's words in the notes, their tags and the typing: none may reach a report.
const BUDGET_TAG = 'quokkabudget';
const FOLDER_TAG = 'tapirhome/narwhal';
const NOTES = Object.freeze([
  {html: '<div>Rent 1,450 Zebrafinch</div><div>Total: $\\frac{a}{b}$</div>', tags: BUDGET_TAG},
  {html: '<div>Call Marmoset tomorrow?</div>', tags: FOLDER_TAG},
]);
const TYPED = ' Okapi 42';
const MARKERS = Object.freeze(['zebrafinch', 'marmoset', 'quokkabudget', 'tapirhome', 'narwhal', 'okapi', '1,450']);
const SHAPED_NOTE = 'Xxxx 0,000 Xxxxxxxxxx';
const SHAPED_TYPING = ' Xxxxx 00';
const FRAC_KEPT = '$\\frac{x}{x}$';
const ERROR_MESSAGE = 'Cannot read Zebrafinch of okapi';
const SHAPED_ERROR = 'Xxxxxx xxxx Xxxxxxxxxx xx xxxxx';
const BUSY_FIELDS = Object.freeze([
  'machineAvailableBytes', 'machineCpuPercent', 'metalistCpuPercent', 'metalistMemoryBytes', 'swapUsedBytes',
]);
const LONE_MODIFIER = /^(Meta|Control|Alt|Shift)(Left|Right)?$/;
const REQUEST_ID = /^[a-f0-9]{8}$/;
const HTTP_OK = 200;
const HTTP_UNPROCESSABLE = 422;
const REPORT_ROW = '.command-palette-row[data-endpoint-id="action.report_problem"]';
const EXPORT_ROW = '.command-palette-row[data-endpoint-id="action.export_problem_reports"]';

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// The files the page hands the browser to save, kept in the page instead.
async function catchDownloads(page) {
  await page.evaluate(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    window.problemReportMode = ModeContextInstance;
    window.caughtReports = [];
    window.caughtReportNames = [];
    const createObjectURL = URL.createObjectURL.bind(URL);
    window.problemReportRestore = {createObjectURL: URL.createObjectURL, click: HTMLAnchorElement.prototype.click};
    URL.createObjectURL = blob => {
      window.caughtReports.push(blob);
      return createObjectURL(blob);
    };
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.download === '') click.call(this);
      else window.caughtReportNames.push(this.download);
    };
  });
}

async function releaseDownloads(page) {
  await page.evaluate(() => {
    URL.createObjectURL = window.problemReportRestore.createObjectURL;
    HTMLAnchorElement.prototype.click = window.problemReportRestore.click;
  });
}

// The next saved file, as text, once it has arrived.
async function nextDownload(page, count) {
  await page.waitForFunction(expected => window.caughtReports.length === expected, {}, count + 1);
  return page.evaluate(index => window.caughtReports[index].text(), count);
}

const downloadCount = page => page.evaluate(() => window.caughtReports.length);

async function makeNotes(page) {
  const ids = await page.evaluate(async notes => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const made = [];
    for (const {html, tags} of notes) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      made.push(note.id);
    }
    return made;
  }, NOTES);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  return ids;
}

async function deleteNotes(page, ids) {
  await page.evaluate(async noteIds => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of noteIds) await NotesAPI.deleteNote(id);
  }, ids);
}

async function startEditing(page, id) {
  await page.click(`.note[data-note-id="${id}"] .note-content`);
  await page.waitForFunction(noteId => window.problemReportMode.isEditing
    && window.problemReportMode.currentNoteId === noteId, {}, id);
  // Keys sent while the edit command still runs are held for it (type-ahead), Escape too.
  await idle(page);
}

// What the palette lists for a query, once Report a Problem… is among its rows.
async function paletteListsExport(page) {
  await page.evaluate(async url => {
    const {CommandPalette} = await import(url);
    await CommandPalette.open();
  }, PALETTE);
  await page.waitForSelector('#command-palette-input', {visible: true});
  await page.type('#command-palette-input', 'Problem');
  await page.waitForSelector(REPORT_ROW, {visible: true});
  const listsExport = (await page.$(EXPORT_ROW)) !== null;
  await page.keyboard.press('Escape');
  await page.waitForSelector('#command-palette-input', {hidden: true});
  return listsExport;
}

async function paletteAction(page, method) {
  await page.evaluate(async ({url, name}) => {
    const {CommandPalette} = await import(url);
    void CommandPalette[name]();
  }, {url: PALETTE, name: method});
}

async function reportProblem(page, sentence) {
  const count = await downloadCount(page);
  await paletteAction(page, 'reportProblem');
  await page.waitForSelector('#problem-report-description', {visible: true});
  await page.type('#problem-report-description', sentence);
  await page.click('#problem-report-export-btn');
  const report = JSON.parse(await nextDownload(page, count));
  await page.waitForSelector('#problem-report-description', {hidden: true});
  await idle(page);
  return report;
}

function assertNoWord(report, label) {
  const text = JSON.stringify(report).toLowerCase();
  assert.deepEqual(MARKERS.filter(marker => text.includes(marker)), [], `${label}: no word of a note, tag or typing`);
}

function assertBusyNumbers(report, label) {
  assert.deepEqual(Object.keys(report.machine).sort(), BUSY_FIELDS, `${label}: the busy snapshot's fields`);
  for (const name of BUSY_FIELDS) {
    assert.equal(typeof report.machine[name], 'number', `${label}: machine.${name} is a number`);
  }
  assert.ok(report.machine.machineCpuPercent >= 0 && report.machine.machineCpuPercent <= 100, `${label}: computer CPU %`);
  assert.ok(report.machine.machineAvailableBytes > 0 && report.machine.metalistMemoryBytes > 0, `${label}: memory`);
}

function standInsOf(report) {
  return report.notes.flatMap(note => note.tags).sort();
}

async function checkUserReport(page, ids) {
  await startEditing(page, ids[0]);
  await page.keyboard.press('End');
  await page.keyboard.type(TYPED);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !window.problemReportMode.isEditing);
  await page.keyboard.down('Meta');
  await page.keyboard.up('Meta');
  await idle(page);
  assert.equal(await paletteListsExport(page), false, 'Export Problem Reports… waits for a kept report');

  // Report a Problem… from edit mode leaves it first.
  await startEditing(page, ids[1]);
  const count = await downloadCount(page);
  await paletteAction(page, 'reportProblem');
  await page.waitForSelector('#problem-report-description', {visible: true});
  assert.equal(await page.evaluate(() => window.problemReportMode.isEditing), false, 'Report a Problem… leaves edit mode');
  assert.equal(await page.$eval('#problem-report-description', box => box.maxLength), MAX_DESCRIPTION);
  await page.type('#problem-report-description', DESCRIPTION);
  await page.click('#problem-report-export-btn');
  const report = JSON.parse(await nextDownload(page, count));
  await page.waitForSelector('#problem-report-description', {hidden: true});
  await idle(page);
  const name = await page.evaluate(() => window.caughtReportNames.at(-1));
  assert.match(name, /^metalist-problem-report-.+\.json$/, 'the file is named as a problem report');

  assert.equal(report.description, DESCRIPTION, 'the sentence exactly as typed');
  assert.equal(report.madeBy, 'user');
  assert.equal(report.error, null);
  assertNoWord(report, 'Report a Problem…');
  assertBusyNumbers(report, 'Report a Problem…');
  assert.deepEqual(report.notes.map(note => note.id).sort(), [...ids].sort(), 'the notes the inputs touched');
  const texts = report.notes.map(note => note.text.redacted);
  assert.ok(texts.some(text => text.startsWith(SHAPED_NOTE)), `a note keeps its shape: ${JSON.stringify(texts)}`);
  assert.ok(texts.some(text => text.includes(FRAC_KEPT)), 'a formula keeps \\frac');
  const typedInNote = report.inputs.filter(input => input.kind === 'type' && input.note === ids[0]);
  assert.deepEqual(typedInNote.map(input => input.typed.redacted), [SHAPED_TYPING], 'the typing as shape only');
  const typed = report.inputs.filter(input => input.kind === 'type').map(input => input.typed.redacted);
  assert.ok(!typed.some(text => text.includes(SHAPED_DESCRIPTION)), `none from the report box: ${JSON.stringify(typed)}`);
  assert.deepEqual(report.inputs.filter(input => LONE_MODIFIER.test(input.code)), [], 'no lone modifier key');
  assert.ok(report.commands.length > 0, 'commands are recorded');
  assert.ok(report.requests.some(request => request.status === HTTP_OK && REQUEST_ID.test(request.requestId)
    && request.server.found), 'requests carry their status and the server\'s record');
  assert.ok(report.view.notesInList >= ids.length && report.view.notesOnScreen > 0
    && report.view.notesOnScreen <= report.view.notesInList, `view size: ${JSON.stringify(report.view)}`);
  const standIns = standInsOf(report);
  assert.deepEqual(standIns.map(tag => tag.split('/').map(part => part.length)).sort(),
    [BUDGET_TAG, FOLDER_TAG].map(tag => tag.split('/').map(part => part.length)).sort(),
    `stand-ins keep each tag's lengths: ${standIns}`);
  assert.equal(await paletteListsExport(page), true, 'Export Problem Reports… once a report is kept');

  const second = await reportProblem(page, '');
  assert.notDeepEqual(standInsOf(second), standIns, 'a second report draws different stand-ins');
  assertNoWord(second, 'second report');
}

async function checkRedErrorReport(page) {
  const count = await downloadCount(page);
  await page.evaluate(async message => {
    const {showFatalError} = await import('/static/js/modules/error-overlay.js');
    const error = new TypeError(message);
    showFatalError(error.message, error.stack, error.name);
  }, ERROR_MESSAGE);
  await page.waitForSelector('#fatal-error-export-report', {visible: true});
  assert.equal(await page.$eval('#fatal-error-export-report', button => button.textContent.trim()), 'Export Report…');
  await page.click('#fatal-error-export-report');
  const report = JSON.parse(await nextDownload(page, count));
  await page.evaluate(() => document.getElementById('fatal-error-overlay').remove());
  assert.equal(report.madeBy, 'overlay');
  assert.equal(report.description, '');
  assert.equal(report.error.class, 'TypeError');
  assert.equal(report.error.message.redacted, SHAPED_ERROR);
  assert.ok(report.error.frames.every(frame => /\.js:\d+/.test(frame)), `frames are code only: ${report.error.frames}`);
  assertNoWord(report, 'Export Report…');
  assertBusyNumbers(report, 'Export Report…');
}

async function checkExportList(page) {
  await paletteAction(page, 'exportProblemReports');
  await page.waitForSelector('#problem-reports-export-btn', {visible: true});
  const kinds = await page.$$eval('.problem-reports-row .problem-reports-kind', rows => rows.map(row => row.textContent.trim()));
  assert.deepEqual(kinds.slice(0, 3), ['TypeError', 'Reported', 'Reported'], 'newest first, with their kinds');
  assert.equal(await page.$$eval('.problem-reports-row input:checked', boxes => boxes.length), kinds.length, 'all ticked');
  const count = await downloadCount(page);
  await page.click('#problem-reports-export-btn');
  const reports = JSON.parse(await nextDownload(page, count));
  await page.waitForSelector('#problem-reports-export-btn', {hidden: true});
  assert.equal(reports.length, kinds.length, 'one file of every report ticked');
  assert.equal(reports[0].error.class, 'TypeError');
  assertNoWord(reports, 'Export Problem Reports…');
  const name = await page.evaluate(() => window.caughtReportNames.at(-1));
  assert.match(name, /^metalist-problem-reports-.+\.json$/);
}

// A report made with no vault open, as the login page makes it: no session, no notes, kept
// nowhere; one that names notes is refused.
async function checkReportWithNoVault(page) {
  const answers = await page.evaluate(async () => {
    const {CONFIG} = await import('/static/js/modules/config.js');
    const {pageDraft, keptReports, NO_ERROR} = await import('/static/js/modules/problem-reports/report-maker.js');
    const keptBefore = (await keptReports()).length;
    const draft = {...pageDraft({madeBy: 'overlay', description: '', error: NO_ERROR}), noteIds: [], search: '', editingNote: ''};
    const send = body => fetch(CONFIG.API.PROBLEM_REPORTS.MAKE_UNSAVED, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    const made = await send(draft);
    const refused = await send({...draft, noteIds: ['some-note']});
    return {
      status: made.status, body: await made.json(), refused: refused.status,
      keptBefore, keptAfter: (await keptReports()).length,
    };
  });
  assert.equal(answers.status, HTTP_OK);
  assert.deepEqual(Object.keys(answers.body), ['report'], 'a report from the login page has no id: it is kept nowhere');
  assert.deepEqual(answers.body.report.notes, []);
  assertBusyNumbers(answers.body.report, 'login-page report');
  assert.equal(answers.keptAfter, answers.keptBefore, 'nothing kept');
  assert.equal(answers.refused, HTTP_UNPROCESSABLE, 'a login-page report naming notes is refused');
}

export async function checkProblemReports(page) {
  const ids = await makeNotes(page);
  await catchDownloads(page);
  await runThenCleanUp('problem reports', async () => {
    await checkUserReport(page, ids);
    await checkRedErrorReport(page);
    await checkExportList(page);
    await checkReportWithNoVault(page);
  }, async () => {
    await releaseDownloads(page);
    await deleteNotes(page, ids);
    await idle(page);
  });
}
