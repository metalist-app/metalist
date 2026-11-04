import assert from 'node:assert/strict';

export async function checkAiPrivacyPreview(page) {
    const ids = await page.evaluate(async () => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        const {serializeCloudPrivacyPolicy} = await import('/static/js/modules/ai-chat/cloud-privacy-policy.js');
        const ids = {};
        for (const [name, tags] of [['allowed', 'shared'], ['blacklisted', 'shared private'], ['notWhitelisted', 'personal']]) {
            const note = await NotesAPI.createNote(null, '');
            await NotesAPI.saveNote(note.id, `<p>${name} privacy preview fixture</p>`, tags);
            ids[name] = note.id;
        }
        const child = await NotesAPI.createChild(ids.blacklisted, '');
        await NotesAPI.saveNote(child.id, '<p>Excluded descendant inherits privacy</p>', 'shared');
        ids.child = child.id;
        await NotesAPI.setCollapsedBulk([ids.blacklisted], false);
        await CommandPalette.applyPreference('pref.ai.cloud_privacy_policy', serializeCloudPrivacyPolicy({
            whitelistTags: ['shared'], whitelistPhrases: [], blacklistTags: ['private'], blacklistPhrases: [],
        }));
        await CommandPalette.applyPreference('pref.show_ai_chat', true);
        return ids;
    });
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
        for (let repeat = 0; repeat < 2; repeat++) {
            await page.hover('#ai-chat-input');
            await page.waitForFunction(ids => ['blacklisted', 'notWhitelisted', 'child'].every(key =>
                document.querySelector(`[data-note-id="${ids[key]}"]`).classList.contains('cloud-ai-private-preview')), {}, ids);
            const styles = await page.evaluate(ids => Object.fromEntries(Object.entries(ids).map(([key, id]) => {
                const note = document.querySelector(`[data-note-id="${id}"]`);
                const icon = getComputedStyle(note, '::after');
                return [key, {noteFilter: getComputedStyle(note).filter,
                    contentFilter: getComputedStyle(note.querySelector(':scope > .note-content')).filter,
                    icon: icon.content,
                    childrenFilter: note.querySelector(':scope > .note-children')
                        ? getComputedStyle(note.querySelector(':scope > .note-children')).filter : 'none'}];
            })), ids);
            for (const key of ['blacklisted', 'notWhitelisted', 'child']) {
                assert.equal(styles[key].contentFilter, 'blur(4px)', `${theme}: ${key}`);
                assert.equal(styles[key].noteFilter, 'none');
                assert.equal(styles[key].childrenFilter, 'none');
                assert.equal(styles[key].icon, 'none');
            }
            assert.equal(styles.allowed.contentFilter, 'none');
            assert.equal(styles.allowed.icon, 'none');
            if (repeat === 0) await page.screenshot({path: `/tmp/metalist-ai-privacy-${theme}.png`});
            await page.mouse.move(2, 2);
            await page.waitForFunction(() => !document.querySelector('.cloud-ai-private-preview'));
            const cleared = await page.evaluate(ids => Object.values(ids).every(id => {
                const note = document.querySelector(`[data-note-id="${id}"]`);
                return getComputedStyle(note, '::after').content === 'none'
                    && getComputedStyle(note.querySelector(':scope > .note-content')).filter === 'none';
            }), ids);
            assert.equal(cleared, true);
        }
    }
    console.log('PASS privacy hover blur without lock icons for blacklist, whitelist exclusion and descendants, both themes, repeated enter/leave');
}

// The never-send and only-send rules in AI Agent Settings (2026-10-31): what is typed is a
// rule however the dialog is left by Save, by Enter (which saves, as in any dialog) or by
// the Add button beside the field (which adds it as a chip and keeps the dialog open).
// Before, only Enter made a typed rule, and Save dropped what was still in the field.
export async function checkPrivacyRuleEntry(page) {
    const open = async () => {
        await page.evaluate(async () => {
            const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
            await CommandPalette.openAiAgentSettings(false);
        });
        await page.waitForSelector('#ai-agent-blacklist-input');
    };
    const savedPolicy = () => page.evaluate(async () => {
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        return CommandPalette.getAiSettings().cloudPrivacyPolicy;
    });
    const closed = () => page.waitForSelector('#ai-agent-settings-modal', {hidden: true});
    const original = await savedPolicy();

    await open();
    await page.type('#ai-agent-blacklist-input', 'typed-then-saved');
    await page.click('#ai-agent-save');
    await closed();
    assert.ok((await savedPolicy()).blacklistTags.includes('typed-then-saved'), 'Save keeps the rule still typed in the field');

    await open();
    await page.type('#ai-agent-blacklist-input', 'typed-then-enter');
    await page.keyboard.press('Enter');
    await closed();
    assert.ok((await savedPolicy()).blacklistTags.includes('typed-then-enter'), 'Enter saves, with the rule typed');

    await open();
    await page.type('#ai-agent-blacklist-input', '"an added phrase"');
    await page.click('#ai-agent-blacklist-add');
    const afterAdd = await page.evaluate(() => ({
        isOpen: getComputedStyle(document.getElementById('ai-agent-settings-modal')).display !== 'none',
        field: document.getElementById('ai-agent-blacklist-input').value,
        chips: [...document.querySelectorAll('#ai-agent-settings-modal .ai-agent-cloud-privacy-settings .ai-settings-chip')]
            .map(chip => chip.textContent.trim()),
    }));
    assert.equal(afterAdd.isOpen, true, 'Add keeps the dialog open');
    assert.equal(afterAdd.field, '', 'Add empties the field for the next rule');
    assert.ok(afterAdd.chips.some(chip => chip.includes('an added phrase')), 'Add shows the rule as a chip');
    await page.click('#ai-agent-save');
    await closed();
    assert.ok((await savedPolicy()).blacklistPhrases.includes('an added phrase'), 'an added rule is saved');

    await page.evaluate(async original => {
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        const {serializeCloudPrivacyPolicy} = await import('/static/js/modules/ai-chat/cloud-privacy-policy.js');
        await CommandPalette.applyPreference('pref.ai.cloud_privacy_policy', serializeCloudPrivacyPolicy(original));
    }, original);
    console.log('PASS privacy rules: a typed rule is kept by Save, by Enter and by Add');
}
