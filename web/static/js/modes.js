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
    var two = document.getElementById("deck-lead-two");
    var twoHits = document.getElementById("deck-lead-two-hits");
    var pairBox = document.getElementById("deck-lead-pair");
    var nameInput = document.getElementById("deck-name-input");
    var title = document.getElementById("deck-title");
    var dataEl = document.getElementById("deck-lead-data");
    if (!input || !hits || !dataEl) return;

    //[{name, mates}]. mates is who that card may sit beside, worked out SERVER
    //side, so the partner rule is written in python and nowhere else
    var cards = JSON.parse(dataEl.textContent) || [];
    var matesOf = {};
    cards.forEach(function (c) { matesOf[c.name.toLowerCase()] = c.mates || []; });

    function fields(cls) {
        return Array.prototype.slice.call(document.querySelectorAll(cls));
    }

    /* one function, so the heading, the hidden fields and the shelf entry can
       never disagree about the name */
    function label() {
        var typed = nameInput ? nameInput.value.trim() : "";
        if (typed) return typed;
        var lead = input.value.trim();
        var mate = (pairBox && !pairBox.hidden && two) ? two.value.trim() : "";
        return mate ? lead + " + " + mate : lead;
    }

    /* the partner slot exists only when the card above can HAVE one, and fills
       itself when the deck holds exactly one card it may sit beside */
    var lastLead = null;

    function syncPair() {
        if (!pairBox || !two) return;
        var lead = input.value.trim().toLowerCase();
        var mates = matesOf[lead] || [];
        pairBox.hidden = !mates.length;
        twoPick.setList(mates);
        //only when the FIRST answer moved, or this wipes what is being typed
        if (lead === lastLead) return;
        lastLead = lead;
        two.value = mates.length === 1 ? mates[0] : "";
    }

    function sync() {
        syncPair();
        var lead = input.value.trim();
        fields(".deck-commander-field").forEach(function (f) { f.value = lead; });
        fields(".deck-name-field").forEach(function (f) { f.value = label(); });
        if (title) title.textContent = label() || "Your deck";
        if (nameInput) nameInput.placeholder = label() || "Named after the commander";
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

    /* both slots are the same control, so it is written once. combobox shape,
       same as base.html's card suggest: a listbox the input owns, the highlight
       announced through aria-activedescendant rather than a class nobody hears */
    function combo(box, list, clearBtn, seed) {
        var names = seed || [];
        var active = -1;
        box.setAttribute("role", "combobox");
        box.setAttribute("aria-autocomplete", "list");
        box.setAttribute("aria-expanded", "false");
        box.setAttribute("aria-controls", list.id);
        list.setAttribute("role", "listbox");

        function rows() {
            return Array.prototype.slice.call(list.querySelectorAll(".suggestion"));
        }

        function mark() {
            rows().forEach(function (row, i) {
                row.classList.toggle("active", i === active);
                row.setAttribute("aria-selected", i === active ? "true" : "false");
            });
            if (active < 0) box.removeAttribute("aria-activedescendant");
            else box.setAttribute("aria-activedescendant", rows()[active].id);
        }

        function close() {
            list.style.display = "none";
            box.setAttribute("aria-expanded", "false");
            box.removeAttribute("aria-activedescendant");
            active = -1;
        }

        function pick(name) {
            box.value = name;
            sync();
            draw();
        }

        /* .suggestion so the header's card search css styles these too */
        function draw() {
            var q = box.value.trim().toLowerCase();
            list.innerHTML = "";
            active = -1;
            /* the whole list when the box is empty, so a deck with one legend
               shows it rather than nothing until somebody guesses what to type */
            var show = names.filter(function (n) { return !q || loose(n, q); }).slice(0, 8);
            if (show.length === 1 && show[0].toLowerCase() === q) return close();
            show.forEach(function (n, i) {
                var row = document.createElement("div");
                row.className = "suggestion";
                //aria-activedescendant points at an id, so every row needs one
                row.id = list.id + "-" + i;
                row.setAttribute("role", "option");
                row.setAttribute("aria-selected", "false");
                row.textContent = n;
                row.addEventListener("mousedown", function (e) {
                    /* mousedown, NOT click: otherwise the blur below closes the
                       list out from under the pointer */
                    e.preventDefault();
                    pick(n);
                });
                list.appendChild(row);
            });
            if (!show.length) return close();
            list.style.display = "block";
            box.setAttribute("aria-expanded", "true");
        }

        box.addEventListener("keydown", function (e) {
            if (list.style.display !== "block") return;
            var n = rows().length;
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                active = e.key === "ArrowDown" ? (active + 1) % n : (active - 1 + n) % n;
                mark();
            } else if (e.key === "Enter" && active >= 0) {
                //only with a row picked, or Enter still submits the form as it should
                e.preventDefault();
                pick(rows()[active].textContent);
            } else if (e.key === "Escape") {
                close();
            }
        });

        box.addEventListener("input", function () {
            /* a typed name still counts: the picker is a shortcut, not a gate */
            sync();
            draw();
        });
        box.addEventListener("focus", draw);
        box.addEventListener("blur", function () {
            /* after the mousedown above has had its turn */
            setTimeout(close, 120);
        });
        if (clearBtn) clearBtn.addEventListener("click", function () {
            box.value = "";
            sync();
            draw();
            box.focus();
        });

        return {setList: function (l) { names = l; }};
    }

    //the partner slot is built FIRST: syncPair reaches for it on the first sync
    var twoPick = (two && twoHits)
        ? combo(two, twoHits, document.getElementById("deck-lead-two-clear"), [])
        : {setList: function () {}};
    combo(input, hits, document.getElementById("deck-lead-clear"),
          cards.map(function (c) { return c.name; }));

    if (nameInput) nameInput.addEventListener("input", sync);
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
