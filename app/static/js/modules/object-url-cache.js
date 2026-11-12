// The page's caches of pictures it has drawn keep only their most recent entries
// (docs/ready-to-build/unbounded-growth-audit.md, M8). A picture's object URL that leaves
// its cache is revoked once nothing can show it again: a picture on screen, in a tab out of
// sight or in a copy of either keeps its URL, which a revoked URL would break as soon as the
// picture is copied (a floating note, a duplicated tab) or opened (zoom, copy image).
import { ApplicationState } from './application-state.js';

// Pictures (object URLs) each cache keeps.
export const RECENT_PICTURES_CAPACITY = 200;
// Remembered picture and diagram sizes each cache keeps.
export const RECENT_SIZES_CAPACITY = 200;

const OBJECT_URL_PREFIX = 'blob:';
const IFRAME_TAG_NAME = 'IFRAME';

const urlState = ApplicationState.createFields('object-url-cache', {
    // Object URL -> WeakRefs of the elements a cache's service set it on. An element the
    // page still holds (on screen, or in an inactive tab's notes) keeps the URL alive.
    holders: new Map(),
    // Object URLs that left their cache while something could still show them.
    retired: new Set(),
});

function requireObjectUrl(objectUrl) {
    if (typeof objectUrl !== 'string' || !objectUrl.startsWith(OBJECT_URL_PREFIX)) {
        throw new Error(`Expected an object URL, received: ${String(objectUrl)}`);
    }
}

function requireMap(map) {
    if (!(map instanceof Map)) {
        throw new Error('Expected a Map');
    }
}

// Makes `key` the newest entry of `map`, set to `value`.
export function rememberNewest(map, key, value) {
    requireMap(map);
    if (map.has(key)) map.delete(key);
    map.set(key, value);
}

// Makes `key`, an entry of `map`, its newest and returns its value.
export function useNewest(map, key) {
    requireMap(map);
    if (!map.has(key)) {
        throw new Error(`No cache entry for ${String(key)}`);
    }
    const value = map.get(key);
    map.delete(key);
    map.set(key, value);
    return map.get(key);
}

// Removes the oldest entries `isEvictable(key, value)` allows until `map` holds at most
// `capacity`, and returns them oldest first as [key, value] pairs.
export function evictOldest(map, capacity, isEvictable) {
    requireMap(map);
    if (!Number.isInteger(capacity) || capacity < 1) {
        throw new Error(`Cache capacity must be a positive integer, received: ${capacity}`);
    }
    if (typeof isEvictable !== 'function') {
        throw new Error('evictOldest requires an isEvictable function');
    }
    const evicted = [];
    for (const key of Array.from(map.keys())) {
        if (map.size <= capacity) break;
        const value = map.get(key);
        if (!isEvictable(key, value)) continue;
        map.delete(key);
        evicted.push([key, value]);
    }
    return evicted;
}

const everyEntry = () => true;

// Remembers a measured size as the newest of `map`, forgetting the oldest beyond the cap.
export function rememberSize(map, key, size) {
    rememberNewest(map, key, size);
    evictOldest(map, RECENT_SIZES_CAPACITY, everyEntry);
}

function showsObjectUrl(element, objectUrl) {
    return element !== undefined && element.src === objectUrl;
}

function liveHolders(objectUrl) {
    if (!urlState.holders.has(objectUrl)) return [];
    return urlState.holders.get(objectUrl).filter((ref) => showsObjectUrl(ref.deref(), objectUrl));
}

// Records that `element` now shows `objectUrl` (its src was just set to it).
export function noteObjectUrlShown(element, objectUrl) {
    requireObjectUrl(objectUrl);
    if (!showsObjectUrl(element, objectUrl)) {
        throw new Error('noteObjectUrlShown expects an element whose src is the object URL');
    }
    const holders = liveHolders(objectUrl);
    if (holders.some((ref) => ref.deref() === element)) {
        if (holders.length !== urlState.holders.get(objectUrl).length) urlState.holders.set(objectUrl, holders);
        return;
    }
    urlState.holders.set(objectUrl, [...holders, new WeakRef(element)]);
}

// Every object URL an element of `rootDocument` uses as its src, including those in open
// shadow roots (a reference's preview card, a floating note) and same-origin frames (the
// file viewer): copies of a picture its service never saw.
function objectUrlsInPage(rootDocument) {
    const shown = new Set();
    const roots = [rootDocument];
    while (roots.length > 0) {
        const root = roots.pop();
        for (const element of root.querySelectorAll('*')) {
            if (typeof element.src === 'string' && element.src.startsWith(OBJECT_URL_PREFIX)) shown.add(element.src);
            if (element.shadowRoot instanceof Object) roots.push(element.shadowRoot);
            if (element.tagName === IFRAME_TAG_NAME && element.contentDocument instanceof Object) roots.push(element.contentDocument);
        }
    }
    return shown;
}

function revokeNow(objectUrl) {
    URL.revokeObjectURL(objectUrl);
    if (urlState.holders.has(objectUrl)) urlState.holders.delete(objectUrl);
}

// Lets go of object URLs dropped from their caches: each is revoked once no element the page
// holds, and no element in the document, shows it; the rest are looked at again next time.
export function releaseObjectUrls(objectUrls) {
    for (const objectUrl of objectUrls) {
        requireObjectUrl(objectUrl);
        urlState.retired.add(objectUrl);
    }
    const unheld = Array.from(urlState.retired).filter((objectUrl) => liveHolders(objectUrl).length === 0);
    if (unheld.length === 0) return;
    const shown = objectUrlsInPage(document);
    for (const objectUrl of unheld) {
        if (shown.has(objectUrl)) continue;
        urlState.retired.delete(objectUrl);
        revokeNow(objectUrl);
    }
}

// Revokes an object URL its cache has replaced (a diagram's older revision) at once.
export function revokeObjectUrl(objectUrl) {
    requireObjectUrl(objectUrl);
    revokeNow(objectUrl);
}
