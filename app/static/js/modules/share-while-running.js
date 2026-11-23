// One request at a time. `shareWhileRunning(load)` gives a function that starts `load()` when
// none is running and gives every caller meanwhile that same request's answer (or failure);
// the first call after it finishes starts a new one.
//
// For requests that are asked for from several places and cost the server real work: the
// password-audit reminder's count of the vault's passwords was asked for again while the first
// count ran, two side by side (problem report 2026-11-22).

export function shareWhileRunning(load) {
    if (typeof load !== 'function') {
        throw new Error('shareWhileRunning requires the request to make');
    }
    const state = { running: null };
    return () => {
        if (state.running === null) {
            // Settled either way, the next call makes a new request. A failure reaches every
            // caller of this one, as it would have reached the one caller of `load`.
            state.running = load().finally(() => {
                state.running = null;
            });
        }
        return state.running;
    };
}
