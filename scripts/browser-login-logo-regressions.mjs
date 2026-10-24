import {assertLoginLogoGeometry} from './browser-validation/login-logo-geometry.mjs';

// A wide window (the stage at its 300 px cap) and a narrow one (the stage at 62% of
// the window): the M stays where it was and the bars are as wide as it, in both.
const WINDOWS = [{width: 1280, height: 800}, {width: 400, height: 800}];

// The Session locked page and the tab that opens another vault show the login screen's
// logo (docs/ui/login-screen.md); the login screen itself is checked in the core smoke.
export async function checkLoginLogo(browser, page, origin) {
  const appWindow = page.viewport();
  try {
    for (const window of WINDOWS) {
      const label = `${window.width}px window`;
      const locked = await browser.newPage();
      try {
        await locked.setViewport(window);
        await locked.goto(new URL('/locked', origin).href, {waitUntil: 'load'});
        await assertLoginLogoGeometry(locked, `Session locked page, ${label}`);
      } finally {
        await locked.close();
      }
      await page.setViewport(window);
      const popupOpened = new Promise(resolve => page.once('popup', resolve));
      await page.evaluate(async () => {
        const {renderNamespaceLoadingTab} = await import('/static/js/modules/modals/namespace-loading-page.js');
        renderNamespaceLoadingTab(window.open('about:blank', '_blank'), 'other');
      });
      const openingTab = await popupOpened;
      try {
        await openingTab.setViewport(window);
        await assertLoginLogoGeometry(openingTab, `vault-opening tab, ${label}`);
      } finally {
        await openingTab.close();
      }
    }
  } finally {
    await page.setViewport(appWindow);
  }
}
