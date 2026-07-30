//the shelf of decks this browser is keeping, and the one place that decides what
//a deck is. four pages touch it, so a rule enforced in one of them is not a rule.
//
//every entry has an id and the id is the whole of its identity. keying on the
//DECKLIST instead would mean: the same list cannot be saved twice, a rename hits
//every deck holding those cards, and the key moves when a swap session changes
//the list, so every lookup becomes a two branch guess.
//
//nothing here talks to the server. a deck never leaves this machine.

export var KEY = "delvefall_recent_decks";

//not about space: a decklist is ~2kb against localStorage's ~5mb. it is about
//how long a list stays scannable. reaching it REFUSES the next deck rather than
//dropping the oldest, see create()
export var KEEP = 10;

//never derived from anything about the deck. the time part keeps ids roughly
//ordered for a human, the random part stops two decks saved in the same
//millisecond (two tabs, one paste each) from being one deck
function newId() {
    return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function read() {
    var decks;
    try { decks = JSON.parse(localStorage.getItem(KEY)) || []; }
    catch (e) { return []; }
    if (!Array.isArray(decks)) return [];

    //shelves written before ids existed are still in people's browsers, and an
    //entry with no id can never be found, renamed or deleted. the whole
    //migration. it WRITES BACK rather than stamping in memory, because an id
    //that changes on every read is not an identity
    var stamped = false;
    decks.forEach(function (d) {
        if (d && !d.id) { d.id = newId(); stamped = true; }
    });
    if (stamped) write(decks);
    return decks;
}

//NO cap here. create() decides whether a deck may be added and refuses rather
//than dropping the oldest; slicing to KEEP here too would be the same rule
//written twice and written differently, and the entries it cut would be exactly
//the ones the shelf exists not to lose
export function write(decks) {
    try { localStorage.setItem(KEY, JSON.stringify(decks)); }
    catch (e) {
        //private browsing, a full quota, or storage switched off. the site works
        //exactly the same without a shelf, so this fails quietly
    }
}

//asked by the hub BEFORE a deck is read, because the answer decides whether
//reading it is worth doing
export function full() {
    return read().length >= KEEP;
}

export function find(id) {
    if (!id) return null;
    var got = null;
    read().forEach(function (d) { if (!got && d.id === id) got = d; });
    return got;
}

/*
    ALWAYS a new deck: nothing here checks whether another entry holds the same
    cards, because two imports of one list are two decks about to go two ways.

    returns the new id, or "" when the shelf is FULL. the oldest deck is never
    thrown away to make room: it may be the one carrying a hundred swaps, and a
    save that deletes a save is the worst thing a save can do
*/
export function create(entry) {
    var decks = read();
    if (decks.length >= KEEP) return "";
    entry.id = newId();
    entry.at = Date.now();
    decks.unshift(entry);
    write(decks);
    return entry.id;
}

/*
    re-reads the shelf rather than trusting the caller's copy, which may be
    twenty minutes old: a swap session reads its deck at the start and writes on
    every swap, and another tab renaming it in between must not be undone. only
    the named fields move, so both writes land.

    returns whether the deck was still there. deleted from the hub in another tab
    is the ordinary case, and writing nothing is the right answer to it
*/
export function patch(id, fields) {
    if (!id) return false;
    var decks = read(), found = false;
    decks.forEach(function (d) {
        if (d.id !== id) return;
        found = true;
        Object.keys(fields).forEach(function (k) { d[k] = fields[k]; });
        d.at = Date.now();
    });
    if (found) write(decks);
    return found;
}

export function drop(id) {
    write(read().filter(function (d) { return d.id !== id; }));
}

//here rather than in the hub so this file is the ONLY one that names KEY
export function clear() {
    try { localStorage.removeItem(KEY); }
    catch (e) {
        //storage switched off, which means there was nothing to clear
    }
}

//two decks may share a name and nothing here checks: the name is a label only,
//and no deck is ever found by one, here or on any page.
