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

    /* one card in a swap pair. the same shape the swap tool draws, because it
       is the same card being shown for the same reason */
    function pairCard(c) {
        var div = document.createElement("div");
        div.className = "result";
        var frame = el("div", "card-frame", div);
        frame.dataset.sideways = c.sideways ? "1" : "";
        frame.dataset.flip = c.flip ? "1" : "";
        frame.dataset.back = c.image_back || "";
        var a = el("a", "", frame);
        a.href = "/search?q=" + encodeURIComponent(c.name);
        a.dataset.card = c.name;
        if (c.scryfall_uri) a.dataset.scryfall = c.scryfall_uri;
        a.title = "search " + c.name + " here. ctrl-click to open it on scryfall";
        var img = el("img", "", a);
        img.src = c.image;
        img.alt = c.name;
        img.width = 488;
        img.height = 680;
        img.loading = "lazy";
        el("div", "result-name", div, c.name);
        if (c.price || c.rank || c.salt) {
            var row = el("div", "result-price", div);
            if (c.price) el("span", "price-figure", row, c.price);
            if (c.rank) el("span", "result-rank", row, c.rank);
            if (c.salt) el("span", "result-salt", row, c.salt);
        }
        return div;
    }

    function copyBox(parent, heading, note, value, label) {
        el("h3", "deck-recent-panel-head", parent, heading);
        el("p", "deck-hub-note", parent, note);
        var ta = el("textarea", "swap-output swap-output-short", parent);
        ta.readOnly = true;
        ta.rows = 6;
        ta.value = value || "";
        var actions = el("div", "swap-actions", parent);
        var btn = el("button", "swap-copy", actions, label);
        btn.type = "button";
        btn.addEventListener("click", function () {
            ta.select();
            navigator.clipboard.writeText(ta.value).then(function () {
                btn.textContent = "Copied";
            }).catch(function () { btn.textContent = "Press Ctrl+C"; });
        });
    }

    /*
        what a swap session left behind, opened under its own deck.

        it is rendered HERE rather than on a page of its own because there is
        no page of its own to render: none of this ever reached the server, so
        there is nothing for a url to point at. the panel is the honest shape
        for data that only exists on this machine
    */
    function panel(d) {
        var box = document.createElement("li");
        box.className = "deck-recent-panel";
        var swaps = d.swaps || [];

        el("p", "deck-hub-note", box, swaps.length
           ? swaps.length + " swap" + (swaps.length === 1 ? "" : "s")
             + (d.goal ? ", making it " + d.goal : "") + "."
           : "Nothing has been changed in this deck yet, so what is below is the "
             + "list exactly as it came in.");

        var made = el("ul", "swap-made", box);
        swaps.forEach(function (s) {
            var li = el("li", "swap-made-row", made);
            var out = el("a", "swap-made-out", li, s.out.name);
            out.href = "/search?q=" + encodeURIComponent(s.out.name);
            out.dataset.card = s.out.name;
            el("span", "swap-made-arrow", li, "→");
            var into = el("a", "swap-made-in", li, s["in"].name);
            into.href = "/search?q=" + encodeURIComponent(s["in"].name);
            into.dataset.card = s["in"].name;
        });

        var pics = el("details", "deck-card-open", box);
        pics.hidden = !swaps.length;
        el("summary", "", pics, "Show the swaps as cards");
        var pairs = el("div", "swap-pairs", pics);
        swaps.forEach(function (s) {
            var row = el("div", "swap-pair", pairs);
            var left = el("div", "swap-pair-side swap-pair-out", row);
            el("span", "swap-pair-label", left, "Out");
            left.appendChild(pairCard(s.out));
            el("div", "swap-pair-arrow", row, "→");
            var right = el("div", "swap-pair-side swap-pair-in", row);
            el("span", "swap-pair-label", right, "In");
            right.appendChild(pairCard(s["in"]));
        });
        /* the frames only exist once the details has been built, and
           enhanceCardFrames marks what it has done, so this is safe to call
           on a panel that may be opened and closed repeatedly */
        pics.addEventListener("toggle", function () {
            if (pics.open) enhanceCardFrames(pics);
        });

        if (d.added) {
            copyBox(box, "Just the new cards",
                    "The cards this session added, on their own. Paste these in rather than "
                    + "reimporting the whole deck and losing the categories you have set up.",
                    d.added, "Copy the new cards");
        }
        if (d.newList) {
            copyBox(box, "The whole new list",
                    "Your original list with the swaps applied. This is what reopening "
                    + "this deck picks up from.", d.newList, "Copy the list");
        }
        /* always last, and always there. checking that an import arrived whole
           is the other reason to open a deck, and until now the only way to do
           it was to reopen the deck and count the cards on the reading */
        copyBox(box, d.newList ? "The list as imported" : "The list",
                d.newList
                    ? "Before any swaps, kept so a session can always be compared "
                      + "against where the deck started."
                    : "Every line this deck was read from, to check it arrived whole.",
                d.text, "Copy the original");
        return box;
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
            {
                var view = el("button", "deck-recent-tool", tools, "⇱");
                view.type = "button";
                view.title = (d.swaps && d.swaps.length)
                    ? "view and export this deck and the " + d.swaps.length + " swap"
                      + (d.swaps.length === 1 ? "" : "s") + " saved for it"
                    : "view and export the cards in this deck";
                view.setAttribute("aria-label", "view and export " + (d.label || "this deck"));
                view.addEventListener("click", function () {
                    var open = li.nextElementSibling;
                    if (open && open.classList.contains("deck-recent-panel")) {
                        open.remove();
                        return;
                    }
                    li.after(panel(d));
                });
            }

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
