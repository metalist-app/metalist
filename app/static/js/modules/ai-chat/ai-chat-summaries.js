/**
 * Long chats (docs/ui/ai-chat.md): what the AI still sees of each turn, and where the
 * summaries that replaced earlier turns sit in the conversation.
 *
 * Every message carries its visibility from the server: 'sent' (the AI sees it),
 * 'summarized' (only a summary stands for it) or 'held_back' (the AI sees nothing of it
 * since the privacy settings changed). A summary sits right after the last message it
 * replaced; one divider follows the last held-back item.
 */

import { LOCAL_MESSAGE_ID_PREFIX } from './ai-chat-refused-turns.js';

export const SUMMARY_VISIBILITY_SENT = 'sent';
export const SUMMARY_VISIBILITY_SUMMARIZED = 'summarized';
export const SUMMARY_VISIBILITY_HELD_BACK = 'held_back';
const VISIBILITIES = new Set([SUMMARY_VISIBILITY_SENT, SUMMARY_VISIBILITY_SUMMARIZED, SUMMARY_VISIBILITY_HELD_BACK]);
export const HELD_BACK_DIVIDER_ID = 'ai-chat-held-back-divider';

export function validateVisibility(visibility) {
    if (!VISIBILITIES.has(visibility)) {
        throw new Error(`AI chat visibility is invalid: ${visibility}`);
    }
    return visibility;
}

export function validateSummary(summary) {
    if (!summary || typeof summary !== 'object' || Array.isArray(summary)) {
        throw new Error('AI chat summary must be an object');
    }
    for (const key of ['id', 'content', 'rendered_content', 'after_message_id']) {
        if (typeof summary[key] !== 'string' || summary[key] === '') {
            throw new Error(`AI chat summary ${key} must be a non-empty string`);
        }
    }
    validateVisibility(summary.visibility);
    return summary;
}

/**
 * The conversation in order: { kind: 'message', message }, { kind: 'summary', summary }
 * after the message it follows, and { kind: 'held-back-divider', id } after the last
 * held-back item.
 */
export function conversationItems(messages, summaries) {
    if (!Array.isArray(messages) || !Array.isArray(summaries)) {
        throw new TypeError('conversationItems requires messages and summaries');
    }
    const summariesAfter = new Map();
    for (const summary of summaries) {
        const following = summariesAfter.get(summary.after_message_id);
        if (following === undefined) {
            summariesAfter.set(summary.after_message_id, [summary]);
        } else {
            following.push(summary);
        }
    }
    const items = [];
    let lastHeldBackIndex = -1;
    for (const message of messages) {
        items.push({ kind: 'message', message });
        if (message.visibility === SUMMARY_VISIBILITY_HELD_BACK) lastHeldBackIndex = items.length - 1;
        const following = summariesAfter.get(message.id);
        if (following === undefined) continue;
        summariesAfter.delete(message.id);
        for (const summary of following) {
            items.push({ kind: 'summary', summary });
            if (summary.visibility === SUMMARY_VISIBILITY_HELD_BACK) lastHeldBackIndex = items.length - 1;
        }
    }
    if (summariesAfter.size > 0) {
        throw new Error('An AI chat summary follows a message the chat does not have');
    }
    if (lastHeldBackIndex >= 0) {
        items.splice(lastHeldBackIndex + 1, 0, { kind: 'held-back-divider', id: HELD_BACK_DIVIDER_ID });
    }
    return items;
}

/** Whether "Summarize now" has anything to do: a turn the AI still sees directly. */
export function hasTurnsToSummarize(messages) {
    if (!Array.isArray(messages)) {
        throw new TypeError('hasTurnsToSummarize requires messages');
    }
    return messages.some((message) => (
        message.role === 'user'
        && message.visibility === SUMMARY_VISIBILITY_SENT
        && !message.id.startsWith(LOCAL_MESSAGE_ID_PREFIX)
    ));
}
