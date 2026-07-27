//the results page: the filter panel, the sort controls, load more, the
//band memory and the recent-searches list. moved out of
//templates/search.html, which is why it reads as one long top level
//rather than a module built to be one.
//
//it was top-level code in a classic script, so everything in it used to
//be a global. nothing outside ever reached in (no inline handlers on the
//page, and cards.js only has its own local named el), so module scope
//costs nothing here and stops the page leaking 23 names onto window.
//
//the four values the template computes still arrive on window, set by the
//small inline script above this one in search.html, and are read back into
//the same names the body already used

import { el } from "dom";

//the searched card's own figures, so results added by load more can
//name what their arrows are measured against, exactly like the
//server-rendered ones do
var ANCHOR = window.ANCHOR;
/*
    sort applies itself, because it sits outside the filters panel
    and people changed it, saw nothing happen, and concluded it was
    broken. everything INSIDE the panel waits for Apply, currency
    included: a control that reloads the page the instant you touch
    it throws you out of the panel you were still working in, which
    is worse than a control that looks patient
*/
/*
    reordering is not researching. changing the sort is the one
    reload that should leave the weaker matches you had opened where
    they are: you are asking for the same cards in a different order.
    everything else that submits this form (Apply, the filters, enter
    in the query box) is a NEW search and starts you back at the
    strong matches.

    the depth rides sessionStorage rather than the url, and is eaten
    on the way in. that is what keeps a plain refresh from restoring
    it too: by then the note has already been read and thrown away
*/
var KEEP_BAND = "delvefall_keep_band";

/*
    the two sort controls. the direction's wording belongs to whatever
    field is picked, so changing the field rewrites its options and
    resets it to that field's natural end (cheapest for money, saltiest
    for salt) rather than carrying over a direction chosen for
    something else. best match has no direction at all and hides it.

    picking a field applies immediately, the same as the old single
    list did. changing only the direction applies too: it is the same
    question asked backwards, and waiting for Apply to reverse a list
    is the friction the auto-submit exists to avoid
*/
var SORT_DIRS = window.SORT_DIRS;
var sortSel = document.querySelector('.filter-bar select[name="sort"]');
var dirSel = document.querySelector('.filter-bar select[name="dir"]');

function applySort(el) {
    if (band !== null) {
        try {
            sessionStorage.setItem(KEEP_BAND, band);
        } catch (e) {}
    }
    el.form.requestSubmit();
}

sortSel.onchange = function() {
    var spec = SORT_DIRS[this.value] || {};
    if (!spec.asc) {
        //no direction to offer, and disabled so it stays out of the url
        dirSel.hidden = true;
        dirSel.disabled = true;
    } else {
        dirSel.options[0].textContent = spec.asc[1];
        dirSel.options[1].textContent = spec.desc[1];
        dirSel.value = spec["default"] || "desc";
        dirSel.hidden = false;
        dirSel.disabled = false;
    }
    applySort(this);
};

dirSel.onchange = function() {
    applySort(this);
};

/*
    an inverted range (a minimum above its maximum) is reported the
    same way the browser reports a price below zero: its own bubble,
    pinned to the offending box, with the panel still open so it can
    be fixed on the spot. the red note above the results is still
    there as the backstop for a url typed by hand, it just stops
    being how anyone normally meets this mistake.

    setCustomValidity is what makes the form refuse to submit, so it
    has to be kept current as you type, not only checked on the way out
*/
var filterForm = document.querySelector(".filter-bar");
var RANGES = [["pmin", "pmax", "price"], ["mvmin", "mvmax", "mana value"]];

function checkRanges() {
    RANGES.forEach(function(r) {
        var lo = filterForm.elements[r[0]];
        var hi = filterForm.elements[r[1]];
        if (!lo || !hi) {
            return;
        }
        var a = parseFloat(lo.value);
        var b = parseFloat(hi.value);
        hi.setCustomValidity(!isNaN(a) && !isNaN(b) && a > b
            ? "The highest " + r[2] + " has to be at least the lowest (" + lo.value + "), or nothing can fit between them."
            : "");
    });
}

