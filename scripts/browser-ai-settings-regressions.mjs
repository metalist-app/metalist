import assert from 'node:assert/strict';
import {clickAndSelectAll} from './browser-select-field.mjs';

export async function checkOpenAiSettings(page) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const settings = CommandPalette.getAiSettings();
    if (settings.provider !== 'openai' || settings.model !== 'gpt-5.6-luna') {
      throw new Error('Fresh AI settings must use the default OpenAI model');
    }
    await CommandPalette.openAiAgentSettings('keys');
  });
  await page.waitForFunction(() => {
    const keyInput = document.getElementById('ai-agent-api-key');
    return keyInput && !keyInput.disabled;
  });
  const initial = await page.evaluate(() => ({
    text: document.getElementById('ai-agent-settings-modal').textContent,
    tabs: [...document.querySelectorAll('#ai-agent-settings-modal .ai-settings-tab')]
      .map((tab) => `${tab.textContent}:${tab.getAttribute('aria-selected')}`),
    // The model is picked in the chat, never here, and never typed in.
    modelPicker: Boolean(document.querySelector('#ai-agent-settings-modal select, #ai-agent-add-model')),
    download: Boolean(document.getElementById('ai-agent-download')),
    webAccessMode: document.querySelector('#ai-agent-web-access [aria-checked="true"]').dataset.mode,
    tokenWindow: document.getElementById('ai-agent-max-page-approximate-tokens').value,
    taggingLimit: Boolean(document.getElementById('ai-agent-tagging-batch-tokens')),
  }));
  assert.match(initial.text, /\(blacklist\)[\s\S]*\(whitelist\)[\s\S]*Max token window/);
  assert.doesNotMatch(initial.text, /Ollama|Download an/);
  assert.deepEqual(initial.tabs, ['OpenAI:true', 'Anthropic:false', 'Google:false']);
  assert.equal(initial.modelPicker, false);
  assert.equal(initial.download, false);
  assert.equal(initial.webAccessMode, 'none');
  assert.equal(initial.tokenWindow, '500000');
  assert.equal(initial.taggingLimit, false);
  // A key in the wrong format is explained under the key, in its tab; Google's AQ. keys
  // (AI Studio, 2026) are accepted. Test keys reach only this test server.
  await page.click('#ai-agent-tab-gemini');
  await page.waitForFunction(() => {
    const keyInput = document.getElementById('ai-agent-api-key');
    return document.getElementById('ai-agent-tab-gemini').getAttribute('aria-selected') === 'true'
      && keyInput && !keyInput.disabled;
  });
  await page.type('#ai-agent-api-key', 'not-a-google-key-0123456789abcdef');
  await page.click('#ai-agent-key-save');
  // A refused key is told in an error dialog over the settings; closing it returns to the key.
  await page.waitForSelector('#error-dialog .error-dialog-text');
  assert.equal(await page.$eval('#error-dialog .error-dialog-text', node => node.textContent),
    'Google API key must start with AIza or AQ.');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#error-dialog', {hidden: true});
  assert.equal(await page.evaluate(() => document.activeElement.id), 'ai-agent-api-key');
  await clickAndSelectAll(page, '#ai-agent-api-key');
  await page.type('#ai-agent-api-key', 'AQ.Test0123456789abcdefghijklmnopqrs');
  await page.click('#ai-agent-key-save');
  await page.waitForSelector('#ai-agent-key-remove');
  assert.equal(await page.$('#error-dialog'), null, 'An accepted key shows no error');
  await page.click('#ai-agent-key-remove');
  await page.waitForSelector('#ai-agent-api-key');
  await page.click('#ai-agent-tab-openai');
  await page.waitForFunction(() => {
    const keyInput = document.getElementById('ai-agent-api-key');
    return document.getElementById('ai-agent-tab-openai').getAttribute('aria-selected') === 'true'
      && keyInput && !keyInput.disabled;
  });
  // Web access is on the Reading tab.
  await page.click('#ai-agent-section-reading');
  await page.click('#ai-agent-web-access [data-mode="contextual"]');
  await page.click('#ai-agent-save');
  await page.waitForSelector('#ai-agent-settings-modal', {hidden: true});
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  // The chat's picker offers exactly the models MetaList ships; picking one there is what sticks.
  const choices = await page.evaluate(async () => {
    const {listAiModelChoices} = await import('/static/js/modules/ai-chat/ai-chat-api.js');
    return listAiModelChoices('openai');
  });
  assert.deepEqual(choices.groups.map((group) => [group.provider, group.models]),
    [['openai', ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']]]);
  const saved = await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.saveAiSettings({provider: 'openai', model: 'gpt-5.6-sol', thinkingLevel: 'low'});
    return CommandPalette.getAiSettings();
  });
  assert.equal(saved.provider, 'openai');
  assert.equal(saved.model, 'gpt-5.6-sol');
  assert.equal(saved.webAccessMode, 'contextual');
  assert.equal(saved.maxPageApproximateTokens, 500000);
  assert.equal('taggingBatchTokens' in saved, false);
  // Save with nothing changed (or changed back) closes the dialog like any Save.
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.openAiAgentSettings('keys');
  });
  await page.waitForFunction(() => {
    const keyInput = document.getElementById('ai-agent-api-key');
    return keyInput && !keyInput.disabled;
  });
  await page.click('#ai-agent-save');
  await page.waitForSelector('#ai-agent-settings-modal', {hidden: true});
  assert.equal(await page.$('#fatal-error-overlay'), null, 'Saving unchanged AI settings must not raise a fatal error');
  await checkSettingsTabs(page);
  console.log('PASS AI settings: provider tabs, the shipped models in the chat picker, web access and the token window save; an unchanged Save closes quietly; four tabs, each palette entry on its own');
}

