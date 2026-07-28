//the page between a deck arriving and something being done with it: pick the
//commander, optionally name it, then choose a mode.
//
//moved out of templates/deck/modes.html, which is also where the two questions
//got separated. picking a commander used to write into the deck's NAME as well,
//so the two could never disagree and a deck could not be called anything else.
//they are independent now: the commander names the deck only when no name has
//been typed, which is the common case and stays one decision.
//
//the shelf and its naming rule live in decks.js, shared with the hub, because a
//rule enforced in one of the two places that name a deck is not a rule

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

    /* what the deck is called: whatever was typed, or the commander when
       nothing was. one function so the heading, the hidden fields and the
       shelf entry can never disagree about it */
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
        /* the deck is now called something, possibly something new. said out
           loud so the half of this file that keeps the shelf can hear it,
           because every way of changing the name comes through here: typing in
           either box, picking a commander off the dropdown, and Clear. the two
           halves share the page rather than their variables, and one event is a
           smaller bridge than moving either of them */
        document.dispatchEvent(new CustomEvent("deck-named"));
    }

    /*
        very loose on purpose: every typed character has to appear in the name,
        in order, but not next to each other. "kr" finds Kratos, "gow" finds
        Kratos, God of War, and a typo in the middle of a long name still
        lands. a deck holds a handful of legends, so there is nothing here that
        a stricter filter would be protecting against
    */
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

    /* laid out like the header's card search: a box, and what matches dropping
       down under it. the rows carry the same class so they are highlighted and
       spaced by the same css rather than by a second set of rules */
    function draw() {
        var q = input.value.trim().toLowerCase();
        hits.innerHTML = "";
        /* the whole candidate list when the box is empty, so a deck with one
           legend in it shows that legend rather than showing nothing until
           somebody guesses what to type */
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
                /* mousedown, not click: the box loses focus first otherwise and
                   the blur below closes the list out from under the pointer */
                e.preventDefault();
                pick(n);
            });
            hits.appendChild(row);
        });
        hits.style.display = show.length ? "block" : "none";
    }

    input.addEventListener("input", function () {
        /* a name typed rather than picked still names the deck: the picker is
           a shortcut, not a gate */
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
        remember this deck in THIS BROWSER. the server has already forgotten
        it: /deck/open parsed the text, rendered this page and kept nothing,
        so the only copy that outlives the tab is the one written here, on the
        user's own machine, where they can delete it from the hub.

        READING A DECK SAVES IT, every time, and this page is the only place
        that ever creates a shelf entry. arriving here means a list was pasted,
        a link was imported or a precon was handed to the lens, and all three
        are somebody saying "this deck, now". the same list read twice is two
        decks, because the two are about to be taken in two directions, and the
        shelf is theirs to prune.

        the one thing that stops it is the shelf being FULL. see below.
    */
    var el = document.getElementById("deck-remember");
    if (!el) return;
    var D = JSON.parse(el.textContent);
    var note = document.getElementById("deck-save-full");

    /*
        WHICH SAVED DECK THIS IS, carried in a hidden field on every form that
        leads off this page. it arrives filled when the deck came from the shelf
        or from another page of the lens, and empty when the deck is new here.

        it used to be the decklist AS IMPORTED, and every page had to hold that
        alongside the list as it stands and guess which of the two it was looking
        at. an id cannot go stale and cannot be two things at once
    */
    var did = D.did;

    function fields(cls) {
        return Array.prototype.slice.call(document.querySelectorAll(cls));
    }

    /* the deck as this page is holding it. every mode form carries it, and
       missing.js rewrites all of them when a card is matched by hand */
    function listNow() {
        var f = document.querySelector('.deck-mode input[name="list"]');
        return f ? f.value : D.text;
    }

    /* what it is called, off the hidden fields the other half of this file
       keeps in step with both boxes. so this reads the answer rather than
       working it out a second way */
    function named() {
        var f = document.querySelector(".deck-name-field");
        return f ? f.value.trim() : "";
    }

    /* who leads it, kept separately from what it is called because they are two
       different facts. the shelf hands both back when the deck is reopened, and
       a deck renamed to "the budget one" still knows which card it is built
       around */
    function leader() {
        var f = document.querySelector(".deck-commander-field");
        return f ? f.value.trim() : "";
    }

    /*
        THE ONE REFUSAL. a shelf with ten decks on it cannot take an eleventh,
        and the alternative (drop the oldest to make room) is a save quietly
        deleting a save, which may be the deck carrying a hundred swaps.

        the hub stops this before a deck is read at all, which is where it
        belongs: nobody wants to find out after the import. this is for the ways
        in that do not pass through the hub, a precon sent to the lens above all,
        and it is a note rather than a block because the deck on screen still
        works. it simply will not be there tomorrow.
    */
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
            /* every way on from this page now knows which deck it is carrying.
               jinja could not fill these in: the entry did not exist when the
               page was built, and the id is what it got when it did */
            fields(".deck-did-field").forEach(function (f) { f.value = did; });
            return;
        }

        var entry = find(did);
        /* deleted from the hub in another tab while this page sat open. the
           right answer is to write nothing: a rename should not resurrect a
           deck somebody has just thrown away */
        if (!entry) return;

        /* the count comes back round too, because it is the shelf's fallback
           name for a deck nobody has named and it can genuinely move: a deck
           reopened after a swap session is being counted again, from the list
           it has now */
        var change = {label: named(), commander: leader(), count: D.count};
        if (text && text !== entry.text) {
            /*
                the list under this deck has moved, and WHICH FIELD that lands
                in turns on whether the deck has been swapped.

                a deck with no swaps on it has not gone anywhere: whatever it is
                holding IS what it was imported as. the way that happens is
                matching a line the parser could not read, which does not change
                the deck, it corrects our reading of it.

                once it has swaps, entry.text is the list they were all made
                against and rebuilding the deck depends on it, so it must not
                move under them. the change is then where the deck has got TO.
            */
            if ((entry.swaps || []).length) change.newList = text;
            else change.text = text;
        }
        patch(did, change);
    }

    /* renamed as it is typed, which is the whole reason this listens for an
       event rather than reading the box: every way of changing the name comes
       through sync(), and a rename is the same write as the first save with a
       different label on it */
    document.addEventListener("deck-named", remember);

    /* and once more on the way out, because the LIST can still change after the
       name has settled: adding a card the parser missed rewrites every list
       field on the page, and this is the last moment to catch it */
    document.querySelectorAll(".deck-mode").forEach(function (form) {
        form.addEventListener("submit", remember);
    });

    /* on arrival. sync() has already run and dispatched its event by the time
       this half of the file is reached, so the first save has to be made here
       rather than waited for */
    remember();
})();
