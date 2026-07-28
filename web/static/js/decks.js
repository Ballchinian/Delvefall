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
//  3. NOTHING. the name is a LABEL. no deck is ever found by it: the hub opens
//     by d.text, the swap tool writes by d.origin || d.text, /deck/view looks
//     up the same way. two decks called "Kratos, God of War" are two rows with
//     the same word on them, which is a thing the person who named them can see
//     and fix, and which breaks nothing at all.
//
//it also answers the hand-edited-localStorage question for free: a duplicate
//name arriving from outside cannot corrupt anything, because nothing resolves a
//deck by name in the first place.
