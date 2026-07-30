//the results page. module scope, so it does not leak 23 names onto window: the
//four values the template computes arrive there instead, set by the inline
//script above this one in search.html

import { el, resultCard } from "dom";
import { wireReports } from "report";

//the searched card's figures, so results added by load more can name what their
//arrows are measured against
var ANCHOR = window.ANCHOR;

/*
    the sort applies ITSELF, because it sits outside the filters panel and people
    changed it, saw nothing happen and reported it broken. everything inside the
    panel waits for Apply, or touching a control throws you out of the panel you
    were still working in.

    changing it no longer carries the weaker matches you had opened (out
    2026-07-27): it was the only reload on the site that did not start clean, so
    how deep you were depended on which control you touched last.

    the direction's wording belongs to whichever field is picked, so changing the
    field rewrites its options and resets it to that field's natural end. best
    match has no direction and hides it
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

/* setCustomValidity is what makes the form refuse to submit, so it is kept
   current as you type rather than checked on the way out. the red note above the
   results stays as the backstop for a url typed by hand */
var filterForm = document.querySelector(".filter-bar");
/* every pair the server checks, and it HAS to stay every pair: salt arrived as
   a range after this list was written and was not added, so an inverted salt
   range got no bubble and had to be met as the red note after a reload */
var RANGES = [["pmin", "pmax", "price"], ["mvmin", "mvmax", "mana value"],
              ["smin", "smax", "salt"]];

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

/* a box inside a shut panel cannot be focused, so the browser refuses to submit
   and shows nothing at all. covers the native min and max messages too */
filterForm.addEventListener("invalid", function(e) {
    var fold = e.target.closest("details");
    if (fold) {
        fold.open = true;
    }
}, true);

/* ANCHOR finishes the verdict sentences ("cheaper than Bolt at $0.25"), which
   is what the server-rendered cards above say too */
function buildResult(r) {
    return resultCard(r, cardName, {anchor: ANCHOR, flag: true});
}

/*
    load more does two jobs: inside a tier it pages 20 at a time, and when a tier
    runs out it steps down to the next BAND of weaker matches, ten percentage
    points at a time.

    the bands are what keep the sorts meaningful down here. opening everything
    below the line at once meant "cheapest first" handed back the cheapest 0%
    match in the database.

    how deep you have gone lives ONLY in these variables, never the url, so
    every reload puts you back at the strong matches
*/
var offset = 20;
var band = null;     //null is the strong tier, a number is that band
var btn = document.getElementById("load-more");
/* ONE FLIGHT AT A TIME. the "Loading..." label reads as busy without being
   busy: a second click landing before the first came back asked for the same
   twenty cards and appended them again, labelled divider and all */
var loading = false;

function loadNext() {
    if (loading) {
        return;
    }
    loading = true;
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
                //a labelled divider per band, so the drop is never silent
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
        })
        .finally(function() {
            //released whichever way it went, or one failed fetch leaves the
            //button permanently deaf
            loading = false;
        });
}

if (btn) {
    //a page that opened with no strong matches at all starts pointed straight
    //at the first band
    if (btn.dataset.next !== undefined) {
        offset = 0;
    }
    btn.onclick = loadNext;
}

/* toggles the line's index in the lines param and reloads, so the url stays
   shareable */
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
    four chip states, each click meaning the opposite of whichever it is in:
      on    -> notags, switch it off
      off   -> out of notags, back on
      aside -> yestags, the line picker guessed wrong, put it back
      kept  -> out of yestags, accept the guess after all
    two params because they answer two questions: notags is "ignore this",
    yestags is "the attribution missed this". both stay empty until something is
    touched, so a plain url still means the whole card
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

/* what is specific to THIS page: its three entry points, and the fact that the
   query string /feedback judges against is simply the page's own url */
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

//wireSuggest is base.html's, and here picking only fills the box in
wireSuggest(document.getElementById("report-input"), document.getElementById("report-suggest"),
    function(name) { document.getElementById("report-input").value = name; });

/* the home page floats these. the CANONICAL name goes in, whatever find_card
   landed on, not the typo that was typed, so clicking it later hits exact match */
var recent = [];
try {
    recent = JSON.parse(localStorage.getItem("recent_searches") || "[]");
} catch (e) {}
var cardName = window.CARD_NAME;
recent = recent.filter(function(n) { return n != cardName; });
recent.unshift(cardName);
/* caught like the read above it: private browsing, a full quota or storage
   switched off all make setItem throw. it is harmless only because this is the
   LAST statement in the file, so an uncaught throw would land after everything
   is wired. one appended line changes that */
try {
    localStorage.setItem("recent_searches", JSON.stringify(recent.slice(0, 8)));
} catch (e) {
}
