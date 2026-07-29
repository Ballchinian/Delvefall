//the decklist arithmetic behind a swap session.
//
//rebuild is the one that earns this file. it takes a string and returns a
//string, it is the only thing standing between a swap and the list somebody
//copies back out, and it was silently corrupting that list for months: matching
//the outgoing card as a SUBSTRING of any line meant a deck holding both Fog and
//Fog Bank had the wrong one rewritten. it produced card names that do not
//exist, in the export, and nothing anywhere would have caught it.

import test from "node:test";
import assert from "node:assert";

import { rebuild, addedList } from "changes";

const swap = (out, into) => ({out: {name: out}, "in": {name: into}});

//how moxfield and archidekt export by default, and the ordering that broke it:
//the longer name sits above the shorter one
const GROUPED = [
    "Creatures (2)",
    "1 Fog Bank",
    "1 Wall of Omens",
    "Instants (2)",
    "1 Fog",
    "1 Opt",
].join("\n");


test("a swap rewrites the line that IS the card", () => {
    const out = rebuild(GROUPED, [swap("Fog", "Moment's Peace")]);
    assert.match(out, /^1 Moment's Peace$/m);
    //the bug: Fog Bank rewritten and the real Fog left behind
    assert.match(out, /^1 Fog Bank$/m, "Fog Bank must not be touched");
    assert.doesNotMatch(out, /Moment's Peace Bank/);
    assert.doesNotMatch(out, /^1 Fog$/m, "the real Fog must be gone");
});

test("a name that is a prefix of a longer one does not bleed into it", () => {
    const deck = ["1 Optimus Prime, Hero", "1 Opt"].join("\n");
    const out = rebuild(deck, [swap("Opt", "Brainstorm")]);
    assert.match(out, /^1 Optimus Prime, Hero$/m);
    assert.doesNotMatch(out, /Brainstormimus/);
    assert.match(out, /^1 Brainstorm$/m);
});

test("swapping the longer name still finds its own line", () => {
    const out = rebuild(GROUPED, [swap("Fog Bank", "Wall of Blossoms")]);
    assert.match(out, /^1 Wall of Blossoms$/m);
    assert.match(out, /^1 Fog$/m, "the short one is untouched");
});

test("counts and exporter trailers still match", () => {
    for (const line of ["4 Fog", "4x Fog", "1 Fog (M19) 123", "1 Fog *F*",
                        "1 Fog [Ramp]", "1 Fog #!Ramp", "SB: 2 Fog"]) {
        const out = rebuild(line, [swap("Fog", "Moment's Peace")]);
        assert.match(out, /Moment's Peace/, line);
        assert.doesNotMatch(out, /\bFog\b/, line);
    }
});

test("the count and the rest of the line survive the substitution", () => {
    //the whole reason it substitutes rather than rebuilding: somebody's 30
    //basics are one line with a count, not thirty lines
    assert.equal(rebuild("30 Fog", [swap("Fog", "Moment's Peace")]), "30 Moment's Peace");
    assert.equal(rebuild("1 Fog (M19) 123 *F*", [swap("Fog", "Opt")]), "1 Opt (M19) 123 *F*");
});

test("several swaps in one session all land on their own lines", () => {
    const out = rebuild(GROUPED, [swap("Fog", "Moment's Peace"),
                                  swap("Fog Bank", "Wall of Blossoms"),
                                  swap("Opt", "Ponder")]);
    assert.match(out, /^1 Moment's Peace$/m);
    assert.match(out, /^1 Wall of Blossoms$/m);
    assert.match(out, /^1 Ponder$/m);
    assert.doesNotMatch(out, /\bFog\b/);
    assert.doesNotMatch(out, /^1 Opt$/m);
});

test("headings and blank lines are left exactly as they were", () => {
    const deck = "Creatures (1)\n\n1 Fog\n\n# a note";
    const out = rebuild(deck, [swap("Fog", "Opt")]);
    assert.equal(out, "Creatures (1)\n\n1 Opt\n\n# a note");
});

test("a card no line holds says so instead of being dropped", () => {
    const out = rebuild("1 Island", [swap("Black Lotus", "Sol Ring")]);
    assert.match(out, /^1 Island$/m);
    assert.match(out, /# swap by hand: Black Lotus -> Sol Ring/);
});

test("no swaps and no text are answered rather than thrown at", () => {
    assert.equal(rebuild("1 Fog", []), "1 Fog");
    assert.equal(rebuild("", [swap("Fog", "Opt")]), "\n# swap by hand: Fog -> Opt");
    assert.equal(rebuild(null, []), "");
    assert.equal(rebuild("1 Fog", null), "1 Fog");
});

test("a name with regex characters in it is matched literally", () => {
    //real names carry commas, apostrophes and plus signs
    const deck = "1 Borborygmos Enraged\n1 Jaya Ballard, Task Mage";
    const out = rebuild(deck, [swap("Jaya Ballard, Task Mage", "Opt")]);
    assert.match(out, /^1 Opt$/m);
    assert.match(out, /^1 Borborygmos Enraged$/m);
});


test("addedList is one copy of each card that came in", () => {
    assert.equal(addedList([swap("Fog", "Opt"), swap("Sol Ring", "Mana Crypt")]),
                 "1 Opt\n1 Mana Crypt");
    assert.equal(addedList([]), "");
    assert.equal(addedList(null), "");
});
