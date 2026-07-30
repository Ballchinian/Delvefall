//the page between a deck arriving and something being done with it.
//
//the two questions are independent: the commander names the deck only when no
//name has been typed. writing it into the name outright would mean a deck can
//never be called anything else.
//
//the shelf and its naming rule live in decks.js, shared with the hub

import { create, find, patch } from "decks";

(function () {
    var input = document.getElementById("deck-lead-input");
    var hits = document.getElementById("deck-lead-hits");
    var nameInput = document.getElementById("deck-name-input");
    var title = document.getElementById("deck-title");
    var dataEl = document.getElementById("deck-lead-data");
    if (!input || !hits || !dataEl) return;
    var names = JSON.parse(dataEl.textContent) || [];

    function fields(cls) {
        return Array.prototype.slice.call(document.querySelectorAll(cls));
    }

    /* one function, so the heading, the hidden fields and the shelf entry can
       never disagree about the name */
    function label() {
        var typed = nameInput ? nameInput.value.trim() : "";
        return typed || input.value.trim();
    }

    function sync() {
        var lead = input.value.trim();
        fields(".deck-commander-field").forEach(function (f) { f.value = lead; });
        fields(".deck-name-field").forEach(function (f) { f.value = label(); });
        if (title) title.textContent = label() || "Your deck";
        if (nameInput) nameInput.placeholder = lead || "Named after the commander";
        /* EVERY way of changing the name comes through here, so the other half
           of this file listens for the event rather than the boxes */
        document.dispatchEvent(new CustomEvent("deck-named"));
    }

    /* every typed character has to appear in order but not adjacent, so "gow"
       finds Kratos, God of War. a deck holds a handful of legends, so a stricter
       filter would be protecting against nothing */
    function loose(name, q) {
        var n = name.toLowerCase(), at = 0;
        for (var i = 0; i < q.length; i++) {
            at = n.indexOf(q[i], at);
            if (at === -1) return false;
            at++;
        }
        return true;
    }

    function pick(name) {
        input.value = name;
        sync();
        draw();
    }

    /* .suggestion so the header's card search css styles these too */
    function draw() {
        var q = input.value.trim().toLowerCase();
        hits.innerHTML = "";
        /* the whole list when the box is empty, so a deck with one legend shows
           it rather than nothing until somebody guesses what to type */
        var show = names.filter(function (n) { return !q || loose(n, q); }).slice(0, 8);
        if (show.length === 1 && show[0].toLowerCase() === q) {
            hits.style.display = "none";
            return;
        }
        show.forEach(function (n) {
            var row = document.createElement("div");
            row.className = "suggestion";
            row.textContent = n;
            row.addEventListener("mousedown", function (e) {
                /* mousedown, NOT click: otherwise the blur below closes the list
                   out from under the pointer */
                e.preventDefault();
                pick(n);
            });
            hits.appendChild(row);
        });
        hits.style.display = show.length ? "block" : "none";
    }

    input.addEventListener("input", function () {
        /* a typed name still counts: the picker is a shortcut, not a gate */
        sync();
        draw();
    });
    input.addEventListener("focus", draw);
    input.addEventListener("blur", function () {
        /* after the mousedown above has had its turn */
        setTimeout(function () { hits.style.display = "none"; }, 120);
    });
    if (nameInput) nameInput.addEventListener("input", sync);

    document.getElementById("deck-lead-clear").addEventListener("click", function () {
        input.value = "";
        sync();
        draw();
        input.focus();
    });
    sync();
})();

(function () {
    /*
        the server kept nothing: /deck/open parsed the text, rendered this page
        and forgot it, so the only copy outliving the tab is written here.

        READING A DECK SAVES IT, and this page is the ONLY place that ever creates
        a shelf entry. the one thing that stops it is the shelf being full
    */
    var el = document.getElementById("deck-remember");
    if (!el) return;
    var D = JSON.parse(el.textContent);
    var note = document.getElementById("deck-save-full");

    /* filled when the deck came from the shelf or another page of the lens, empty
       when it is new here. it used to be the decklist AS IMPORTED, so every page
       held that alongside the list as it stands and guessed which it had */
    var did = D.did;

    function fields(cls) {
        return Array.prototype.slice.call(document.querySelectorAll(cls));
    }

    /* every mode form carries it, and missing.js rewrites all of them when a
       card is matched by hand */
    function listNow() {
        var f = document.querySelector('.deck-mode input[name="list"]');
        return f ? f.value : D.text;
    }

    /* off the hidden field, so this reads the answer rather than working it out
       a second way */
    function named() {
        var f = document.querySelector(".deck-name-field");
        return f ? f.value.trim() : "";
    }

    /* kept apart from the name, because a deck renamed "the budget one" still
       knows which card it is built around */
    function leader() {
        var f = document.querySelector(".deck-commander-field");
        return f ? f.value.trim() : "";
    }

    /* the hub refuses a full shelf BEFORE a deck is read, which is where it
       belongs. this is for the ways in that skip the hub, a precon sent to the
       lens above all, and it is a note because the deck on screen still works */
    function refuse() {
        if (note) note.hidden = false;
    }

    function remember() {
        var text = listNow();
        if (!text) return;

        if (!did) {
            did = create({text: text, count: D.count,
                          label: named(), commander: leader()});
            if (!did) return refuse();
            /* jinja could not fill these: the entry did not exist at build time */
            fields(".deck-did-field").forEach(function (f) { f.value = did; });
            return;
        }

        var entry = find(did);
        /* deleted from the hub in another tab. write nothing: a rename must not
           resurrect a deck somebody just threw away */
        if (!entry) return;

        /* the count rides along because it is the fallback NAME for an unnamed
           deck, and it moves: a deck reopened after a session is counted again */
        var change = {label: named(), commander: leader(), count: D.count};
        if (text && text !== entry.text) {
            /*
                WHICH FIELD this lands in turns on whether the deck has swaps.

                with none, the list it holds IS what it was imported as: the only
                way it moved is a line matched by hand, which corrects our reading
                rather than the deck.

                with swaps, entry.text is the list they were all made against and
                rebuild depends on it, so it must not move under them
            */
            if ((entry.swaps || []).length) change.newList = text;
            else change.text = text;
        }
        patch(did, change);
    }

    /* every way of changing the name comes through sync(), so listening for its
       event catches all of them */
    document.addEventListener("deck-named", remember);

    /* again on the way out, because the LIST can still change after the name has
       settled: matching a missed card rewrites every list field on the page */
    document.querySelectorAll(".deck-mode").forEach(function (form) {
        form.addEventListener("submit", remember);
    });

    /* sync() has already fired its event by the time this half of the file runs,
       so the first save has to be made here rather than waited for */
    remember();
})();
