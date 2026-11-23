// Counts the page's requests from inside the page, where a request ends when its
// fetch settles, aborted or not. Every request MetaList sends is a fetch (it uses
// no XMLHttpRequest, beacon, EventSource or socket). Puppeteer's own count, which
// page.waitForNetworkIdle reads, can lose a request the page aborts as it starts
// while request interception is on (browser-smoke.mjs turns it on for the update
// fixture), and then never reaches idle again. Runs before any page script, on
// every load of the page. Times are Date.now(), so the suite's clock compares.
export async function installRequestMonitor(page) {
  await page.evaluateOnNewDocument(() => {
    // lastActivityAt: when a request last started or ended, or a quiet wait last
    // saw MetaList busy.
    // open: the paths of the requests in flight; lastSaidBusyAt: when a quiet wait last said in
    // the console what kept MetaList busy (isAppIdle).
    const requests = {inFlight: 0, lastActivityAt: Date.now(), open: [], lastSaidBusyAt: 0};
    Object.defineProperty(window, '__metalistRequests', {value: requests});
    const pageFetch = window.fetch;
    const changed = delta => {
      requests.inFlight += delta;
      requests.lastActivityAt = Date.now();
    };
    const pathOf = resource => new URL(resource instanceof Request ? resource.url : String(resource), location.href).pathname;
    // MetaList's own checks, asked every second whatever the suite does (the status check, the
    // AI chat's live state, the background work): counting them, requests were never quiet for
    // long once they came every second (GitHub, 2026-11-15). What they set off (a view
    // refresh) is counted.
    const backgroundChecks = ['/api2/auth/status', '/api2/ai/chat/live', '/api2/background-work'];
    const isBackgroundCheck = resource => {
      const url = new URL(resource instanceof Request ? resource.url : String(resource), location.href);
      return backgroundChecks.includes(url.pathname);
    };
    window.fetch = (...args) => {
      if (isBackgroundCheck(args[0])) return pageFetch.apply(window, args);
      const path = pathOf(args[0]);
      changed(1);
      requests.open.push(path);
      return pageFetch.apply(window, args).finally(() => {
        changed(-1);
        requests.open.splice(requests.open.indexOf(path), 1);
      });
    };
  });
}

// Runs in the page. MetaList is idle: nothing is loading, no command is running,
// no search is waiting for its typing delay and no dictation paste is being
// cleaned up (those two run outside CommandGate). With `quiet`, it has also been
// quiet for quiet.quietMs since the wait started at quiet.startedAt: idle at every
// check, no request in flight, none started or ended, and nothing else loading
// (images, a floating window's stylesheets, fonts). That covers what MetaList
// sends outside CommandGate after a command (saving the tab state 300 ms after a
// search, recording a view, loading suggestions) and work a timer starts within
// the window (as page.waitForNetworkIdle, the window starts no earlier than the wait).
// MetaList loads no image lazily, so every image completes (a broken one too).
async function isAppIdle(quiet) {
  const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
  const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
  const {isDebouncedSearchPending} = await import('/static/js/modules/mode-manager/services/search-debounce-service.js');
  const {isDictationCleanupInProgress} = await import('/static/js/modules/mode-manager/services/dictation-paste-service.js');
  // Here, not at the top of the file: this function runs in the page, which has only what is in it.
  const SAY_BUSY_AFTER_MS = 5000;
  const SAID_ADDRESS_LENGTH = 120;
  const MS_PER_SECOND = 1000;
  const busyWith = [];
  if (mode.isLoading) busyWith.push('a view is loading');
  if (CommandGate.isBusy()) busyWith.push('a command is running');
  else if (CommandGate.isTurnTaken()) busyWith.push('background work has the turn');
  if (isDebouncedSearchPending()) busyWith.push('a typed search waits to run');
  if (isDictationCleanupInProgress()) busyWith.push('a dictation paste is being cleaned up');
  if (quiet === null) return busyWith.length === 0;
  const requests = window.__metalistRequests;
  if (requests === undefined) throw new Error('installRequestMonitor must run before the page loads');
  // A floating note window is the one shadow root, with its own stylesheets and images.
  const roots = [document, ...[...document.querySelectorAll('.floating-note-window')].map(host => host.shadowRoot)];
  if (requests.inFlight > 0) busyWith.push(`requests in flight: ${requests.open.join(', ')}`);
  if (document.fonts.status === 'loading') busyWith.push('a font is loading');
  for (const root of roots) {
    for (const image of root.querySelectorAll('img')) {
      if (!image.complete) {
        // Its parent and the file embed it may sit in say which picture this is.
        const embeds = [image.closest('[data-file-ref-id]')].filter(embed => embed !== null);
        const embedSays = `file embeds around it: ${JSON.stringify(embeds.map(embed => ({...embed.dataset})))}`;
        busyWith.push(`an image is loading: ${image.src.slice(0, SAID_ADDRESS_LENGTH)} (class "${image.className}", parent "${image.parentElement.className}"`
          + `, ${embedSays}, ${image.naturalWidth}x${image.naturalHeight}`
          + `, in the page ${image.isConnected}, shown ${image.getClientRects().length > 0})`);
      }
    }
    for (const link of root.querySelectorAll('link[rel="stylesheet"]')) {
      if (link.sheet === null) busyWith.push(`a stylesheet is loading: ${link.href}`);
    }
  }
  if (busyWith.length > 0) {
    const now = Date.now();
    requests.lastActivityAt = now;
    // A wait that never ends says why in the browser's log, which a failed run keeps: the wait's
    // own failure names only its time (Firefox, CI, 2026-11-15: edit-previews was never quiet
    // for 30 s and nothing said what kept it busy).
    if (now - quiet.startedAt >= SAY_BUSY_AFTER_MS && now - requests.lastSaidBusyAt >= SAY_BUSY_AFTER_MS) {
      requests.lastSaidBusyAt = now;
      // A picture that never finishes: whether its address can still be read says if the address
      // was let go under it (edit-previews, Firefox, CI, 2026-11-16: a file picture stayed 0x0).
      for (const root of roots) {
        for (const image of root.querySelectorAll('img')) {
          if (image.complete) continue;
          const embeds = [image.closest('.note-file-image-embed')].filter(embed => embed !== null);
          const states = embeds.map(embed => `${embed.dataset.previewState}`);
          const probe = new XMLHttpRequest();
          probe.open('GET', image.src);
          probe.responseType = 'blob';
          probe.onload = () => console.log(`[WAIT]: the stuck picture's address still reads: ${probe.response.size} bytes of ${probe.response.type}; its embed's state: ${states}`);
          probe.onerror = () => console.log(`[WAIT]: the stuck picture's address no longer reads; its embed's state: ${states}`);
          probe.send();
        }
      }
      console.log(`[WAIT]: not quiet ${Math.round((now - quiet.startedAt) / MS_PER_SECOND)} s into a wait: ${busyWith.join('; ')}`);
    }
    return false;
  }
  return Date.now() - Math.max(requests.lastActivityAt, quiet.startedAt) >= quiet.quietMs;
}

