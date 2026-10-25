import { ApplicationState } from './application-state.js';
import { isNetworkTransportError } from './api-failure-classification-service.js';

export class UserInputRejected extends Error {}

// Input refused because of one field, which the error dialog then names (modals/error-dialog.js).
export class FieldInputRejected extends UserInputRejected {
    constructor(message, fieldId) {
        super(message);
        if (typeof fieldId !== 'string' || fieldId.length === 0) {
            throw new Error('FieldInputRejected requires the field id');
        }
        this.name = 'FieldInputRejected';
        this.fieldId = fieldId;
        ApplicationState.own(this, 'FieldInputRejected', new.target === FieldInputRejected);
    }
}

export class HttpRequestError extends Error {
    constructor(message) {
        super(message);
        this.name = 'HttpRequestError';
    }
}

// The server rejected what the user entered (e.g. a search that does not
// parse). Shown as a polite warning, never as a fatal error.
export class ServerInputRejectedError extends HttpRequestError {
    constructor(message) {
        super(message);
        this.name = 'ServerInputRejectedError';
    }
}

// A file edited in MetaList (an Excalidraw diagram) was saved elsewhere since this window loaded it.
export class FileRevisionConflictError extends HttpRequestError {
    constructor(message, currentRevision) {
        super(message);
        this.name = 'FileRevisionConflictError';
        if (!Number.isInteger(currentRevision) || currentRevision < 1) {
            throw new Error('FileRevisionConflictError requires a positive integer currentRevision');
        }
        this.currentRevision = currentRevision;
    }
}

// The server no longer holds the diagram editing session (it expired, or the app was locked).
export class FileEditSessionExpiredError extends HttpRequestError {
    constructor(message) {
        super(message);
        this.name = 'FileEditSessionExpiredError';
    }
}

// This whitelist covers expected platform failures, not arbitrary Error,
// TypeError, or errors whose message merely happens to mention fetch.
export function rethrowUnexpectedError(error) {
    if (error instanceof UserInputRejected || error instanceof HttpRequestError || isNetworkTransportError(error)) return;
    if (error instanceof DOMException && ['NotAllowedError', 'AbortError', 'NotSupportedError'].includes(error.name)) return;
    throw error;
}
