//the saved decks list on /deck: names kept in this browser only, drawn
//back as a list you can reopen, rename, drop or export. moved out of
//templates/deck/hub.html, which had no jinja in it at all, so this is a
//straight relocation minus its own copy of el

import { el } from "dom";
import { read, write, KEY } from "decks";

(function () {
    var box = document.getElementById("deck-recent");
    var list = document.getElementById("deck-recent-list");
    if (!box || !list) return;

    /* a dedupe() ran here, renumbering any two decks that shared a name on the
       first visit after the numbering rule arrived. it is gone with the rest of
       the numbering: a shelf carrying two decks called the same thing is only
       an eyesore, because NOTHING ON THIS SITE FINDS A DECK BY ITS NAME. every
       lookup is by the decklist the deck was imported as, here and in the swap
       tool and on /deck/view alike. renaming somebody's decks on sight to fix
       something that was never broken is the worse of the two options */

    function open(d) {
        /* reopening picks up where the deck was left, so what goes back is the
           list AFTER any swaps. it used to send d.text every time, which meant
           a session's work was recorded on the shelf and then handed back
           undone, with nothing on screen to say so.

           d.text still rides along as the origin, because it is what this
           shelf is keyed on. without it the deck would arrive looking like a
           list nobody had seen before and be saved a second time as "#2",
           which is the same deck twice under two names */
        document.getElementById("deck-recent-list-field").value = d.newList || d.text;
        document.getElementById("deck-recent-origin-field").value = d.text;
        /* the name goes back with the list. the commander is the name without
           the "#2" a repeat picked up here, since the numbering belongs to
           this list and not to the deck */
        document.getElementById("deck-recent-name-field").value = d.label || "";
        document.getElementById("deck-recent-commander-field").value =
            (d.label || "").replace(/ #\d+$/, "");
        document.getElementById("deck-recent-form").submit();
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
        if (!decks.length) return;

        decks.forEach(function (d, i) {
            var li = el("li", "deck-recent-row", list);
            var btn = el("button", "deck-recent-open", li, d.label || (d.count + " cards"));
            btn.type = "button";
            btn.addEventListener("click", function () { open(d); });
            /* HOW MUCH THIS DECK HAS MOVED, not how big it is. the card count
               was the same number on every row for anybody who plays one format
               (a hundred, a hundred, a hundred) and said nothing about which
               deck you were looking at.
               the swaps are a running total: every change ever made to this
               list, across every session, never reset. that is what makes it
               worth a line on the shelf */
            var n = (d.swaps || []).length;
            el("span", "deck-recent-meta", li,
               n ? n + (n === 1 ? " change" : " changes") : "unchanged");

            var tools = el("span", "deck-recent-tools", li);

            /* everything a finished swap session left behind: what changed,
               and the two lists to paste back. only offered on a deck that has
               been through the swap tool, because on any other one the panel
               would open onto nothing */
            /* renaming is what makes this a shelf rather than a history. a
               deck called "Kratos, God of War #2" is the site's guess, and the
               person who built it knows whether it is the budget one */
            var ren = el("button", "deck-recent-tool", tools, "✎");
            ren.type = "button";
            ren.title = "rename this deck";
            ren.setAttribute("aria-label", "rename " + (d.label || "this deck"));
            ren.addEventListener("click", function () {
                var was = d.label || "";
                var now = window.prompt("Call this deck:", was);
                if (now === null) return;
                now = now.trim();
                var all = read();
                /* whatever was typed, including a name another deck already
                   has. see decks.js for the three rules this went through and
                   why none of them earned their keep: the name is a label, and
                   nothing on this site finds a deck by one */
                /* matched by TEXT, never by position: the list may have been
                   rewritten in another tab since this row was drawn */
                all.forEach(function (x) { if (x.text === d.text) x.label = now; });
                write(all);
                draw();
            });

            var del = el("button", "deck-recent-tool deck-recent-drop", tools, "×");
            del.type = "button";
            del.title = "forget this deck";
            del.setAttribute("aria-label", "forget " + (d.label || "this deck"));
            del.addEventListener("click", function () {
                write(read().filter(function (x) { return x.text !== d.text; }));
                draw();
            });
        });
    }

    draw();

    document.getElementById("deck-recent-clear").addEventListener("click", function () {
        try { localStorage.removeItem(KEY); } catch (e) {}
        draw();
    });
})();