filterForm.addEventListener("input", checkRanges);
checkRanges();

/*
    a box inside a shut panel cannot be focused, so the browser would
    refuse to submit and show nothing at all. opening the fold on the
    way to the bubble covers every native message in there, the
    built-in min and max ones included
*/
filterForm.addEventListener("invalid", function(e) {
    var fold = e.target.closest("details");
    if (fold) {
        fold.open = true;
    }
}, true);

/*
    one result card as dom elements, mirroring the server-rendered
    markup above. everything is set through textContent and
    properties, never glued into an html string, so a name or a rules
    line full of quotes (or anything else) can't break out of the
    markup. tiny helper: make an element, place it, fill it
*/
function buildResult(r) {
    var div = document.createElement("div");
    div.className = "result";

    var frame = el("div", "card-frame", div);
    frame.dataset.sideways = r.sideways ? "1" : "";
    frame.dataset.flip = r.flip ? "1" : "";
    frame.dataset.back = r.image_back;
    var link = el("a", "", frame);
    link.href = "/search?q=" + encodeURIComponent(r.name);
    link.dataset.card = r.name;
    link.dataset.scryfall = r.scryfall_uri;
    link.title = "search " + r.name + " here. ctrl-click to open it on scryfall";
    var img = el("img", "", link);
    img.src = r.image;
    img.alt = r.name;
    img.width = 488;   //scryfall's normal size, same as the
    img.height = 680;  //server-rendered cards declare
    img.loading = "lazy";
    var flag = el("button", "report-flag", frame, "?");
    flag.title = "shouldn't be here? report this as a bad match";
    flag.dataset.id = r.oracle_id;
    flag.dataset.name = r.name;

    var name = el("div", "result-name", div, r.name + " ");
    var pct = el("span", "percent" + (r.concept_only ? " concept" : ""), name, r.percent + "%");
    if (r.blended) {
        pct.title = "rules text " + r.mech_pct + "%, concepts " + r.concept_pct + "%, evenly blended";
    }
    if (r.price || r.rank || r.salt || r.age) {
        var price = el("div", "result-price", div);
        var figure = el("span", "price-figure " + r.price_vs, price, r.price);
        if (r.price_vs) {
            figure.title = r.price_vs.replace("-", " ") + " than " + cardName + " at " + ANCHOR.price;
            el("span", "price-vs", figure, r.price_vs.indexOf("cheaper") > -1 ? "↓" : "↑");
        }
        if (r.rank) {
            var rank = el("span", "result-rank", price, r.rank);
            rank.title = "play rate: edhrec's rank for how often this card is played in " +
                "commander, where #1 is the most played card in the format";
            if (r.rank_vs) {
                el("span", "rank-vs", rank, r.rank_vs == "more-played" ? "↑" : "↓")
                    .title = (r.rank_vs == "more-played" ? "more" : "less") + " played than " +
                        cardName + " at " + ANCHOR.rank;
            }
        }
        //empty means the card has no score at all, not that it is mild
        if (r.salt) {
            var salt = el("span", "result-salt " + r.salt_vs, price);
            el("i", "salt-mark", salt).setAttribute("aria-hidden", "true");
            salt.appendChild(document.createTextNode(r.salt));
            if (r.salt_vs) {
                salt.title = r.salt_vs.replace("-", " ").replace("milder", "less salty") +
                    " than " + cardName + " at " + ANCHOR.salt;
                el("span", "salt-vs", salt, r.salt_vs.indexOf("milder") > -1 ? "↓" : "↑");
            } else {
                salt.title = "salt " + r.salt + " out of about 3, from edhrec's salt " +
                    "survey, where players vote on the cards they least enjoy facing";
            }
        }
        //no arrow, unlike the three before it. older and newer are not better
        //and worse, so there is no verdict here to point either way
        if (r.age) {
            el("span", "result-age", price, r.age).title = "card age: how long ago this " +
                "card was first printed, counted from its earliest printing, so a reprint " +
                "does not make an old card new";
        }
    }
    if (r.their_line) {
        var ml = el("div", "match-line", div);
        manaFill(ml, '"' + r.their_line + '"');
        ml.title = "matches your card's line: " + r.our_line +
            (r.matched_back ? " (printed on the back face, shown here)" : "");
    }
    if (r.more_count) {
        el("div", "more-lines", div, "+" + r.more_count + " more matching " + (r.more_count == 1 ? "line" : "lines")).title = r.more_text;
    }
    if (r.concept_tags) {
        el("div", "concept-tags", div, r.concept_tags).title =
            "community tags shared with your card" + (r.concept_only ? "" : " - concept match " + r.concept_pct + "%");
    }
    return div;
}

