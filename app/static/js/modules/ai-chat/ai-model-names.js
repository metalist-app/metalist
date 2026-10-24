// Model names typed into AI Agent Settings' Add a model, checked as the server checks
// them (app/services/ai_catalog.py), so a mistake is explained before saving.

// A model name as providers write them.
const MODEL_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;
export const MAX_MODEL_NAME_CHARACTERS = 128;
const MAX_ADDED_MODELS = 20;

// Why a name typed into Add a model cannot be added, or '' when it can.
export function addedModelNameProblem(name, { installedModels, addedModels }) {
    if (typeof name !== 'string' || !Array.isArray(installedModels) || !Array.isArray(addedModels)) {
        throw new Error('addedModelNameProblem requires a name and the model lists');
    }
    if (name === '') return 'Type the model\'s name first.';
    if (name.length > MAX_MODEL_NAME_CHARACTERS || !MODEL_NAME_PATTERN.test(name)) {
        return `${name} is not a model name. Use the name the provider gives, like gpt-5.6-luna.`;
    }
    if (installedModels.includes(name)) return `${name} is already in the list.`;
    if (addedModels.length >= MAX_ADDED_MODELS) return `At most ${MAX_ADDED_MODELS} added models.`;
    return '';
}

// The chat's model picker lists every provider's models (POST /ai/model-choices); an
// option names both, since picking a model picks its provider. A provider id is
// lowercase letters and a model name has no space, so a space separates them.
const PROVIDER_ID_PATTERN = /^[a-z]+$/;
const MODEL_CHOICE_SEPARATOR = ' ';

export function modelChoiceValue(provider, model) {
    if (!PROVIDER_ID_PATTERN.test(provider) || !MODEL_NAME_PATTERN.test(model)) {
        throw new Error(`Not a model choice: ${provider} ${model}`);
    }
    return `${provider}${MODEL_CHOICE_SEPARATOR}${model}`;
}

export function parseModelChoiceValue(value) {
    if (typeof value !== 'string') throw new Error('A model choice must be a string');
    const separatorIndex = value.indexOf(MODEL_CHOICE_SEPARATOR);
    if (separatorIndex === -1) throw new Error(`Not a model choice: ${value}`);
    const provider = value.slice(0, separatorIndex);
    const model = value.slice(separatorIndex + MODEL_CHOICE_SEPARATOR.length);
    // Round-tripping checks both halves.
    if (modelChoiceValue(provider, model) !== value) throw new Error(`Not a model choice: ${value}`);
    return { provider, model };
}

export function validateModelGroups(payload) {
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.groups) || payload.groups.length === 0) {
        throw new Error('AI model choices must list at least one provider');
    }
    return payload.groups.map((group) => {
        if (!group || typeof group.label !== 'string' || group.label === '' || !Array.isArray(group.models)) {
            throw new Error('AI model choice group is malformed');
        }
        for (const model of group.models) modelChoiceValue(group.provider, model);
        return { provider: group.provider, label: group.label, models: [...group.models] };
    });
}
