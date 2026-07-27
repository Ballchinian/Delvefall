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

import { read, write, uniqueName, baseName, noteRename } from "decks";

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

    function remember() {
        /* read at SUBMIT time, never at load. what the deck is called is not
           settled until the commander has been picked, and what is IN it is
           not settled until the unmatched lines have been dealt with, so a
           snapshot taken on load is a snapshot of neither */
        var d = JSON.parse(el.textContent);
        var listField = document.querySelector('.deck-mode input[name="list"]');
        var text = listField ? listField.value : d.text;
        if (!text) return;
        /*
            which deck this IS, as against what is currently in it. a deck off
            the shelf carries the list it was first imported as, and that is
            what the shelf is keyed on: reopening a deck after a swap session
            hands back the swapped list, and keying on that would file the same
            deck a second time as "#2" every time it was picked up.

            a fresh paste or import has no origin, so it is keyed on itself.
        */
        var key = d.origin || text;
        var f = document.querySelector(".deck-name-field");
        var wanted = f ? f.value.trim() : "";

        var decks = read();
        /* the same deck twice is one entry, moved back to the front, rather
           than a history that fills with the deck you keep rereading. its OLD
           entry is found before it is removed, because a deck coming back
           round keeps the name it was given: renumbering it on every visit is
           how one deck became #2, then #4, then #6 */
        var was = null;
        decks = decks.filter(function (x) {
            if (x.text === key) { was = x; return false; }
            return true;
        });

        /* it already had a name of its own, so it keeps it. only a deck being
           named for the first time, or renamed, goes through the numbering */
        var name = wanted;
        if (was && was.label && wanted === was.label) name = was.label;
        else name = uniqueName(wanted, decks, key);

        /* it got NUMBERED, so say so on the page this is about to land on.
           checked off the number rather than off "the name changed", because
           uniqueName also tidies a "#2" somebody typed themselves down to the
           bare name, and that is not a clash and not worth a word */
        if (name && wanted && name !== wanted && baseName(name).n > 1) {
            noteRename(baseName(name).name, name);
        }

        /* the entry is keyed on the origin and remembers where the deck has
           actually got to, so a row can offer both: the deck as imported,
           and the deck as it stands. whatever a swap session left behind
           rides along untouched, because picking a deck back up is not
           what should undo the work done to it */
        var entry = {text: key, count: d.count, label: name, at: Date.now()};
        if (was) {
            ["swaps", "goal", "added", "newList"].forEach(function (k) {
                if (was[k]) entry[k] = was[k];
            });
        }
        /* it arrived as a list that is not the one it was imported as, so
           that IS where it has got to, and it replaces whatever the last
           session recorded */
        if (key !== text) entry.newList = text;
        decks.unshift(entry);
        write(decks);
    }

    document.querySelectorAll(".deck-mode").forEach(function (form) {
        form.addEventListener("submit", remember);
    });
})();
