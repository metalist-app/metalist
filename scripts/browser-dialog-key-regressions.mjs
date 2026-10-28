import assert from 'node:assert/strict';

// Enter and first focus in dialogs (docs/ui/modals.md, "Dialog and menu conventions",
// rule 4 and 5; agreed case by case 2026-10-24):
// - Enter never triggers a destructive action. A destructive dialog opens with focus on
//   Cancel (Enter cancels), or in the field the user must type in (Enter does nothing).
// - Enter on a focused button presses that button, so Enter on Cancel cancels.
// - Enter in Open Vault opens the vault in this tab instead of throwing.

const FRAMES_TO_SETTLE = 3;

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

// Records every changing request (not a read) whose path contains one of `fragments` and
// answers it with an error, so an action the test triggers by mistake is seen and never
// carried out.
async function recordRequests(page, fragments) {
  await page.evaluate(watched => {
    window.dialogKeyTest = {requests: []};
    const originalFetch = window.fetch;
    window.dialogKeyTest.restore = () => { window.fetch = originalFetch; };
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      const method = new Request(input, init).method;
      if (method !== 'GET' && watched.some(fragment => url.pathname.includes(fragment))) {
        window.dialogKeyTest.requests.push(url.pathname);
        return new Response(JSON.stringify({detail: 'Blocked by the dialog key test'}),
          {status: 409, headers: {'Content-Type': 'application/json'}});
      }
      return originalFetch(input, init);
    };
  }, fragments);
}

async function recordedRequests(page) {
  return page.evaluate(() => {
    const requests = window.dialogKeyTest.requests;
    window.dialogKeyTest.restore();
    return requests;
  });
}

async function focusedId(page) {
  return page.evaluate(() => document.activeElement.id);
}

async function isShown(page, selector) {
  return page.evaluate(target => {
    const element = document.querySelector(target);
    return element instanceof HTMLElement && element.getClientRects().length > 0;
  }, selector);
}

// Opens one of the confirmation-style dialogs that resolve a promise, and keeps its answer.
async function openPromiseDialog(page, modulePath, className, method, context) {
  await page.evaluate(async ({modulePath, className, method, context}) => {
    const module = await import(modulePath);
    window.dialogKeyAnswer = {settled: false, value: undefined};
    new module[className]()[method](context).then(value => {
      window.dialogKeyAnswer = {settled: true, value};
    });
  }, {modulePath, className, method, context});
}

async function answer(page) {
  return page.evaluate(() => window.dialogKeyAnswer);
}

async function checkConfirmationStartsOnCancel(page, {label, modulePath, className, method, context, cancelId}) {
  await openPromiseDialog(page, modulePath, className, method, context);
  await page.waitForSelector(`#${cancelId}`, {visible: true});
  await settle(page);
  assert.equal(await focusedId(page), cancelId, `${label}: focus must start on Cancel`);
  await page.keyboard.press('Enter');
  await settle(page);
  const result = await answer(page);
  assert.equal(result.settled, true, `${label}: Enter on Cancel must close the dialog`);
  assert.notEqual(result.value, true, `${label}: Enter must not confirm the destructive action`);
  assert.equal(await isShown(page, `#${cancelId}`), false, `${label}: the dialog must be closed`);
}

async function checkConfirmations(page) {
  await checkConfirmationStartsOnCancel(page, {
    label: 'Delete confirmation', modulePath: '/static/js/modules/modals/confirmation-modal.js',
    className: 'ConfirmationModal', method: 'openForConfirmation',
    context: {eyebrow: 'Reference', title: 'Delete this note?', description: 'It is referenced elsewhere.',
      confirmLabel: 'Delete', isDangerous: true},
    cancelId: 'confirmation-cancel-btn',
  });
  await checkConfirmationStartsOnCancel(page, {
    label: 'Reset Timestamps', modulePath: '/static/js/modules/modals/reset-updated-at-modal.js',
    className: 'ResetUpdatedAtModal', method: 'openForSearchContext', context: {searchQuery: ''},
    cancelId: 'reset-updated-at-cancel-btn',
  });
  await checkConfirmationStartsOnCancel(page, {
    label: 'Alphabetize', modulePath: '/static/js/modules/modals/alphabetize-root-notes-modal.js',
    className: 'AlphabetizeRootNotesModal', method: 'openForDirection', context: {direction: 'asc', searchQuery: ''},
    cancelId: 'alphabetize-root-notes-cancel-btn',
  });
}

