import { isAiProvider } from './ai-providers.js';

// One setting: how much of the model's context window an answer, or a batch of a summary or of
// tag suggestions, may fill (app/services/agent/retrieval_settings.py).
export const AGENT_RETRIEVAL_PREFERENCE_KEYS = Object.freeze({
    windowPercent: 'pref.ai.retrieval.window_percent',
});

const DEFAULT_WINDOW_PERCENT = 50;
export const DEFAULT_AGENT_RETRIEVAL_SETTINGS = Object.freeze({ windowPercent: DEFAULT_WINDOW_PERCENT });

const MINIMUM_WINDOW_PERCENT = 1;
const MAXIMUM_WINDOW_PERCENT = 100;
const PERCENT = 100;
// A value saved as tokens reads as its share of OpenAI's window, as on the server.
const OLD_TOKEN_LIMIT_PREFERENCE_KEY = 'pref.ai.openai.retrieval.max_page_approximate_tokens';
const LEGACY_DEFAULT_TOKEN_LIMIT = 24000;
const OPENAI_MODEL_CONTEXT_TOKENS = 1050000;


export class AgentRetrievalSettingsValidationError extends Error {}


export function validateAgentRetrievalSettings(settings, provider) {
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
        throw new TypeError('Agent retrieval settings must be an object');
    }
    const validationMessage = getAgentRetrievalSettingsValidationMessage(settings, provider);
    if (validationMessage !== '') {
        throw new AgentRetrievalSettingsValidationError(validationMessage);
    }
    return { windowPercent: settings.windowPercent };
}


export function getAgentRetrievalSettingsValidationMessage(settings, provider) {
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
        throw new TypeError('Agent retrieval settings must be an object');
    }
    requireProvider(provider);
    const { windowPercent } = settings;
    if (!Number.isInteger(windowPercent) || windowPercent < MINIMUM_WINDOW_PERCENT || windowPercent > MAXIMUM_WINDOW_PERCENT) {
        return `Model window used must be from ${MINIMUM_WINDOW_PERCENT} to ${MAXIMUM_WINDOW_PERCENT}%.`;
    }
    return '';
}


export function readAgentRetrievalSettings(getPreference, provider) {
    if (typeof getPreference !== 'function') {
        throw new Error('readAgentRetrievalSettings requires getPreference');
    }
    requireProvider(provider);
    return validateAgentRetrievalSettings({ windowPercent: storedWindowPercent(getPreference) }, provider);
}


function storedWindowPercent(getPreference) {
    const saved = getPreference(AGENT_RETRIEVAL_PREFERENCE_KEYS.windowPercent);
    if (isStored(saved)) {
        return parseStoredInteger(saved);
    }
    const savedTokens = getPreference(OLD_TOKEN_LIMIT_PREFERENCE_KEY);
    if (!isStored(savedTokens) || parseStoredInteger(savedTokens) === LEGACY_DEFAULT_TOKEN_LIMIT) {
        return DEFAULT_AGENT_RETRIEVAL_SETTINGS.windowPercent;
    }
    return Math.max(MINIMUM_WINDOW_PERCENT, Math.round(parseStoredInteger(savedTokens) * PERCENT / OPENAI_MODEL_CONTEXT_TOKENS));
}


function isStored(value) {
    return value !== null && value !== undefined && value !== '';
}


function parseStoredInteger(value) {
    if (typeof value !== 'string' || !/^[1-9][0-9]*$/.test(value)) {
        throw new Error('Stored agent evidence preference is invalid');
    }
    return Number(value);
}


function requireProvider(provider) {
    if (!isAiProvider(provider)) {
        throw new Error(`Unsupported agent retrieval provider: ${provider}`);
    }
}
