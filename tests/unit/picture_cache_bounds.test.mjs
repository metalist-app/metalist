// The picture caches keep their 200 most recent pictures and revoke a dropped picture's
// object URL only once nothing on the page can show it (unbounded-growth-audit.md, M8): not
// one on screen, in an inactive tab's notes, or copied into a shadow root or a frame.
import assert from 'node:assert/strict';
import test from 'node:test';
import v8 from 'node:v8';
import vm from 'node:vm';

import { initializeSessionIdentity } from '../../app/static/js/modules/session-auth.js';

const CAPACITY = 200;

// A small page for these tests: elements with tags, classes and data attributes, compound
// selectors, open shadow roots, frames, and object URLs whose revocation is recorded. Also a
// forced garbage collection, so an element the page has let go of can be told from one it
// still holds.

v8.setFlagsFromString('--expose-gc');
const runGarbageCollection = vm.runInNewContext('gc');

async function collectGarbage() {
    // A WeakRef's target stays alive until the current job ends.
    await new Promise((resolve) => { setImmediate(resolve); });
    runGarbageCollection();
    await new Promise((resolve) => { setImmediate(resolve); });
    runGarbageCollection();
}

function camelCase(name) {
    return name.replace(/-([a-z])/g, (match, letter) => letter.toUpperCase());
}

