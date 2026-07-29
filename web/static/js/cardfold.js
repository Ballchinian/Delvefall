//the batching behind partials/deckcards.html.
//
//every card is already in the page, so this reveals rather than fetches: there
//is nothing to ask for and no url to ask at, since a pasted deck is a POST
//result. one query returning a hundred rows costs what one returning twenty
//does, and the alternative is a round trip the page cannot make.
//
//it wires ANY .deck-card-fold on the page, so a template that includes the
//partial twice gets two independent folds without saying anything about it.
//
//partials/standing.html has its own version of this idea, wired by standing.js
//against the panel machinery it also drives (five panels, two ends each, the
//name list and the pictures sharing a count). they are not worth merging: that
//one has to keep two lists in step through a reordering, this one moves a
//class on one grid

(function () {
    var folds = document.querySelectorAll(".deck-card-fold");
    if (!folds.length) return;

    folds.forEach(function (fold) {
        var grid = fold.querySelector(".deck-card-grid");
        var more = fold.querySelector(".deck-card-more");
        if (!grid || !more) return;

        var step = parseInt(grid.dataset.step, 10) || 20;
        var btn = more.querySelector(".deck-card-more-btn");
        var left = more.querySelector(".deck-card-more-left");
        var shown = step;

        /*
            the tiles as they stand, read every time rather than captured once
            at load.

            both pages that include this fold REPLACE tiles in the grid: the
            swap tool redraws the one whose card has just been swapped out, and
            /deck/view redraws it again when the card is put back. a list taken
            at load is a list of nodes that are no longer on the page by then,
            so every class landed on a detached div while the tile actually on
            screen kept whatever it was born with. the visible symptom was a
            swapped card sitting past the first batch that "load more" could
            never reveal, because the class hiding it was never taken off
        */
        function tiles() {
            return Array.prototype.slice.call(grid.children);
        }

        function paint() {
            var cards = tiles();
            cards.forEach(function (card, i) {
                card.classList.toggle("is-over", i >= shown);
            });
            var rest = cards.length - shown;
            more.hidden = rest <= 0;
            if (left) left.textContent = rest > 0 ? rest + " more" : "";
            if (btn) {
                btn.textContent = rest >= step ? "Load " + step + " more"
                                               : "Load the last " + rest;
            }
        }

        btn.addEventListener("click", function () {
            /* clamped, so the count can never run past the end. it did once,
               because the hidden attribute was not hiding this button and the
               presses kept landing: the label counted down through zero and
               the button offered to "load the last -44" */
            shown = Math.min(shown + step, grid.children.length);
            paint();
            /* the frames that just appeared need wiring for the rotate and flip
               overlay. enhanceCardFrames marks what it has already done, so
               calling it again over the whole grid is free */
            enhanceCardFrames(grid);
        });

        /* closing the fold puts it back to the first batch. somebody who opened
           a hundred cards and shut them again meant to be rid of them, and
           reopening onto all hundred is the fold not having worked. it also
           keeps the button honest: it says "load 20 more" from a known place */
        fold.addEventListener("toggle", function () {
            if (fold.open) {
                enhanceCardFrames(grid);
                return;
            }
            if (shown === step) return;
            shown = step;
            paint();
        });

        paint();
    });
})();
