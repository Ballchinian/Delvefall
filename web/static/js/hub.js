//the saved decks list on /deck: names kept in this browser only, drawn
//back as a list you can reopen, rename, drop or export. moved out of
//templates/deck/hub.html, which had no jinja in it at all, so this is a
//straight relocation minus its own copy of el

import { el } from "dom";
import { read, write, uniqueName, dedupe, KEY } from "decks";

(function () {
    var box = document.getElementById("deck-recent");
    var list = document.getElementById("deck-recent-list");
    if (!box || !list) return;

    /* shelves written before deck names had to be distinct can hold two decks
       called the same thing, and a rule that only applies to new ones leaves
       those there for good. this numbers the clashes once, on the first visit
       after the rule arrived, keeping the earliest of each name as it is */
    var fixed = dedupe(read());
    if (fixed) write(fixed);

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
                var all = read();
                /* two decks on this shelf cannot share a name, and renaming was
                   the way round that: type "Goblins" over a second deck and you
                   had two. it goes through the same rule the modes page names a
                   deck with, so a clash is numbered rather than allowed.
                   d.text is passed as "mine" so a deck keeping its own name is
                   not numbered against itself */
                var name = uniqueName(now, all, d.text);
                /* matched by TEXT, never by position: the list may have been
                   rewritten in another tab since this row was drawn */
                all.forEach(function (x) { if (x.text === d.text) x.label = name; });
                write(all);
                draw();
                if (name !== now.trim() && name) {
                    /* say so rather than silently filing it under another name.
                       it is the only moment the shelf overrules what was typed */
                    window.alert("You already have a deck called " + now.trim()
                                 + ", so this one is " + name + ".");
                }
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
