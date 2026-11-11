import assert from 'node:assert/strict';

function copiedResponseHtml(paragraph) {
    return '<div class="ai-chat-message-content meta-markdown" data-markdown-rendered="true">'
        + `<p>${paragraph}</p><section class="ai-chat-references" aria-label="References">`
        + '<details class="ai-chat-references-disclosure">'
        + '<summary class="ai-chat-references-heading">References</summary>'
        + '<ol><li class="ai-chat-web-reference"><span class="ai-chat-reference-number">[1]</span>'
        + '<a href="https://example.com" target="_blank" rel="noopener noreferrer">Example</a>'
        + '</li></ol></details></section></div>';
}

// What a link's fetched title does to a copied response: its note's drawn content changes, and
// the view refreshes (polling-service.js, refreshForLinkTitleChanges).
async function redrawNoteContent(page, noteId, paragraph) {
    await page.evaluate(async (noteId, html) => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
        await NotesAPI.saveNote(noteId, html, '@ai');
        await actionRefreshAndMaybeSelect({context: 'link-title-refresh'});
    }, noteId, copiedResponseHtml(paragraph));
    await page.waitForFunction(
        (noteId, paragraph) => document.querySelector(`[data-note-id="${noteId}"] .ai-chat-message-content > p`)?.textContent === paragraph,
        {},
        noteId,
        paragraph,
    );
}

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
            model: 'gpt-5.6-luna', visibility: 'sent', activities: [],
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

    const copiedResponseNoteId = await page.evaluate(async html => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const created = await NotesAPI.createNote(null, '');
        await NotesAPI.saveNote(created.id, html, '@ai');
        return created.id;
    }, copiedResponseHtml('Copied AI response.'));
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

    // Left closed, a redraw leaves it closed; opened, a redraw leaves it open, however many come.
    await redrawNoteContent(page, copiedResponseNoteId, 'First redraw');
    assert.equal(await page.$eval(disclosureSelector, details => details.open), false, 'a redraw must not open References');
    await page.click(`${disclosureSelector} > summary`);
    await page.waitForFunction(selector => document.querySelector(selector)?.open === true, {}, disclosureSelector);
    for (const paragraph of ['Second redraw', 'Third redraw']) {
        await redrawNoteContent(page, copiedResponseNoteId, paragraph);
        assert.equal(await page.$eval(disclosureSelector, details => details.open), true, `References closed at "${paragraph}"`);
    }

    // Editing the note and leaving it draws References closed, as a reload does.
    await page.click(`[data-note-id="${copiedResponseNoteId}"] .ai-chat-message-content > p`);
    await page.waitForSelector(`[data-note-id="${copiedResponseNoteId}"].editing`);
    await page.keyboard.press('Escape');
    await page.waitForSelector(`[data-note-id="${copiedResponseNoteId}"]:not(.editing)`);
    await page.waitForSelector(`${disclosureSelector} > summary`);
    assert.equal(await page.$eval(disclosureSelector, details => details.open), false, 'leaving edit mode draws References closed');

    // Two answers copied into one note: each References keeps its own state.
    await page.evaluate(async (noteId, html) => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
        await NotesAPI.saveNote(noteId, html, '@ai');
        await actionRefreshAndMaybeSelect({context: 'link-title-refresh'});
    }, copiedResponseNoteId, copiedResponseHtml('First answer') + copiedResponseHtml('Second answer'));
    await page.waitForFunction(selector => document.querySelectorAll(selector).length === 2, {}, disclosureSelector);
    const openStates = () => page.$$eval(disclosureSelector, folds => folds.map(fold => fold.open));
    await page.click(`[data-note-id="${copiedResponseNoteId}"] .ai-chat-message-content:last-of-type details > summary`);
    await page.waitForFunction(selector => document.querySelectorAll(selector)[1].open, {}, disclosureSelector);
    assert.deepEqual(await openStates(), [false, true]);
    await page.evaluate(async (noteId, html) => {
        const {NotesAPI} = await import('/static/js/modules/api-client.js');
        const {actionRefreshAndMaybeSelect} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
        await NotesAPI.saveNote(noteId, html, '@ai');
        await actionRefreshAndMaybeSelect({context: 'link-title-refresh'});
    }, copiedResponseNoteId, copiedResponseHtml('First answer, redrawn') + copiedResponseHtml('Second answer'));
    await page.waitForFunction(
        noteId => document.querySelector(`[data-note-id="${noteId}"] .ai-chat-message-content > p`).textContent === 'First answer, redrawn',
        {},
        copiedResponseNoteId,
    );
    assert.deepEqual(await openStates(), [false, true], 'each References keeps its own state');
    console.log('PASS copied AI response References stays as left while link titles arrive');
}
