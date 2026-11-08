import { MS_PER_SECOND, SECONDS_PER_MINUTE } from '../time-units.js';

// Count processing time, excluding time spent answering preflight questions.
export function createBulkElapsedClock(now) {
    let accumulated = 0;
    let started = 0;
    let running = false;
    return {
        resume() {
            if (running) return;
            started = now();
            running = true;
        },
        pause() {
            if (!running) return;
            accumulated += now() - started;
            running = false;
        },
        seconds() {
            return Math.floor((accumulated + (running ? now() - started : 0)) / MS_PER_SECOND);
        },
    };
}

export function formatBulkElapsed(seconds) {
    if (seconds < SECONDS_PER_MINUTE) return `${seconds}s`;
    return `${Math.floor(seconds / SECONDS_PER_MINUTE)}m ${seconds % SECONDS_PER_MINUTE}s`;
}
