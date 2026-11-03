import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A picture shows at its own size, never larger (the maintainer, 2026-11-02: small images
// stretched to the card's width "are weird looking now"); a large one still fills the card.

const REQUESTS_QUIET_MS = 300;
const SMALL_PX = 64;
const LARGE = {width: 1600, height: 1000};
// The card's widest picture (main.css, .note-file-image-embed).
const CARD_MAX_PX = 520;
const LOAD_TIMEOUT_MS = 20000;

async function picturesShown(page, ids) {
  return page.evaluate(ids => ids.map(id => {
    const note = document.querySelector(`.note[data-note-id="${id}"]`);
    const image = note.querySelector('.note-file-image-preview');
    const frame = note.querySelector('.note-file-image-preview-frame');
    const box = image.getBoundingClientRect();
    return {width: Math.round(box.width), height: Math.round(box.height), frameWidth: Math.round(frame.getBoundingClientRect().width)};
  }), ids);
}

export async function checkImageSizes(page) {
  const ids = await page.evaluate(async ({small, large}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const picture = async (width, height, name) => {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      canvas.getContext('2d').fillRect(0, 0, width, height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      return (await FilesAPI.uploadFile(new File([blob], name, {type: 'image/png'}))).file_id;
    };
    const made = [];
    for (const [width, height, name] of [[small, small, 'icon.png'], [large.width, large.height, 'photo.png']]) {
      const fileId = await picture(width, height, name);
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>![[${fileId}]]</p>`, 'imagesizetest');
      made.push(note.id);
    }
    return made;
  }, {small: SMALL_PX, large: LARGE});
  await runThenCleanUp('image sizes', async () => {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await waitForAppQuiet(page, REQUESTS_QUIET_MS);
    await page.waitForFunction(ids => ids.every(id => document.querySelector(`.note[data-note-id="${id}"] .note-file-image-embed`)?.dataset.previewState === 'loaded'),
      {timeout: LOAD_TIMEOUT_MS}, ids);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const [small, large] = await picturesShown(page, ids);
    assert.deepEqual([small.width, small.height], [SMALL_PX, SMALL_PX], 'a small picture shows at its own size');
    assert.ok(small.frameWidth <= SMALL_PX + 2, `its frame hugs it (${small.frameWidth} px)`);
    assert.equal(large.frameWidth, CARD_MAX_PX, 'a large picture still fills the card');
    assert.equal(large.height, Math.round(large.width * LARGE.height / LARGE.width), 'in its proportions');
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