/*
    the load more button, which is doing two jobs at once. inside a
    tier it pages 20 at a time. when a tier runs out it steps down to
    the next BAND of weaker matches, ten percentage points at a time,
    and says which range it is about to show.

    the bands are the reason the sorts still mean something down here.
    the old button opened everything below the line at once, so
    "cheapest first" over that pile handed back the cheapest 0% match
    in the database. one band at a time means a sort runs among cards
    that match about equally well, which is the only way the answer is
    worth reading
*/
/*
    how deep into the weaker matches you have gone lives only in this
    variable, deliberately: it is not in the url and does not ride the
    filter form, so applying a filter and reloading the page both put
    you back at the strong matches. carrying it across an apply was
    tried and felt wrong, because changing a filter is the moment you
    want to see what the NEW search turned up, not to be handed the
    same depth of weak results you were digging through before
*/
var offset = 20;
var band = null;     //null is the strong tier, a number is that band
var btn = document.getElementById("load-more");

function loadNext() {
    var stepping = btn.dataset.next !== undefined;  //moving to a new band
    var target = stepping ? Number(btn.dataset.next) : band;
    var words = btn.dataset.words;
    var resting = btn.textContent;
    btn.textContent = "Loading...";
    var params = new URLSearchParams(window.location.search);
    params.set("offset", stepping ? 0 : offset);
    if (target !== null) {
        params.set("band", target);
    } else {
        params.delete("band");
    }
    return fetch("/more?" + params.toString())
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var grid = document.querySelector(".card-grid");
            if (stepping) {
                band = target;
                offset = 0;
                //every band gets its own labelled divider, so it is
                //always clear that the cards under it are a step worse
                if (data.results.length) {
                    el("div", "weak-divider", grid, words);
                }
            }
            data.results.forEach(function(r) {
                grid.appendChild(buildResult(r));
            });
            //the fresh frames need their rotate/flip/transform buttons
            enhanceCardFrames(grid);
            offset = offset + data.results.length;
            if (data.has_more) {
                delete btn.dataset.next;
                delete btn.dataset.words;
                btn.textContent = "Load 20 more";
            } else if (data.next_band) {
                btn.dataset.next = data.next_band.lo;
                btn.dataset.words = data.next_band.words;
                btn.textContent = "Show " + data.next_band.count + " " + data.next_band.words;
            } else {
                //truly nothing left, no point keeping the button around
                btn.remove();
            }
            return data;
        })
        .catch(function() {
            //a network hiccup shouldn't strand the button on "Loading..."
            btn.textContent = resting;
            return null;
        });
}

if (btn) {
    //a page that opened with no strong matches at all starts the
    //button pointed straight at the first band
    if (btn.dataset.next !== undefined) {
        offset = 0;
    }
    btn.onclick = loadNext;

    /*
        put back the depth a sort change left behind. the note is
        read once and deleted immediately, so this fires for the
        reload the sort caused and for nothing after it: refresh that
        same page and there is nothing left to read.

        it walks down using the button's own path, so the restored
        cards come back in the NEW sort order, which is the whole
        point of having kept them. the step ceiling is a stop against
        a nonsense value, not a limit anyone reaches
    */
    var keep = null;
    try {
        keep = sessionStorage.getItem(KEEP_BAND);
        sessionStorage.removeItem(KEEP_BAND);
    } catch (e) {}
    if (keep !== null && keep !== "") {
        var steps = 0;
        (function walk() {
            if (!btn.isConnected || steps++ > 40) {
                return;
            }
            if (band !== null && band <= Number(keep)) {
                return;
            }
            loadNext().then(function(data) {
                if (data) {
                    walk();
                }
            });
        })();
    }
}

