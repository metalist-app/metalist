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
    const input = document.getElementById('ai-agent-add-model');
    return input && !input.disabled;
  });
  const initial = await page.evaluate(() => ({
    text: document.getElementById('ai-agent-settings-modal').textContent,
    tabs: [...document.querySelectorAll('#ai-agent-settings-modal .ai-settings-tab')]
      .map((tab) => `${tab.textContent}:${tab.getAttribute('aria-selected')}`),
    // The model is picked in the chat, not here.
    modelPicker: Boolean(document.querySelector('#ai-agent-settings-modal select')),
    download: Boolean(document.getElementById('ai-agent-download')),
    addedModels: document.getElementById('ai-agent-added-models').textContent.trim(),
    webAccessMode: document.querySelector('#ai-agent-web-access [aria-checked="true"]').dataset.mode,
    tokenWindow: document.getElementById('ai-agent-max-page-approximate-tokens').value,
    taggingLimit: Boolean(document.getElementById('ai-agent-tagging-batch-tokens')),
  }));
  assert.match(initial.text, /\(blacklist\)[\s\S]*\(whitelist\)[\s\S]*Max token window/);
  assert.doesNotMatch(initial.text, /Ollama|Download an/);
  assert.deepEqual(initial.tabs, ['OpenAI:true', 'Claude:false', 'Gemini:false']);
  assert.equal(initial.modelPicker, false);
  assert.equal(initial.download, false);
  assert.equal(initial.addedModels, '');
  assert.equal(initial.webAccessMode, 'none');
  assert.equal(initial.tokenWindow, '500000');
  assert.equal(initial.taggingLimit, false);
  await page.type('#ai-agent-add-model', 'gpt-5.7-nova');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.getElementById('ai-agent-added-models').textContent.includes('gpt-5.7-nova'));
  await page.click('#ai-agent-web-access [data-mode="contextual"]');
  await page.click('#ai-agent-save');
  await page.waitForSelector('#ai-agent-settings-modal', {hidden: true});
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  // The chat's picker offers the added model; picking one there is what sticks.
  const choices = await page.evaluate(async () => {
    const {listAiModelChoices} = await import('/static/js/modules/ai-chat/ai-chat-api.js');
    return listAiModelChoices('openai');
  });
  assert.deepEqual(choices.groups.map((group) => [group.provider, group.models.at(-1)]), [['openai', 'gpt-5.7-nova']]);
  const saved = await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.saveAiSettings({provider: 'openai', model: 'gpt-5.7-nova', thinkingLevel: 'low'});
    return CommandPalette.getAiSettings();
  });
  assert.equal(saved.provider, 'openai');
  assert.equal(saved.model, 'gpt-5.7-nova');
  assert.equal(saved.webAccessMode, 'contextual');
  assert.equal(saved.maxPageApproximateTokens, 500000);
  assert.equal('taggingBatchTokens' in saved, false);
  console.log('PASS AI settings: provider tabs, added models reach the chat picker, web access and the token window save');
}
