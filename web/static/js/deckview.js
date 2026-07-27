//the change blocks on /deck/view.
//
//the cards on that page are server rendered, because the server knows what a
//decklist holds. what CHANGED is a different kind of fact: a swap session never
//reaches the server, so the only record of it is the shelf in this browser.
//that is why these blocks arrive empty and are filled in here, and why a deck
//opened in a browser that never swapped it correctly shows nothing.
//
//it reads the shelf and never writes to it. reaching this page is not an event
//in a deck's history, so nothing about it belongs in the record

import { el, cardLink, pairCard, swapPair, fitText } from "dom";

(function () {
    var dataEl = document.getElementById("deck-view-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);
    var KEY = "delvefall_recent_decks";
    var $ = function (id) { return document.getElementById(id); };

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

    function wireCopy(btnId, boxId) {
        var btn = $(btnId);
        if (!btn) return;
        btn.addEventListener("click", function () {
            var out = $(boxId);
            out.select();
            navigator.clipboard.writeText(out.value).then(function () {
                btn.textContent = "Copied";
            }).catch(function () { btn.textContent = "Press Ctrl+C"; });
        });
    }
    wireCopy("deck-copy-list", "deck-list");
    wireCopy("deck-copy-added", "deck-added");

    /* what the shelf remembers about this deck, painted onto the empty blocks.
       it was the rest of this function and is now a named one, so the sizing
       below can run whether or not there was anything to paint */
    function fillIn() {
    var swaps = entry.swaps || [];
    if (swaps.length) {
        $("deck-changed-note").textContent =
            swaps.length + " card" + (swaps.length === 1 ? " has" : "s have")
            + " been changed since this deck was imported"
            + (entry.goal ? ", making it " + entry.goal : "") + ".";
        var list = $("deck-changed-list");
        var pairs = $("deck-changed-pairs");
        swaps.forEach(function (s) {
            var li = el("li", "swap-made-row", list);
            cardLink(s.out.name, "swap-made-out", li);
            el("span", "swap-made-arrow", li, "→");
            cardLink(s["in"].name, "swap-made-in", li);

            swapPair(pairs, s, pairCard);
        });
        /* the frames only exist once the fold has been built, and
           enhanceCardFrames marks what it has done, so opening and closing it
           repeatedly is safe */
        var pics = $("deck-changed-pics");
        pics.addEventListener("toggle", function () {
            if (pics.open) enhanceCardFrames(pics);
        });
        $("deck-changed").hidden = false;
    }

    /*
        a card this deck GAINED, marked where it sits in the deck grid.

        deliberately just a star and a tooltip. the swap tool briefly redrew
        these tiles as full result cards, with the match percent, the verdicts
        and the matched line on them, and that was the wrong trade: one tile in
        a hundred wearing four extra rows is the grid shouting about the least
        interesting thing on it, and "what changed" already has its own section
        directly above with the pairs in it. this is a footnote, so it reads
        like one.

        matched on the card id where the shelf has one and on the NAME where it
        does not: entries written before the id was stored are still on people's
        shelves, and a deck that silently stops marking its swaps is worse than
        one matched slightly loosely. names in a deck grid are unique anyway,
        since it draws the distinct cards
    */
    function markSwapped(swaps) {
        var grid = document.querySelector(".deck-card-fold .deck-card-grid");
        if (!grid || !swaps.length) return;
        var byOid = {}, byName = {};
        swaps.forEach(function (s) {
            if (s["in"].oracle_id) byOid[s["in"].oracle_id] = s.out.name;
            byName[s["in"].name] = s.out.name;
        });
        Array.prototype.forEach.call(grid.children, function (tile) {
            var name = tile.querySelector(".card-name");
            if (!name) return;
            var was = byOid[tile.dataset.oid] || byName[name.textContent];
            if (!was) return;
            el("span", "deck-card-swapped", name.parentNode, "*").title =
                "swapped in for " + was;
        });
    }
    markSwapped(swaps);

    if (entry.added) {
        $("deck-added").value = entry.added;
        $("deck-added-box").hidden = false;
    }

    /* the list this page is holding is the deck as it stands, not as it was
       imported, whenever a session has moved it on */
    if (entry.newList) $("deck-list").value = entry.newList;

    /* the list on the page is whatever this deck is holding now. say so when
       that is not what was imported, because "the whole list" is ambiguous on
       a deck that has been changed and the difference is the whole point of
       having opened this page */
    if (entry.newList && entry.newList !== entry.text) {
        $("deck-list-note").textContent =
            "The deck as it stands, with the swaps above applied. Ready to paste back "
            + "wherever it came from.";
    }
    }

    if (entry) fillIn();

    /* both boxes are on screen from the start now, so they size straight away:
       a textarea inside a closed details measures 0, which is the only reason
       this used to wait for a fold to open. AFTER fillIn, or a deck whose list
       has moved on gets sized to the list it replaced. the css caps the result */
    fitText($("deck-list"));
    fitText($("deck-added"));
})();
