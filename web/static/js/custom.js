//the /custom page: the wake ping, the blank card that fills in as you type, and
//load more, which posts the form instead of reading the url.
//
//search.js is not reused here and could not be. it drives the same #load-more
//button, but off window.location.search and against /more, and everything else
//in it belongs to a printed card: the reports, the line picker, the tag chips
//and the recent-search list, none of which a card somebody typed has.

import { el, resultCard } from "dom";

var form = document.querySelector(".custom-form");
var text = document.getElementById("custom-text");
var nameBox = document.getElementById("custom-name");

/*
    the wake, on the FIRST focus of the textarea and only that one. the packet
    is the point and not the answer: it is what starts a sleeping container, so
    the model is loading while somebody is still typing, and a ping per
    keystroke is noise at a service that is already awake
*/
var woken = false;

text.addEventListener("focus", function() {
    if (woken) {
        return;
    }
    woken = true;
    //caught and dropped. nothing on the page waits on the reply, and a service
    //that is not there yet is what the form's own message is for
    fetch("/custom/wake", {method: "POST"}).catch(function() {});
});

/*
    the blank card. the server draws it too, so whatever was posted comes back
    filled in, and this only keeps it current while somebody types.

    textContent throughout: this is the visitor's own text going back onto their
    own page, and it is never markup
*/
var previewName = document.getElementById("preview-name");
var previewType = document.getElementById("preview-type");
var previewRules = document.getElementById("preview-rules");
var typeBox = document.getElementById("custom-type");
//the cap the server draws to. past it the form is turned away anyway, and
//without it a pasted megabyte draws a megabyte of card
var MAX_LINES = Number(text.dataset.maxLines);

function paint() {
    previewName.textContent = nameBox.value.trim();
    previewType.textContent = typeBox.value.trim();
    previewRules.textContent = "";
    text.value.split("\n").filter(function(line) {
        return line.trim();
    }).slice(0, MAX_LINES).forEach(function(line) {
        el("p", "", previewRules, line);
    });
}

nameBox.addEventListener("input", paint);
typeBox.addEventListener("input", paint);
text.addEventListener("input", paint);

/*
    the sort applies itself, for the reason it does on /search: it sits outside
    the filters panel, and people changed it, saw nothing happen and reported it
    broken.

    the direction's wording belongs to whichever field is picked, so changing
    the field rewrites its options and resets it to that field's own end. without
    the reset the old value rides along with the submit, and moving from price
    to salt would ask for the least salty first
*/
//a tick box coming off is a new ranking, so it resubmits the way the sort
//selects do. with javascript off, Apply in the filter bar sends the same form
form.addEventListener("change", function(e) {
    if (e.target && e.target.name === "lines") {
        form.requestSubmit();
    }
});

var sortSel = form.querySelector('select[name="sort"]');
var dirSel = form.querySelector('select[name="dir"]');

if (sortSel && window.SORT_DIRS) {
    sortSel.onchange = function() {
        var spec = window.SORT_DIRS[this.value] || {};
        if (!spec.asc) {
            //no direction to offer, and disabled so it stays out of the post
            dirSel.hidden = true;
            dirSel.disabled = true;
        } else {
            dirSel.options[0].textContent = spec.asc[1];
            dirSel.options[1].textContent = spec.desc[1];
            dirSel.value = spec["default"] || "desc";
            dirSel.hidden = false;
            dirSel.disabled = false;
        }
        form.requestSubmit();
    };
    dirSel.onchange = function() {
        form.requestSubmit();
    };
}

/*
    load more does the two jobs it does on /search: inside a tier it pages 20 at
    a time, and when the tier runs out it steps down to the next BAND of weaker
    matches, ten percentage points at a time.

    it POSTS the whole form where /search sends the url's query string, because
    the text is what the server scores against and this page will not put that
    in a url. how deep you have gone lives only in these two variables
*/
var offset = 20;
var band = null;     //null is the strong tier, a number is that band
var btn = document.getElementById("load-more");
/* one flight at a time: a second click landing before the first came back asked
   for the same twenty cards and appended them again */
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
    var body = new URLSearchParams(new FormData(form));
    body.set("offset", stepping ? 0 : offset);
    if (target !== null) {
        body.set("band", target);
    } else {
        body.delete("band");
    }
    return fetch("/custom/more", {method: "POST", body: body})
        .then(function(r) {
            //a 503 is the model asleep, not the end of the list. read as an
            //empty page it would take the button away and say the cards ran out
            if (!r.ok) {
                throw new Error("the matcher answered " + r.status);
            }
            return r.json();
        })
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
                //no anchor and no flag: there is no searched card for a price to
                //be cheaper than, and none to report a bad match against
                grid.appendChild(resultCard(r, "", {flag: false}));
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
            //a sleeping model or a network hiccup shouldn't strand the button
            //on "Loading...", and pressing it again is the right next move
            btn.textContent = resting;
            return null;
        })
        .finally(function() {
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
