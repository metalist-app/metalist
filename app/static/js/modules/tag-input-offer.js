// What a field that asks for a tag offers as you type (docs/ui/modals.md, "Fields that take a
// tag"): the search bar's tags by how many notes have them, those whose name starts with the letters first, minus
// built-in tags and the ones already chosen. Nothing for "a phrase in quotes" or text with a
// space, which is no tag.
const MAX_SHOWN = 8;
const NOT_A_TAG = /^["']|\s/u;

// The tags to offer for what is typed, from the search bar's ranked suggestions.
export function tagsToOffer(typed, suggestions, chosen) {
    if (typeof typed !== 'string' || !Array.isArray(suggestions) || !Array.isArray(chosen)) {
        throw new Error('tagsToOffer requires the typed text, the suggestions and the chosen tags');
    }
    const text = typed.trim();
    if (text === '' || NOT_A_TAG.test(text)) {
        return [];
    }
    const left = new Set(chosen.map((tag) => tag.toLowerCase()));
    const prefix = text.toLowerCase();
    const tags = suggestions.filter((tag) => typeof tag === 'string' && !tag.startsWith('@') && !left.has(tag.toLowerCase()));
    const starting = tags.filter((tag) => tag.toLowerCase().startsWith(prefix));
    const laterPart = tags.filter((tag) => !tag.toLowerCase().startsWith(prefix));
    return [...starting, ...laterPart].slice(0, MAX_SHOWN);
}

export function isTagText(typed) {
    const text = typed.trim();
    return text !== '' && !NOT_A_TAG.test(text);
}

