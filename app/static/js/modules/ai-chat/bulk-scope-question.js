/**
 * Pure description of tag proposals' scope question: the scope's size against the
 * evidence budget (the server label), "<verb> all N", "Use first K only" when a
 * leading prefix fits, and Cancel last, with a focus selector when the focus is
 * not already fixed.
 */

export const TAG_FOCUS_CHOICES = Object.freeze([
    Object.freeze(['existing', 'Existing tags only']),
    Object.freeze(['new', 'New tags only']),
    Object.freeze(['both', 'Both, favoring existing tags']),
]);

const SCOPE_QUESTIONS = Object.freeze({
    tag_scope_confirmation: Object.freeze({
        allVerb: 'Tag',
        offersPrefix: (event) => event.prefix_root_count > 0,
    }),
});

function requireCount(event, field) {
    if (!Number.isInteger(event[field]) || event[field] < 0) {
        throw new TypeError(`Scope question requires non-negative ${field}`);
    }
}

export function describeScopeQuestion(event) {
    if (typeof event !== 'object' || event === null) {
        throw new TypeError('Scope question must be an object');
    }
    const question = SCOPE_QUESTIONS[event.kind];
    if (question === undefined) throw new Error(`Unknown bulk question kind ${event.kind}`);
    for (const field of ['root_count', 'batch_count', 'prefix_root_count']) {
        requireCount(event, field);
    }
    let focusDefault = null;
    if (event.kind === 'tag_scope_confirmation') {
        if (typeof event.chooses_focus !== 'boolean') {
            throw new Error('Tag scope question requires chooses_focus');
        }
        if (!TAG_FOCUS_CHOICES.some(([value]) => value === event.focus)) {
            throw new Error('Tag scope question requires a valid focus');
        }
        if (event.chooses_focus) focusDefault = event.focus;
    }
    let prefixLabel = null;
    if (question.offersPrefix(event)) {
        if (event.prefix_root_count < 1 || event.prefix_root_count >= event.root_count) {
            throw new Error('Scope question prefix must be a proper leading subset');
        }
        prefixLabel = `Use first ${event.prefix_root_count} only`;
    }
    return {
        allLabel: `${question.allVerb} all ${event.root_count}`,
        prefixLabel,
        focusDefault,
    };
}

/** Answer value the server expects for a button, given the selected focus if any. */
export function scopeAnswerValue(event, choice, focusValue) {
    const description = describeScopeQuestion(event);
    if (choice === 'cancel') return 'cancel';
    if (choice !== 'all' && choice !== 'prefix') throw new Error(`Unknown scope choice ${choice}`);
    if (choice === 'prefix' && description.prefixLabel === null) {
        throw new Error('This scope question offers no prefix');
    }
    if (description.focusDefault === null) {
        if (focusValue !== null) throw new Error('This scope question has no focus selector');
        return choice === 'all' ? 'proceed' : 'use_prefix';
    }
    if (!TAG_FOCUS_CHOICES.some(([value]) => value === focusValue)) {
        throw new Error('Tag scope answer requires a selected focus');
    }
    return choice === 'all' ? `focus_${focusValue}` : `prefix_focus_${focusValue}`;
}
