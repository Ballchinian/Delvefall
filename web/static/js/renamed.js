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

import { takeRename } from "decks";

(function () {
    var box = document.getElementById("deck-renamed");
    if (!box) return;
    var note = takeRename();
    if (!note || !note.now) return;

    box.textContent = "Saved as " + note.now + ", because this browser already had a "
        + "deck called " + note.was + ". Rename it from the deck list on /deck.";
    box.hidden = false;
})();
