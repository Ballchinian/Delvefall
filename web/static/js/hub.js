//the saved decks list on /deck: names kept in this browser only, drawn
//back as a list you can reopen, rename, drop or export. moved out of
//templates/deck/hub.html, which had no jinja in it at all, so this is a
//straight relocation minus its own copy of el

import { el } from "dom";

(function () {
    var KEY = "delvefall_recent_decks";
    var box = document.getElementById("deck-recent");
    var list = document.getElementById("deck-recent-list");
    if (!box || !list) return;

    function read() {
        try { return JSON.parse(localStorage.getItem(KEY)) || []; }
        catch (e) { return []; }
    }

    function write(decks) {
        try { localStorage.setItem(KEY, JSON.stringify(decks)); } catch (e) {}
    }

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
            el("span", "deck-recent-meta", li, d.count + " cards");

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
