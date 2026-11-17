import assert from 'node:assert/strict';
import test from 'node:test';
import { restoredPoint } from '../../app/static/js/modules/mode-manager/services/viewport-hold-service.js';

const TEXT_NODE = 3;
const ELEMENT_NODE = 1;

function textNode(data) {
    return { nodeType: TEXT_NODE, data, isConnected: true };
}

// A note's content holding the given text nodes, with the page globals its walker reads.
function contentOf(textNodes) {
    const content = { nodeType: ELEMENT_NODE, childNodes: textNodes, contains: node => textNodes.includes(node) };
    globalThis.Node = { TEXT_NODE, ELEMENT_NODE };
    globalThis.NodeFilter = { SHOW_TEXT: 4, SHOW_ELEMENT: 1, FILTER_ACCEPT: 1, FILTER_SKIP: 3 };
    globalThis.document = {
        createTreeWalker: () => {
            let next = 0;
            return {
                nextNode: () => {
                    const node = next < textNodes.length ? textNodes[next] : null;
                    next += 1;
                    return node;
                },
            };
        },
    };
    return content;
}

test('a kept node whose offset still fits is restored by node', () => {
    const kept = textNode('hello');
    assert.deepEqual(restoredPoint(contentOf([kept]), kept, 5, 5), { node: kept, offset: 5 });
});

test('a kept text node the redraw shortened is restored by content position', () => {
    // The redraw kept the node and gave it shorter text: the old offset is past its end.
    const kept = textNode('he');
    const rest = textNode('llo');
    assert.deepEqual(restoredPoint(contentOf([kept, rest]), kept, 5, 5), { node: rest, offset: 3 });
});

test('a kept element that lost children is restored by content position', () => {
    const only = textNode('hi');
    const content = contentOf([only]);
    const kept = { nodeType: ELEMENT_NODE, childNodes: [only], isConnected: true };
    content.contains = () => true;
    assert.deepEqual(restoredPoint(content, kept, 3, 2), { node: only, offset: 2 });
});
