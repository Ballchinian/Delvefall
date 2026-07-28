//the change blocks on /deck/view.
//
//the cards on that page are server rendered, because the server knows what a
//decklist holds. what CHANGED is a different kind of fact: a swap session never
//reaches the server, so the only record of it is the shelf in this browser.
//that is why these blocks arrive empty and are filled in here, and why a deck
//opened in a browser that never swapped it correctly shows nothing.
//
//the drawing itself is js/changes.js, shared with the end of /deck/swap. this
//file is now only the two things that are this page's own: finding the shelf
//entry, and putting a card back.
//
//IT WRITES TO THE SHELF NOW, and that is a deliberate reversal. it used to only
//read, on the reasoning that reaching this page is not an event in a deck's
//history. putting a card back IS an event, and it was offered on the swap page
//and nowhere else, which meant the only way to undo a swap you regretted was to
//still be standing in the session that made it.

import { paintChanges, rebuild, addedList } from "changes";
import { el, pairCard } from "dom";

(function () {
    var dataEl = document.getElementById("deck-view-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);
    var KEY = "delvefall_recent_decks";

    /* the shelf is keyed on the list a deck was IMPORTED as. this page may be
       holding a list that has moved on since, so the origin is what to look
       up, exactly as the swap tool does */
    var key = D.origin || D.text;
    var entry = null;
    try {
        var decks = JSON.parse(localStorage.getItem(KEY)) || [];
        for (var i = 0; i < decks.length; i++) {
            if (decks[i].text === key) { entry = decks[i]; break; }
        }
    } catch (e) {
        /* storage off, private browsing, or a full quota. the cards above are
           server rendered and unaffected, so the page is still the page */
    }

    /*
        a card this deck GAINED, marked where it sits in the deck grid.

        deliberately just a star and a tooltip. the swap tool briefly redrew
        these tiles as full result cards, with the match percent, the verdicts
        and the matched line on them, and that was the wrong trade: one tile in
        a hundred wearing four extra rows is the grid shouting about the least
        interesting thing on it, and the swaps have their own section directly
        above with the pairs in it. this is a footnote, so it reads like one.

        matched on the card id where the shelf has one and on the NAME where it
        does not: entries written before the id was stored are still on people's
        shelves, and a deck that silently stops marking its swaps is worse than
        one matched slightly loosely. names in a deck grid are unique anyway,
        since it draws the distinct cards
    */
    function markSwapped(swaps) {
        var grid = document.querySelector(".deck-card-fold .deck-card-grid");
        if (!grid) return;
        var byOid = {}, byName = {};
        swaps.forEach(function (s) {
            if (s["in"].oracle_id) byOid[s["in"].oracle_id] = s.out.name;
            byName[s["in"].name] = s.out.name;
        });
        Array.prototype.forEach.call(grid.children, function (tile) {
            var name = tile.querySelector(".card-name");
            if (!name) return;
            /* redrawn from scratch every paint, because a revert takes a mark
               off as surely as a swap puts one on */
            var had = tile.querySelector(".deck-card-swapped");
            if (had) had.remove();
            var was = byOid[tile.dataset.oid] || byName[name.textContent];
            if (!was) return;
            el("span", "deck-card-swapped", name.parentNode, "*").title =
                "swapped in for " + was;
        });
    }

    /*
        put a card back, from the page that is only looking at the deck.

        the list is rebuilt from the deck as IMPORTED rather than patched out of
        the one on screen: undoing a swap means the list without it, and taking
        the card out of the current list would leave the one it replaced missing
        from a deck that is meant to have it back.

        entry.text is the shelf key, which is the imported list. that is what
        makes this possible here at all.
    */
    /* the grid is SERVER rendered, from the list this page was posted, so the
       tile for a reverted card is showing the card that is no longer in the
       deck. the shelf keeps both sides of a swap whole, which is exactly enough
       to draw the one coming back, and it is drawn by the same builder every
       other card on the site goes through */
    function restoreTile(s) {
        var grid = document.querySelector(".deck-card-fold .deck-card-grid");
        if (!grid) return;
        var tile = null;
        Array.prototype.forEach.call(grid.children, function (t) {
            var n = t.querySelector(".card-name");
            if (!n) return;
            if ((s["in"].oracle_id && t.dataset.oid === s["in"].oracle_id) ||
                n.textContent === s["in"].name) tile = t;
        });
        if (!tile) return;
        var fresh = pairCard(s.out);
        fresh.dataset.oid = s.out.oracle_id || "";
        /* whether it is past the first batch is a fact about its POSITION, and
           the position has not changed */
        if (tile.classList.contains("is-over")) fresh.classList.add("is-over");
        tile.replaceWith(fresh);
        enhanceCardFrames(grid);
    }

    function revert(i) {
        if (!entry) return;
        restoreTile(entry.swaps[i]);
        entry.swaps.splice(i, 1);
        entry.newList = rebuild(entry.text, entry.swaps);
        entry.added = addedList(entry.swaps);
        entry.at = Date.now();
        try {
            var all = JSON.parse(localStorage.getItem(KEY)) || [];
            all.forEach(function (x) {
                if (x.text !== key) return;
                x.swaps = entry.swaps;
                x.newList = entry.newList;
                x.added = entry.added;
                x.at = entry.at;
            });
            localStorage.setItem(KEY, JSON.stringify(all));
        } catch (e) {
            /* the page still shows the undo, it just will not survive a
               reload. failing loudly here would be worse: the swap is already
               gone from the screen */
        }
        draw();
    }

    function draw() {
        var swaps = (entry && entry.swaps) || [];
        paintChanges({
            swaps: swaps,
            added: entry ? entry.added : "",
            newList: entry ? entry.newList : "",
            text: entry ? entry.text : D.text,
            goal: entry ? entry.goal : ""
        }, {
            onRevert: entry ? revert : null,
            /* this page's own sentence, and the reason the note exists at all.
               somebody arriving here may not have made these swaps five minutes
               ago, so the deck being different from the one they imported is
               news rather than a recap */
            note: swaps.length
                ? swaps.length + " card" + (swaps.length === 1 ? " has" : "s have")
                  + " been changed since this deck was imported"
                  + (entry && entry.goal ? ", making it " + entry.goal : "") + "."
                : ""
        });
        markSwapped(swaps);
    }

    draw();
})();
