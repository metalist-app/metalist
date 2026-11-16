// Gives the vault its first password with no MetaList code running, and opens the login screen.
//
// Setting a password ends every session. An app page still open then asks its once-a-second
// checks with the ended session, is told it is not logged in, and goes to Session locked
// (Auth.forceLogout empties the page and replaces it with /locked). That could cancel the
// suite's own reload already under way and leave the login screen unopened; the emptied page's
// observers also threw meanwhile ("notes-container not found"). Seen in `core`, in Chrome and
// Firefox, 2026-11-15; the backup restore in browser-smoke.mjs and the installed-package check
// (2026-10-24) met the same race. So the request goes from a page of this server that holds no
// app, with the session headers read from the app's page first.

// A file every MetaList serves without a session and that runs no script.
const PAGE_WITHOUT_THE_APP = '/static/css/main.css?sets-the-password';
const LOGIN_PASSWORD_FIELD = '#login-panel[data-revealed="true"] #login-password';

export async function setFirstPasswordAndOpenLogin(page, password) {
  if (typeof password !== 'string' || password === '') {
    throw new Error('setFirstPasswordAndOpenLogin needs the password to set');
  }
  const origin = new URL(page.url()).origin;
  const headers = await page.evaluate(async () => {
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    return buildSessionHeaders(true);
  });
  await page.goto(`${origin}${PAGE_WITHOUT_THE_APP}`);
  await page.evaluate(async ({headers, password}) => {
    const response = await fetch('/api2/auth/settings/password/create',
      {method: 'POST', headers, body: JSON.stringify({password, keeps_window_logged_in: false})});
    if (!response.ok) throw new Error(`Password setup failed: ${response.status}: ${await response.text()}`);
  }, {headers, password});
  await page.goto(origin);
  await page.waitForSelector(LOGIN_PASSWORD_FIELD, {visible: true});
}