/*
    the line picker. clicking a rules line toggles its index in the
    lines url param and reloads, so the search only uses the picked
    lines and the url stays shareable
*/
document.querySelectorAll(".oracle-line").forEach(function(el) {
    el.onclick = function() {
        var params = new URLSearchParams(window.location.search);
        var picked = [];
        if (params.get("lines")) {
            picked = params.get("lines").split(",");
        }
        var i = picked.indexOf(el.dataset.idx);
        if (i == -1) {
            picked.push(el.dataset.idx);
        } else {
            picked.splice(i, 1);
        }
        if (picked.length) {
            params.set("lines", picked.join(","));
        } else {
            params.delete("lines");
        }
        window.location.search = params.toString();
    };
});

/*
    the tag picker, the line picker's opposite number. a chip is in one
    of four states and clicking it means the obvious opposite of
    whichever it's in:
      on    -> notags, switch it off
      off   -> out of notags, back on
      aside -> yestags, the line picker guessed wrong, put it back
      kept  -> out of yestags, accept the guess after all
    two params rather than one because they answer different questions:
    notags is "ignore this", yestags is "the attribution missed this".
    both stay empty until you actually touch something, so a plain url
    still means the whole card
*/
document.querySelectorAll(".tag-chip").forEach(function(el) {
    el.onclick = function() {
        var params = new URLSearchParams(window.location.search);
        var state = el.dataset.state;
        var key = (state == "aside" || state == "kept") ? "yestags" : "notags";
        var list = params.get(key) ? params.get(key).split(",") : [];
        var i = list.indexOf(el.dataset.tag);
        if (i == -1) {
            list.push(el.dataset.tag);
        } else {
            list.splice(i, 1);
        }
        if (list.length) {
            params.set(key, list.join(","));
        } else {
            params.delete(key);
        }
        window.location.search = params.toString();
    };
});

/*
    the report bar. two ways in: the "expected a card that isn't here?"
    link opens it as a missing-card report (name the card, plus anything
    extra you want to add), and the little flag under any result opens it
    as a misplaced-card report with that card marked in red (just say why
    it's a bad match, nobody has to know a better card off the top of
    their head). the server answers with a human sentence either way,
    including "your filters are hiding that card, here's which one" for
    missing reports that aren't really the matcher's fault
*/
var reportBar = document.getElementById("report-bar");
var reportTitle = document.getElementById("report-title");
var reportPick = document.getElementById("report-pick");
var reportInput = document.getElementById("report-input");
var reportReason = document.getElementById("report-reason");
var reportMsg = document.getElementById("report-msg");
var reportSuggest = document.getElementById("report-suggest");
var reportTagPick = document.getElementById("report-tag-pick");
var reportKind = "";
var flagged = null;  //{id, name, el} of the card a misplaced report is about

