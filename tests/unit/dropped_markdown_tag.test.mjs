import assert from 'node:assert/strict';
import test from 'node:test';

import { tagsAfterTextDrop } from '../../app/static/js/modules/mode-manager/services/dropped-markdown-tag.js';

// A .md file dropped into an empty note and made a note is tagged @markdown (the maintainer,
// 2026-11-18: it came in as its source, since the tag was not added).

test('a Markdown file made a note in an empty note adds @markdown', () => {
    assert.equal(tagsAfterTextDrop({ tags: '', fileNames: ['readme.md'], noteIsEmpty: true }), '@markdown');
    assert.equal(tagsAfterTextDrop({ tags: 'ML3', fileNames: ['Plan.MARKDOWN'], noteIsEmpty: true }), 'ML3 @markdown');
    assert.equal(tagsAfterTextDrop({ tags: '', fileNames: ['a.txt', 'b.md'], noteIsEmpty: true }), '@markdown');
});

test('the tags stay as they are otherwise', () => {
    assert.equal(tagsAfterTextDrop({ tags: 'ML3', fileNames: ['notes.txt'], noteIsEmpty: true }), 'ML3', 'no Markdown file');
    assert.equal(tagsAfterTextDrop({ tags: 'ML3', fileNames: ['readme.md'], noteIsEmpty: false }), 'ML3', 'the note already holds text');
    assert.equal(tagsAfterTextDrop({ tags: 'ML3 @Markdown', fileNames: ['readme.md'], noteIsEmpty: true }), 'ML3 @Markdown', 'already tagged');
});
