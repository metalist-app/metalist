import assert from 'node:assert/strict';
import test from 'node:test';

import {HTTP_PORT_VARIABLE, HTTPS_PORT_VARIABLE, pickPortPair, portsForRun} from '../../scripts/free-ports.mjs';

// Runs side by side once shared ports, one run's HTTP port being the other's HTTPS port
// (GitHub, 2026-11-21). The runner picks every run's ports and never hands one out twice.
test('ports picked side by side for many runs are never handed out twice', async () => {
    const handedOut = new Set();
    const runs = 40;
    const pairs = await Promise.all(Array.from({length: runs}, () => pickPortPair(handedOut)));
    const ports = pairs.flatMap(pair => [pair.http, pair.https]);
    assert.equal(new Set(ports).size, ports.length);
    assert.equal(handedOut.size, ports.length);
});

test('a run uses the ports the runner gave it', async () => {
    assert.deepEqual(await portsForRun({[HTTP_PORT_VARIABLE]: '40001', [HTTPS_PORT_VARIABLE]: '40002'}), {http: 40001, https: 40002});
});

test('a run started on its own picks two different ports', async () => {
    const ports = await portsForRun({});
    assert.notEqual(ports.http, ports.https);
});

test('the runner gives both ports or neither, as numbers', async () => {
    await assert.rejects(portsForRun({[HTTP_PORT_VARIABLE]: '40001'}), /together/);
    await assert.rejects(portsForRun({[HTTP_PORT_VARIABLE]: '40001', [HTTPS_PORT_VARIABLE]: 'x'}), /must be a port number/);
    await assert.rejects(portsForRun({[HTTP_PORT_VARIABLE]: '40001', [HTTPS_PORT_VARIABLE]: '40001'}), /both 40001/);
});
