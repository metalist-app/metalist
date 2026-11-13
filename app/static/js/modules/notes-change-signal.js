// Tells whoever listens that the vault's notes may have changed: a change made here (an answer
// carrying a new update id, api-client.js) or anywhere else, this tab, another or another computer
// (the note revision in the status the app already polls, polling-service.js). Listeners are told
// often and must be cheap: the Password Audit panel waits for the changes to settle, then updates.
import { ApplicationState } from './application-state.js';

const signalState = ApplicationState.createFields('notes-change-signal', {
    listeners: [],
});

// Returns the function that stops listening.
export function onNotesChanged(listener) {
    if (typeof listener !== 'function') {
        throw new Error('onNotesChanged requires a listener');
    }
    signalState.listeners = [...signalState.listeners, listener];
    return () => {
        signalState.listeners = signalState.listeners.filter((each) => each !== listener);
    };
}

export function notesMayHaveChanged() {
    for (const listener of signalState.listeners) {
        listener();
    }
}
