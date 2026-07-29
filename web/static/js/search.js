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

import { el, resultCard } from "dom";
import { wireReports } from "report";

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
    changing the sort used to CARRY the weaker matches you had opened
    across the reload, on the reasoning that reordering is not
    researching. it is out, 2026-07-27: it was the only reload on the
    site that did not start clean, so how deep you were depended on
    which control you had touched last, and there was nothing on
    screen saying so. every reload now puts you back at the strong
    matches, which is what a plain refresh and Apply already did.

    that also took a sessionStorage key and a replay loop with it, and
    the loop was the fiddliest thing on this page: it walked the load
    more button on its own, N fetches deep, and had a step ceiling to
    stop a doctored value spinning it
*/

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
    one result card, from dom.js, which is now the only place on the
    site that draws one. it used to be written out here in full and
    again in the swap tool, and the two had already drifted: the swap
    tool's cards were missing the age arrow, the "+2 more matching
    lines" note and the shared tags.

    ANCHOR finishes the verdict sentences ("cheaper than Bolt at
    $0.25"), which is what the server-rendered cards above say too
*/
function buildResult(r) {
    return resultCard(r, cardName, {anchor: ANCHOR, flag: true});
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
    filter form, so every reload puts you back at the strong matches.
    the sort was the one exception and it is gone, so there is now one
    rule with nothing carved out of it
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
    the report bar, from report.js, which /deck/swap now uses too. what stays
    here is what is specific to THIS page: its three entry points, and the fact
    that the query string /feedback is judged against is simply this page's own
*/
var reports = wireReports({
    query: function () { return new URLSearchParams(window.location.search).toString(); },
    grid: document.querySelector(".card-grid")
});

document.getElementById("report-missing").onclick = function(e) {
    e.preventDefault();
    reports.open("missing", null);
};

//only rendered when a line is picked, so it is absent most of the time
var reportTagLink = document.getElementById("report-tag");
if (reportTagLink) {
    reportTagLink.onclick = function(e) {
        e.preventDefault();
        reports.open("tag", null);
    };
}

//the rabbit-hole hop that used to live here is the plain click now,
//and the ctrl-click that carried it belongs to the one card-link rule
//in base.html. nothing on this page has to know about either

//the same name suggestions as the search bar, wired by the shared
//helper in base.html, picking just fills the box in
wireSuggest(document.getElementById("report-input"), document.getElementById("report-suggest"),
    function(name) { document.getElementById("report-input").value = name; });

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
/* the write is caught like the read above it, and like every other write to
   this browser's storage (see decks.js). private browsing, a full quota or
   storage switched off make setItem throw, and the read was already guarded
   while the write next to it was not.
   it costs nothing today because this is the last statement in the file, so
   the throw lands after every control on the page is wired and only reaches
   the console. that is luck rather than design: it is one appended line away
   from taking the rest of the module with it, and a home page with no recent
   cards is the honest outcome of a browser that will not remember any */
try {
    localStorage.setItem("recent_searches", JSON.stringify(recent.slice(0, 8)));
} catch (e) {
}