// AI Agent Settings' four tabs (agreed 2026-11-07): Keys, Privacy, Reading and Tagging, one Save.
const SECTIONS = ['keys', 'privacy', 'reading', 'tagging'];
// The palette entries and the tab each opens on.
const ENTRIES = [
  ['form.ai_agent_settings', 'Keys'],
  ['form.cloud_ai_privacy', 'Privacy'],
  ['form.tagging_vocabulary', 'Tagging'],
];
const SETTINGS = '#ai-agent-settings-modal';

// Runs a palette entry itself, as choosing it in the palette does, and waits for the key status.
async function openFromPalette(page, endpointId) {
  await page.evaluate(async (id) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette._endpoints.find((endpoint) => endpoint.id === id).execute();
  }, endpointId);
  await page.waitForFunction(() => {
    const keyControl = document.getElementById('ai-agent-api-key') || document.getElementById('ai-agent-key-remove');
    return keyControl && !keyControl.disabled;
  });
}

async function closeSettings(page) {
  await page.keyboard.press('Escape');
  await page.waitForSelector(SETTINGS, {hidden: true});
}

function openTab(page) {
  return page.evaluate(() => ({
    tab: document.querySelector('#ai-agent-settings-modal .ai-settings-section-tab[aria-selected="true"]').textContent,
    // Only the open tab's panel can be used; the others are drawn but inert and hidden.
    usable: [...document.querySelectorAll('#ai-agent-settings-modal .ai-settings-section-panel')]
      .filter((panel) => !panel.inert && getComputedStyle(panel).visibility === 'visible')
      .map((panel) => panel.id),
    focused: document.activeElement.id,
  }));
}

async function checkSettingsTabs(page) {
  for (const [endpointId, tab] of ENTRIES) {
    await openFromPalette(page, endpointId);
    const opened = await openTab(page);
    assert.equal(opened.tab, tab, `${endpointId} opens AI Agent Settings on ${tab}`);
    assert.deepEqual(opened.usable, [`ai-agent-panel-${tab.toLowerCase()}`], `only ${tab} is usable`);
    if (tab === 'Privacy') {
      assert.equal(opened.focused, 'ai-agent-blacklist-input', 'Cloud AI Privacy puts the cursor in the first rule field');
    }
    await closeSettings(page);
  }

  // The dialog keeps one size whichever tab is open: nothing moves when switching.
  await openFromPalette(page, 'form.ai_agent_settings');
  const sizes = [];
  for (const section of SECTIONS) {
    await page.click(`#ai-agent-section-${section}`);
    sizes.push(await page.$eval(`${SETTINGS} .modal-content`, (content) => {
      const rect = content.getBoundingClientRect();
      return [rect.left, rect.top, rect.width, rect.height];
    }));
  }
  for (const size of sizes.slice(1)) assert.deepEqual(size, sizes[0], 'the dialog keeps its place and size on every tab');

  // What is typed but not yet added stays when switching tabs.
  await page.click('#ai-agent-section-privacy');
  await page.type('#ai-agent-blacklist-input', 'typed but not added');
  await page.click('#ai-agent-section-reading');
  await page.click('#ai-agent-section-privacy');
  assert.equal(await page.$eval('#ai-agent-blacklist-input', (input) => input.value), 'typed but not added',
    'switching tabs keeps typed text');
  await page.$eval('#ai-agent-blacklist-input', (input) => { input.value = ''; });
  await closeSettings(page);

  // The tagging vocabulary is saved with the rest, and an unchanged Save does nothing.
  await openFromPalette(page, 'form.tagging_vocabulary');
  await page.click('#ai-agent-tagging-vocabulary [data-vocabulary="existing"]');
  await page.click('#ai-agent-save');
  await page.waitForSelector(SETTINGS, {hidden: true});
  const saved = await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    return CommandPalette._preferences.getRaw('pref.ai.tagging.vocabulary');
  });
  assert.equal(saved, 'existing', 'the Tagging tab saves the vocabulary');
  await openFromPalette(page, 'form.tagging_vocabulary');
  assert.equal(await page.$eval('#ai-agent-tagging-vocabulary [data-vocabulary="existing"]',
    (choice) => choice.getAttribute('aria-checked')), 'true', 'reopened, the saved choice is shown');
  await page.click('#ai-agent-save');
  await page.waitForSelector(SETTINGS, {hidden: true});
  assert.equal(await page.$('#fatal-error-overlay'), null, 'an unchanged Save raises no fatal error');
}
