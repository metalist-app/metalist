import assert from 'node:assert/strict';

// The login-style screens' logo (docs/ui/login-screen.md, "Logo"): the M stays exactly
// where the old mark put it, and the bars are as wide as the M. The old mark was a
// 340-unit-wide viewBox filling the stage, with the M from 30 to 309 units and 136 units
// tall, in a mark 223 units tall. Everything under the logo (the vault picker, password
// field, OK, the progress bar, Session locked and its button, the "Starting…" line) lines
// up with the M's edges too (2026-10-24).
const OLD_MARK_UNITS = 340;
const M_LEFT_UNITS = 30;
const M_WIDTH_UNITS = 279;
const M_HEIGHT_UNITS = 136;
const MARK_HEIGHT_UNITS = 223;
// Browsers place each box on a layout grid: 1/64 px in Chrome and Edge, 1/60 px in Firefox
// (the coarser, so the step allowed). Each size is checked against what the browser derives
// it from, so it is rounded once: the mark's height comes from its width (already rounded),
// and the M fills the mark exactly (preserveAspectRatio none, app/templates/_logo_mark.html).
// Against the ideal values, a size rounded twice drifts past one step (Chrome 155, 2026-10-25).
const LAYOUT_STEP_PX = 1 / 60;

function assertWithinLayoutStep(actual, expected, message) {
  assert(Math.abs(actual - expected) <= LAYOUT_STEP_PX, `${message}: ${actual} instead of ${expected}`);
}

export async function assertLoginLogoGeometry(target, label) {
  const layout = await target.evaluate(() => {
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, width: rect.width, height: rect.height};
    };
    const stage = document.querySelector('.login-stage');
    const mark = stage.querySelector('.login-logo-mark');
    // Hidden parts (a note not shown yet, the loading view before the password) have no box.
    const shown = [...stage.querySelectorAll('.login-panel, .login-views, .login-opening-note')]
      .filter(element => element.getClientRects().length > 0);
    return {
      stage: box(stage),
      mark: box(mark),
      m: box(mark.querySelector('polygon')),
      bars: [...mark.querySelectorAll('rect')].map(box),
      under: shown.map(element => ({name: element.className, ...box(element)})),
    };
  });
  const unit = layout.stage.width / OLD_MARK_UNITS;
  const mLeft = layout.stage.left + M_LEFT_UNITS * unit;
  const mWidth = M_WIDTH_UNITS * unit;
  assertWithinLayoutStep(layout.m.left, mLeft, `${label}: the M's left edge moved`);
  assertWithinLayoutStep(layout.m.width, mWidth, `${label}: the M's width changed`);
  assertWithinLayoutStep(layout.m.height, layout.mark.height * M_HEIGHT_UNITS / MARK_HEIGHT_UNITS,
    `${label}: the M's height changed`);
  assertWithinLayoutStep(layout.m.top, layout.mark.top, `${label}: the M must start at the top of the mark`);
  assertWithinLayoutStep(layout.mark.width, mWidth, `${label}: the mark must be the M's box`);
  assertWithinLayoutStep(layout.mark.height, layout.mark.width * MARK_HEIGHT_UNITS / M_WIDTH_UNITS,
    `${label}: the mark's height changed, which would move everything under it`);
  assert.equal(layout.bars.length, 2, `${label}: the full mark has two bars`);
  for (const bar of layout.bars) {
    assertWithinLayoutStep(bar.left, mLeft, `${label}: a bar must start where the M starts`);
    assertWithinLayoutStep(bar.width, mWidth, `${label}: a bar must be as wide as the M`);
  }
  assert(layout.under.length > 0, `${label}: nothing under the logo was measured`);
  for (const part of layout.under) {
    assertWithinLayoutStep(part.left, mLeft, `${label}: ${part.name} must start where the M starts`);
    assertWithinLayoutStep(part.width, mWidth, `${label}: ${part.name} must be as wide as the M`);
  }
}
