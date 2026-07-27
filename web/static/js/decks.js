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
//ONE PAST THE HIGHEST, not the smallest free number. the shelf is newest first,
//so a number has to climb with recency or it reads backwards: taking the free
//#1 while a #2 sat below meant the newest deck wore the lowest number and the
//list counted upwards as it got older. dedupe closes any gap this leaves on the
//next visit to the hub, so "#2 and #3 with no #1" is a state that tidies itself.
//
//`mine` is the entry being named, by its text key, and is skipped: a deck
//keeping the name it already has must not be numbered against itself.
//
//names are matched CASE INSENSITIVELY, and they have to be, because dedupe()
//already was. matching exactly here let "goblins" onto a shelf that had
//"Goblins", and then dedupe renamed it to "goblins #2" on the next visit to the
//hub: the deck was numbered either way, just silently and one page later, which
//is the worst of both. two rules for one question is how that happens
export function uniqueName(want, decks, mine) {
    want = (want || "").trim();
    if (!want) return "";
    //compared folded, RETURNED as typed. the shelf decides which decks share a
    //name, it does not decide how somebody capitalises their own deck
    var wanted = baseName(want).name;
    var key = wanted.toLowerCase();
    var top = 0;
    decks.forEach(function (d) {
        if (mine !== undefined && d.text === mine) return;
        var b = baseName(d.label);
        if (b.name.toLowerCase() === key && b.n > top) top = b.n;
    });
    return top ? wanted + " #" + (top + 1) : wanted;
}

//every deck on the shelf given a name nothing else on it has.
//
//shelves written before the rule existed can hold two decks called the same
//thing, and a rule that only applies to new decks leaves those there forever.
//this runs on load, keeps the OLDEST of any clash unnumbered and numbers the
//rest, so nobody loses a deck and nobody has to be asked about it.
//
//OLDEST, and that is the whole reason for the reverse below. the shelf is
//newest first, so numbering down the array handed the bare name to the deck
//that arrived LAST and pushed "#2" onto the one that had been there for weeks.
//uniqueName numbers the arrival, not the resident, and the two have to agree:
//#2 is the later deck, which on a newest-first shelf is the one ABOVE, so the
//numbers count down the list the way a reader expects them to.
//
//it returns null when there was nothing to do, which is the usual case and
//saves writing the whole shelf back on every page view
export function dedupe(decks) {
    var seen = {}, changed = false;
    var out = decks.slice().reverse().map(function (d) {
        var b = baseName(d.label);
        if (!b.name) return d;
        var key = b.name.toLowerCase();
        seen[key] = (seen[key] || 0) + 1;
        var want = seen[key] > 1 ? b.name + " #" + seen[key] : b.name;
        if (want === d.label) return d;
        changed = true;
        return Object.assign({}, d, {label: want});
    }).reverse();
    return changed ? out : null;
}
