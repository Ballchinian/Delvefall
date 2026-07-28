//the shelf of decks this browser is keeping, and the one place that decides
//what a deck is called.
//
//it lives here rather than in the two pages that touch it because the naming
//rule has to be the same in both: the modes page names a deck when it is first
//read, the hub renames one later, and a rule enforced in one of those is not a
//rule.
//
//the rule is now simply that two decks cannot share a name, refused at the
//moment of naming. see nameTaken for what it replaced and why.
//
//nothing here talks to the server. a deck never leaves this machine, which is
//the whole design of the feature and the reason there is no account to make

export var KEY = "delvefall_recent_decks";

//ten rather than five. a decklist is about 2kb against localStorage's ~5mb
//budget, so the cap was never about space: it is about how long a list stays
//scannable, and with a rename and a drop on every row the shelf is something
//you keep rather than something that happens to you
export var KEEP = 10;

//the rename note that used to live here is GONE, along with the banner it fed.
//it carried "we called your deck something else" from the page that renamed to
//the page that landed, and it only ever existed because the shelf renamed decks
//behind your back. nothing does that now: a clash is refused while you are still
//looking at the box you typed it in, which is the moment it can be fixed.
//
//it is worth knowing that leftover notes may still sit in a tab's sessionStorage
//under "delvefall_renamed". nothing reads them, and sessionStorage dies with the
//tab, so they need no cleaning up.

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

//the deck on this shelf already called `want`, or null.
//
//THE SHELF USED TO NUMBER A CLASH INSTEAD OF REFUSING IT, appending "#2" and
//then telling you it had. that rule is gone, and it is worth writing down why,
//because it looked reasonable and was wrong in four separate ways:
//
//  - it normalised what you typed before comparing, so asking for
//    "Kratos, God of War #3" was read as a request for "Kratos, God of War",
//    which clashed, and came back as "#2". the answer to a name you chose was
//    a different name you did not.
//  - it had to tell you afterwards, which needed a note carried between two
//    pages, which needed the note to know which deck it was about, which it
//    could not, because a numbered deck and the deck it was numbered against
//    share the name the note was matched on.
//  - "#2" is not a name. it is the shelf admitting it could not do the thing
//    and going ahead anyway.
//  - and the numbers had to be maintained: dedupe() existed only to close the
//    gaps the numbering left behind.
//
//refusing is one rule with no state, nothing to carry between pages and nothing
//to tidy up afterwards. the person naming the deck is right there and is the
//only one who knows what they meant.
//
//`mine` is the entry being named, by its text key, and is skipped: a deck
//keeping the name it already has has not clashed with anything.
//
//names are compared CASE INSENSITIVELY and with the ends trimmed, so "goblins "
//does not slip onto a shelf that has "Goblins". it is a comparison only: what
//gets stored is what was typed, because the shelf decides which decks share a
//name, not how somebody capitalises their own deck
export function nameTaken(want, decks, mine) {
    want = (want || "").trim().toLowerCase();
    if (!want) return null;
    var hit = null;
    (decks || []).forEach(function (d) {
        if (hit || (mine !== undefined && d.text === mine)) return;
        if ((d.label || "").trim().toLowerCase() === want) hit = d;
    });
    return hit;
}
