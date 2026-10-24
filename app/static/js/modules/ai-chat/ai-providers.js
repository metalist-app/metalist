// The AI providers MetaList offers, in the order it lists them, with the model a vault
// starts on: the browser's copy of app/services/ai_catalog.py (test_ai_models.py checks
// that the two match).
export const AI_PROVIDERS = Object.freeze([
    Object.freeze({ provider: 'openai', label: 'OpenAI', defaultModel: 'gpt-5.6-luna' }),
    Object.freeze({ provider: 'anthropic', label: 'Claude', defaultModel: 'claude-sonnet-5-5' }),
    Object.freeze({ provider: 'gemini', label: 'Gemini', defaultModel: 'gemini-3.8-flash' }),
]);

export function isAiProvider(provider) {
    return AI_PROVIDERS.some((entry) => entry.provider === provider);
}

export function aiProvider(provider) {
    const entry = AI_PROVIDERS.find((candidate) => candidate.provider === provider);
    if (entry === undefined) {
        throw new Error(`Unsupported AI provider: ${provider}`);
    }
    return entry;
}