function openReportBar(kind, flag) {
    if (flagged) {
        flagged.el.classList.remove("flagged");
    }
    reportKind = kind;
    flagged = flag || null;
    if (kind == "tag") {
        reportTitle.textContent = "Which tag is on the wrong line? Whether it should be there or shouldn't is worked out from where it sits now, so just pick it.";
        reportReason.placeholder = "(optional) which line does it really belong to?";
    } else if (flagged) {
        flagged.el.classList.add("flagged");
        reportTitle.textContent = 'You flagged "' + flagged.name + '" as a bad match. Please put a small description about why it\'s bad.';
        reportReason.placeholder = "why is it a bad match?";
    } else {
        reportTitle.textContent = "Which card should be here? It gets checked against your filters first, and only real gaps reach the log.";
        reportReason.placeholder = "(optional) anything else worth knowing?";
    }
    //three shapes: missing names a card, misplaced only explains, tag
    //picks from the card's own tags
    reportPick.hidden = (kind != "missing");
    if (reportTagPick) {
        reportTagPick.hidden = (kind != "tag");
    }
    reportBar.hidden = false;
    reportMsg.hidden = true;
    reportInput.value = "";
    reportReason.value = "";
    reportBar.scrollIntoView({behavior: "smooth", block: "nearest"});
    if (kind == "missing") {
        reportInput.focus();
    } else if (kind == "tag" && reportTagPick) {
        reportTagPick.focus();
    } else {
        reportReason.focus();
    }
}

function closeReportBar() {
    if (flagged) {
        flagged.el.classList.remove("flagged");
    }
    flagged = null;
    reportKind = "";
    reportBar.hidden = true;
    reportSuggest.style.display = "none";
}

function showReportMsg(text, good) {
    reportMsg.textContent = text;
    reportMsg.className = good ? "good" : "bad";
    reportMsg.hidden = false;
}

document.getElementById("report-missing").onclick = function(e) {
    e.preventDefault();
    openReportBar("missing", null);
};

//only rendered when a line is picked, so it is absent most of the time
var reportTagLink = document.getElementById("report-tag");
if (reportTagLink) {
    reportTagLink.onclick = function(e) {
        e.preventDefault();
        openReportBar("tag", null);
    };
}

document.getElementById("report-cancel").onclick = closeReportBar;

/*
    one listener on the grid covers every flag, including the ones load
    more adds later
*/
document.querySelector(".card-grid").addEventListener("click", function(e) {
    var flagBtn = e.target.closest(".report-flag");
    if (flagBtn) {
        openReportBar("misplaced", {id: flagBtn.dataset.id, name: flagBtn.dataset.name, el: flagBtn.closest(".result")});
    }
});

//the rabbit-hole hop that used to live here is the plain click now,
//and the ctrl-click that carried it belongs to the one card-link rule
//in base.html. nothing on this page has to know about either

//the same name suggestions as the search bar, wired by the shared
//helper in base.html, picking just fills the box in
wireSuggest(reportInput, reportSuggest, function(name) {
    reportInput.value = name;
});

document.getElementById("report-send").onclick = function() {
    var body = {kind: reportKind, reason: reportReason.value.trim()};
    if (reportKind == "misplaced") {
        if (!body.reason) {
            showReportMsg("Say a few words about why it's a bad match first.", false);
            return;
        }
        body.got_id = flagged.id;
    } else if (reportKind == "tag") {
        //no reason required: the disagreement is the report, and which
        //way it runs is read off the attribution rather than typed
        body.tag = reportTagPick ? reportTagPick.value : "";
        if (!body.tag) {
            showReportMsg("Pick which tag looks wrong first.", false);
            return;
        }
    } else {
        body.expected = reportInput.value.trim();
        if (!body.expected) {
            showReportMsg("Type a card name first.", false);
            return;
        }
    }
    //the page's whole query string rides along, like the load more button
    fetch("/feedback?" + new URLSearchParams(window.location.search).toString(), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
    })
        .then(function(r) { return r.json(); })
        .then(function(data) { showReportMsg(data.msg, data.ok); })
        .catch(function() { showReportMsg("Something went wrong sending that, sorry.", false); });
};

/*
    remember this search so the home page can float it as a recent card.
    the canonical name goes in (whatever find_card landed on), not the
    typo the user actually typed, so clicking it later hits exact match
*/
var recent = [];
try {
    recent = JSON.parse(localStorage.getItem("recent_searches") || "[]");
} catch (e) {}
var cardName = window.CARD_NAME;
recent = recent.filter(function(n) { return n != cardName; });
recent.unshift(cardName);
localStorage.setItem("recent_searches", JSON.stringify(recent.slice(0, 8)));
