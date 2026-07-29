//the unmatched lines of a pasted deck, and the offer to name what they were
//meant to be. it fills in partials/missing.html.
//
//it was templates/partials/missing_js.html, a <script> tag with no jinja in it
//at all, inlined into two pages. this is that file with the tags taken off:
//nothing about it needed rendering, so nothing about it needed to be a
//template. as a file it gets the content-hashed url static_url stamps, which
//is what lets it be cached at all, and it stops riding in the html of every
//deck page that shows the box.
//
//wireSuggest is base.html's, reached as a global exactly the way search.js
//reaches it. it is the one autocomplete on the site and it belongs to the page
//rather than to any of the scripts that ask it for a card name

(function () {
    var box = document.getElementById("deck-missing");
    if (!box) return;

    /*
        the list every form on this page is carrying. adding a card writes to
        all of them at once, because the paste box, the two mode buttons and
        the swap form each hold their own copy of the text: one field updated
        and the others not is how you get a reading of a deck the user is no
        longer looking at
    */
    function fields() {
        return Array.prototype.slice.call(
            document.querySelectorAll('input[name="list"], textarea[name="list"]'));
    }

    function addLine(name) {
        fields().forEach(function (f) {
            var v = f.value || "";
            f.value = v + (v.slice(-1) === "\n" || !v ? "" : "\n") + "1 " + name;
        });
    }

    box.addEventListener("click", function (e) {
        var btn = e.target.closest(".deck-missing-try");
        if (!btn) return;
        var row = btn.closest(".deck-missing-row");
        var fix = row.querySelector(".deck-missing-fix");
        btn.hidden = true;
        fix.hidden = false;
        var input = row.querySelector(".deck-missing-input");
        var drop = row.querySelector(".deck-missing-drop");
        input.focus();
        input.select();
        /* the same autocomplete the search bar and the report box use, wired
           the same way, so a card is found here exactly as it is found there */
        wireSuggest(input, drop, function (name) {
            input.value = name;
            take(row, btn.dataset.raw, name);
        });
        /* typing the whole name and pressing enter works too. wireSuggest only
           answers enter when one of its own rows is highlighted, and the
           server resolves a typed name the same forgiving way the search bar
           does, so there is nothing to be gained by insisting on the dropdown.

           it asks the EVENT whether that already happened, rather than looking
           at whether the dropdown is open. those are not the same question and
           the difference was the common case: type a full card name, the
           suggestions appear because they always do, and enter did nothing at
           all, because wireSuggest ignores enter with no row highlighted and
           this handler bowed out to it anyway.

           the state cannot be read off the dom either. wireSuggest hides the box
           and clears the highlight BEFORE this listener runs, so by the time we
           look, every trace of it having acted is already gone and we would fire
           a second time on top of it. defaultPrevented is the one flag that
           survives, because it lives on the event both handlers are holding */
        input.addEventListener("keydown", function (e) {
            if (e.key !== "Enter" || e.defaultPrevented) return;
            e.preventDefault();
            take(row, btn.dataset.raw, input.value.trim());
        });
    });

    function take(row, raw, name) {
        var said = row.querySelector(".deck-missing-said");
        said.textContent = "adding…";
        fetch("/deck/found", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({raw: raw, name: name})
        }).then(function (r) { return r.json(); }).then(function (j) {
            if (!j.ok) { said.textContent = j.msg || "Couldn't find that one."; return; }
            addLine(j.name);
            row.classList.add("is-fixed");
            row.querySelector(".deck-missing-fix").hidden = true;
            said.textContent = "added " + j.name;
            box.querySelector(".deck-missing-again").hidden = false;
            /* the deck this browser is about to remember has just changed, so
               the payload it will be remembered from changes with it. without
               this, a card fixed here is in the reading and then gone the next
               time the deck is opened out of the recent list, which is the one
               place the fix most needs to have stuck */
            var mem = document.getElementById("deck-remember");
            if (mem) {
                try {
                    var m = JSON.parse(mem.textContent);
                    m.count = (m.count || 0) + 1;
                    mem.textContent = JSON.stringify(m);
                } catch (e) {}
            }
        }).catch(function () {
            said.textContent = "Couldn't reach the card database. Try again in a moment.";
        });
    }

})();
