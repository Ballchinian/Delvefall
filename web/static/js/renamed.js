//"your deck was saved under another name", said on the page the rename landed
//on rather than on the page that caused it.
//
//the naming page cannot say it: the shelf numbers a clash at submit time and
//submitting navigates away, so the only moment the answer exists is after this
//page has already loaded. predicting it on the way out was tried and pulled for
//firing on decks that did not actually clash.
//
//it reads the note ONCE and deletes it, so a refresh does not repeat itself.
//no note is the usual case and the banner simply never appears.
//
//and it only speaks for the deck the note is ABOUT. the note lives in
//sessionStorage, which belongs to the tab, so it has no owner of its own: any
//page that asked first got it. that is how a rename of one deck ended up
//announced on the page of another, days of clicking later, with a warning
//about a name the user could no longer see anywhere on screen.
//
//the mismatch case still DELETES it rather than putting it back. a note that
//has reached the wrong deck has already missed the page it was written for,
//and the alternative is leaving it in the tab to miss another one

import { takeRename } from "decks";

(function () {
    var box = document.getElementById("deck-renamed");
    if (!box) return;
    var note = takeRename();
    if (!note || !note.now) return;

    /* the name the deck went in under, which is what the page it lands on is
       titled with: the shelf numbered it afterwards and the form never heard.
       an empty data-deck means the page did not say, and an unnamed deck is
       not one this note can be checked against, so it is let through */
    var mine = box.dataset.deck || "";
    if (mine && note.was && note.was !== mine) return;

    box.textContent = "Saved as " + note.now + ", because this browser already had a "
        + "deck called " + note.was + ". Rename it from the deck list on /deck.";
    box.hidden = false;
})();
