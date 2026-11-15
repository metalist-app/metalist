// How often a view checks for changes made in other views: every second in a desktop browser, every
// 2 seconds on a phone, sparing its battery and data (the maintainer, 2026-11-15). Decided by the
// device, not the window's width: a narrow desktop window is no phone.
import { CONFIG } from './config.js';

const PHONE_AGENT = /iPhone|iPad|Android|Mobile/i;

export function statusCheckIntervalMs() {
    if (PHONE_AGENT.test(navigator.userAgent)) {
        return CONFIG.SYNC.PHONE_POLL_INTERVAL_MS;
    }
    return CONFIG.SYNC.POLL_INTERVAL_MS;
}
