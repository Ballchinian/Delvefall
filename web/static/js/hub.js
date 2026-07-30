//the saved decks panel on /deck. it holds no rules about what a deck IS:
//decks.js owns that, which is why the rename here and the one on the modes page
//cannot disagree.
//
//the second half of the file is the shelf being FULL, the one thing this page
//refuses to do rather than draw.

import { el, cardLink } from "dom";
import { read, drop, patch, clear, full, KEEP } from "decks";

(function () {
    var box = document.getElementById("deck-recent");
    var list = document.getElementById("deck-recent-list");
    if (!box || !list) return;

    /* no dedupe by name, deliberately: NOTHING ON THIS SITE FINDS A DECK BY ITS
       NAME, so two rows sharing one is an eyesore and never a bug */

    function open(d) {
        /* newList, not d.text: sending the imported list handed a session's work
           back undone with nothing on screen to say so.
           the id says WHICH saved deck this is. without it the deck arrives
           looking unseen and is saved a second time, on a shelf that holds ten */
        document.getElementById("deck-recent-list-field").value = d.newList || d.text;
        document.getElementById("deck-recent-did-field").value = d.id;
        /* the name and the commander are TWO facts and the shelf keeps both.
           sending the label as the commander was near enough until somebody
           renamed a deck: "Budget Krenko" is not a card, and the picker on the
           next page opened with it typed in and nothing matching */
        document.getElementById("deck-recent-name-field").value = d.label || "";
        document.getElementById("deck-recent-commander-field").value = d.commander || "";
        document.getElementById("deck-recent-form").submit();
    }

    /* oldest first, the same order /deck/swap and /deck/view show them. folded,
       or ten decks listing thirty changes each bury what the panel is for */
    function changes(li, d) {
        var swaps = d.swaps || [];
        var n = swaps.length;
        if (!n) {
            /* how much this deck has MOVED, not how big it is: a card count read
               "a hundred, a hundred, a hundred" down the whole shelf */
            el("span", "deck-recent-meta", li, "unchanged");
            return;
        }
        var fold = el("details", "deck-recent-changes", li);
        el("summary", "deck-recent-meta", fold,
           n + (n === 1 ? " change" : " changes"));
        var rows = el("ol", "deck-recent-swaps", fold);
        swaps.forEach(function (s) {
            /* localStorage is hand editable and older versions of this code are
               still out there: one malformed swap costs its own row, not the
               whole shelf below it */
            if (!s || !s.out || !s["in"]) return;
            var row = el("li", "deck-recent-swap", rows);
            row.appendChild(cardLink(s.out.name, "swap-made-out"));
            el("span", "swap-made-arrow", row, "→");
            row.appendChild(cardLink(s["in"].name, "swap-made-in"));
        });
    }

    /* an unnamed deck is called after its size, which is at least a fact */
    function opener(d, li) {
        var btn = el("button", "deck-recent-open", li,
                     d.label || (d.count ? d.count + " cards" : "Unnamed deck"));
        btn.type = "button";
        btn.addEventListener("click", function () { open(d); });
        return btn;
    }

    /* the glyphs are the same on every row, so the label carries the deck's name
       for a screen reader and moves when the name does */
    function relabel(li, d) {
        var name = d.label || "this deck";
        li.querySelectorAll(".deck-recent-tool").forEach(function (t) {
            t.setAttribute("aria-label",
                (t.classList.contains("deck-recent-drop") ? "forget " : "rename ") + name);
        });
    }

    /*
        saves on every letter, the same rule the modes page follows.

        only the ONE ROW is put back on the way out, never a redraw: a redraw
        deletes every other row's buttons mid-click, so going straight from
        renaming one deck to forgetting another did nothing the first time
    */
    function rename(li, d) {
        var was = li.querySelector(".deck-recent-open");
        if (!was) return;
        /* every letter is already saved, so escape has no draft to throw away,
           only a name to put back */
        var before = d.label || "";

        var field = document.createElement("input");
        field.type = "text";
        field.className = "deck-recent-name";
        field.value = before;
        field.placeholder = "Call this deck";
        field.setAttribute("aria-label", "the name of this deck");
        was.replaceWith(field);
        field.focus();
        field.select();

        function done() {
            field.remove();
            /* el appends and the name belongs at the top, so prepend */
            li.prepend(opener(d, li));
            relabel(li, d);
        }

        field.addEventListener("input", function () {
            /* whatever was typed, a name another deck already has included */
            d.label = field.value.trim();
            patch(d.id, {label: d.label});
        });
        field.addEventListener("blur", done);
        field.addEventListener("keydown", function (e) {
            /* both mean "done", nothing being cancellable. escape differs only in
               putting the old name back */
            if (e.key === "Enter") field.blur();
            if (e.key === "Escape") {
                d.label = before;
                patch(d.id, {label: before});
                field.blur();
            }
        });
    }

    /* rebuilt rather than patched, which is the right trade at ten entries */
    function draw() {
        var decks = read();
        list.innerHTML = "";
        box.hidden = !decks.length;
        say(decks.length);
        if (!decks.length) return;

        decks.forEach(function (d) {
            var li = el("li", "deck-recent-row", list);
            opener(d, li);
            changes(li, d);

            var tools = el("span", "deck-recent-tools", li);

            var ren = el("button", "deck-recent-tool", tools, "✎");
            ren.type = "button";
            ren.title = "rename this deck";
            ren.addEventListener("click", function () { rename(li, d); });

            var del = el("button", "deck-recent-tool deck-recent-drop", tools, "×");
            del.type = "button";
            del.title = "forget this deck";
            del.addEventListener("click", function () {
                /* by id, NEVER by position or list: two rows may hold the same
                   cards, and another tab may have rewritten the shelf since */
                drop(d.id);
                draw();
            });

            relabel(li, d);
        });
    }

    /* the number that decides whether the next deck can be read at all, so
       being turned away is learning it too late */
    var room = document.getElementById("deck-recent-room");

    function say(n) {
        if (!room) return;
        room.textContent = n >= KEEP
            ? "This is full at " + KEEP + " decks. Forget one to make room for the next."
            : n + " of " + KEEP + " saved.";
    }

    draw();

    document.getElementById("deck-recent-clear").addEventListener("click", function () {
        /* asks first: these decks live nowhere else and one may carry a session's
           worth of swaps. create() refuses to drop even one old deck to make
           room, so binning all ten on an unanswered click would be two different
           sites */
        var n = read().length;
        if (n && !confirm("Forget all " + n + " saved deck" + (n === 1 ? "" : "s") +
                          "? They are only in this browser, so this cannot be undone.")) {
            return;
        }
        clear();
        draw();
    });
})();

/*
    THE FULL SHELF, REFUSED HERE, before the deck is read rather than on the page
    afterwards.

    BOTH ways in are guarded, because both read a deck: the importer and the
    paste box
*/
(function () {
    var note = document.getElementById("deck-full");
    if (!note) return;

    document.querySelectorAll(".deck-import, .deck-paste").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            if (!full()) return;
            e.preventDefault();
            note.hidden = false;
            note.scrollIntoView({block: "nearest", behavior: "smooth"});
        });
    });
})();
