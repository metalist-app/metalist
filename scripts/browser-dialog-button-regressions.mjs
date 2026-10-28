import assert from 'node:assert/strict';

// The order and labels of every dialog's action row (docs/ready-to-build/
// docs/ui/modals.md, "Dialog and menu conventions", rules 1-3 and 7; agreed case by case 2026-10-24): the
// main action rightmost, Cancel or Back directly left of it, a rare alternative at the far
// left; on a narrow screen the row stacks with the main action on top.

const FRAMES_TO_SETTLE = 3;
const WIDE_WINDOW = {width: 1280, height: 900};
// Under the 640 px breakpoint where action rows stack (main.css).
const NARROW_WINDOW = {width: 420, height: 900};
// Wider than the Mac's default sans-serif, as Linux's DejaVu Sans is.
const WIDE_FONT = 'Verdana, "DejaVu Sans", sans-serif';
const EDGE_PX = 1;
// Escape presses that close whatever a failed case left open.
const ESCAPES_AFTER_A_FAILURE = 3;

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

// The visible buttons of the row holding `mainSelector`, with their boxes.
async function readRow(page, mainSelector) {
  return page.evaluate(selector => {
    const main = document.querySelector(selector);
    const row = main.closest('.form-actions, .reminder-form-actions, .image-file-insert-choice-actions, .ontology-dialog-footer');
    const rowBox = row.getBoundingClientRect();
    const buttons = [...row.querySelectorAll('button')]
      .filter(button => button.getClientRects().length > 0)
      .map(button => {
        const box = button.getBoundingClientRect();
        return {label: button.textContent.trim(), left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          isMain: button === main, className: button.className};
      });
    const style = getComputedStyle(row);
    return {left: rowBox.left + parseFloat(style.paddingLeft), right: rowBox.right - parseFloat(style.paddingRight), buttons};
  }, mainSelector);
}

async function assertRow(page, {label, mainSelector, labels, mainClass, hasAlternative}) {
  const row = await readRow(page, mainSelector);
  const byPosition = [...row.buttons].sort((a, b) => a.left - b.left);
  assert.deepEqual(byPosition.map(button => button.label), labels, `${label}: buttons left to right`);
  // One row: each button overlaps the first vertically. Buttons of different font metrics
  // can sit a fraction of a pixel apart on one row (Firefox on Linux, 2026-10-28); a wrapped
  // button sits a whole button lower and overlaps nothing.
  const tops = byPosition.map(button => `${button.label}: ${button.top}-${button.bottom}`).join(', ');
  for (const button of byPosition) {
    assert.ok(button.top < byPosition[0].bottom && button.bottom > byPosition[0].top,
      `${label}: the buttons must share one row (${tops})`);
  }
  const main = byPosition[byPosition.length - 1];
  assert.equal(main.isMain, true, `${label}: the main action must be rightmost`);
  assert(main.className.split(' ').includes(mainClass), `${label}: the main action must be ${mainClass}, not ${main.className}`);
  // The main action ends the row; an alternative starts it, apart from the others.
  assert(Math.abs(main.right - row.right) <= EDGE_PX, `${label}: the main action must end the row`);
  if (hasAlternative) {
    assert(Math.abs(byPosition[0].left - row.left) <= EDGE_PX, `${label}: the alternative must start the row`);
  }
}

async function assertStacked(page, {label, mainSelector, labels}) {
  const row = await readRow(page, mainSelector);
  const topToBottom = [...row.buttons].sort((a, b) => a.top - b.top);
  assert.deepEqual(topToBottom.map(button => button.label), [...labels].reverse(),
    `${label}: on a narrow screen the main action must be on top`);
}

async function openModal(page, modulePath, className, method, argument) {
  await page.evaluate(async ({modulePath, className, method, argument}) => {
    const module = await import(modulePath);
    window.dialogButtonModal = new module[className]();
    if (argument === null) {
      void window.dialogButtonModal[method]();
    } else {
      void window.dialogButtonModal[method](argument);
    }
  }, {modulePath, className, method, argument});
}

async function openPalette(page, method, argument) {
  await page.evaluate(async ({method, argument}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    if (argument === null) {
      void CommandPalette[method]();
    } else {
      void CommandPalette[method](argument);
    }
  }, {method, argument});
}

async function closeWithEscape(page) {
  await page.keyboard.press('Escape');
  await settle(page);
}

// A simple dialog: open, wait for its main button, check its row wide (and narrow when asked).
function simpleCase({label, open, mainSelector, labels, mainClass, hasAlternative, checksNarrow}) {
  return [label, async page => {
    await open(page);
    await page.waitForSelector(mainSelector, {visible: true});
    await settle(page);
    await assertRow(page, {label, mainSelector, labels, mainClass, hasAlternative});
    if (checksNarrow) {
      await page.setViewport(NARROW_WINDOW);
      await settle(page);
      await assertStacked(page, {label, mainSelector, labels});
      await page.setViewport(WIDE_WINDOW);
      await settle(page);
    }
    await closeWithEscape(page);
  }];
}

