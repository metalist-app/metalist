import assert from 'node:assert/strict';

export async function checkAiResponseMenu(page) {
    await page.evaluate(async () => {
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        await CommandPalette.applyPreference('pref.show_ai_chat', true);
        const {AiChatPanel} = await import('/static/js/modules/ai-chat/ai-chat-panel-controller.js');
        AiChatPanel._messages.push({
            id: 'response-menu-fixture', role: 'assistant', status: 'complete',
            content: 'A response long enough to fill the available bubble width and wrap to another line.',
            rendered_content: '<p>A response long enough to fill the available bubble width and wrap to another line.</p><p><a href="https://example.com">Example link</a></p>',
            thinking: '', rendered_thinking: '', error: '', provider: 'openai',
            model: 'gpt-5.6-luna', activities: [],
        });
        AiChatPanel._render({shouldScrollToBottom: true});
    });
    const selector = '[data-message-id="response-menu-fixture"]';
    for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
        const points = await page.$eval(selector, bubble => {
            const rect = bubble.getBoundingClientRect();
            const text = bubble.querySelector('p').getBoundingClientRect();
            const link = bubble.querySelector('a').getBoundingClientRect();
            return [
                ['text', text.left + 8, text.top + 8],
                ['left padding', rect.left + 2, rect.top + rect.height / 2],
                ['right padding', rect.right - 2, rect.top + rect.height / 2],
                ['top padding', rect.left + rect.width / 2, rect.top + 2],
                ['bottom padding', rect.left + rect.width / 2, rect.bottom - 2],
                ['link', link.left + 8, link.top + 8],
            ];
        });
        for (const [label, x, y] of points) {
            await page.mouse.click(x, y, {button: 'right'});
            const labels = await page.$$eval('.context-menu.is-visible button', buttons => buttons
                .filter(button => button.getClientRects().length).map(button => button.textContent.trim()));
            assert.deepEqual(labels, ['Copy Response'], `${theme}: ${label}`);
            await page.keyboard.press('Escape');
        }
    }
    for (const [role, status] of [['assistant', 'streaming'], ['assistant', 'error'], ['user', 'complete']]) {
        await page.evaluate(({role, status}) => import('/static/js/modules/ai-chat/ai-chat-panel-controller.js').then(({AiChatPanel}) => {
            const message = AiChatPanel._messages.find(message => message.id === 'response-menu-fixture');
            if (message.role !== role) message.role = role;
            if (message.status !== status) message.status = status;
            AiChatPanel._render({shouldScrollToBottom: true});
        }), {role, status});
        await page.click(selector, {button: 'right'});
        const labels = await page.$$eval('.context-menu.is-visible button', buttons => buttons.map(button => button.textContent.trim()));
        assert(!labels.includes('Copy Response'), `${role}/${status} must not offer Copy Response`);
        await page.keyboard.press('Escape');
    }
    console.log('PASS Copy Response across bubble text, padding, and links in both themes');

    const copiedResponseNoteId = await page.evaluate(async () => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const created = await NotesAPI.createNote(null, '');
        await NotesAPI.saveNote(
            created.id,
            '<div class="ai-chat-message-content meta-markdown" data-markdown-rendered="true">'
            + '<p>Copied AI response.</p><section class="ai-chat-references" aria-label="References">'
            + '<details class="ai-chat-references-disclosure">'
            + '<summary class="ai-chat-references-heading">References</summary>'
            + '<ol><li class="ai-chat-web-reference"><span class="ai-chat-reference-number">[1]</span>'
            + '<a href="https://example.com" target="_blank" rel="noopener noreferrer">Example</a>'
            + '</li></ol></details></section></div>',
            '@ai',
        );
        return created.id;
    });
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    const disclosureSelector = (
        `[data-note-id="${copiedResponseNoteId}"] `
        + 'details.ai-chat-references-disclosure'
    );
    await page.waitForSelector(`${disclosureSelector} > summary`);
    assert.equal(await page.$eval(disclosureSelector, details => details.open), false);
    for (const expectedOpen of [true, false]) {
        await page.click(`${disclosureSelector} > summary`);
        await page.waitForFunction(
            (selector, isOpen) => document.querySelector(selector)?.open === isOpen,
            {},
            disclosureSelector,
            expectedOpen,
        );
        const editingState = await page.evaluate(async noteId => {
            const {ModeContextInstance} = await import(
                '/static/js/modules/mode-manager/mode-context.js'
            );
            return {
                isEditing: ModeContextInstance.isEditing,
                noteHasEditingClass: document.querySelector(
                    `[data-note-id="${noteId}"]`,
                ).classList.contains('editing'),
            };
        }, copiedResponseNoteId);
        assert.deepEqual(editingState, {
            isEditing: false,
            noteHasEditingClass: false,
        });
    }
    console.log('PASS copied AI response References opens and closes without edit mode');
}
