import assert from 'node:assert/strict';
import test from 'node:test';

import { placeChatMessageElements } from '../../app/static/js/modules/ai-chat/ai-chat-message-placement.js';


class FakeDocument {
    createElement(tagName) {
        return new FakeElement(tagName, this);
    }
}


class FakeElement {
    constructor(tagName, ownerDocument) {
        this.tagName = tagName.toUpperCase();
        this.ownerDocument = ownerDocument;
        this.children = [];
        this.parentElement = null;
        this.dataset = {};
        this.className = '';
        this.hidden = false;
        this._textContent = '';
    }

    get textContent() {
        return this._textContent + this.children.map((child) => child.textContent).join('');
    }

    set textContent(value) {
        for (const child of this.children) child.parentElement = null;
        this.children = [];
        this._textContent = String(value);
    }

    _detach(node) {
        if (node.parentElement === null) return;
        const siblings = node.parentElement.children;
        siblings.splice(siblings.indexOf(node), 1);
        node.parentElement = null;
    }

    append(...nodes) {
        for (const node of nodes) {
            this._detach(node);
            node.parentElement = this;
            this.children.push(node);
        }
    }

    insertBefore(node, reference) {
        if (reference === null) {
            this.append(node);
            return node;
        }
        const index = this.children.indexOf(reference);
        if (index === -1) throw new Error('Reference node is not a child');
        this._detach(node);
        node.parentElement = this;
        this.children.splice(this.children.indexOf(reference), 0, node);
        return node;
    }

    replaceChildren(...nodes) {
        for (const child of this.children) child.parentElement = null;
        this.children = [];
        this._textContent = '';
        this.append(...nodes);
    }

    remove() {
        this._detach(this);
    }
}


function element(documentRef, label) {
    const node = documentRef.createElement('article');
    node.dataset.label = label;
    return node;
}


function labels(container) {
    return container.children.map((child) => child.dataset.label);
}


function summaryStack() {
    const documentRef = new FakeDocument();
    const stack = documentRef.createElement('div');
    stack.hidden = true;
    return stack;
}


function cardSummary(stack) {
    return stack.children.map((card) => ({
        batch: card.dataset.summaryBatch,
        status: card.dataset.summaryStatus,
        text: card.textContent,
    }));
}


test('operation panel sits between the current user request and the streaming answer', () => {
    const documentRef = new FakeDocument();
    const container = documentRef.createElement('div');
    const panel = element(documentRef, 'panel');
    // The controller appends a new panel after the rendered conversation.
    container.append(element(documentRef, 'stale'), panel);
    container.children[0].remove();

    const renderedMessages = [
        { messageId: 'old-user', element: element(documentRef, 'old-user') },
        { messageId: 'old-assistant', element: element(documentRef, 'old-assistant') },
        { messageId: 'current-user', element: element(documentRef, 'current-user') },
        { messageId: 'current-assistant', element: element(documentRef, 'current-assistant') },
    ];
    placeChatMessageElements({
        container,
        renderedMessages,
        operationPanel: panel,
        operationAnchorMessageId: 'current-assistant',
    });

    assert.deepEqual(labels(container), [
        'old-user', 'old-assistant', 'current-user', 'panel', 'current-assistant',
    ]);
});


test('operation panel keeps its anchor slot before the answer starts rendering', () => {
    const documentRef = new FakeDocument();
    const container = documentRef.createElement('div');
    const panel = element(documentRef, 'panel');
    container.append(panel);

    placeChatMessageElements({
        container,
        renderedMessages: [
            { messageId: 'current-user', element: element(documentRef, 'current-user') },
            { messageId: 'current-assistant', element: null },
        ],
        operationPanel: panel,
        operationAnchorMessageId: 'current-assistant',
    });
    assert.deepEqual(labels(container), ['current-user', 'panel']);

    // A later render with streamed content keeps the answer below the panel.
    for (const child of [...container.children]) if (child !== panel) child.remove();
    placeChatMessageElements({
        container,
        renderedMessages: [
            { messageId: 'current-user', element: element(documentRef, 'current-user') },
            { messageId: 'current-assistant', element: element(documentRef, 'answer-growing') },
        ],
        operationPanel: panel,
        operationAnchorMessageId: 'current-assistant',
    });
    assert.deepEqual(labels(container), ['current-user', 'panel', 'answer-growing']);
});


test('re-rendering never moves the operation panel so its buttons stay clickable', () => {
    const documentRef = new FakeDocument();
    const container = documentRef.createElement('div');
    const panel = element(documentRef, 'panel');
    container.append(panel);
    let panelMoves = 0;
    const originalAppend = container.append.bind(container);
    const originalInsertBefore = container.insertBefore.bind(container);
    container.append = (...nodes) => {
        if (nodes.includes(panel)) panelMoves += 1;
        originalAppend(...nodes);
    };
    container.insertBefore = (node, reference) => {
        if (node === panel) panelMoves += 1;
        return originalInsertBefore(node, reference);
    };

    for (let render = 0; render < 3; render += 1) {
        for (const child of [...container.children]) if (child !== panel) child.remove();
        placeChatMessageElements({
            container,
            renderedMessages: [
                { messageId: 'user', element: element(documentRef, 'user') },
                { messageId: 'answer', element: element(documentRef, 'answer') },
            ],
            operationPanel: panel,
            operationAnchorMessageId: 'answer',
        });
    }

    assert.equal(panelMoves, 0);
    assert.deepEqual(labels(container), ['user', 'panel', 'answer']);
});


test('message placement without an operation panel preserves conversation order', () => {
    const documentRef = new FakeDocument();
    const container = documentRef.createElement('div');
    placeChatMessageElements({
        container,
        renderedMessages: [
            { messageId: 'a', element: element(documentRef, 'a') },
            { messageId: 'b', element: null },
            { messageId: 'c', element: element(documentRef, 'c') },
        ],
        operationPanel: null,
        operationAnchorMessageId: '',
    });
    assert.deepEqual(labels(container), ['a', 'c']);
});


test('message placement fails loudly when the operation anchor is missing', () => {
    const documentRef = new FakeDocument();
    const container = documentRef.createElement('div');
    const panel = element(documentRef, 'panel');
    assert.throws(() => placeChatMessageElements({
        container,
        renderedMessages: [{ messageId: 'a', element: element(documentRef, 'a') }],
        operationPanel: panel,
        operationAnchorMessageId: 'a',
    }), /already be inside/);
    container.append(panel);
    assert.throws(() => placeChatMessageElements({
        container,
        renderedMessages: [{ messageId: 'a', element: element(documentRef, 'a') }],
        operationPanel: panel,
        operationAnchorMessageId: 'missing',
    }), /anchor/);
    assert.throws(() => placeChatMessageElements({
        container,
        renderedMessages: [],
        operationPanel: panel,
        operationAnchorMessageId: '',
    }), /anchor/);
    assert.throws(() => placeChatMessageElements({
        container,
        renderedMessages: [],
        operationPanel: null,
        operationAnchorMessageId: 'a',
    }), /anchor/);
});
