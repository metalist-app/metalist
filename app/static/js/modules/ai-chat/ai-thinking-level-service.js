export const DEFAULT_AI_THINKING_LEVEL = 'low';

// In menu order: the most thinking at the top.
export const AI_THINKING_LEVEL_OPTIONS = Object.freeze([
    Object.freeze({ value: 'high', label: 'High Thinking' }),
    Object.freeze({ value: 'medium', label: 'Medium Thinking' }),
    Object.freeze({ value: 'low', label: 'Low Thinking' }),
    Object.freeze({ value: 'off', label: 'Thinking Off' }),
]);

const AI_THINKING_LEVEL_VALUES = new Set(
    AI_THINKING_LEVEL_OPTIONS.map((option) => option.value),
);


export function validateAiThinkingLevel(thinkingLevel) {
    if (typeof thinkingLevel !== 'string' || !AI_THINKING_LEVEL_VALUES.has(thinkingLevel)) {
        throw new Error(`Unsupported AI thinking level: ${thinkingLevel}`);
    }
    return thinkingLevel;
}


export function isThinkingLevelAvailableForModel({ model, thinkingLevel }) {
    if (typeof model !== 'string') {
        throw new Error('Thinking level requires model string');
    }
    validateAiThinkingLevel(thinkingLevel);
    return true;
}


export function normalizeThinkingLevelForModel({ model, thinkingLevel }) {
    isThinkingLevelAvailableForModel({ model, thinkingLevel });
    return validateAiThinkingLevel(thinkingLevel);
}
