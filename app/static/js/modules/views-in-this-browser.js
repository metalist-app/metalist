// The other tabs of this browser on the same vault (a BroadcastChannel is per origin, and each vault
// has its own port). A tab that needs the others to hear something now, rather than at their next
// status check, asks them to check at once: taking a note over waits for the tab it takes it from to
// save and leave (multi-view editing step 4, edit-lock-service.js).
import { ApplicationState } from './application-state.js';

const CHANNEL_NAME = 'metalist-views';
const CHECK_NOW = 'check-now';

const channelState = ApplicationState.createFields('views-in-this-browser', {
    // Opened on first use: an open channel keeps a page's (or a test's) event loop alive.
    channel: null,
});

function openChannel() {
    if (channelState.channel === null) {
        channelState.channel = new BroadcastChannel(CHANNEL_NAME);
    }
    return channelState.channel;
}

export function askOtherTabsToCheckNow() {
    openChannel().postMessage({ type: CHECK_NOW });
}

export function whenAskedToCheckNow(check) {
    if (typeof check !== 'function') {
        throw new Error('whenAskedToCheckNow requires what to do');
    }
    openChannel().addEventListener('message', (event) => {
        if (event.data !== null && typeof event.data === 'object' && event.data.type === CHECK_NOW) {
            check();
        }
    });
}
