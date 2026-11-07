import assert from 'node:assert/strict';
import {existsSync, readdirSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import test from 'node:test';

import {prepareScaleVault} from '../../scripts/browser-scale-regressions.mjs';

// A small vault: the preparation is checked, not the scale.
const NOTE_COUNT = 60;
const FILE_COUNT = 3;
const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';

test('the scale server gets a generated vault, its import folder, the scripted AI and the answered folder dialog', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'scale-prepare-'));
  try {
    const env = {...process.env, METALIST_DATA_DIRECTORY: directory};
    const rootCount = prepareScaleVault({python: resolve(python), directory, env, noteCount: NOTE_COUNT, fileCount: FILE_COUNT});
    assert(Number.isInteger(rootCount) && rootCount > 0 && rootCount <= NOTE_COUNT, `the root count comes from the generator: ${rootCount}`);
    assert(existsSync(join(directory, 'namespaces', 'default')), 'the vault is written in the default namespace');
    const importFolder = join(directory, 'import-files');
    assert.equal(env.METALIST_TEST_PICK_FOLDER, importFolder);
    const files = readdirSync(importFolder, {recursive: true}).filter(name => name.endsWith('.md'));
    assert.equal(files.length, FILE_COUNT);
    assert(existsSync(env.METALIST_SCRIPTED_AI), 'the scripted AI is a file in the repository');
    assert(env.METALIST_SCRIPTED_AI.endsWith(join('tests', 'fixtures', 'scripted-ai', 'search-view.json')));
  } finally {
    await rm(directory, {recursive: true, force: true});
  }
});

test('preparing the scale server refuses a vault of no notes', async () => {
  assert.throws(() => prepareScaleVault({python, directory: tmpdir(), env: {}, noteCount: 0, fileCount: FILE_COUNT}), /note count/);
  assert.throws(() => prepareScaleVault({python, directory: tmpdir(), env: {}, noteCount: NOTE_COUNT, fileCount: 0}), /file count/);
});
