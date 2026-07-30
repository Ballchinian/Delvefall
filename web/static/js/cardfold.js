//the batching behind partials/deckcards.html. every card is already in the page,
//so this REVEALS rather than fetches: a pasted deck is a POST result with no url
//to ask at.
//
//wires ANY .deck-card-fold, so including the partial twice gets two independent
//folds.
//
//standing.js has its own version of this against the panel machinery. not worth
//merging: that one keeps two lists in step through a reordering, this one moves
//a class on one grid

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

        /* read every time, NEVER captured at load: both pages that include this
           fold replace tiles in the grid, so a captured list is nodes no longer
           on the page and every class lands on a detached div. the symptom was a
           swapped card past the first batch that "load more" could never reveal */
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
            /* clamped, or the label counts down through zero: it once offered to
               "load the last -44" */
            shown = Math.min(shown + step, grid.children.length);
            paint();
            /* enhanceCardFrames marks what it has done, so calling it again over
               the whole grid is free */
            enhanceCardFrames(grid);
        });

        /* closing resets to the first batch, so reopening does not land on all
           hundred and the button counts from a known place */
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
