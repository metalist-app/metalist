import { ApplicationState } from './application-state.js';
import { isNetworkTransportError } from './api-failure-classification-service.js';
import { ServerInputRejectedError } from './expected-errors.js';
import { CONFIG } from './config.js';
import { HTTP_STATUS } from './http-status.js';

// The red overlay is drawn above every dialog (.modal, 15000), floating card (20000) and the
// login cover (21000): under a dialog, an error there looked like a click doing nothing
// (2026-11-12). Tests: tests/unit/fatal_overlay_layering.test.mjs.
const FATAL_OVERLAY_Z_INDEX = 22000;

const moduleState = ApplicationState.createFields('error-overlay', {
    installed: false,
    // Whether the server runs older code than this page, asked once: a promise of a boolean.
    serverCodeCheck: null,
    // The first fatal error waits for that answer; later ones show at once.
    hasExplainedFatal: false,
    // The error the overlay shows, for Export Report… (docs/ready-to-build/error-reports.md §4).
    shownError: null,
});

const OVERLAY_TEXT_ID = 'fatal-error-text';
const EXPORT_REPORT_ID = 'fatal-error-export-report';

// A page newer than its server (the server's Python is read when it starts, the page's
// files on every load: app/services/server_code.py) fails on answers in the old shape.
// Errors then say so first (asked for 2026-10-30).
export const STALE_SERVER_MESSAGE = "MetaList's server is running older code than its files: restart MetaList. "
  + 'Errors until then may come from that.';
// A server from before this check has no such route: it refuses it as not public (401) or
// does not know it (404). Either way it is older than this page; on a current server the
// route is public, so neither can come from it.
const OLDER_SERVER_STATUSES = Object.freeze([HTTP_STATUS.UNAUTHORIZED, HTTP_STATUS.NOT_FOUND]);

export function checkServerCodeIsStale() {
  if (moduleState.serverCodeCheck === null) {
    moduleState.serverCodeCheck = fetch(CONFIG.API.AUTH.SERVER_CODE).then(async (response) => {
      if (OLDER_SERVER_STATUSES.includes(response.status)) {
        return true;
      }
      if (!response.ok) {
        throw new Error(`Server code check failed (${response.status})`);
      }
      const body = await response.json();
      if (typeof body.stale !== 'boolean') {
        throw new Error('Server code check answered without stale');
      }
      return body.stale;
    });
  }
  return moduleState.serverCodeCheck;
}


// Input the server rejected (e.g. a search that does not parse) is an expected
// failure: a polite warning, not the fatal overlay. Null for anything else,
// which still fails fast and loud.
export function rejectedInputWarning(reason) {
  if (reason instanceof ServerInputRejectedError) {
    return `That could not be used: ${reason.message}.`;
  }
  return null;
}

// The browser's note that a ResizeObserver's callback changed the layout again, so it holds the
// rest of its notifications for the next frame (the spec's wording in Chrome and Firefox, and
// Safari's older one). It is not a failure in MetaList, and no error object comes with it: an
// Error MetaList throws with the same words still shows (the maintainer's dad, 2026-11-12:
// 0.28.1 listened from the login page on and showed it on every load).
const RESIZE_OBSERVER_LOOP_NOTES = new Set([
  'ResizeObserver loop completed with undelivered notifications.',
  'ResizeObserver loop limit exceeded',
]);

export function isBrowserResizeObserverNote(event) {
  return (event.error === null || event.error === undefined) && RESIZE_OBSERVER_LOOP_NOTES.has(event.message);
}

export function shouldSuppressFatalOverlay(reason) {
  return isNetworkTransportError(reason);
}

