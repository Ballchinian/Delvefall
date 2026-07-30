//the change blocks on /deck/view.
//
//a swap session never reaches the server, so the only record of it is the shelf
//in this browser: that is why these blocks arrive empty and why a deck opened in
//a browser that never swapped it correctly shows nothing.
//
//the drawing is js/changes.js, shared with the end of /deck/swap. this file is
//the two things this page owns: finding the shelf entry, and putting a card back.
//offered here as well as on the swap page, or undoing a swap would mean still
//standing in the session that made it.

import { paintChanges, rebuild, addedList, carryList } from "changes";
import { find, patch } from "decks";
import { el, pairCard } from "dom";

(function () {
    var dataEl = document.getElementById("deck-view-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);

    /* a deck arriving without one (a precon handed straight to the lens) has no
       history, and the blocks below stay empty */
    var entry = find(D.did);

    /*
        a star and a tooltip, deliberately: the swaps have their own section
        directly above with the pairs in it, so this is a footnote.

        matched on the id where the shelf has one and on the NAME where it does
        not, because entries written before the id was stored are still on
        people's shelves. names in a deck grid are unique, it draws distinct cards
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
            /* redrawn every paint: a revert takes a mark off as surely as a swap
               puts one on */
            var had = tile.querySelector(".deck-card-swapped");
            if (had) had.remove();
            var was = byOid[tile.dataset.oid] || byName[name.textContent];
            if (!was) return;
            el("span", "deck-card-swapped", name.parentNode, "*").title =
                "swapped in for " + was;
        });
    }

    /* the grid is SERVER rendered from the list this page was posted, so the tile
       for a reverted card shows the card no longer in the deck. the shelf keeps
       both sides of a swap whole, which is enough to draw the one coming back */
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
        /* is-over is a fact about POSITION, which has not changed */
        if (tile.classList.contains("is-over")) fresh.classList.add("is-over");
        tile.replaceWith(fresh);
        enhanceCardFrames(grid);
    }

    function revert(i) {
        if (!entry) return;
        restoreTile(entry.swaps[i]);
        entry.swaps.splice(i, 1);
        /* from entry.text, the deck as IMPORTED: patching the list on screen
           would leave the card coming back missing from it */
        entry.newList = rebuild(entry.text, entry.swaps);
        entry.added = addedList(entry.swaps);
        /* only the three fields a revert changes, so a rename made in another tab
           is not written back over */
        patch(D.did, {swaps: entry.swaps, newList: entry.newList,
                      added: entry.added});
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
            /* somebody arriving here may not have made these swaps five minutes
               ago, so this is news rather than a recap */
            note: swaps.length
                ? swaps.length + " card" + (swaps.length === 1 ? " has" : "s have")
                  + " been changed since this deck was imported"
                  + (entry && entry.goal ? ", making it " + entry.goal : "") + "."
                : ""
        });
        markSwapped(swaps);
        /* the mode rows were rendered with the list this page was POSTED, so
           without this "Change it" offers a card no longer in the deck */
        carryList(entry && entry.newList);
    }

    draw();
})();