async function checkPrioritizeEnterDoesNotReorder(page) {
  await openPromiseDialog(page, '/static/js/modules/modals/prioritize-modal.js', 'PrioritizeModal',
    'openForDirection', {direction: 'front', searchQuery: ''});
  await page.waitForSelector('#prioritize-tag-input', {visible: true});
  await settle(page);
  assert.equal(await focusedId(page), 'prioritize-tag-input', 'Prioritize: focus must start in the tag field');
  await page.keyboard.type('nosuchtagforthistest');
  await settle(page);
  await page.keyboard.press('Enter');
  await settle(page);
  assert.equal((await answer(page)).settled, false, 'Prioritize: Enter in the tag field must not reorder');
  assert.equal(await isShown(page, '#prioritize-tag-input'), true, 'Prioritize: the dialog must stay open');
  await page.keyboard.press('Escape');
  await settle(page);
  assert.equal((await answer(page)).settled, true, 'Prioritize: Escape must close the dialog');
}

async function checkSearchStatisticsReset(page) {
  await recordRequests(page, ['search-suggestion', 'search-statistics', 'search-activity']);
  await page.evaluate(async () => {
    window.dialogKeyTest.restore();
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    void CommandPalette.openSearchSuggestionStatistics();
  });
  await page.waitForSelector('#search-suggestion-statistics-reset-btn', {visible: true});
  await recordRequests(page, ['reset']);
  await page.click('#search-suggestion-statistics-reset-btn');
  await page.waitForSelector('#search-suggestion-statistics-reset-cancel-btn', {visible: true});
  await settle(page);
  assert.equal(await focusedId(page), 'search-suggestion-statistics-reset-cancel-btn',
    'Reset Activity: focus must start on Cancel');
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], 'Reset Activity: Enter must not reset');
  assert.equal(await isShown(page, '#search-suggestion-statistics-reset-confirm-btn'), false,
    'Reset Activity: Enter on Cancel must leave the confirmation');
  await page.keyboard.press('Escape');
  await settle(page);
}

async function checkDeleteVault(page) {
  await page.evaluate(async () => {
    const {DeleteNamespaceModal} = await import('/static/js/modules/modals/delete-namespace-modal.js');
    window.dialogKeyDelete = new DeleteNamespaceModal();
    void window.dialogKeyDelete.open();
  });
  await page.waitForFunction(() => document.querySelector('#delete-namespace-modal .form-actions button') !== null);
  // The confirm step for this vault, as the dialog reaches it after its preflight (the test
  // vault is the only one, so the choose step offers nothing to delete).
  await page.evaluate(() => {
    const modal = window.dialogKeyDelete;
    modal.updateModalState({
      loading: false, confirming: true, namespace: 'default', targetNamespaceText: 'default', confirmationText: '',
      activeNamespaceDeleted: true, redirectNamespaces: ['default'], redirectNamespace: 'default',
      recreatesDefault: true, error: '', status: '',
    });
    modal.renderModalContent();
  });
  await page.waitForSelector('#delete-namespace-confirmation', {visible: true});
  await settle(page);
  assert.equal(await focusedId(page), 'delete-namespace-confirmation',
    'Delete Vault: focus must start in the vault-name field');
  await recordRequests(page, ['/namespaces/delete']);
  const vault = await page.$eval('#delete-namespace-confirmation', input => input.placeholder);
  await page.keyboard.type(vault);
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual((await recordedRequests(page)).filter(path => !path.includes('preflight')), [],
    'Delete Vault: Enter in the name field must not delete');
  assert.equal(await isShown(page, '#delete-namespace-confirmation'), true, 'Delete Vault: the dialog must stay open');
  await page.keyboard.press('Escape');
  await settle(page);
}

async function checkImportOverwrite(page) {
  await page.evaluate(async () => {
    const {BackupRestoreModal} = await import('/static/js/modules/modals/backup-restore-modal.js');
    window.dialogKeyRestore = new BackupRestoreModal();
    await window.dialogKeyRestore.open();
  });
  await page.waitForSelector('#close-backup-modal-btn', {visible: true});
  // The overwrite step of an import over another existing vault, reached as the dialog
  // reaches it after its preflight: a backup chosen, the target vault named and checked.
  await page.evaluate(() => {
    const modal = window.dialogKeyRestore;
    modal.updateModalState({
      loading: false,
      backups: [{backup_id: 'b1', filename: 'other-backup.zip', namespace: 'other', created_at: '2026-10-24T10:00:00Z',
        size_bytes: 2048, source: 'internal'}],
      selectedBackupId: 'b1', targetNamespaceText: 'default', confirming: true,
      preflight: {same_namespace: false, target_exists: true, target_requires_password: false},
      overwriteConfirmText: '', error: '',
    });
    modal.renderModalContent();
  });
  await page.waitForSelector('#backup-overwrite-confirmation', {visible: true});
  await settle(page);
  assert.equal(await focusedId(page), 'backup-overwrite-confirmation',
    'Import And Overwrite Vault: focus must start in the vault-name field');
  await recordRequests(page, ['restore', 'import']);
  await page.keyboard.type('default');
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], 'Import And Overwrite Vault: Enter must not overwrite');
  await page.keyboard.press('Escape');
  await settle(page);
}

