//the unmatched lines of a pasted deck, filling in partials/missing.html.
//
//a file rather than an inline block, so it gets the content-hashed url
//static_url stamps and can be cached at all.
//
//wireSuggest is base.html's, reached as a global the way search.js reaches it

(function () {
    var box = document.getElementById("deck-missing");
    if (!box) return;

    /* ALL of them at once: the paste box, the two mode buttons and the swap form
       each hold their own copy, and one field updated without the others is a
       reading of a deck the user is no longer looking at */
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
        wireSuggest(input, drop, function (name) {
            input.value = name;
            take(row, btn.dataset.raw, name);
        });
        /* typing the whole name and pressing enter works too. it asks the EVENT
           whether wireSuggest already handled it, never the dom: wireSuggest
           ignores enter with no row highlighted, so keying off "is the dropdown
           open" made the common case (a full name typed, suggestions showing) do
           nothing at all. and it hides the box and clears the highlight BEFORE
           this listener runs, so every trace is gone by the time we could look.
           defaultPrevented is the one flag that survives */
        input.addEventListener("keydown", function (e) {
            if (e.key !== "Enter" || e.defaultPrevented) return;
            e.preventDefault();
            take(row, btn.dataset.raw, input.value.trim());
        });
    });

    /* one flight per ROW, not per box, so two lines can be fixed at once.
       without it, two quick presses of enter sent two posts and addLine ran twice,
       putting the recovered card in the decklist twice */
    function take(row, raw, name) {
        if (row.dataset.sending) {
            return;
        }
        row.dataset.sending = "1";
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
            /* the payload modes.js remembers the deck from has to move too, or a
               card fixed here is in the reading and gone the next time the deck
               is opened off the shelf */
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
        }).finally(function () {
            /* released either way, so a row that failed can be tried again */
            delete row.dataset.sending;
        });
    }

})();
