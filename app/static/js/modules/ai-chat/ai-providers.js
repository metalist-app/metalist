// The AI providers MetaList offers, in the order it lists them, with the model a vault
// starts on and where its users see what they spent: the browser's copy of
// app/services/ai_catalog.py (test_ai_models.py checks that the two match).
export const AI_PROVIDERS = Object.freeze([
    Object.freeze({ provider: 'openai', label: 'OpenAI', defaultModel: 'gpt-5.6-luna', billingUrl: 'https://platform.openai.com/usage' }),
    Object.freeze({ provider: 'anthropic', label: 'Anthropic', defaultModel: 'claude-sonnet-5-5', billingUrl: 'https://platform.claude.com/usage' }),
    Object.freeze({ provider: 'gemini', label: 'Google', defaultModel: 'gemini-3.8-flash', billingUrl: 'https://aistudio.google.com/usage' }),
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