async function checkEnterOnCancelCancels(page, {label, open, cancelSelector, watched}) {
  await recordRequests(page, watched);
  await page.evaluate(open);
  await page.waitForSelector(cancelSelector, {visible: true});
  await settle(page);
  await page.focus(cancelSelector);
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], `${label}: Enter on Cancel must not run the main action`);
  assert.equal(await isShown(page, cancelSelector), false, `${label}: Enter on Cancel must close the dialog`);
}

async function checkCancelButtons(page) {
  await checkEnterOnCancelCancels(page, {
    label: 'Session Timeout', cancelSelector: '#session-timeout-cancel-btn', watched: ['session-timeout'],
    open: async () => {
      const {SessionTimeoutModal} = await import('/static/js/modules/modals/session-timeout-modal.js');
      void new SessionTimeoutModal().open();
    },
  });
  await checkEnterOnCancelCancels(page, {
    label: 'Back Up Now', cancelSelector: '#backup-settings-cancel-btn', watched: ['/backup/create', '/backup/run'],
    open: async () => {
      const {BackupSettingsModal} = await import('/static/js/modules/modals/backup-settings-modal.js');
      void new BackupSettingsModal().openForBackup();
    },
  });
  await checkEnterOnCancelCancels(page, {
    label: 'Restore', cancelSelector: '#close-backup-modal-btn', watched: ['restore', 'import'],
    open: async () => {
      const {BackupRestoreModal} = await import('/static/js/modules/modals/backup-restore-modal.js');
      void new BackupRestoreModal().open();
    },
  });
  await checkEnterOnCancelCancels(page, {
    label: 'Add Password', cancelSelector: '#cancel-btn', watched: ['/password/create'],
    open: async () => {
      const {AddPasswordModal} = await import('/static/js/modules/modals/password-modal.js');
      void new AddPasswordModal().open();
    },
  });
  // The paste-an-image choice is its own small dialog with a capture-phase key listener.
  await page.evaluate(async () => {
    const {promptForImageFileInsertMode} = await import('/static/js/modules/mode-manager/services/image-file-insert-choice-modal-service.js');
    window.dialogKeyImage = {settled: false, value: undefined};
    promptForImageFileInsertMode({imageCount: 1, source: 'paste'}).then(value => {
      window.dialogKeyImage = {settled: true, value};
    });
  });
  await page.waitForSelector('#image-file-insert-choice-cancel', {visible: true});
  await settle(page);
  await page.focus('#image-file-insert-choice-cancel');
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await page.evaluate(() => window.dialogKeyImage), {settled: true, value: null},
    'Paste Image choice: Enter on Cancel must cancel');
}

async function checkTagManagerDelete(page) {
  await page.evaluate(async () => {
    const {OntologyModal} = await import('/static/js/modules/modals/ontology-modal.js');
    window.dialogKeyOntology = new OntologyModal();
    await window.dialogKeyOntology.open();
  });
  await page.waitForSelector('[data-action="dialog-cancel"]');
  // The tag manager puts focus in its search field as it opens; a tag is deleted later.
  await page.waitForFunction(() => document.activeElement?.id === 'ontology-search-input');
  await recordRequests(page, ['/delete-tag']);
  await page.evaluate(() => { void window.dialogKeyOntology._deleteFocusedTag('dialog-key-test-tag'); });
  await page.waitForSelector('[data-action="dialog-cancel"]', {visible: true});
  await page.waitForFunction(() => document.activeElement?.closest('#ontology-dialog-overlay') != null);
  await settle(page);
  const focused = await page.evaluate(() => document.activeElement.outerHTML.slice(0, 160));
  assert.equal(await page.evaluate(() => document.activeElement.dataset.action), 'dialog-cancel',
    `Tag manager Delete: focus must start on Cancel, not ${focused}`);
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], 'Tag manager Delete: Enter must not delete');
  assert.equal(await isShown(page, '[data-action="dialog-cancel"]'), false, 'Tag manager Delete: Enter on Cancel must close the confirmation');
  await page.keyboard.press('Escape');
  await settle(page);
}

