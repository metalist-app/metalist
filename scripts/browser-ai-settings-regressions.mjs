import assert from 'node:assert/strict';

export async function checkOpenAiSettings(page) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    const settings = CommandPalette.getAiSettings();
    if (settings.provider !== 'openai' || settings.model !== 'gpt-5.6-luna') {
      throw new Error('Fresh AI settings must use the default OpenAI model');
    }
    await CommandPalette.openAiAgentSettings(false);
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
  await page.click('#ai-agent-api-key', {clickCount: 3});
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
    await CommandPalette.openAiAgentSettings(false);
  });
  await page.waitForFunction(() => {
    const keyInput = document.getElementById('ai-agent-api-key');
    return keyInput && !keyInput.disabled;
  });
  await page.click('#ai-agent-save');
  await page.waitForSelector('#ai-agent-settings-modal', {hidden: true});
  assert.equal(await page.$('#fatal-error-overlay'), null, 'Saving unchanged AI settings must not raise a fatal error');
  console.log('PASS AI settings: provider tabs, the shipped models in the chat picker, web access and the token window save; an unchanged Save closes quietly');
}
