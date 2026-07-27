//the shelf of decks this browser is keeping, and the one place that decides
//what a deck is called.
//
//it lives here rather than in the two pages that touch it because the naming
//rule has to be the same in both: the modes page names a deck when it is first
//read, the hub renames one later, and a rule enforced in one of those is not a
//rule. it is also why dedupe() exists, for shelves written before there was one.
//
//nothing here talks to the server. a deck never leaves this machine, which is
//the whole design of the feature and the reason there is no account to make

export var KEY = "delvefall_recent_decks";

//ten rather than five. a decklist is about 2kb against localStorage's ~5mb
//budget, so the cap was never about space: it is about how long a list stays
//scannable, and with a rename and a drop on every row the shelf is something
//you keep rather than something that happens to you
export var KEEP = 10;

export function read() {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; }
    catch (e) { return []; }
}

export function write(decks) {
    try { localStorage.setItem(KEY, JSON.stringify(decks.slice(0, KEEP))); }
    catch (e) {
        //private browsing, a full quota, or storage switched off. the site works
        //exactly the same without a shelf, so this fails quietly
    }
}

//a label split into the name somebody meant and the number this shelf added.
//"Goblins #3" is Goblins, third of that name; "Goblins" is Goblins, first
export function baseName(label) {
    var m = /^(.*?)(?: #(\d+))?$/.exec(label || "");
    return m ? {name: m[1], n: parseInt(m[2] || "1", 10)} : {name: "", n: 1};
}

//`want`, numbered if this shelf already has a deck of that name.
//
//the SMALLEST free number, found rather than stored, so deleting the first
//"Goblins" leaves the next one taking the bare name instead of a #2 with no #1
//in front of it.
//
//`mine` is the entry being named, by its text key, and is skipped: a deck
//keeping the name it already has must not be numbered against itself.
export function uniqueName(want, decks, mine) {
    want = (want || "").trim();
    if (!want) return "";
    var wanted = baseName(want).name;
    var used = {};
    decks.forEach(function (d) {
        if (mine !== undefined && d.text === mine) return;
        var b = baseName(d.label);
        if (b.name === wanted) used[b.n] = true;
    });
    var n = 1;
    while (used[n]) n++;
    return n > 1 ? wanted + " #" + n : wanted;
}

//every deck on the shelf given a name nothing else on it has.
//
//shelves written before the rule existed can hold two decks called the same
//thing, and a rule that only applies to new decks leaves those there forever.
//this runs on load, keeps the FIRST of any clash as it is and numbers the rest,
//so nobody loses a deck and nobody has to be asked about it.
//
//it returns null when there was nothing to do, which is the usual case and
//saves writing the whole shelf back on every page view
export function dedupe(decks) {
    var seen = {}, changed = false;
    var out = decks.map(function (d) {
        var b = baseName(d.label);
        if (!b.name) return d;
        var key = b.name.toLowerCase();
        seen[key] = (seen[key] || 0) + 1;
        var want = seen[key] > 1 ? b.name + " #" + seen[key] : b.name;
        if (want === d.label) return d;
        changed = true;
        return Object.assign({}, d, {label: want});
    });
    return changed ? out : null;
}
