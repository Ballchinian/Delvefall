//the saved decks panel on /deck. every deck this browser has read, each one a
//row you can reopen, rename in place, unfold the whole history of, or drop.
//
//it holds no rules about what a deck IS: decks.js owns that, and this file only
//draws it. that split is what makes the panel safe to change, and it is why the
//rename here and the rename on the modes page cannot disagree.
//
//the second half of the file is the shelf being FULL, which is the one thing
//this page refuses to do rather than draw.

import { el, cardLink } from "dom";
import { read, drop, patch, clear, full, KEEP } from "decks";

(function () {
    var box = document.getElementById("deck-recent");
    var list = document.getElementById("deck-recent-list");
    if (!box || !list) return;

    /* a dedupe() ran here, renumbering any two decks that shared a name on the
       first visit after the numbering rule arrived. it is gone with the rest of
       the numbering: a shelf carrying two decks called the same thing is only
       an eyesore, because NOTHING ON THIS SITE FINDS A DECK BY ITS NAME. every
       lookup is by the deck's id, here and in the swap tool and on /deck/view
       alike. renaming somebody's decks on sight to fix something that was never
       broken is the worse of the two options */

    function open(d) {
        /* reopening picks up where the deck was left, so what goes back is the
           list AFTER any swaps. it used to send d.text every time, which meant
           a session's work was recorded on the shelf and then handed back
           undone, with nothing on screen to say so.

           the id rides along beside it, and that is what says WHICH saved deck
           this is. without it the deck would arrive looking like a list nobody
           had seen before and be saved a second time, which is the same deck
           twice on a shelf that only holds ten */
        document.getElementById("deck-recent-list-field").value = d.newList || d.text;
        document.getElementById("deck-recent-did-field").value = d.id;
        /* the name goes back with the list, and the commander with it. they are
           two different facts and the shelf keeps both: it used to send the
           label as the commander too, which was near enough while a deck was
           named after its commander and wrong the moment somebody renamed one.
           "Budget Krenko" is not a card, and the picker on the page that lands
           would open with it typed in and nothing matching */
        document.getElementById("deck-recent-name-field").value = d.label || "";
        document.getElementById("deck-recent-commander-field").value = d.commander || "";
        document.getElementById("deck-recent-form").submit();
    }

    /*
        every swap this deck has ever had, oldest first, which is the order they
        were made in and the same order /deck/swap and /deck/view show them.

        folded, because it is a history rather than a summary: ten decks each
        listing thirty changes would bury the one thing this panel is for, which
        is getting back into a deck. the summary line carries the count, so the
        fold is closed at exactly the size the old plain count was
    */
    function changes(li, d) {
        var swaps = d.swaps || [];
        var n = swaps.length;
        if (!n) {
            /* HOW MUCH THIS DECK HAS MOVED, not how big it is. the card count
               was the same number on every row for anybody who plays one format
               (a hundred, a hundred, a hundred) and said nothing about which
               deck you were looking at */
            el("span", "deck-recent-meta", li, "unchanged");
            return;
        }
        var fold = el("details", "deck-recent-changes", li);
        el("summary", "deck-recent-meta", fold,
           n + (n === 1 ? " change" : " changes"));
        var rows = el("ol", "deck-recent-swaps", fold);
        swaps.forEach(function (s) {
            /* localStorage is the user's own file and can be hand edited, and
               entries written by older versions of this code are still out
               there. one malformed swap should cost its own row, not the whole
               shelf below it */
            if (!s || !s.out || !s["in"]) return;
            var row = el("li", "deck-recent-swap", rows);
            row.appendChild(cardLink(s.out.name, "swap-made-out"));
            el("span", "swap-made-arrow", row, "→");
            row.appendChild(cardLink(s["in"].name, "swap-made-in"));
        });
    }

    /* the deck's name, as the button that opens it. a deck nobody has named yet
       is called after its size, which is at least a fact about it: the pen is
       right there, and an unnamed deck is not a broken row */
    function opener(d, li) {
        var btn = el("button", "deck-recent-open", li,
                     d.label || (d.count ? d.count + " cards" : "Unnamed deck"));
        btn.type = "button";
        btn.addEventListener("click", function () { open(d); });
        return btn;
    }

    /* what the two tools say they will do, which is the deck's name and so
       moves when the name does. read out loud by a screen reader on a row where
       every other row has the same two glyphs on it */
    function relabel(li, d) {
        var name = d.label || "this deck";
        li.querySelectorAll(".deck-recent-tool").forEach(function (t) {
            t.setAttribute("aria-label",
                (t.classList.contains("deck-recent-drop") ? "forget " : "rename ") + name);
        });
    }

    /*
        rename in place, as you type, which is the same rule the modes page
        follows for the same box.

        it was a window.prompt, and a prompt is a modal dialog for one text
        field: it stops the page, it looks like the browser asking rather than
        the site, and what you typed only landed if you found the right button.
        this lands on every letter.

        only the ONE ROW is put back on the way out, rather than the list being
        redrawn. a redraw would delete every other row's buttons in the middle of
        the click that dismissed this box, so clicking straight from renaming one
        deck to forgetting another did nothing at all the first time
    */
    function rename(li, d) {
        var was = li.querySelector(".deck-recent-open");
        if (!was) return;
        /* what it was called when the box opened, which is the only thing
           escape can mean here: every letter has already been saved, so there
           is no draft to throw away, only a name to put back */
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
            /* el appends, and the name belongs at the top of the row. prepend
               on a node already in the parent moves it rather than copying it */
            li.prepend(opener(d, li));
            relabel(li, d);
        }

        field.addEventListener("input", function () {
            /* whatever was typed, including a name another deck already has.
               see decks.js for the three rules this went through and why none
               of them earned their keep: the name is a label, and nothing on
               this site finds a deck by one */
            d.label = field.value.trim();
            patch(d.id, {label: d.label});
        });
        field.addEventListener("blur", done);
        field.addEventListener("keydown", function (e) {
            /* enter and escape both mean "done", because there is nothing to
               cancel: every letter is already saved. they differ only in that
               escape puts the old name back */
            if (e.key === "Enter") field.blur();
            if (e.key === "Escape") {
                d.label = before;
                patch(d.id, {label: before});
                field.blur();
            }
        });
    }

    /*
        the list, drawn from scratch each time it changes. rebuilding rather
        than patching rows is the right trade at ten entries: one path that is
        always right beats three that have to agree with each other
    */
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

            /* renaming is what makes this a shelf rather than a history. a deck
               called after its commander is the site's guess, and the person
               who built it knows whether it is the budget one */
            var ren = el("button", "deck-recent-tool", tools, "✎");
            ren.type = "button";
            ren.title = "rename this deck";
            ren.addEventListener("click", function () { rename(li, d); });

            var del = el("button", "deck-recent-tool deck-recent-drop", tools, "×");
            del.type = "button";
            del.title = "forget this deck";
            del.addEventListener("click", function () {
                /* by id, never by position or by list: two rows may hold the
                   same cards, and the shelf may have been rewritten in another
                   tab since this row was drawn */
                drop(d.id);
                draw();
            });

            relabel(li, d);
        });
    }

    /* how much room is left, said on the panel that fills up rather than only
       at the moment something is refused. it is the one number that decides
       whether the next deck can be read at all, so finding it out by being
       turned away is finding it out too late */
    var room = document.getElementById("deck-recent-room");

    function say(n) {
        if (!room) return;
        room.textContent = n >= KEEP
            ? "This is full at " + KEEP + " decks. Forget one to make room for the next."
            : n + " of " + KEEP + " saved.";
    }

    draw();

    document.getElementById("deck-recent-clear").addEventListener("click", function () {
        clear();
        draw();
    });
})();

/*
    THE FULL SHELF, REFUSED HERE.

    reading a deck saves it, so a shelf with no room is a reading that cannot be
    kept, and the honest moment to say so is before the deck is read rather than
    on the page afterwards. the alternative was the shelf silently dropping its
    oldest deck to make room, which is a save deleting a save, possibly the one
    carrying a hundred swaps.

    both ways in are guarded, because both of them read a deck: the importer and
    the paste box. the message is the page's own error line, in the place every
    other thing wrong with a paste is already reported
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
