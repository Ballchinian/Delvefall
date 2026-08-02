//the standings on /deck/read and /precons/<slug>. loaded with defer, so it runs
//after the dom is parsed. the iife is redundant in a file of its own and is kept
//so this stayed a move out of partials/standing_js.html rather than a rewrite
(function () {
    /*
        two independent controls: "rank by" picks WHICH number, "from the" picks
        WHICH END of it. both are pills, the same ones /precons draws as links,
        so the two pages pick a measurement the same way.

        everything is already in the page and NOTHING is fetched, which is what
        keeps it readable with no script at all. /deck/read has no url to fetch
        from anyway
    */
    var sorts = document.getElementById("deck-sorts");
    var endsNav = document.getElementById("deck-ends");
    var panels = Array.prototype.slice.call(document.querySelectorAll(".deck-metric"));
    if (!panels.length) return;

    var swapEl = document.getElementById("deck-swap-axes");
    var swaps = swapEl ? JSON.parse(swapEl.textContent) : null;
    var swapAxis = document.querySelector('#deck-swap-start select[name="goal"]');

    /* here rather than in the dom, so a panel keeps its state while hidden
       behind another one */
    var ends = {}, shown = {};

    function lists(panel) {
        return [panel.querySelector(".deck-cards"),
                panel.querySelector(".deck-card-grid")].filter(Boolean);
    }

    /*
        the flipped reading is the SAME cards backwards, so this MOVES nodes
        rather than the page carrying a second copy of every list: five duplicated
        card lists took a 388kb page to 750kb.

        reordered in the dom and not with css order, because the names list is a
        multi-column layout and order does nothing inside one
    */
    function paint(panel) {
        var end = ends[panel.id], n = shown[panel.id];
        lists(panel).forEach(function (box) {
            var kids = Array.prototype.slice.call(box.children);
            /* sorted by the index it was RENDERED with, so a flip and a flip
               back land exactly where they began */
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

    /* ONE row for all five panels, so its labels are whichever panel is on
       screen. .on is a colour, so pressed is the only reading of it that carries */
    function markEnds(panel) {
        if (!endsNav || panel !== panels[at]) return;
        var end = ends[panel.id] || "desc";
        endsNav.querySelectorAll(".deck-end").forEach(function (b) {
            var mine = b.dataset.end === end;
            b.textContent = b.dataset.end === "asc" ? panel.dataset.labelAsc
                                                    : panel.dataset.label;
            b.classList.toggle("on", mine);
            b.setAttribute("aria-pressed", mine ? "true" : "false");
        });
    }

    function setEnd(panel, end) {
        ends[panel.id] = end;
        panel.querySelectorAll(".deck-reading").forEach(function (r) {
            r.hidden = r.dataset.end !== end;
        });
        markEnds(panel);
        /* the heading follows the end: the cheapest cards in a deck are not "the
           priciest cards" read upside down */
        var head = panel.querySelector(".deck-cards-head");
        if (head) head.textContent = end === "asc" ? head.dataset.labelAsc : head.dataset.label;
        paint(panel);
        offer();
    }

    /* points AWAY from the end on screen: "saltiest" offers to make the deck
       milder. a reading with no axis (either end of originality) leaves the
       picker alone rather than approximating one, so the row is never missing
       and a hand-picked axis is never overwritten by paging past it */
    function offer() {
        if (!swaps || !swapAxis) return;
        var panel = panels[at];
        var end = ends[panel.id] || "desc";
        var reading = panel.querySelector('.deck-reading[data-end="' + end + '"]');
        var link = reading ? reading.querySelector(".deck-board-link a") : null;
        var sortKey = link ? (link.getAttribute("href").split("sort=")[1] || "") : "";
        var s = swaps[sortKey];
        if (!s) return;
        swapAxis.value = s.axis + ":" + s.dir;
        //js/ways.js writes the go line off this, so the sentence has one author
        swapAxis.dispatchEvent(new Event("change", {bubbles: true}));
    }

    var at = 0;
    var host = document.querySelector("[data-opened]");
    /* the sort the visitor clicked through from, so landing off the salt board
       opens on salt */
    var opened = host ? host.dataset.opened : "";
    panels.forEach(function (s, i) { if (s.id === "metric-" + opened) at = i; });

    /* up with the other controls, but money only: the other four readings do not
       change with it. it renders VISIBLE, so a page with no script running keeps
       it alongside the price panel it belongs to */
    var money = document.getElementById("deck-money");

    function go(i) {
        /* wraps: the arrow keys still walk them, and a dead key at either end
           reads as a broken control */
        at = (i + panels.length) % panels.length;
        panels.forEach(function (s, n) { s.hidden = n !== at; });
        if (money) money.hidden = panels[at].id !== "metric-price";
        if (sorts) sorts.querySelectorAll(".deck-sort").forEach(function (b) {
            var mine = b.dataset.panel === panels[at].id;
            b.classList.toggle("on", mine);
            b.setAttribute("aria-pressed", mine ? "true" : "false");
        });
        markEnds(panels[at]);
        /* NOTHING here scrolls: pulling the controls to the top moved the page
           out from under the cursor, so pressing the same chip twice needed the
           mouse moved in between */
        offer();
    }

    /* all of them before any is shown, so arrowing away and back finds a panel
       as it was left */
    panels.forEach(function (panel) {
        var namesBox = panel.querySelector(".deck-cards");
        var step = (namesBox && parseInt(namesBox.dataset.step, 10)) || 12;
        shown[panel.id] = step;
        //the steps differ per panel, so the ends row asks the panel on screen
        panel.dataset.step = step;
        setEnd(panel, "desc");

        var more = panel.querySelector(".deck-card-more-btn");
        if (more) more.addEventListener("click", function () {
            /* clamped, same reason as cardfold.js: a press past the last card is
               a no-op and not a negative */
            var have = (panel.querySelector(".deck-card-grid") || {children: []}).children.length;
            shown[panel.id] = Math.min(shown[panel.id] + step, have);
            paint(panel);
            /* enhanceCardFrames marks what it has done, so this is free */
            enhanceCardFrames(panel);
        });

        /* the names list SHARES this count and its only control lives inside the
           fold, so without a reset here closing the pictures left the names
           expanded with nothing left on screen able to shrink them */
        var open = panel.querySelector(".deck-card-open");
        if (open) open.addEventListener("toggle", function () {
            if (open.open || shown[panel.id] === step) return;
            shown[panel.id] = step;
            paint(panel);
        });
    });

    /* the ends row is ONE row for five panels, so it is wired once and reads the
       panel on screen rather than being wired per panel */
    if (endsNav) {
        endsNav.querySelectorAll(".deck-end").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var panel = panels[at];
                /* twelve cards into the priciest end is not twelve into the
                   cheapest */
                shown[panel.id] = parseInt(panel.dataset.step, 10) || 12;
                setEnd(panel, btn.dataset.end);
            });
        });
        endsNav.hidden = false;
    }

    if (sorts && panels.length > 1) {
        sorts.querySelectorAll(".deck-sort").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var to = panels.findIndex(function (p) { return p.id === btn.dataset.panel; });
                if (to > -1) go(to);
            });
        });

        /* the arrow keys walk them too, but never while somebody is typing */
        document.addEventListener("keydown", function (e) {
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            var t = e.target;
            if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
            if (e.key === "ArrowLeft") { go(at - 1); }
            else if (e.key === "ArrowRight") { go(at + 1); }
            else return;
            e.preventDefault();
        });
        sorts.hidden = false;
    }
    go(at);
})();
