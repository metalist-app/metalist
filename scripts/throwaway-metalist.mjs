// A throwaway MetaList for looking at a change (AGENTS.md, "Early Look"): its own temporary
// data folder, always at http://127.0.0.1:8600 (a free HTTPS port beside it; never the
// user's vault or 8443), filled with
// made-up notes that exercise rendering. It prints its address and runs until Ctrl-C, which
// stops it and deletes its data. Start it with `npm run throwaway`; `--keep` keeps the data
// folder, `--empty` starts with no sample notes.

import {spawn} from 'node:child_process';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {createServer} from 'node:net';
import puppeteer from 'puppeteer';
import {closeBrowser, installedBrowserExecutable} from './installed-browser.mjs';

// The same address every time, so a bookmark or an open page keeps working (2026-10-29).
const THROWAWAY_PORT = 8600;
const SERVER_START_TIMEOUT_MS = 30_000;
// What the server logs once it answers requests (uvicorn).
const SERVER_READY_LINE = 'Uvicorn running on';
const APP_READY_TIMEOUT_MS = 30_000;
// process.argv holds node and the script before the options.
const FIRST_OPTION_INDEX = 2;
const LONG_NOTE_LINES = 40;
const TREE_DEPTH = 5;
const OPTIONS = new Set(process.argv.slice(FIRST_OPTION_INDEX));
for (const option of OPTIONS) {
  if (!['--keep', '--empty'].includes(option)) throw new Error(`Unknown option ${option}: use --keep or --empty`);
}

// Stops with a clear message when the port is taken: never a quiet move to another port.
async function requirePortFree(port) {
  const probe = createServer();
  await new Promise((free, taken) => {
    probe.once('error', error => taken(new Error(
      `Port ${port} is taken (${error.code}): another throwaway MetaList may still be running; stop it with Ctrl-C, or find what uses the port with: lsof -i :${port}`,
    )));
    probe.listen(port, '127.0.0.1', free);
  });
  await new Promise(done => probe.close(done));
}

async function freePort() {
  const probe = createServer();
  await new Promise(done => probe.listen(0, '127.0.0.1', done));
  const port = probe.address().port;
  await new Promise(done => probe.close(done));
  return port;
}

// Made-up notes, top to bottom: each [text lines, tag bar], with `children` and `collapsed` where set.
function sampleNotes() {
  const longLines = Array.from({length: LONG_NOTE_LINES}, (_, index) => `Line ${index + 1} of a long note about tide pools and the creatures in them.`);
  return [
    {lines: ['Sample notes for a quick look (made up)'], tags: 'sample'},
    {lines: ['# Trip plan', '', 'A **bold** start, then a table:', '', '| Day | City | Notes |', '| --- | --- | --- |', '| 1 | Lisbon | Tram 28, custard tarts |', '| 2 | Porto | Bridge walk at dusk |'], tags: '@markdown'},
    {lines: ['Name,Role,Started', 'Ada,Analyst,2024-03-01', 'Grace,Admiral,2023-11-15', 'Linus,Maintainer,2025-01-20'], tags: '@csv'},
    {lines: ['graph TD', '  Idea --> Draft', '  Draft --> Review', '  Review -->|changes| Draft', '  Review --> Done'], tags: '@mermaid'},
    {lines: ['e^{i\\pi} + 1 = 0'], tags: '@LaTeX'},
    {lines: ['def greet(name):', '    """Say hello."""', '    return f"Hello, {name}!"', '', 'print(greet("tide pool"))'], tags: '@code=python'},
    {lines: ['{"trip": "Lisbon", "days": 2, "budget": {"food": 120, "travel": 80}}'], tags: '@json'},
    {lines: ['Water the plants'], tags: '@todo'},
    {lines: ['A deep tree'], tags: 'sample', depth: TREE_DEPTH},
    {lines: ['A collapsed note with children'], tags: 'sample', collapsed: true, children: ['First hidden child', 'Second hidden child']},
    {lines: longLines, tags: 'sample long'},
    // References are filled in once the notes they point at exist.
    {lines: ['A link to the trip plan: [[REF:1]]', 'And the CSV embedded:', '![[REF:2]]'], tags: 'sample references'},
  ];
}

