import { isServerErrorStatus } from './http-status.js';

const ERROR_TYPE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const CODE_LOCATION = /^(?:app(?:\/[A-Za-z_][A-Za-z0-9_]*)+\.py:\d+|external)$/;
const REQUEST_ID = /^[a-f0-9]{8}$/;
// The server names every answer's request id in this header (app/main.py REQUEST_ID_HEADER), so a
// failure shown here matches its line in the server log.
const REQUEST_ID_HEADER = 'X-Request-Id';

function requestIdOf(response) {
    const requestId = response.headers.get(REQUEST_ID_HEADER);
    return REQUEST_ID.test(requestId) ? requestId : null;
}

export async function describeApiFailure(response) {
    const base = `API call failed: ${response.status} ${response.statusText}`;
    const requestId = requestIdOf(response);
    const details = [];
    if (isServerErrorStatus(response.status) && response.headers.get('content-type')?.includes('application/json')) {
        const body = await response.json();
        const diagnostic = body?.diagnostic;
        if (ERROR_TYPE.test(diagnostic?.errorType) && CODE_LOCATION.test(diagnostic?.codeLocation)) {
            details.push(`${diagnostic.errorType} at ${diagnostic.codeLocation}`);
        }
    }
    if (requestId !== null) {
        details.push(`request ${requestId}`);
    }
    return details.length === 0 ? base : `${base} (${details.join(', ')})`;
}
