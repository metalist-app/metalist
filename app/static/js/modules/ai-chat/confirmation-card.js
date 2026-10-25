/**
 * Yes/No card for changes the AI proposes (accepting or removing tag proposals,
 * opening web addresses that contain text the user did not type). The server
 * waits for the answer; nothing happens until the user clicks Yes.
 */

import { rethrowUnexpectedError } from '../expected-errors.js';
import { AiApiError } from './ai-chat-api.js';
import { proposalRequest } from './bulk-proposal-ui.js';
import { describeConfirmationQuestion } from './confirmation-question.js';

/**
 * Render the card into `host`. The returned promise resolves once the server
 * accepted an answer ('yes' or 'no'), or with 'cancelled' when the chat request
 * ends first; the card is removed either way. A rejected answer stays on the
 * card so the user can retry. Callers must not await it while reading the
 * stream: the server sends nothing until the answer arrives, and a cancelled
 * request must still end the stream.
 */
export function showConfirmationCard({ event, host, signal }) {
    const question = describeConfirmationQuestion(event);
    if (!(host instanceof HTMLElement)) throw new TypeError('Confirmation card requires a host element');
    const card = document.createElement('section');
    card.className = 'ai-chat-confirmation';
    card.setAttribute('aria-label', 'Confirm change');
    const heading = document.createElement('h2');
    heading.textContent = 'Confirm';
    const label = document.createElement('p');
    label.className = 'ai-chat-confirmation-label';
    label.textContent = question.label;
    const items = document.createElement('ul');
    items.className = 'ai-chat-confirmation-items';
    for (const text of question.items) {
        const item = document.createElement('li');
        const code = document.createElement('code');
        code.textContent = text;
        item.append(code);
        items.append(item);
    }
    const error = document.createElement('p');
    error.setAttribute('role', 'alert');
    // Cancel, then the main action rightmost (docs/ui/modals.md, "Dialog and menu conventions").
    const yes = document.createElement('button');
    yes.type = 'button';
    yes.textContent = 'Apply';
    yes.dataset.answer = 'yes';
    const no = document.createElement('button');
    no.type = 'button';
    no.className = 'secondary-btn';
    no.textContent = 'Cancel';
    no.dataset.answer = 'no';
    const actions = document.createElement('div');
    actions.className = 'form-actions';
    actions.append(no, yes);
    card.append(heading, label);
    if (question.items.length > 0) card.append(items);
    card.append(actions, error);
    host.append(card);
    yes.focus();
    return new Promise((resolve) => {
        const abandon = () => {
            card.remove();
            resolve('cancelled');
        };
        if (signal.aborted) {
            abandon();
            return;
        }
        signal.addEventListener('abort', abandon, { once: true });
        const answer = async (value) => {
            yes.disabled = true;
            no.disabled = true;
            error.textContent = '';
            // lint: allow-JS001 rationale="submit an external HTTP answer; rethrow internal failures"
            try {
                await proposalRequest('answer', { question_id: question.questionId, value }, signal);
            // lint: allow-JS001 rationale="cancellation and HTTP rejection are expected; internal errors propagate"
            } catch (caught) {
                rethrowUnexpectedError(caught);
                if (signal.aborted) return;
                if (!(caught instanceof AiApiError)) throw caught;
                error.textContent = caught.message;
                yes.disabled = false;
                no.disabled = false;
                return;
            }
            signal.removeEventListener('abort', abandon);
            card.remove();
            resolve(value);
        };
        yes.addEventListener('click', () => answer('yes'));
        no.addEventListener('click', () => answer('no'));
    });
}
