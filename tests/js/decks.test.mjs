//the saved deck shelf, which is the only thing on this site that holds work
//somebody would be upset to lose. it lives entirely in one browser and there is
//no server copy, so every rule here is the whole rule.
//
//localStorage is the memory stub from register.mjs, swapped for a fresh one per
//test so no test can be affected by what another one left behind.

import test, { beforeEach } from "node:test";
import assert from "node:assert";

import { KEY, KEEP, read, write, create, find, patch, drop, clear, full } from "decks";

beforeEach(() => {
    globalThis.localStorage = new globalThis.MemoryStorage();
});

const raw = () => JSON.parse(globalThis.localStorage.getItem(KEY) || "[]");
const fill = (n) => {
    for (let i = 0; i < n; i++) create({text: "1 Island", label: "deck " + i});
};


test("a saved deck comes back", () => {
    const id = create({text: "1 Sol Ring", label: "ramp"});
    assert.ok(id);
    assert.equal(read().length, 1);
    assert.equal(find(id).label, "ramp");
    assert.equal(find(id).text, "1 Sol Ring");
});

test("every deck gets its own id, even saved in the same millisecond", () => {
    //the clock is frozen, so the time half of an id cannot tell them apart and
    //only the random half can. two tabs each pasting a deck is the real case
    const now = Date.now;
    Date.now = () => 1750000000000;
    try {
        const ids = new Set();
        for (let i = 0; i < KEEP; i++) ids.add(create({text: "1 Island"}));
        assert.ok(!ids.has(""), "the shelf should not be full inside the cap");
        assert.equal(ids.size, KEEP);
    } finally {
        Date.now = now;
    }
});

test("two imports of the same list are two decks", () => {
    //deliberate: the person is about to take them in two directions
    create({text: "1 Island"});
    create({text: "1 Island"});
    assert.equal(read().length, 2);
});


test("a full shelf REFUSES rather than dropping the oldest", () => {
    fill(KEEP);
    const oldest = read()[read().length - 1].id;
    assert.ok(full());
    assert.equal(create({text: "1 Mountain", label: "new"}), "",
                 "create must refuse once the shelf is full");
    assert.equal(read().length, KEEP);
    assert.ok(find(oldest), "the oldest deck must still be there");
});

test("a write never silently drops a deck", () => {
    //the rule lived in two places and they disagreed: create refused, write
    //trimmed. nothing reaches write with more than KEEP today, and if anything
    //ever does, the entries it would cut are the ones the shelf exists to keep
    const over = [];
    for (let i = 0; i < KEEP + 4; i++) over.push({id: "d" + i, text: "1 Island"});
    write(over);
    assert.equal(raw().length, KEEP + 4);
    assert.equal(read().length, KEEP + 4);
});

test("room is reported off the real count", () => {
    assert.ok(!full());
    fill(KEEP - 1);
    assert.ok(!full());
    fill(1);
    assert.ok(full());
});


test("a patch changes only the fields it names", () => {
    const id = create({text: "1 Sol Ring", label: "ramp", commander: "Jhoira"});
    patch(id, {label: "budget ramp"});
    const d = find(id);
    assert.equal(d.label, "budget ramp");
    assert.equal(d.text, "1 Sol Ring", "the list must not move");
    assert.equal(d.commander, "Jhoira", "an unnamed field must not move");
});

test("a patch reads the shelf again rather than trusting a stale copy", () => {
    //a swap session holds its deck for twenty minutes. a rename in another tab
    //in the meantime must survive the session's next write
    const id = create({text: "1 Sol Ring", label: "before"});
    const stale = read();
    patch(id, {label: "renamed in another tab"});
    //the session writes something it decided long ago, from its own old copy
    stale.find((d) => d.id === id).swaps = [{out: {name: "Fog"}, "in": {name: "Opt"}}];
    patch(id, {swaps: stale.find((d) => d.id === id).swaps});
    const d = find(id);
    assert.equal(d.label, "renamed in another tab", "the rename must survive");
    assert.equal(d.swaps.length, 1, "and the swap must land");
});

test("patching a deck that has been deleted writes nothing back", () => {
    const id = create({text: "1 Sol Ring"});
    drop(id);
    assert.equal(patch(id, {label: "back from the dead"}), false);
    assert.equal(read().length, 0, "a patch must never resurrect a deck");
});

test("a drop takes the named deck and only that one", () => {
    const a = create({text: "1 Island", label: "a"});
    const b = create({text: "1 Island", label: "b"});
    drop(a);
    assert.equal(read().length, 1);
    assert.equal(find(b).label, "b");
    assert.equal(find(a), null);
});

test("clear empties the shelf", () => {
    fill(3);
    clear();
    assert.equal(read().length, 0);
});


test("a shelf written before ids existed gets them once and keeps them", () => {
    globalThis.localStorage.setItem(KEY, JSON.stringify([{text: "1 Island", label: "old"}]));
    const first = read();
    assert.ok(first[0].id, "the migration must stamp an id");
    const again = read();
    assert.equal(again[0].id, first[0].id, "an id that changes per read is not an identity");
    assert.equal(raw()[0].id, first[0].id, "and it has to be written back");
});

test("junk in storage reads as an empty shelf rather than throwing", () => {
    for (const junk of ["not json at all", "null", '{"not":"an array"}', '"a string"']) {
        globalThis.localStorage.setItem(KEY, junk);
        assert.deepEqual(read(), [], junk);
    }
});

test("storage being switched off costs the shelf and nothing else", () => {
    //private browsing, a full quota. every path has to survive it
    globalThis.localStorage = {
        getItem() { throw new Error("denied"); },
        setItem() { throw new Error("denied"); },
        removeItem() { throw new Error("denied"); },
    };
    assert.deepEqual(read(), []);
    assert.doesNotThrow(() => write([{id: "d1"}]));
    assert.doesNotThrow(() => clear());
    assert.doesNotThrow(() => drop("d1"));
    assert.equal(find("d1"), null);
});
