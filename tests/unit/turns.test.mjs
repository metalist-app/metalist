import assert from 'node:assert/strict';
import test from 'node:test';

import { isTurnTaken, takeTurn, turnRunning } from '../../app/static/js/modules/mode-manager/services/turns.js';

// One thing at a time changes the page's notes and tabs (docs/ui/command-gate.md, "Turns"):
// commands, background work (the infinite scroll, a change made elsewhere) and what the server
// sends each take a turn, in the order they asked.

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
}

test('a turn asked for while another runs starts when that one has finished', async () => {
    const events = [];
    const first = deferred();
    const one = takeTurn('one', async () => {
        events.push('one starts');
        await first.promise;
        events.push('one ends');
    });
    const two = takeTurn('two', async () => { events.push('two starts'); });
    await pause(0);
    assert.deepEqual(events, ['one starts']);
    assert.equal(turnRunning(), 'one');
    first.resolve();
    await Promise.all([one, two]);
    assert.deepEqual(events, ['one starts', 'one ends', 'two starts']);
});

test('a turn is taken from the moment it is asked for until the last one waiting has finished', async () => {
    assert.equal(isTurnTaken(), false);
    const first = deferred();
    const one = takeTurn('one', () => first.promise);
    assert.equal(isTurnTaken(), true, 'taken at once, before the work starts');
    const two = takeTurn('two', async () => {});
    first.resolve();
    await one;
    assert.equal(isTurnTaken(), true, 'the second is still to run');
    await two;
    assert.equal(isTurnTaken(), false);
    assert.equal(turnRunning(), null);
});

test('a turn gives its caller what its work returned', async () => {
    assert.equal(await takeTurn('answer', async () => 'done'), 'done');
});

test('a turn that fails tells its caller, and the next one still runs', async () => {
    const failing = takeTurn('failing', async () => { throw new Error('the work failed'); });
    const next = takeTurn('next', async () => 'ran');
    await assert.rejects(failing, /the work failed/);
    assert.equal(await next, 'ran');
    assert.equal(isTurnTaken(), false);
});

test('a turn needs a name and its work', () => {
    assert.throws(() => takeTurn('', async () => {}), /name/);
    assert.throws(() => takeTurn('nameless', null), /work/);
});

// A seeded generator, so a failure names the run that failed.
function generator(seed) {
    let state = seed;
    return () => {
        state = (state * 1103515245 + 12345) % 2147483648;
        return state / 2147483648;
    };
}

const RUNS = 200;
const MOST_TURNS = 12;
const LONGEST_MS = 3;

test('in any order of asking and any lengths of work, turns run one at a time in the order asked', async () => {
    for (let seed = 1; seed <= RUNS; seed += 1) {
        const random = generator(seed);
        const count = 2 + Math.floor(random() * MOST_TURNS);
        const started = [];
        let running = 0;
        const turns = [];
        for (let index = 0; index < count; index += 1) {
            // Some are asked for at once, some while earlier ones run.
            if (random() < 0.5) await pause(Math.floor(random() * LONGEST_MS));
            const workMs = Math.floor(random() * LONGEST_MS);
            const fails = random() < 0.2;
            // Settled as it is made: a turn that fails is looked at below, not left unwatched.
            turns.push(Promise.allSettled([takeTurn(`turn ${index}`, async () => {
                running += 1;
                assert.equal(running, 1, `seed ${seed}: turn ${index} started while another ran`);
                started.push(index);
                await pause(workMs);
                running -= 1;
                if (fails) throw new Error('expected');
            })]));
        }
        const outcomes = (await Promise.all(turns)).map(([outcome]) => outcome);
        assert.deepEqual(started, [...Array(count).keys()], `seed ${seed}: the order asked`);
        const unexpected = outcomes.filter((outcome) => outcome.status === 'rejected' && outcome.reason.message !== 'expected');
        assert.deepEqual(unexpected, [], `seed ${seed}: only the failures the turns were told to have`);
        assert.equal(isTurnTaken(), false, `seed ${seed}: nothing is left waiting`);
    }
});

test('with no turn taken the work starts at once, before the caller goes on', async () => {
    const events = [];
    const turn = takeTurn('at once', async () => { events.push('started'); });
    events.push('caller goes on');
    await turn;
    assert.deepEqual(events, ['started', 'caller goes on']);
    await assert.rejects(takeTurn('fails as it starts', () => { throw new Error('at the start'); }), /at the start/);
    assert.equal(isTurnTaken(), false);
});
