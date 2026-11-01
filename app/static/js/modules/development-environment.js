// Whether MetaList runs in development (METALIST_ENVIRONMENT=development), as the page says:
// developer tools, such as the Obsidian import's developer version (PLAN.md), exist only then.
export function isDevelopmentEnvironment() {
    const app = document.getElementById('app');
    if (!(app instanceof HTMLElement)) {
        throw new Error('The page has no #app element');
    }
    const flag = app.dataset.development;
    if (flag !== 'true' && flag !== 'false') {
        throw new Error(`#app data-development must be "true" or "false", got ${flag}`);
    }
    return flag === 'true';
}
