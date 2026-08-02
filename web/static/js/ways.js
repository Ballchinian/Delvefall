//the axis picker on a deckways row into /deck/swap. delegated on the document,
//because a page can draw several rows and /deck/read rewrites its one from the
//pager.
//
//standing.js sets the select and fires a change event rather than writing the
//go line itself, so the sentence is built in one place.
(function () {
    function goLine(sel) {
        var form = sel.closest(".deck-mode");
        var go = form && form.querySelector(".deck-mode-go");
        if (!go) return;
        //the option text IS the goal word, so nothing here holds a second copy
        go.textContent = "Make this deck " + sel.options[sel.selectedIndex].text + " →";
    }

    document.addEventListener("change", function (e) {
        var sel = e.target;
        if (sel.matches && sel.matches('.deck-mode-axis select[name="goal"]')) goLine(sel);
    });
})();
