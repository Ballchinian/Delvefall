//the shelf of decks this browser is keeping, and the one place that decides
//what a deck IS.
//
//it lives here rather than in the pages that touch it because FOUR of them do:
//the modes page creates a deck and renames it as you type, the hub renames and
//deletes, the swap tool writes a session onto one, /deck/view puts a card back.
//a rule enforced in one of those is not a rule.
//
//EVERY ENTRY HAS AN ID, AND THE ID IS THE WHOLE OF ITS IDENTITY. that is the
//change this file exists to make, and everything below follows from it. the
//shelf used to be keyed on the DECKLIST, and keying a saved deck on its own
//contents cost more than it ever bought:
//
//  1. THE SAME DECK COULD NOT BE SAVED TWICE. pasting a list you already had
//     found the old entry and wrote over it, so "import it again and keep both"
//     was not a thing the shelf could express. it is a perfectly ordinary thing
//     to want: the same list, forked two ways.
//  2. A RENAME HIT EVERY DECK WITH THAT LIST. the hub renamed by matching text,
//     so two entries holding the same cards were renamed together, silently.
//  3. THE KEY MOVED WHEN THE DECK DID. a swap session changes the list, so
//     every page had to carry the list as IMPORTED alongside the list as it
//     stands, and every lookup was a two branch guess about which of the two it
//     was holding. that guess is gone: pages carry an id, which is four bytes
//     and cannot go stale.
//
//nothing here talks to the server. a deck never leaves this machine, which is
//the whole design of the feature and the reason there is no account to make.

export var KEY = "delvefall_recent_decks";

//ten rather than five. a decklist is about 2kb against localStorage's ~5mb
//budget, so the cap was never about space: it is about how long a list stays
//scannable, and with a rename and a drop on every row the shelf is something
//you keep rather than something that happens to you.
//
//reaching it now REFUSES THE NEXT DECK rather than quietly dropping the oldest.
//see create()
export var KEEP = 10;

//a deck's identity, made once and never derived from anything about the deck.
//the time part keeps ids roughly ordered when read by a human, the random part
//is what stops two decks saved in the same millisecond (two tabs, one paste
//each) from being one deck
function newId() {
    return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function read() {
    var decks;
    try { decks = JSON.parse(localStorage.getItem(KEY)) || []; }
    catch (e) { return []; }
    if (!Array.isArray(decks)) return [];

    //shelves written before ids existed are still sitting in people's browsers,
    //and an entry with no id is an entry nothing can find, rename or delete. so
    //it gets one here, on the first read after this code arrives, and that is
    //the whole migration. it writes back rather than stamping in memory each
    //time, because an id that changes on every read is not an identity
    var stamped = false;
    decks.forEach(function (d) {
        if (d && !d.id) { d.id = newId(); stamped = true; }
    });
    if (stamped) write(decks);
    return decks;
}

export function write(decks) {
    try { localStorage.setItem(KEY, JSON.stringify(decks.slice(0, KEEP))); }
    catch (e) {
        //private browsing, a full quota, or storage switched off. the site works
        //exactly the same without a shelf, so this fails quietly
    }
}

//is there room for another deck. asked by the hub BEFORE a deck is read rather
//than after, because the answer decides whether reading it is worth doing
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
    a new deck on the shelf, ALWAYS a new one. nothing here looks at whether
    some other entry holds the same cards, and that is the point: two imports of
    one list are two decks, because the person doing it is about to take them in
    two directions. the shelf is theirs, and a row they did not want is one
    click to drop.

    it returns the new id, or "" when the shelf is FULL. full means full: the
    oldest deck is not thrown away to make room, because the oldest deck is
    somebody's, it may be the one carrying a hundred swaps, and a save that
    silently deletes a save is the worst thing a save can do. the caller says so
    and the user deletes one.
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
    change some fields on one deck, leaving the rest of it alone.

    it re-reads the shelf rather than working from a copy the caller is holding,
    because the caller may have been holding it for twenty minutes: a swap
    session reads its deck at the start and writes on every swap, and another tab
    renaming that deck in between should not be undone by the write. only the
    named fields move, so the two writes both land.

    returns whether the deck was still there. it may not be: deleted from the
    hub in another tab is the ordinary case, and the right answer to that is to
    write nothing rather than to bring it back.
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

//the whole shelf, gone. it is here rather than in the hub so that this file is
//the ONLY one that names the storage key, which is what makes it the only one
//that can be wrong about the shape of what is in there
export function clear() {
    try { localStorage.removeItem(KEY); }
    catch (e) {
        //storage switched off, which means there was nothing to clear
    }
}

//TWO DECKS MAY SHARE A NAME, and nothing here checks. this went through three
//rules before landing on none, which is worth writing down so it is not
//reinvented a fourth time:
//
//  1. NUMBER THE CLASH. the shelf appended "#2" and told you afterwards, which
//     needed a note carried between two pages, which needed the note to know
//     which deck it was about, which it could not: a numbered deck and the deck
//     it was numbered against share the very name the note was matched on. it
//     also normalised what you typed before comparing, so asking for
//     "Kratos, God of War #3" came back as "#2".
//  2. REFUSE THE CLASH. one rule, no state, said where the name was typed. but
//     refusing means blocking the submit, and the submit was the mode button:
//     pick a name another deck had and View it simply stopped working. a naming
//     rule that can break the page's primary action is worse than the thing it
//     was protecting against.
//  3. NOTHING. the name is a LABEL, and since ids arrived it is ONLY a label:
//     no deck is ever found by one, here or on any page. two decks called
//     "Kratos, God of War" are two rows with the same word on them, which is a
//     thing the person who named them can see and fix, and which breaks nothing.
