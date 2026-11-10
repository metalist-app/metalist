import assert from 'node:assert/strict';
import test from 'node:test';
import { ARROW_CARD_COUNT, createCardDeck, createNoteCardDealer } from '../../app/static/js/modules/skin-arrow-cards.js';

function seededRandom(seed) {
    let state = seed;
    return () => {
        state = (state * 16807) % 2147483647;
        return state / 2147483647;
    };
}

test('every card is dealt once before any card comes back', () => {
    const deal = createCardDeck(ARROW_CARD_COUNT, seededRandom(7));
    for (let deck = 0; deck < 50; deck += 1) {
        const dealt = Array.from({ length: ARROW_CARD_COUNT }, deal);
        assert.equal(new Set(dealt).size, ARROW_CARD_COUNT);
    }
});

test('no card follows itself across a reshuffle', () => {
    for (let seed = 1; seed < 200; seed += 1) {
        const deal = createCardDeck(3, seededRandom(seed));
        const dealt = Array.from({ length: 300 }, deal);
        dealt.slice(1).forEach((card, index) => assert.notEqual(card, dealt[index]));
    }
});

test('the order differs from deck to deck', () => {
    const deal = createCardDeck(ARROW_CARD_COUNT, seededRandom(11));
    const first = Array.from({ length: ARROW_CARD_COUNT }, deal);
    const second = Array.from({ length: ARROW_CARD_COUNT }, deal);
    assert.notDeepEqual(first, second);
});

test('a note keeps the card it was dealt', () => {
    const cardOf = createNoteCardDealer(createCardDeck(ARROW_CARD_COUNT, seededRandom(3)));
    const first = cardOf('note-a');
    cardOf('note-b');
    assert.equal(cardOf('note-a'), first);
});
