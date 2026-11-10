// Ye Olde Scrypte's fold arrows are pictures dealt from a deck: every picture once, in no
// particular order, then a reshuffle (docs/ui/skins.md).
export const ARROW_CARD_COUNT = 16;
const MIN_DECK_SIZE = 2;

function shuffled(cardCount, randomNumber) {
    const cards = Array.from({ length: cardCount }, (unused, card) => card);
    for (let index = cards.length - 1; index > 0; index -= 1) {
        const other = Math.floor(randomNumber() * (index + 1));
        [cards[index], cards[other]] = [cards[other], cards[index]];
    }
    return cards;
}

// A new deck never starts with the card the last one ended on, so no two in a row match.
export function createCardDeck(cardCount, randomNumber) {
    if (!Number.isInteger(cardCount) || cardCount < MIN_DECK_SIZE) {
        throw new Error('A deck needs at least two cards');
    }
    let cards = [];
    let lastCard = null;
    return () => {
        if (cards.length === 0) {
            cards = shuffled(cardCount, randomNumber);
            if (cards[cards.length - 1] === lastCard) {
                cards.reverse();
            }
        }
        lastCard = cards.pop();
        return lastCard;
    };
}

// Each note keeps its card for as long as the page is open: it doesn't change when the note is
// folded or redrawn, or when the window of loaded notes moves.
export function createNoteCardDealer(deal) {
    const cardByNoteId = new Map();
    return (noteId) => {
        if (!cardByNoteId.has(noteId)) {
            cardByNoteId.set(noteId, deal());
        }
        return cardByNoteId.get(noteId);
    };
}
