// What the Illuminated skin swaps when it draws a note's words as old English (docs/ui/skins.md).

const THOU_VERBS = [
    ['know', 'knowest'], ['want', 'wantest'], ['need', 'needest'], ['think', 'thinkest'], ['see', 'seest'], ['say', 'sayest'],
    ['like', 'likest'], ['love', 'lovest'], ['make', 'makest'], ['take', 'takest'], ['give', 'givest'], ['come', 'comest'],
    ['go', 'goest'], ['get', 'gettest'], ['mean', 'meanest'], ['can', 'canst'], ['could', 'couldst'], ['would', 'wouldst'],
    ['should', 'shouldst'], ['were', 'wert'], ['are', 'art'], ['have', 'hast'], ['will', 'wilt'], ['do', 'dost'],
];

const ASKED_VERBS = [
    ['are', 'art'], ['have', 'hast'], ['will', 'wilt'], ['do', 'dost'], ['can', 'canst'],
    ['could', 'couldst'], ['would', 'wouldst'], ['should', 'shouldst'],
];

export const TWO_WORD_SWAPS = new Map([
    ...THOU_VERBS.map(([verb, olde]) => [`you ${verb}`, `thou ${olde}`]),
    ...ASKED_VERBS.map(([verb, olde]) => [`${verb} you`, `${olde} thou`]),
    ['it is', "'tis"], ['it was', "'twas"], ['it will', "'twill"], ['there is', 'there be'], ['there are', 'there be'],
    ['i think', 'methinks'], ['thank you', 'gramercy'], ['to the', 'unto ye'], ['of the', "o' ye"], ['to my', 'unto my'],
    ['to your', 'unto thy'], ['to our', 'unto our'], ['to their', 'unto their'],
]);

export const WORD_SWAPS = new Map([
    // Words.
    ['your', 'thy'], ['yours', 'thine'], ['the', 'ye'], ['has', 'hath'], ['does', 'doth'], ['before', 'ere'],
    ['often', 'oft'], ['over', "o'er"], ['ever', "e'er"], ['never', "ne'er"], ['between', 'betwixt'], ['among', 'amongst'],
    ['while', 'whilst'], ['against', "'gainst"], ['perhaps', 'perchance'], ['maybe', 'mayhap'], ['yes', 'aye'],
    ['why', 'wherefore'], ['will', 'shall'], ['soon', 'anon'], ['very', 'exceeding'], ['really', 'verily'], ['truly', 'verily'],
    ['indeed', 'forsooth'], ['today', 'this day'], ['tonight', 'this night'], ['tomorrow', 'on ye morrow'],
    ['morning', 'morn'], ['evening', 'eventide'],
    // Contractions.
    ["it's", "'tis"], ["i'm", 'I am'], ["you're", 'thou art'], ["you've", 'thou hast'], ["you'll", 'thou wilt'],
    ["don't", 'do not'], ["doesn't", 'doth not'], ["isn't", 'is not'], ["didn't", 'did not'], ["won't", 'shall not'], ["can't", 'cannot'],
    // Courtesies.
    ['hello', 'hail'], ['hi', 'hail'], ['goodbye', 'fare thee well'], ['please', 'prithee'], ['thanks', 'gramercy'],
    // Things.
    ['shop', 'shoppe'], ['store', 'shoppe'], ['old', 'olde'], ['town', 'towne'], ['money', 'coin'], ['doctor', 'physician'],
    ['car', 'carriage'], ['cars', 'carriages'], ['email', 'missive'], ['emails', 'missives'], ['message', 'missive'], ['messages', 'missives'],
    ['meeting', 'council'], ['meetings', 'councils'], ['food', 'victuals'], ['beer', 'ale'], ['book', 'tome'], ['books', 'tomes'],
    ['friend', 'good fellow'], ['friends', 'good fellows'], ['computer', 'reckoning engine'], ['computers', 'reckoning engines'],
    // How things are.
    ['great', 'wondrous'], ['bad', 'foul'], ['big', 'mighty'], ['small', 'wee'], ['beautiful', 'fair'], ['happy', 'merry'],
    ['sad', 'woeful'], ['angry', 'wroth'], ['tired', 'weary'], ['weird', 'wyrd'],
]);

export const THEE_AFTER = new Set([
    'to', 'for', 'with', 'at', 'from', 'of', 'by', 'on', 'in', 'about', 'see', 'tell', 'give', 'thank', 'thanked', 'ask', 'call', 'help',
]);
export const VERB_SUBJECTS = new Set(['he', 'she', 'it']);
export const NOT_VERBS = new Set(['is', 'was', 'has', 'does', 'this', 'his', 'its', 'us', 'as', 'less', 'always', 'perhaps', 'thus', 'yes', 'across', 'besides']);

// The shortest word an ending respells, in letters: shorter words are too often other words
// ('bed', 'king', 'own').
const SHORT_WORD_LETTERS = 4;
const MIDDLING_WORD_LETTERS = 5;
const LONG_WORD_LETTERS = 6;

// Old spellings, by a word's ending: the first that fits.
export const SPELLING_ENDINGS = [
    { pattern: /([^s])tion$/, replacement: '$1cioun', minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /ing$/, replacement: 'ynge', minLetters: LONG_WORD_LETTERS },
    { pattern: /([^aeiouytd])ed$/, replacement: "$1'd", minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /ness$/, replacement: 'nesse', minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /less$/, replacement: 'lesse', minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /ful$/, replacement: 'full', minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /ic$/, replacement: 'ick', minLetters: MIDDLING_WORD_LETTERS },
    { pattern: /own$/, replacement: 'owne', minLetters: SHORT_WORD_LETTERS },
    { pattern: /(oo[a-z])$/, replacement: '$1e', minLetters: SHORT_WORD_LETTERS },
    { pattern: /([aeiou]ll)$/, replacement: '$1e', minLetters: SHORT_WORD_LETTERS },
    { pattern: /([^aeiouy])y$/, replacement: '$1ie', minLetters: SHORT_WORD_LETTERS },
];

// Words those endings would get wrong.
export const NOT_RESPELLED = new Set([
    'thing', 'nothing', 'something', 'anything', 'everything', 'during', 'string', 'spring', 'bring', 'hundred', 'sacred', 'naked', 'wicked',
]);