async function seed(page) {
  await page.evaluate(async notes => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const escape = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const html = lines => lines.map(line => `<div>${line === '' ? '<br>' : escape(line)}</div>`).join('');
    const ids = [];
    // New notes go to the top, so the last is created first.
    for (const note of [...notes].reverse()) {
      const created = await NotesAPI.createNote(null, '');
      ids.unshift(created.id);
      await NotesAPI.saveNote(created.id, html(note.lines), note.tags);
      if (note.children) {
        for (const child of [...note.children].reverse()) {
          const made = await NotesAPI.createChild(created.id, '');
          await NotesAPI.saveNote(made.id, html([child]), '');
        }
      }
      if (note.depth) {
        let parent = created.id;
        for (let level = 1; level <= note.depth; level += 1) {
          const made = await NotesAPI.createChild(parent, '');
          await NotesAPI.saveNote(made.id, html([`Level ${level}`]), '');
          parent = made.id;
        }
      }
      if (note.collapsed) await NotesAPI.collapseNote(created.id);
    }
    for (const [index, note] of notes.entries()) {
      const withIds = note.lines.map(line => line.replace(/REF:(\d+)/g, (_, at) => ids[Number(at)]));
      if (withIds.join() !== note.lines.join()) await NotesAPI.saveNote(ids[index], html(withIds), note.tags);
    }
  }, sampleNotes());
}

const directory = await mkdtemp(join(tmpdir(), 'metalist-throwaway-'));
const port = THROWAWAY_PORT;
await requirePortFree(port);
let httpsPort = await freePort();
while (httpsPort === port) httpsPort = await freePort();
const origin = `http://127.0.0.1:${port}`;
const env = {...process.env};
for (const key of Object.keys(env)) {
  if (key.startsWith('METALIST_') || key === 'TEST_MODE') delete env[key];
}
Object.assign(env, {
  METALIST_DATA_DIRECTORY: directory, METALIST_ENVIRONMENT: 'production', METALIST_PORT: String(port),
  METALIST_HTTPS_PORT: String(httpsPort), API_PREFIX: '/api2', V1_API_PREFIX: '/api',
});
const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const server = spawn(resolve(python), ['serve_namespace.py', '--namespace', 'default', '--port', String(port)], {env, stdio: ['ignore', 'pipe', 'pipe']});

// Ready once the server says it is listening; its output is kept for an error.
function serverReady() {
  let output = '';
  return new Promise((ready, failed) => {
    const timer = setTimeout(() => failed(new Error(`The throwaway server did not start:\n${output}`)), SERVER_START_TIMEOUT_MS);
    const listen = chunk => {
      output += chunk;
      if (output.includes(SERVER_READY_LINE)) {
        clearTimeout(timer);
        // Stop collecting: the streams keep flowing, their output dropped.
        server.stdout.off('data', listen);
        server.stderr.off('data', listen);
        ready();
      }
    };
    server.stdout.on('data', listen);
    server.stderr.on('data', listen);
    server.on('exit', code => failed(new Error(`The throwaway server exited (${code}):\n${output}`)));
  });
}

async function stop() {
  server.kill();
  if (!OPTIONS.has('--keep')) await rm(directory, {recursive: true, force: true});
  process.exit(0);
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
// The terminal closing stops it too (stop-children-on-exit.mjs).
process.on('SIGHUP', stop);

await serverReady();

if (!OPTIONS.has('--empty')) {
  const browser = await puppeteer.launch({headless: true, browser: 'chrome', executablePath: installedBrowserExecutable('chrome', process.env)});
  const page = await browser.newPage();
  await page.goto(origin, {waitUntil: 'networkidle0'});
  await page.waitForSelector('[data-app-ready="true"]', {timeout: APP_READY_TIMEOUT_MS});
  await seed(page);
  await closeBrowser(browser);
}
console.log(`Throwaway MetaList at ${origin} (data: ${directory}). Ctrl-C stops it${OPTIONS.has('--keep') ? '' : ' and deletes its data'}.`);
