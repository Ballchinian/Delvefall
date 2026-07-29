//the report bar, wired once for both pages that carry one.
//
//it lived in search.js, which is why /deck/swap had no way to say "this
//suggestion is wrong" even though a suggestion is the thing on this site most
//worth arguing with: the tool proposing a card for your deck is making a much
//stronger claim than a list of similar cards is.
//
//the markup is partials/reportbar.html and the sentences are here. what differs
//between the two pages is ONE function, `query`, which says what the report is
//about: /search reads its own url, the swap tool builds one from the card it is
//standing on and whatever the pickers were told. /feedback reads that query
//string exactly as it always did, so the server needed no new shape.

export function wireReports(opts) {
    var bar = document.getElementById("report-bar");
    if (!bar) return null;
    var title = document.getElementById("report-title");
    var pick = document.getElementById("report-pick");
    var input = document.getElementById("report-input");
    var reason = document.getElementById("report-reason");
    var msg = document.getElementById("report-msg");
    var suggest = document.getElementById("report-suggest");
    var tagPick = document.getElementById("report-tag-pick");
    var kind = "";
    var flagged = null;  //{id, name, el} of the card a misplaced report is about

    function open(want, flag) {
        if (flagged) flagged.el.classList.remove("flagged");
        kind = want;
        flagged = flag || null;
        if (kind === "tag") {
            title.textContent = "Which tag is on the wrong line? Whether it should be there or shouldn't is worked out from where it sits now, so just pick it.";
            reason.placeholder = "(optional) which line does it really belong to?";
        } else if (flagged) {
            flagged.el.classList.add("flagged");
            title.textContent = 'You flagged "' + flagged.name + '" as a bad match. Please put a small description about why it\'s bad.';
            reason.placeholder = "why is it a bad match?";
        } else {
            title.textContent = "Which card should be here? It gets checked against your filters first, and only real gaps reach the log.";
            reason.placeholder = "(optional) anything else worth knowing?";
        }
        //three shapes: missing names a card, misplaced only explains, tag picks
        //from the card's own tags
        if (pick) pick.hidden = (kind !== "missing");
        if (tagPick) tagPick.hidden = (kind !== "tag");
        bar.hidden = false;
        msg.hidden = true;
        if (input) input.value = "";
        reason.value = "";
        bar.scrollIntoView({behavior: "smooth", block: "nearest"});
        if (kind === "missing" && input) input.focus();
        else if (kind === "tag" && tagPick) tagPick.focus();
        else reason.focus();
    }

    function close() {
        if (flagged) flagged.el.classList.remove("flagged");
        flagged = null;
        kind = "";
        bar.hidden = true;
        if (suggest) suggest.style.display = "none";
    }

    function say(text, good) {
        msg.textContent = text;
        msg.className = good ? "good" : "bad";
        msg.hidden = false;
    }

    /* the tag list belongs to whichever card the page is about, and on the swap
       tool that changes every time the queue moves. refilled from the chips
       actually on screen, so the options can never name a tag the panel is not
       showing */
    function fillTags(root) {
        if (!tagPick) return;
        tagPick.innerHTML = "";
        (root || document).querySelectorAll(".tag-chip").forEach(function (chip) {
            var o = document.createElement("option");
            var state = chip.dataset.state;
            o.value = chip.dataset.tag;
            o.textContent = chip.dataset.tag + (state === "aside" ? " (set aside)"
                : state === "kept" ? " (put back by you)"
                : state === "off" ? " (switched off)" : " (kept)");
            tagPick.appendChild(o);
        });
    }

    document.getElementById("report-cancel").onclick = close;

    /* one report per press. this one WRITES, so a double click is not a wasted
       request like the results page's load more, it is two identical rows in
       the review queue for somebody to read and throw away. the flag goes up
       only after the checks below have passed, so a press that was rejected
       for having no reason typed can be pressed again straight away */
    var sending = false;

    document.getElementById("report-send").onclick = function () {
        if (sending) {
            return;
        }
        var body = {kind: kind, reason: reason.value.trim()};
        if (kind === "misplaced") {
            if (!body.reason) return say("Say a few words about why it's a bad match first.", false);
            body.got_id = flagged.id;
        } else if (kind === "tag") {
            //no reason required: the disagreement is the report, and which way
            //it runs is read off the attribution rather than typed
            body.tag = tagPick ? tagPick.value : "";
            if (!body.tag) return say("Pick which tag looks wrong first.", false);
        } else {
            body.expected = input ? input.value.trim() : "";
            if (!body.expected) return say("Type a card name first.", false);
        }
        sending = true;
        fetch("/feedback?" + opts.query(), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body)
        })
            .then(function (r) { return r.json(); })
            .then(function (d) { say(d.msg, d.ok); })
            .catch(function () { say("Something went wrong sending that, sorry.", false); })
            /* released either way: the panel stays open after an answer, and a
               report that failed to send has to be sendable again */
            .finally(function () { sending = false; });
    };

    /* one listener on the container covers every flag, including the ones drawn
       later by load more or by the next card in the queue */
    if (opts.grid) {
        opts.grid.addEventListener("click", function (e) {
            var btn = e.target.closest(".report-flag");
            if (btn) {
                open("misplaced", {id: btn.dataset.id, name: btn.dataset.name,
                                   el: btn.closest(".result")});
            }
        });
    }

    return {open: open, close: close, fillTags: fillTags};
}