// The restore dialog's confirm step for a backup of `namespace` into `default`, as the
// dialog reaches it after its preflight.
async function showRestoreConfirmation(page, {namespace, sameNamespace, targetExists}) {
  await page.evaluate(async ({namespace, sameNamespace, targetExists}) => {
    const {BackupRestoreModal} = await import('/static/js/modules/modals/backup-restore-modal.js');
    const modal = new BackupRestoreModal();
    await modal.open();
    modal.updateModalState({
      loading: false,
      backups: [{backup_id: 'b1', filename: `${namespace}-backup.zip`, namespace, created_at: '2026-10-24T10:00:00Z',
        size_bytes: 2048, source: 'internal'}],
      selectedBackupId: 'b1', targetNamespaceText: 'default', confirming: true,
      preflight: {same_namespace: sameNamespace, target_exists: targetExists, target_requires_password: false},
      overwriteConfirmText: '', error: '',
    });
    modal.renderModalContent();
  }, {namespace, sameNamespace, targetExists});
  await page.waitForSelector('#restore-backup-btn', {visible: true});
  await settle(page);
}

function restoreCase(label, preflight, labels, mainClass) {
  return [label, async page => {
    await showRestoreConfirmation(page, preflight);
    await assertRow(page, {label, mainSelector: '#restore-backup-btn', labels, mainClass, hasAlternative: false});
    await closeWithEscape(page);
  }];
}