function ensureOverlay() {
  let overlay = document.getElementById('fatal-error-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'fatal-error-overlay';
    Object.assign(overlay.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      right: '0',
      background: '#8b0000',
      color: '#fff',
      padding: '10px 14px',
      fontFamily: 'monospace',
      fontSize: '13px',
      zIndex: String(FATAL_OVERLAY_Z_INDEX),
      whiteSpace: 'pre-wrap',
      borderBottom: '2px solid #550000',
      maxHeight: '40vh',
      overflowY: 'auto',
    });
    const text = document.createElement('div');
    text.id = OVERLAY_TEXT_ID;
    const exportButton = document.createElement('button');
    exportButton.id = EXPORT_REPORT_ID;
    exportButton.type = 'button';
    exportButton.textContent = 'Export Report…';
    Object.assign(exportButton.style, {
      marginTop: '8px',
      font: 'inherit',
      color: '#fff',
      background: 'transparent',
      border: '1px solid rgba(255, 255, 255, 0.7)',
      borderRadius: '4px',
      padding: '3px 10px',
      cursor: 'pointer',
    });
    // A report of what led up to the error, redacted, saved as a file to send.
    // Loaded when pressed: the overlay stands alone, before the app it reports on has loaded.
    exportButton.addEventListener('click', () => {
      if (moduleState.shownError === null) throw new Error('Export Report… pressed with no error shown');
      const shownError = moduleState.shownError;
      void import('./problem-reports/report-maker.js').then(({ exportOverlayReport }) => exportOverlayReport(shownError));
    });
    overlay.append(text, exportButton);
    document.body.appendChild(overlay);
  }
  return overlay;
}

function overlayText() {
  const text = ensureOverlay().querySelector(`#${OVERLAY_TEXT_ID}`);
  if (!(text instanceof HTMLElement)) throw new Error('The fatal overlay has no text');
  return text;
}

export function showFatalError(message, details, className) {
  if (typeof className !== 'string') throw new Error('showFatalError requires the error class name');
  moduleState.shownError = Object.freeze({
    className, message: String(message), stack: details ? String(details) : '',
  });
  const time = new Date().toISOString();
  const lines = [
    `[${time}] FATAL: ${String(message)}`,
    details ? String(details) : '',
  ].filter(Boolean);
  overlayText().textContent = lines.join('\n');
  // Only the first error waits for the answer: a check that fails itself reaches this
  // overlay once, not again.
  if (!moduleState.hasExplainedFatal) {
    moduleState.hasExplainedFatal = true;
    void checkServerCodeIsStale().then((isStale) => {
      if (isStale) {
        const shown = overlayText();
        shown.textContent = `${STALE_SERVER_MESSAGE}\n${shown.textContent}`;
      }
    });
  }
}

// The error's class for a report: its name if it is an Error, else nothing.
function errorClassName(error) {
  return error instanceof Error ? error.name : '';
}

// `showWarning(message)` shows a polite, non-fatal banner (ErrorHandler.showInfoBanner).
export function installGlobalErrorOverlay(showWarning) {
  if (typeof showWarning !== 'function') {
    throw new Error('installGlobalErrorOverlay requires a showWarning function');
  }
  if (moduleState.installed) return;
  moduleState.installed = true;
  // Say it before anything fails, too.
  void checkServerCodeIsStale().then((isStale) => {
    if (isStale) {
      showWarning(STALE_SERVER_MESSAGE);
    }
  });

  window.addEventListener('error', (event) => {
    if (isBrowserResizeObserverNote(event)) return;
    let msg = null;
    if (event && event.error && typeof event.error.message === 'string') {
      msg = event.error.message;
    } else if (event && typeof event.message === 'string') {
      msg = event.message;
    } else {
      msg = 'Uncaught error';
    }

    let stack = '';
    if (event && event.error && typeof event.error.stack === 'string') {
      stack = event.error.stack;
    }
    showFatalError(msg, stack, errorClassName(event ? event.error : null));
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event?.reason;
    const warning = rejectedInputWarning(reason);
    if (warning !== null) {
      event.preventDefault();
      showWarning(warning);
      return;
    }
    if (shouldSuppressFatalOverlay(reason)) {
      event.preventDefault();
      console.info('[ErrorOverlay] Connection failure is already shown in the status banner');
      return;
    }
    let msg = null;
    if (reason && typeof reason.message === 'string') {
      msg = reason.message;
    } else if (reason) {
      msg = String(reason);
    } else {
      msg = 'Unhandled promise rejection';
    }
    const stack = reason && reason.stack ? reason.stack : '';
    showFatalError(msg, stack, errorClassName(reason));
  });
}
