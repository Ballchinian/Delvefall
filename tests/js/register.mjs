//loaded with --import so the resolve hook is in place before any test runs.
//
//the browser modules also reach for a few things that only exist in a page:
//document, localStorage, and the two globals cards.js defines. none of them is
//touched at import time, so a module loads fine without them; they are stubbed
//here for the tests that call a function which does use one.
//
//deliberately minimal. this is not a dom implementation and nothing here should
//grow into one: the functions worth testing this way are the ones that take
//values and return values, and a test that needs a real dom is telling you it
//is testing the wrong thing.

import { register } from "node:module";

register("./resolve.mjs", import.meta.url);

//a real map with the storage api's shape, so read/write round trip properly and
//a test can inspect what actually landed
class MemoryStorage {
    constructor() {
        this.map = new Map();
    }
    getItem(k) {
        return this.map.has(k) ? this.map.get(k) : null;
    }
    setItem(k, v) {
        this.map.set(k, String(v));
    }
    removeItem(k) {
        this.map.delete(k);
    }
    clear() {
        this.map.clear();
    }
}

globalThis.MemoryStorage = MemoryStorage;
globalThis.localStorage = new MemoryStorage();

//cards.js is a classic script in the browser, so these are globals rather than
//imports. only the drawing paths call them, which the tests here do not
globalThis.manaFill = function () {};
globalThis.enhanceCardFrames = function () {};
