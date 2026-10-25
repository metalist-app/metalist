// A search's terms as the phone shows them: one pill per term, removable with one tap
// (docs/ready-to-build/phone-prototype.md, §2). A term is a run of non-space text, or a
// quoted phrase kept whole; a leading minus makes it an exclusion. The search syntax itself
// is read by search-syntax-service.js; this only splits it for display and removal.

const EXCLUSION_PREFIX = '-';
const QUOTES = new Set(['"', "'"]);

function termEnd(query, start) {
    let index = start;
    if (query[index] === EXCLUSION_PREFIX) {
        index += 1;
    }
    if (QUOTES.has(query[index])) {
        const closing = query.indexOf(query[index], index + 1);
        if (closing !== -1) {
            return closing + 1;
        }
    }
    while (index < query.length && !/\s/u.test(query[index])) {
        index += 1;
    }
    return index;
}

function termTexts(query) {
    if (typeof query !== 'string') {
        throw new Error('A search must be text');
    }
    const terms = [];
    let index = 0;
    while (index < query.length) {
        if (/\s/u.test(query[index])) {
            index += 1;
            continue;
        }
        const end = termEnd(query, index);
        terms.push(query.slice(index, end));
        index = end;
    }
    return terms;
}

export function searchTermsOf(query) {
    return termTexts(query).map((text) => ({ text, isExclusion: text.startsWith(EXCLUSION_PREFIX) && text.length > 1 }));
}

export function withoutSearchTerm(query, termIndex) {
    const terms = termTexts(query);
    if (!Number.isInteger(termIndex) || termIndex < 0 || termIndex >= terms.length) {
        throw new Error(`The search has no term ${termIndex}`);
    }
    return terms.filter((_, index) => index !== termIndex).join(' ');
}

export function withSearchTerm(query, tag) {
    if (typeof tag !== 'string' || tag.trim() === '') {
        throw new Error('A search term must be non-empty text');
    }
    const terms = termTexts(query);
    if (terms.includes(tag)) {
        return terms.join(' ');
    }
    return [...terms, tag].join(' ');
}