async function checkOpenVaultEnter(page) {
  // Only this vault exists in the test, so opening it in this tab is refused with a
  // message; Enter used to throw instead (handleSubmit without its tab choice).
  const pageErrors = [];
  const recordError = error => pageErrors.push(error.message);
  page.on('pageerror', recordError);
  try {
    await page.evaluate(async () => {
      const {OpenNamespaceModal} = await import('/static/js/modules/modals/namespace-modals.js');
      void new OpenNamespaceModal().open();
    });
    await page.waitForSelector('#open-namespace-this-tab-btn', {visible: true});
    await settle(page);
    // Enter after picking a vault in the list.
    await page.focus('input[name="open-namespace-choice"]');
    await page.evaluate(() => {
      window.dialogKeyOpenThrew = false;
      window.addEventListener('unhandledrejection', () => { window.dialogKeyOpenThrew = true; }, {once: true});
    });
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.dialogKeyOpenThrew || document.getElementById('error-dialog') !== null);
    assert.equal(await page.$eval('#error-dialog .error-dialog-text', element => element.textContent.trim()),
      'That is the vault you are in. Pick another one.', 'Open Vault: Enter must try to open the vault in this tab');
    await page.keyboard.press('Escape');
    await settle(page);
  } finally {
    page.off('pageerror', recordError);
  }
  assert.deepEqual(pageErrors, [], 'Open Vault: Enter must not throw');
  await page.keyboard.press('Escape');
  await settle(page);
}

async function checkRemovePassword(page, password) {
  await page.evaluate(async secret => {
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/auth/settings/password/create',
      {method: 'POST', headers: buildSessionHeaders(true), body: JSON.stringify({password: secret})});
    if (!response.ok) throw new Error(`Password setup failed: ${response.status}`);
    const {RemovePasswordModal} = await import('/static/js/modules/modals/password-modal.js');
    void new RemovePasswordModal().open();
  }, password);
  await page.waitForSelector('#current-password', {visible: true});
  await settle(page);
  // What has focus instead, when it fails (Firefox on Linux found none, 2026-10-28).
  const focused = await page.evaluate(() => {
    const active = document.activeElement;
    return `${active.tagName}#${active.id}.${active.className} in ${active.closest('[id]')?.id}; dialog shown: ${document.getElementById('current-password') !== null}`;
  });
  assert.equal(await focusedId(page), 'current-password', `Remove Password: focus must start in the password field (focus: ${focused})`);
  await recordRequests(page, ['/password/remove']);
  await page.keyboard.type(password);
  await page.click('#confirm-remove');
  await page.focus('#current-password');
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], 'Remove Password: Enter in the field must not remove the password');
  assert.equal(await isShown(page, '#current-password'), true, 'Remove Password: the dialog must stay open');
  await recordRequests(page, ['/password/remove']);
  await page.focus('#cancel-btn');
  await page.keyboard.press('Enter');
  await settle(page);
  assert.deepEqual(await recordedRequests(page), [], 'Remove Password: Enter on Cancel must not remove the password');
  assert.equal(await isShown(page, '#current-password'), false, 'Remove Password: Enter on Cancel must close the dialog');
}

// Escape presses that close whatever a failed case left open, a dialog over a dialog at most.
const ESCAPES_AFTER_A_FAILURE = 3;

export async function checkDialogKeys(page) {
  const cases = [
    ['confirmations', checkConfirmations],
    ['prioritize', checkPrioritizeEnterDoesNotReorder],
    ['search statistics reset', checkSearchStatisticsReset],
    ['delete vault', checkDeleteVault],
    ['import and overwrite', checkImportOverwrite],
    ['Enter on Cancel', checkCancelButtons],
    ['tag manager delete', checkTagManagerDelete],
    ['open vault', checkOpenVaultEnter],
    // Last: it gives the test vault a password.
    ['remove password', currentPage => checkRemovePassword(currentPage, 'Dialog-key-test-password!2026')],
  ];
  const failures = [];
  for (const [label, run] of cases) {
    try {
      await run(page);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
      console.log(`FAIL ${label}: ${error.message}`);
      for (let press = 0; press < ESCAPES_AFTER_A_FAILURE; press++) await page.keyboard.press('Escape');
      await settle(page);
    }
  }
  if (failures.length > 0) throw new assert.AssertionError({message: failures.join('\n')});
}
