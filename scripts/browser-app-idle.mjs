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
    // waiting: the work the page has put off and not yet done, by its timer's or frame's id: a
    // timer of at most SOON_MS and every animation frame asked for. While any waits, MetaList is
    // not idle: that is a fact, where a quiet wait alone guesses that 300 ms is long enough for
    // late work to have started (docs/future-plans/one-writer-refactoring.md, idea 5). Longer
    // timers are not work about to happen (a message that leaves after some seconds, a watchdog);
    // work that repeats (setInterval: the status check, the infinite scroll's look) is not counted,
    // and what it starts is, as a request or a turn.
    const SOON_MS = 750;
    const requests = {inFlight: 0, lastActivityAt: Date.now(), open: [], lastSaidBusyAt: 0, waiting: new Map()};
    Object.defineProperty(window, '__metalistRequests', {value: requests});
    const pageSetTimeout = window.setTimeout;
    const pageClearTimeout = window.clearTimeout;
    const pageRequestFrame = window.requestAnimationFrame;
    const pageCancelFrame = window.cancelAnimationFrame;
    const done = key => {
      if (!requests.waiting.delete(key)) return;
      requests.lastActivityAt = Date.now();
    };
    // Whether MetaList put the work off, by where the call came from: its modules are served
    // under /static/. A suite's own watcher in the page (a frame loop that samples positions) is
    // not MetaList's work. One timer is MetaList's and still not counted: the wait of a change
    // made elsewhere (live-changes-service.js, retryLater), which looks again every 250 ms for as
    // long as a dialog, a menu or the find bar is open; MetaList says itself when such a change is
    // about to be shown (isChangeAboutToBeShown, asked in isAppIdle).
    const isMetaListsOwn = () => {
      const from = new Error().stack;
      return from.includes('/static/') && !from.includes('retryLater');
    };
    window.setTimeout = (work, delay, ...rest) => {
      const delayMs = Number(delay) > 0 ? Number(delay) : 0;
      if (typeof work !== 'function' || delayMs > SOON_MS || !isMetaListsOwn()) return pageSetTimeout(work, delay, ...rest);
      const id = pageSetTimeout((...args) => {
        done(`timer ${id}`);
        work(...args);
      }, delay, ...rest);
      requests.waiting.set(`timer ${id}`, `a ${delayMs} ms timer for ${work.name === '' ? 'unnamed work' : work.name}`);
      return id;
    };
    window.clearTimeout = id => {
      done(`timer ${id}`);
      pageClearTimeout(id);
    };
    window.requestAnimationFrame = work => {
      if (!isMetaListsOwn()) return pageRequestFrame(work);
      const id = pageRequestFrame(time => {
        done(`frame ${id}`);
        work(time);
      });
      requests.waiting.set(`frame ${id}`, `a frame for ${work.name === '' ? 'unnamed work' : work.name}`);
      return id;
    };
    window.cancelAnimationFrame = id => {
      done(`frame ${id}`);
      pageCancelFrame(id);
    };
    // Resolves once the browser has drawn `frames` more frames: what a change of the window's
    // size or of a style needs before the page shows it, and no work of MetaList's (untilIdle).
    requests.drawn = frames => new Promise(resolve => {
      let left = frames;
      const next = () => {
        left -= 1;
        if (left <= 0) resolve();
        else pageRequestFrame(next);
      };
      pageRequestFrame(next);
    });
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

// Runs in the page. MetaList is idle: nothing is loading, no command or background work has the
// turn, no search is waiting for its typing delay, no dictation paste is being cleaned up and no
// change made elsewhere is about to be shown. With `quiet` (a wait that began at
// quiet.startedAt), it has also finished everything it put off: no request is in flight, no timer
// or animation frame of MetaList's own is waiting (installRequestMonitor counts them), and nothing
// else is loading (images, a floating window's stylesheets, fonts). That is a fact, where
// quiet.quietMs was a guess at how long late work takes to start (saving the tab state 300 ms
// after a search, recording a view, loading suggestions): the time is no longer read
// (docs/future-plans/one-writer-refactoring.md, idea 5).
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
  const {isChangeAboutToBeShown} = await import('/static/js/modules/mode-manager/services/live-changes-service.js');
  if (isChangeAboutToBeShown()) busyWith.push('a change made elsewhere is about to be shown');
  if (quiet === null) return busyWith.length === 0;
  const requests = window.__metalistRequests;
  if (requests === undefined) throw new Error('installRequestMonitor must run before the page loads');
  // A floating note window is the one shadow root, with its own stylesheets and images.
  const roots = [document, ...[...document.querySelectorAll('.floating-note-window')].map(host => host.shadowRoot)];
  if (requests.inFlight > 0) busyWith.push(`requests in flight: ${requests.open.join(', ')}`);
  if (requests.waiting.size > 0) busyWith.push(`work put off: ${[...new Set(requests.waiting.values())].join(', ')}`);
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
  // Idle is a fact now (nothing running, in flight or put off), so no time is waited on top of
  // it: quiet.quietMs was a guess at how long late work takes to start, and is no longer read.
  // The suites still pass it; it goes when their fixed pauses do.
  return true;
}

// The one definition of idle the browser suites wait on, so a new idle condition
// is added once.
export async function waitForAppIdle(page) {
  await untilIdle(page, null, page.getDefaultTimeout());
}

// Asked from here, not by a watcher in the page: page.waitForFunction watches with the page's own
// timers and frames, which isAppIdle counts as work put off. Each question stands alone, so a
// page that loads anew between two of them is simply asked again.
const ASK_EVERY_MS = 50;
const FRAMES_DRAWN = 2;
async function untilIdle(page, quiet, timeoutMs) {
  const startedAt = Date.now();
  // Idle, and still idle once the browser has drawn: a window resized or a style changed just
  // before is laid out in the next frames, and what that starts (an observer's work) is seen.
  // A page opened without installRequestMonitor counts no timers and has no frames to wait for.
  const idleAndDrawn = async () => {
    if (!(await page.evaluate(isAppIdle, quiet))) return false;
    const isDrawn = await page.evaluate(async frames => {
      if (window.__metalistRequests === undefined) return false;
      await window.__metalistRequests.drawn(frames);
      return true;
    }, FRAMES_DRAWN);
    if (!isDrawn) return true;
    return page.evaluate(isAppIdle, quiet);
  };
  while (!(await idleAndDrawn())) {
    if (Date.now() - startedAt > timeoutMs) {
      // What the page still holds, so the failure says what never finished.
      const held = await page.evaluate(() => {
        const requests = window.__metalistRequests;
        if (requests === undefined) return {putOff: [], requests: []};
        return {putOff: [...new Set(requests.waiting.values())], requests: [...requests.open]};
      });
      throw new Error(`MetaList was not idle within ${timeoutMs} ms: ${JSON.stringify(held)}`);
    }
    await new Promise(resolve => setTimeout(resolve, ASK_EVERY_MS));
  }
}

// MetaList is idle and has been quiet for quietMs (see isAppIdle): what a step
// waits for before it reloads, reads the server, or checks that nothing else changes.
export async function waitForAppQuiet(page, quietMs) {
  await untilIdle(page, {quietMs, startedAt: Date.now()}, page.getDefaultTimeout());
}

// waitForAppQuiet, failing after timeoutMs instead of the page's default timeout.
export async function waitForAppQuietWithin(page, quietMs, timeoutMs) {
  await untilIdle(page, {quietMs, startedAt: Date.now()}, timeoutMs);
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