const CASES = [
  simpleCase({label: 'AI Agent Settings', open: page => openPalette(page, 'openAiAgentSettings', false),
    mainSelector: '#ai-agent-save', labels: ['Cancel', 'Save'], mainClass: 'primary-btn', hasAlternative: false,
    checksNarrow: true}),
  simpleCase({label: 'Session Timeout', open: page => openModal(page, '/static/js/modules/modals/session-timeout-modal.js',
    'SessionTimeoutModal', 'open', null),
  mainSelector: '#session-timeout-save-btn', labels: ['Cancel', 'Save'], mainClass: 'primary-btn', hasAlternative: false}),
  simpleCase({label: 'Note Layout', open: page => openPalette(page, 'openNoteLayoutAppearance', null),
    mainSelector: '#note-layout-save-btn', labels: ['Cancel', 'Save'], mainClass: 'primary-btn', hasAlternative: false}),
  simpleCase({label: 'Back Up Now', open: page => openModal(page, '/static/js/modules/modals/backup-settings-modal.js',
    'BackupSettingsModal', 'openForBackup', null),
  mainSelector: '#backup-settings-run-btn', labels: ['Cancel', 'Back Up Now'], mainClass: 'primary-btn', hasAlternative: false}),
  simpleCase({label: 'Create Vault', open: page => openPalette(page, 'openCreateNamespace', null),
    mainSelector: '#create-namespace-submit-btn', labels: ['Cancel', 'Create and Open Vault'], mainClass: 'primary-btn',
    hasAlternative: false}),
  simpleCase({label: 'Rename Vault', open: page => openPalette(page, 'openRenameCurrentNamespace', null),
    mainSelector: '#rename-namespace-submit-btn', labels: ['Cancel', 'Rename and Restart'], mainClass: 'primary-btn',
    hasAlternative: false}),
  simpleCase({label: 'Vault Ports', open: page => openPalette(page, 'openManageNamespacePorts', null),
    mainSelector: '#manage-namespace-ports-save-btn', labels: ['Cancel', 'Save Ports'], mainClass: 'primary-btn',
    hasAlternative: false}),
  simpleCase({label: 'Add Password', open: page => openModal(page, '/static/js/modules/modals/password-modal.js',
    'AddPasswordModal', 'open', null),
  mainSelector: '[data-password-submit]', labels: ['Cancel', 'Add Password'], mainClass: 'primary-btn', hasAlternative: false}),
  simpleCase({label: 'Delete Vault, first step', open: page => openModal(page, '/static/js/modules/modals/delete-namespace-modal.js',
    'DeleteNamespaceModal', 'open', null),
  mainSelector: '#delete-namespace-continue-btn', labels: ['Cancel', 'Continue'], mainClass: 'primary-btn', hasAlternative: false}),
  ['Delete Vault, confirm step', async page => {
    await openModal(page, '/static/js/modules/modals/delete-namespace-modal.js', 'DeleteNamespaceModal', 'open', null);
    await page.waitForSelector('#delete-namespace-modal .form-actions button', {visible: true});
    await page.evaluate(() => {
      const modal = window.dialogButtonModal;
      modal.updateModalState({
        loading: false, confirming: true, namespace: 'default', targetNamespaceText: 'default', confirmationText: '',
        activeNamespaceDeleted: true, redirectNamespaces: ['default'], redirectNamespace: 'default',
        recreatesDefault: true, error: '', status: '',
      });
      modal.renderModalContent();
    });
    await page.waitForSelector('#delete-namespace-submit-btn', {visible: true});
    await settle(page);
    const labels = ['Back', 'Delete Vault'];
    await assertRow(page, {label: 'Delete Vault, confirm step', mainSelector: '#delete-namespace-submit-btn', labels,
      mainClass: 'danger-btn', hasAlternative: false});
    await page.setViewport(NARROW_WINDOW);
    await settle(page);
    await assertStacked(page, {label: 'Delete Vault, confirm step', mainSelector: '#delete-namespace-submit-btn', labels});
    await page.setViewport(WIDE_WINDOW);
    await settle(page);
    await closeWithEscape(page);
  }],
  simpleCase({label: 'Restore, first step', open: page => openModal(page, '/static/js/modules/modals/backup-restore-modal.js',
    'BackupRestoreModal', 'open', null),
  mainSelector: '#restore-backup-btn', labels: ['Cancel', 'Continue'], mainClass: 'primary-btn', hasAlternative: false}),
  restoreCase('Restore, confirm step', {namespace: 'default', sameNamespace: true, targetExists: true},
    ['Back', 'Restore Backup'], 'primary-btn'),
  restoreCase('Import, confirm step', {namespace: 'other', sameNamespace: false, targetExists: false},
    ['Back', 'Import Backup'], 'primary-btn'),
  restoreCase('Import over a vault, confirm step', {namespace: 'other', sameNamespace: false, targetExists: true},
    ['Back', 'Import And Overwrite Vault'], 'danger-btn'),
  simpleCase({label: 'Open Vault', open: page => openModal(page, '/static/js/modules/modals/namespace-modals.js',
    'OpenNamespaceModal', 'open', null),
    mainSelector: '#open-namespace-this-tab-btn', labels: ['Open in New Tab', 'Cancel', 'Open in This Tab'],
    mainClass: 'primary-btn', hasAlternative: true, checksNarrow: true}),
  ['Paste Image choice', async page => {
    await page.evaluate(async () => {
      const {promptForImageFileInsertMode} = await import('/static/js/modules/mode-manager/services/image-file-insert-choice-modal-service.js');
      void promptForImageFileInsertMode({imageCount: 1, source: 'paste'});
    });
    await page.waitForSelector('#image-file-insert-choice-embed', {visible: true});
    await settle(page);
    await assertRow(page, {label: 'Paste Image choice', mainSelector: '#image-file-insert-choice-embed',
      labels: ['Save as File', 'Cancel', 'Paste Inline'], mainClass: 'primary-btn', hasAlternative: true});
    await closeWithEscape(page);
  }],
  simpleCase({label: 'Reminders form', open: page => openPalette(page, 'openReminders', {search: ''}),
    mainSelector: '[data-reminder-save]', labels: ['Clear Form', 'Add Reminder'], mainClass: 'primary-btn',
    hasAlternative: true}),
  // Linux's default font is wider than the Mac's; with it the Reminders form's main action
  // wrapped onto a second row in CI (2026-10-28). A wide font here checks the same on a Mac.
  ['Reminders form, wide font', async page => {
    await openPalette(page, 'openReminders', {search: ''});
    await page.waitForSelector('[data-reminder-save]', {visible: true});
    await page.evaluate(font => {
      const style = document.createElement('style');
      style.id = 'dialog-button-wide-font';
      style.textContent = `.reminder-form-actions button { font-family: ${font} !important; letter-spacing: 0.4px; }`;
      document.head.append(style);
    }, WIDE_FONT);
    await settle(page);
    await assertRow(page, {label: 'Reminders form, wide font', mainSelector: '[data-reminder-save]',
      labels: ['Clear Form', 'Add Reminder'], mainClass: 'primary-btn', hasAlternative: true});
    await page.evaluate(() => document.getElementById('dialog-button-wide-font').remove());
    await closeWithEscape(page);
  }],
  ['Tag manager', async page => {
    await openModal(page, '/static/js/modules/modals/ontology-modal.js', 'OntologyModal', 'open', null);
    await page.waitForFunction(() => document.activeElement?.id === 'ontology-search-input');
    const editorOrder = await page.$$eval('.ontology-dialog-footer button', buttons => buttons.map(button => button.textContent.trim()));
    assert.deepEqual(editorOrder, ['Delete Tag…', 'Cancel', 'Save'], 'Tag manager editor: buttons in order');
    await page.evaluate(() => { void window.dialogButtonModal._deleteFocusedTag('dialog-button-test-tag'); });
    await page.waitForSelector('[data-action="dialog-submit"]', {visible: true});
    await settle(page);
    await assertRow(page, {label: 'Tag manager delete confirmation', mainSelector: '[data-action="dialog-submit"]',
      labels: ['Cancel', 'Delete Tag'], mainClass: 'ontology-dialog-destructive', hasAlternative: false});
    await closeWithEscape(page);
    await closeWithEscape(page);
  }],
];

export async function checkDialogButtons(page) {
  const appWindow = page.viewport();
  await page.setViewport(WIDE_WINDOW);
  const failures = [];
  for (const [label, run] of CASES) {
    try {
      await run(page);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
      console.log(`FAIL ${label}: ${error.message}`);
      for (let press = 0; press < ESCAPES_AFTER_A_FAILURE; press++) await page.keyboard.press('Escape');
      await page.setViewport(WIDE_WINDOW);
      await settle(page);
    }
  }
  await page.setViewport(appWindow);
  if (failures.length > 0) throw new assert.AssertionError({message: failures.join('\n')});
}
