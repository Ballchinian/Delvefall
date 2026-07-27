//the standings on /deck/read and /precons/<slug>. moved out of
//partials/standing_js.html unchanged: same code, same sloppy-mode
//semantics, loaded with defer so it still runs after the dom is parsed.
//the iife it is wrapped in is redundant in a file of its own and is kept
//so this stayed a move rather than a rewrite
(function () {
    /*
        the standings. two controls, and they are independent: the arrows pick
        WHICH number, the "from the" buttons pick WHICH END of it.

        everything is already in the page. the arrows hide four panels and show
        the fifth, and the end buttons swap which of two standings is visible
        and reverse the card list in place. nothing is fetched, which is what
        keeps the page readable with no script at all: a crawler meets all five
        standings of a precon, and /deck/read has no url to fetch from anyway.
    */
    var pager = document.getElementById("deck-pager");
    var panels = Array.prototype.slice.call(document.querySelectorAll(".deck-metric"));
    if (!panels.length) return;

    var swapEl = document.getElementById("deck-swap-axes");
    var swaps = swapEl ? JSON.parse(swapEl.textContent) : null;
    var swapForm = document.getElementById("deck-swap-start");
    var changeBox = document.getElementById("deck-change");

    /* which end each panel is being read from, and how many of its cards are
       on screen. both live here rather than in the dom so a panel keeps its
       state while it is hidden behind another one */
    var ends = {}, shown = {};

    function lists(panel) {
        return [panel.querySelector(".deck-cards"),
                panel.querySelector(".deck-card-grid")].filter(Boolean);
    }

    /*
        show the first N of the list as it reads from the active end.

        the flipped reading is the SAME cards backwards, so this moves the
        nodes rather than the page carrying a second copy of every list: five
        duplicated card lists took a 388kb page to 750kb.

        the reordering is done in the DOM and not with css order, because the
        names list is a multi-column layout and order does nothing inside one.
        appendChild moves a node it is already holding, so this is a reshuffle
        rather than a rebuild and nothing is recreated or refetched
    */
    function paint(panel) {
        var end = ends[panel.id], n = shown[panel.id];
        lists(panel).forEach(function (box) {
            var kids = Array.prototype.slice.call(box.children);
            /* back to the order it was rendered in, then reversed if the far
               end is the one being read. sorting by the index it was rendered
               with means a flip and a flip back land exactly where they began */
            kids.sort(function (a, b) { return (+a.dataset.i) - (+b.dataset.i); });
            if (end === "asc") kids.reverse();
            kids.forEach(function (el, rank) {
                box.appendChild(el);
                el.classList.toggle("is-over", rank >= n);
            });
        });
        var more = panel.querySelector(".deck-card-more");
        if (more) {
            var grid = panel.querySelector(".deck-card-grid");
            var left = (grid ? grid.children.length : 0) - n;
            more.hidden = left <= 0;
            var label = more.querySelector(".deck-card-more-left");
            if (label) label.textContent = left > 0 ? left + " more" : "";
        }
    }

    function setEnd(panel, end) {
        ends[panel.id] = end;
        panel.querySelectorAll(".deck-reading").forEach(function (r) {
            r.hidden = r.dataset.end !== end;
        });
        panel.querySelectorAll(".deck-end").forEach(function (b) {
            b.classList.toggle("on", b.dataset.end === end);
        });
        /* the heading over the evidence follows the end too: the cheapest
           cards in a deck are not "the priciest cards" read upside down */
        var head = panel.querySelector(".deck-cards-head");
        if (head) head.textContent = end === "asc" ? head.dataset.labelAsc : head.dataset.label;
        paint(panel);
        offer();
    }

    /*
        what "change it" proposes, off the reading on screen. it points AWAY
        from the end being shown, because that is the useful direction:
        "saltiest" offers to make the deck milder, "cheapest" offers pricier.
        a reading with no axis (either end of originality) hides the block
        rather than approximating one
    */
    function offer() {
        if (!swaps || !swapForm || !changeBox) return;
        var panel = panels[at];
        var end = ends[panel.id] || "desc";
        var reading = panel.querySelector('.deck-reading[data-end="' + end + '"]');
        var link = reading ? reading.querySelector(".deck-board-link a") : null;
        var sortKey = link ? (link.getAttribute("href").split("sort=")[1] || "") : "";
        var s = swaps[sortKey];
        changeBox.hidden = !s;
        if (s) {
            swapForm.elements.axis.value = s.axis;
            swapForm.elements.dir.value = s.dir;
            swapForm.querySelector("button").textContent = "Make this deck " + s.goal;
        }
    }

    var at = 0;
    var host = document.querySelector("[data-opened]");
    /* which one the page was opened on: the sort the visitor clicked through
       from, so landing here off the salt board opens on salt rather than on a
       number nobody asked about */
    var opened = host ? host.dataset.opened : "";
    panels.forEach(function (s, i) { if (s.id === "metric-" + opened) at = i; });

    function go(i) {
        /* wraps, because five panels behind two arrows is a ring and a dead
           arrow at either end is a control that looks broken */
        at = (i + panels.length) % panels.length;
        panels.forEach(function (s, n) { s.hidden = n !== at; });
        var end = ends[panels[at].id] || "desc";
        document.getElementById("deck-pager-now").textContent =
            end === "asc" ? panels[at].dataset.labelAsc : panels[at].dataset.label;
        /*
            NOTHING here scrolls. it used to pull the pager to the top of the
            viewport, which moved the page under a cursor resting on an arrow,
            so pressing the same arrow twice needed the mouse moved in between.
            the arrows are already on screen by definition, since you just
            clicked one
        */
        offer();
    }

    /* set every panel up before any of them is shown, so flipping an end on
       one and arrowing away and back finds it as it was left */
    panels.forEach(function (panel) {
        var namesBox = panel.querySelector(".deck-cards");
        var step = (namesBox && parseInt(namesBox.dataset.step, 10)) || 12;
        shown[panel.id] = step;
        setEnd(panel, "desc");

        panel.querySelectorAll(".deck-end").forEach(function (btn) {
            btn.addEventListener("click", function () {
                /* back to the top of the list: twelve cards into the priciest
                   end is not twelve cards into the cheapest one */
                shown[panel.id] = step;
                setEnd(panel, btn.dataset.end);
                if (panel === panels[at]) {
                    var end = ends[panel.id];
                    document.getElementById("deck-pager-now").textContent =
                        end === "asc" ? panel.dataset.labelAsc : panel.dataset.label;
                }
            });
        });

        var more = panel.querySelector(".deck-card-more-btn");
        if (more) more.addEventListener("click", function () {
            /* clamped to the grid, same reason as cardfold.js: a press that
               lands after the last card should be a no-op, not a negative */
            var have = (panel.querySelector(".deck-card-grid") || {children: []}).children.length;
            shown[panel.id] = Math.min(shown[panel.id] + step, have);
            paint(panel);
            /* the frames that just appeared need wiring. enhanceCardFrames
               marks what it has already done, so calling it again is free */
            enhanceCardFrames(panel);
        });

        /* closing the fold puts the count back to the first batch.
           without this, "View more card images" was a one way door: it lives INSIDE
           the fold and the names list above shares its count, so opening the
           pictures, revealing another twelve and closing again left the names
           list expanded with the only control that could shrink it now hidden.
           the cards retracted and their names did not */
        var open = panel.querySelector(".deck-card-open");
        if (open) open.addEventListener("toggle", function () {
            if (open.open || shown[panel.id] === step) return;
            shown[panel.id] = step;
            paint(panel);
        });
    });

    if (pager && panels.length > 1) {
        document.getElementById("deck-prev").addEventListener("click", function () { go(at - 1); });
        document.getElementById("deck-next").addEventListener("click", function () { go(at + 1); });

        /* the arrow keys walk them too, the same way they walk the suggestion
           list, but never while somebody is typing in a box */
        document.addEventListener("keydown", function (e) {
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            var t = e.target;
            if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
            if (e.key === "ArrowLeft") { go(at - 1); }
            else if (e.key === "ArrowRight") { go(at + 1); }
            else return;
            e.preventDefault();
        });
        pager.hidden = false;
    }
    go(at);
})();