// `tag.class[data-x][data-y="v"]` and `*`, no combinators.
function parseCompound(selector) {
    const trimmed = selector.trim();
    if (trimmed === '*') return { any: true };
    const match = /^([a-z]+)?((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/i.exec(trimmed);
    if (!match) throw new Error(`Unsupported selector in the fake page: ${selector}`);
    const classes = [];
    const attributes = [];
    for (const [part] of match[2].matchAll(/\.[\w-]+|\[[^\]]+\]/g)) {
        if (part.startsWith('.')) {
            classes.push(part.slice(1));
            continue;
        }
        const attribute = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(part);
        if (!attribute[1].startsWith('data-')) throw new Error(`Unsupported attribute: ${part}`);
        attributes.push({ name: camelCase(attribute[1].slice('data-'.length)), value: attribute[2] });
    }
    return { any: false, tag: match[1] ? match[1].toUpperCase() : null, classes, attributes };
}

function matches(element, selector) {
    return selector.split(',').some((part) => {
        const compound = parseCompound(part);
        if (compound.any) return true;
        if (compound.tag !== null && element.tagName !== compound.tag) return false;
        if (!compound.classes.every((name) => element.classes.has(name))) return false;
        return compound.attributes.every(({ name, value }) => (
            typeof element.dataset[name] === 'string'
            && (value === undefined || element.dataset[name] === value)
        ));
    });
}

class FakeNode {
    constructor() {
        this.children = [];
    }

    appendChild(child) {
        if (child.parentNode !== null) child.remove();
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    querySelectorAll(selector) {
        const found = [];
        for (const child of this.children) {
            if (matches(child, selector)) found.push(child);
            found.push(...child.querySelectorAll(selector));
        }
        return found;
    }

    querySelector(selector) {
        const found = this.querySelectorAll(selector);
        return found.length > 0 ? found[0] : null;
    }
}

function createStorage(initialEntries) {
    const entries = new Map(initialEntries);
    return {
        getItem(key) {
            return entries.has(key) ? entries.get(key) : null;
        },
        setItem(key, value) {
            entries.set(key, String(value));
        },
        removeItem(key) {
            entries.delete(key);
        },
    };
}

// Each page's object URLs differ from an earlier page's: the caches outlive one test.
let pagesInstalled = 0;

function installFakePage(t) {
    pagesInstalled += 1;
    const pageNumber = pagesInstalled;
    const saved = ['window', 'document', 'URL', 'HTMLElement', 'HTMLImageElement', 'fetch', 'sessionStorage', 'localStorage']
        .map((name) => [name, globalThis[name]]);
    const created = [];
    const revoked = new Set();

    class FakeDocument extends FakeNode {
        constructor() {
            super();
            this.nodeType = 9;
        }
    }
    const page = new FakeDocument();

    class FakeElement extends FakeNode {
        constructor(tagName, classNames, data) {
            super();
            this.tagName = tagName.toUpperCase();
            this.classes = new Set(classNames);
            this.dataset = { ...data };
            this.parentNode = null;
            this.ownerDocument = page;
            this.nodeType = 1;
            this.style = {};
            this.hidden = false;
            this.textContent = '';
            this.shadowRoot = null;
            this.clientWidth = 600;
        }

        remove() {
            const siblings = this.parentNode.children;
            siblings.splice(siblings.indexOf(this), 1);
            this.parentNode = null;
        }

        closest(selector) {
            for (let node = this; node instanceof FakeElement; node = node.parentNode) {
                if (matches(node, selector)) return node;
            }
            return null;
        }

        attachShadow() {
            this.shadowRoot = new FakeNode();
            return this.shadowRoot;
        }

        getBoundingClientRect() {
            return { height: 120 };
        }
    }

    class FakeImageElement extends FakeElement {
        constructor(classNames, data) {
            super('img', classNames, data);
            this.src = '';
            this.naturalWidth = 300;
            this.naturalHeight = 200;
        }

        // Pictures never report loading here, so no size is recorded.
        addEventListener() {}

        removeAttribute(name) {
            if (name !== 'src') throw new Error(`Unsupported attribute: ${name}`);
            this.src = '';
        }

        decode() {
            return Promise.resolve();
        }
    }

    class FakeFrameElement extends FakeElement {
        constructor() {
            super('iframe', [], {});
            this.contentDocument = new FakeDocument();
        }
    }

    globalThis.document = page;
    globalThis.sessionStorage = createStorage([['metalist_tab_id', 'tab-123']]);
    globalThis.localStorage = createStorage([]);
    globalThis.window = { addEventListener() {} };
    globalThis.HTMLElement = FakeElement;
    globalThis.HTMLImageElement = FakeImageElement;
    globalThis.URL = {
        createObjectURL() {
            const objectUrl = `blob:page-${pageNumber}-picture-${created.length + 1}`;
            created.push(objectUrl);
            return objectUrl;
        },
        // An earlier test's pictures, let go of meanwhile, are revoked here too; only this
        // page's own are recorded.
        revokeObjectURL(objectUrl) {
            if (revoked.has(objectUrl)) throw new Error(`Revoked twice: ${objectUrl}`);
            if (created.includes(objectUrl)) revoked.add(objectUrl);
        },
    };
    t.after(() => {
        for (const [name, value] of saved) globalThis[name] = value;
    });

    return { page, created, revoked, FakeElement, FakeImageElement, FakeFrameElement };
}

function buildTarget(FakeElement, FakeImageElement, fileId) {
    const target = new FakeElement('div', ['note-file-image-embed'], { fileRefId: fileId, previewState: 'idle' });
    const frame = new FakeElement('div', ['note-file-image-preview-frame'], {});
    const image = new FakeImageElement(['note-file-image-preview'], {});
    image.hidden = true;
    frame.appendChild(image);
    frame.appendChild(new FakeElement('div', ['note-file-image-preview-placeholder'], {}));
    target.appendChild(frame);
    return { target, image };
}

function removeAll(notes) {
    for (const note of notes.splice(0)) note.remove();
}

test('viewing 250 pictures keeps 200, revokes the dropped ones nothing shows, and fetches a dropped one again', async (t) => {
    const fake = installFakePage(t);
    const { FilesAPI } = await import('../../app/static/js/modules/api-client.js');
    const { hydrateImageFilePreviews } = await import('../../app/static/js/modules/mode-manager/services/file-image-preview-service.js');
    const originalDownloadFile = FilesAPI.downloadFile;
    t.after(() => { FilesAPI.downloadFile = originalDownloadFile; });
    const downloads = [];
    FilesAPI.downloadFile = async (fileId) => {
        downloads.push(fileId);
        return { blob: new Blob([fileId], { type: 'image/png' }), filename: `${fileId}.png` };
    };

    const shownNotes = [];
    const inactiveTabNotes = [];
    const urlOf = new Map();
    // Pictures 1-10 stay on screen; 11-20 move to an inactive tab's notes (held, out of the
    // document); every other note is drawn, then thrown away.
    async function view(number) {
        const fileId = `file-${number}`;
        const note = new fake.FakeElement('div', ['note'], {});
        const { target, image } = buildTarget(fake.FakeElement, fake.FakeImageElement, fileId);
        note.appendChild(target);
        fake.page.appendChild(note);
        await hydrateImageFilePreviews(note);
        assert.equal(target.dataset.previewState, 'loaded');
        urlOf.set(number, image.src);
        if (number <= 10) {
            shownNotes.push(note);
            return;
        }
        note.remove();
        if (number <= 20) inactiveTabNotes.push(note);
    }
    for (let number = 1; number <= 250; number += 1) await view(number);
    // Copies its service never saw: picture 25's in a reference card's shadow root, picture
    // 26's in the file viewer's frame.
    const card = fake.page.appendChild(new fake.FakeElement('div', ['reference-preview-card'], {}));
    card.attachShadow().appendChild(new fake.FakeImageElement([], {})).src = urlOf.get(25);
    const viewer = fake.page.appendChild(new fake.FakeFrameElement());
    viewer.contentDocument.appendChild(new fake.FakeImageElement([], {})).src = urlOf.get(26);

    await collectGarbage();
    await view(251);

    assert.equal(downloads.length, 251);
    const live = fake.created.filter((objectUrl) => !fake.revoked.has(objectUrl));
    const expectedRevoked = [];
    for (let number = 21; number <= 51; number += 1) {
        if (number !== 25 && number !== 26) expectedRevoked.push(urlOf.get(number));
    }
    assert.deepEqual([...fake.revoked].sort(), expectedRevoked.sort());
    // The cache's 200 (52-251) and the 22 dropped pictures something still shows.
    assert.equal(live.length, CAPACITY + 22);

    // A cached picture comes from the cache; a dropped one is fetched again, as a new URL.
    await view(251);
    assert.equal(downloads.length, 251);
    const revokedUrl = urlOf.get(30);
    await view(30);
    assert.equal(downloads.length, 252);
    assert.equal(downloads.at(-1), 'file-30');
    assert.notEqual(urlOf.get(30), revokedUrl);
    assert.equal(fake.revoked.has(urlOf.get(30)), false);

    // Once the shown pictures leave the page, the next drop revokes them too.
    // In a function of its own: a suspended async frame may still hold its last loop value.
    removeAll(shownNotes);
    await collectGarbage();
    await view(252);
    for (let number = 1; number <= 10; number += 1) {
        assert.equal(fake.revoked.has(urlOf.get(number)), true, `picture ${number}`);
    }
    for (let number = 11; number <= 20; number += 1) {
        assert.equal(fake.revoked.has(urlOf.get(number)), false, `picture ${number} in an inactive tab`);
    }
    assert.equal(inactiveTabNotes.length, 10);
});

function proxyPathOf(number) {
    return `/api2/remote-images/${String(number).padStart(32, 'A')}`;
}

test('viewing 250 remote pictures keeps 200, revokes the dropped ones nothing shows, and fetches a dropped one again', async (t) => {
    const fake = installFakePage(t);
    initializeSessionIdentity();
    const fetched = [];
    globalThis.fetch = async (url) => {
        fetched.push(url);
        return { ok: true, async blob() { return new Blob([url], { type: 'image/png' }); } };
    };
    const { hydrateRemoteImageProxies } = await import('../../app/static/js/modules/mode-manager/services/remote-image-proxy-service.js');

    const shownNotes = [];
    const urlOf = new Map();
    // Pictures 1-10 stay on screen; every other note is drawn, then thrown away.
    async function view(number) {
        const note = fake.page.appendChild(new fake.FakeElement('div', ['note'], {}));
        const image = note.appendChild(new fake.FakeImageElement([], { remoteImageProxySrc: proxyPathOf(number) }));
        await hydrateRemoteImageProxies(note);
        assert.equal(image.dataset.remoteImageProxyState, 'loaded');
        urlOf.set(number, image.src);
        if (number <= 10) {
            shownNotes.push(note);
            return;
        }
        note.remove();
    }
    for (let number = 1; number <= 250; number += 1) await view(number);
    await collectGarbage();
    await view(251);

    assert.equal(fetched.length, 251);
    const expectedRevoked = [];
    for (let number = 11; number <= 51; number += 1) expectedRevoked.push(urlOf.get(number));
    assert.deepEqual([...fake.revoked].sort(), expectedRevoked.sort());
    assert.equal(fake.created.length - fake.revoked.size, CAPACITY + 10);

    const revokedUrl = urlOf.get(30);
    await view(30);
    assert.equal(fetched.length, 252);
    assert.equal(fetched.at(-1), proxyPathOf(30));
    assert.notEqual(urlOf.get(30), revokedUrl);
    assert.equal(fake.revoked.has(urlOf.get(30)), false);
    assert.equal(shownNotes.length, 10);
});

const VARIANTS = ['light', 'dark'];

function buildEmbed(fake, fileId) {
    const embed = new fake.FakeElement('div', ['note-file-excalidraw-embed'], {
        fileRefId: fileId, fileRevision: '1', previewState: 'idle',
    });
    embed.appendChild(new fake.FakeElement('div', ['note-file-excalidraw-frame'], {}));
    embed.appendChild(new fake.FakeElement('div', ['note-file-excalidraw-placeholder'], {}));
    for (const variant of VARIANTS) {
        embed.appendChild(new fake.FakeImageElement(['note-file-excalidraw-preview'], { previewVariant: variant })).hidden = true;
    }
    return embed;
}

function previewUrls(embed) {
    return embed.querySelectorAll('.note-file-excalidraw-preview').map((image) => image.src);
}

async function installDiagrams(t) {
    const fake = installFakePage(t);
    const { FilesAPI } = await import('../../app/static/js/modules/api-client.js');
    const service = await import('../../app/static/js/modules/excalidraw/excalidraw-preview-service.js');
    const original = FilesAPI.downloadFilePreview;
    t.after(() => { FilesAPI.downloadFilePreview = original; });
    const downloads = [];
    const slow = new Map();
    FilesAPI.downloadFilePreview = (fileId, variant) => {
        downloads.push(`${fileId}:${variant}`);
        if (slow.has(`${fileId}:${variant}`)) return slow.get(`${fileId}:${variant}`);
        return Promise.resolve({ status: 'ready', blob: new Blob([fileId], { type: 'image/svg+xml' }) });
    };
    return { fake, downloads, slow, hydrate: service.hydrateExcalidrawPreviews };
}

test('viewing 250 diagrams keeps 200 previews, revokes the dropped ones nothing shows, and fetches a dropped one again', async (t) => {
    const { fake, downloads, hydrate } = await installDiagrams(t);
    const shownNotes = [];
    const urlsOf = new Map();
    // Diagrams 1-5 stay on screen; every other note is drawn, then thrown away.
    async function view(number) {
        const note = fake.page.appendChild(new fake.FakeElement('div', ['note'], {}));
        const embed = note.appendChild(buildEmbed(fake, `diagram-${number}`));
        await hydrate(note);
        assert.equal(embed.dataset.previewState, 'loaded');
        urlsOf.set(number, previewUrls(embed));
        if (number <= 5) {
            shownNotes.push(note);
            return;
        }
        note.remove();
    }
    for (let number = 1; number <= 250; number += 1) await view(number);
    await collectGarbage();
    await view(251);

    assert.equal(downloads.length, 251 * VARIANTS.length);
    // Two previews a diagram: the cache holds diagrams 152-251.
    const expectedRevoked = [];
    for (let number = 6; number <= 151; number += 1) expectedRevoked.push(...urlsOf.get(number));
    assert.deepEqual([...fake.revoked].sort(), expectedRevoked.sort());
    assert.equal(fake.created.length - fake.revoked.size, CAPACITY + 5 * VARIANTS.length);

    await view(251);
    assert.equal(downloads.length, 251 * VARIANTS.length);
    const revokedUrls = urlsOf.get(30);
    await view(30);
    assert.deepEqual(downloads.slice(-VARIANTS.length), ['diagram-30:light', 'diagram-30:dark']);
    for (const objectUrl of urlsOf.get(30)) {
        assert.equal(revokedUrls.includes(objectUrl), false);
        assert.equal(fake.revoked.has(objectUrl), false);
    }
    assert.equal(shownNotes.length, 5);
});

test('a diagram whose other preview still loads keeps its loaded one, however many diagrams load meanwhile', async (t) => {
    const { fake, slow, hydrate } = await installDiagrams(t);
    let finishDark;
    slow.set('slow-diagram:dark', new Promise((resolve) => { finishDark = resolve; }));
    const note = fake.page.appendChild(new fake.FakeElement('div', ['note'], {}));
    const embed = note.appendChild(buildEmbed(fake, 'slow-diagram'));
    const slowHydration = hydrate(note);

    for (let number = 1; number <= 250; number += 1) {
        const other = fake.page.appendChild(new fake.FakeElement('div', ['note'], {}));
        other.appendChild(buildEmbed(fake, `meanwhile-${number}`));
        await hydrate(other);
        other.remove();
    }
    finishDark({ status: 'ready', blob: new Blob(['slow'], { type: 'image/svg+xml' }) });
    await slowHydration;

    assert.equal(embed.dataset.previewState, 'loaded');
    for (const objectUrl of previewUrls(embed)) {
        assert.equal(objectUrl.startsWith('blob:'), true);
        assert.equal(fake.revoked.has(objectUrl), false, objectUrl);
    }
});
