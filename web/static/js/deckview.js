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

    /* a list box is grown to its content the first time its fold is opened.
       done on open rather than on load because a textarea inside a closed
       details has no height to measure: scrollHeight is 0 until it is on
       screen, so sizing it early sizes it to nothing */
    document.querySelectorAll(".deck-card-open").forEach(function (fold) {
        var box = fold.querySelector(".swap-output");
        if (!box) return;
        fold.addEventListener("toggle", function () {
            if (fold.open) fitText(box);
        });
    });

    if (!entry) return;

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
})();
