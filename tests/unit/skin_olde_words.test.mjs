import assert from 'node:assert/strict';
import test from 'node:test';
import { oldeTextParts } from '../../app/static/js/modules/skin-olde-words.js';

const drawn = (text) => oldeTextParts(text).map((part) => part.text).join('');
const real = (text) => oldeTextParts(text).map((part) => ('original' in part ? part.original : part.text)).join('');

for (const [written, expected] of [
    ['The birch waits for you', 'Ye birch waits for thee'],
    ['You are late', 'Thou art late'],
    ['you have it', 'thou hast it'],
    ['It is raining', "'Tis rainynge"],
    ['Your shop has gone', 'Thy shoppe hath gone'],
    ['She walks to town', 'She walketh to towne'],
    ['he goes and she tries', 'he goeth and she trieth'],
    ['THE END', 'YE END'],
    ['how to give "mutation" powers to the AI?', 'how to give "mutacioun" powers unto ye AI?'],
    ['Do you know the way?', 'Dost thou know ye way?'],
    ['you know the town', 'thou knowest ye towne'],
    ['I think it was a great meeting', "Methinks 'twas a wondrous council"],
    ["Don't worry, it's a small book", "Do not worrie, 'tis a wee tome"],
    ['Thank you, my friend', 'Gramercy, my good fellow'],
    ['We walked home quickly from the music shop', "We walk'd home quicklie from ye musick shoppe"],
    ['See you tomorrow morning', 'See thee on ye morrow morn'],
    ['There are good books', 'There be goode tomes'],
    ['That is weird', 'That is wyrd'],
    ['This is not a thing', 'This is not a thing'],
]) {
    test(`"${written}" is drawn "${expected}"`, () => {
        assert.equal(drawn(written), expected);
    });
}

for (const written of ['two long walks', 'this class', 'she is here', 'Bridge walk at dusk', '12 + 30', '', 'iPhone and GitHub', 'see a@the.com or the/path', 'old-fashioned']) {
    test(`"${written}" keeps its words where it should`, () => {
        assert.equal(real(written), written);
    });
}

test('a noun in the plural is not a verb', () => {
    assert.equal(drawn('two long walks'), 'two long walks');
});

test('every swap keeps the real words, spaces and punctuation', () => {
    for (const written of ['Hello, you!  It is the old town.', 'Maybe\tyou are; perhaps not', "You've seen the shop's sign"]) {
        assert.equal(real(written), written);
    }
});

test('names, addresses and mixed-case words are left alone', () => {
    assert.equal(drawn('We met Mary in Harry Street'), 'We met Mary in Harry Street');
    assert.equal(drawn('iPhone and GitHub'), 'iPhone and GitHub');
    assert.equal(drawn('see a@the.com or the/path'), 'see a@the.com or the/path');
    assert.equal(drawn('old-fashioned'), 'old-fashioned');
    assert.equal(drawn('Ask the example.com team'), 'Ask ye example.com team');
});

test('a curly apostrophe is an apostrophe', () => {
    assert.equal(drawn('it\u2019s here'), "'tis here");
});
