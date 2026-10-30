import { ApplicationState } from './application-state.js';
import { isNetworkTransportError } from './api-failure-classification-service.js';
import { ServerInputRejectedError } from './expected-errors.js';
import { CONFIG } from './config.js';
import { HTTP_STATUS } from './http-status.js';


const moduleState = ApplicationState.createFields('error-overlay', {
    installed: false,
    // Whether the server runs older code than this page, asked once: a promise of a boolean.
    serverCodeCheck: null,
    // The first fatal error waits for that answer; later ones show at once.
    hasExplainedFatal: false,
});

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
      zIndex: '10000',
      whiteSpace: 'pre-wrap',
      borderBottom: '2px solid #550000',
      maxHeight: '40vh',
      overflowY: 'auto',
    });
    document.body.appendChild(overlay);
  }
  return overlay;
}

export function showFatalError(message, details) {
  const overlay = ensureOverlay();
  const time = new Date().toISOString();
  const lines = [
    `[${time}] FATAL: ${String(message)}`,
    details ? String(details) : '',
  ].filter(Boolean);
  overlay.textContent = lines.join('\n');
  // Only the first error waits for the answer: a check that fails itself reaches this
  // overlay once, not again.
  if (!moduleState.hasExplainedFatal) {
    moduleState.hasExplainedFatal = true;
    void checkServerCodeIsStale().then((isStale) => {
      if (isStale) {
        const shown = ensureOverlay();
        shown.textContent = `${STALE_SERVER_MESSAGE}\n${shown.textContent}`;
      }
    });
  }
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
    showFatalError(msg, stack);
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
    showFatalError(msg, stack);
  });
}
