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

import { read, write } from "decks";

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

        it runs on SUBMIT rather than on load, because what the deck is called
        is not settled until the commander has been picked, and an entry
        written on load would be the one that had to be corrected later
    */
    var el = document.getElementById("deck-remember");
    if (!el) return;

    /* what this deck is called and which shelf entry it is */
    function reading() {
        var d = JSON.parse(el.textContent);
        var listField = document.querySelector('.deck-mode input[name="list"]');
        var text = listField ? listField.value : d.text;
        var f = document.querySelector(".deck-name-field");
        var decks = read();
        /*
            WHICH DECK THIS IS, as against what is currently in it.

            a deck off the shelf carries the list it was first imported as, and
            that is what the shelf is keyed on: reopening a deck after a swap
            session hands back the swapped list, and keying on that would file
            the same deck a second time.

            a fresh paste has no origin, so it is keyed on its own text, and
            that USED to be the end of it. it is not enough: a pasted deck that
            has since been swapped comes back holding the new list, whose text
            matches no entry, so the shelf saw a stranger and filed a second
            copy. so a list that matches some entry's newList identifies that
            entry too. this is the whole of "is this a deck I already have"
        */
        var key = d.origin || text;
        var was = null;
        decks.forEach(function (x) {
            if (was) return;
            if (x.text === key || (text && x.newList === text)) was = x;
        });
        if (was) key = was.text;
        return {d: d, text: text, key: key, was: was, decks: decks,
                wanted: f ? f.value.trim() : ""};
    }

    /*
        THIS NEVER REFUSES AND NEVER PREVENTS ANYTHING.

        it briefly did both, to stop two decks sharing a name, and the cost was
        out of all proportion: the submit it blocked was the mode button, so
        typing a name another deck had made View it stop working, with a
        sentence beside the box as the only clue. saving a deck is what this
        page is FOR, and nothing about a label is worth not doing it.

        AND IT RUNS ON ARRIVAL, not only on the way out. it used to wait for a
        submit, on the reasoning that what a deck is called is not settled until
        the commander has been picked. true, and it made reaching this page and
        going anywhere else lose the deck entirely: the one moment a person is
        most likely to wander off is before they have chosen what to do with it.
        so the deck is saved the moment it is read, and every later touch of the
        name is a rename of an entry that already exists. an unnamed deck is a
        saved deck with no name yet, which is a better thing to be than gone.
    */
    function remember() {
        var r = reading();
        if (!r.text) return;

        var decks = r.decks.filter(function (x) { return x.text !== r.key; });
        /* a deck coming back round keeps the name it was given unless a new one
           was typed over it */
        var name = r.wanted || (r.was && r.was.label) || "";

        /* the entry is keyed on the origin and remembers where the deck has
           actually got to, so a row can offer both: the deck as imported,
           and the deck as it stands. whatever a swap session left behind
           rides along untouched, because picking a deck back up is not
           what should undo the work done to it */
        var entry = {text: r.key, count: r.d.count, label: name, at: Date.now()};
        if (r.was) {
            ["swaps", "goal", "added", "newList"].forEach(function (k) {
                if (r.was[k]) entry[k] = r.was[k];
            });
        }
        /* it arrived as a list that is not the one it was imported as, so
           that IS where it has got to, and it replaces whatever the last
           session recorded */
        if (r.key !== r.text) entry.newList = r.text;
        decks.unshift(entry);
        write(decks);
    }

    /* renamed as it is typed. the entry is found by its list, not its name, so
       a rename is the same write as the first save with a different label on it */
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