// The one definition of idle the browser suites wait on, so a new idle condition
// is added once.
export async function waitForAppIdle(page) {
  await page.waitForFunction(isAppIdle, {}, null);
}

// MetaList is idle and has been quiet for quietMs (see isAppIdle): what a step
// waits for before it reloads, reads the server, or checks that nothing else changes.
export async function waitForAppQuiet(page, quietMs) {
  await page.waitForFunction(isAppIdle, {}, {quietMs, startedAt: Date.now()});
}

// waitForAppQuiet, failing after timeoutMs instead of the page's default timeout.
export async function waitForAppQuietWithin(page, quietMs, timeoutMs) {
  await page.waitForFunction(isAppIdle, {timeout: timeoutMs}, {quietMs, startedAt: Date.now()});
}

// The page has stopped moving: MetaList is idle, its requests are quiet, and for
// STILL_FOR_MS no command has run, no Mermaid diagram has been rendering, no image in
// view has been loading, and the scroll position, page height and every note's top
// have stayed the same. That is longer than the slowest timer MetaList starts work or
// moves anything with (a note animation's 320 ms fallback, the search that runs 300 ms
// after typing stops, the 180 ms follow-up scroll, CSS transitions of at most 200 ms),
// so late work still starts, and a late jump still lands, before this returns. It
// replaces fixed settle pauses, which waited the worst case every time.
const STILL_FOR_MS = 500;
// A page still moving after this long fails the check instead of hanging it.
const SETTLE_DEADLINE_MS = 10000;
// Shorter than STILL_FOR_MS on purpose: an open floating note window asks for its
// note every 500 ms, so requests are never quiet for that long while one is open.
const SETTLE_REQUESTS_QUIET_MS = 300;

export async function waitForPageSettled(page) {
  await waitForAppQuiet(page, SETTLE_REQUESTS_QUIET_MS);
  await page.evaluate(async ({stillForMs, deadlineMs}) => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    await new Promise((resolve, reject) => {
      const inView = element => {
        const rect = element.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < window.innerHeight;
      };
      const observe = () => {
        const busyReasons = [
          mode.isLoading,
          CommandGate.isBusy() || CommandGate.isTurnTaken(),
          document.querySelector('[data-mermaid-state="rendering"]') !== null,
          [...document.images].some(image => inView(image) && !image.complete),
        ];
        return {
          layout: [window.scrollY, document.documentElement.scrollHeight,
            ...[...document.querySelectorAll('.note[data-note-id]')].map(note => Math.round(note.getBoundingClientRect().top))].join(','),
          isBusy: busyReasons.includes(true),
        };
      };
      const startedAt = performance.now();
      let last = observe();
      let stillSince = startedAt;
      const check = () => {
        const now = performance.now();
        const current = observe();
        if (current.layout !== last.layout || current.isBusy) {
          last = current;
          stillSince = now;
        } else if (now - stillSince >= stillForMs) {
          resolve();
          return;
        }
        if (now - startedAt > deadlineMs) {
          reject(new Error(`The page was still moving or rendering after ${deadlineMs} ms`));
          return;
        }
        requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    });
  }, {stillForMs: STILL_FOR_MS, deadlineMs: SETTLE_DEADLINE_MS});
}
