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
    what this page's list was scored on, read once as it loads: load more asks for
    page two of THAT. the form itself is live, typing clears the picks, and a body
    read at click time appended page two of a different search under page one.
    after the filter panel's own script, so a hidden slot is already left out
*/
var asked = new URLSearchParams(new FormData(form));

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
    setPicked([]);
    previewName.textContent = nameBox.value.trim();
    previewType.textContent = typeBox.value.trim();
    previewRules.textContent = "";
    text.value.split("\n").filter(function(line) {
        return line.trim();
    }).slice(0, MAX_LINES).forEach(function(line) {
        el("p", "", previewRules, line);
    });
}

/*
    a line on the card is the same control /search's anchor card carries: click it
    and the list is ranked on that line alone, click again to put it back. the
    picked indexes ride in hidden inputs, because the card is drawn text rather
    than form controls, and /custom/more posts this same form.

    typing clears them. the text moving shifts every index, so a pick made against
    the old text would quietly rank on a different ability.

    the next picks come from the card as drawn and not from the inputs, so a
    second click before the page answers asks the same thing again rather than
    toggling the line back off
*/
function picked() {
    return Array.prototype.map.call(previewRules.querySelectorAll(".oracle-line.picked"),
        function(line) {
            return line.dataset.idx;
        });
}

function setPicked(values) {
    Array.prototype.forEach.call(form.querySelectorAll('input[name="lines"]'),
        function(input) {
            input.remove();
        });
    values.forEach(function(value) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = "lines";
        input.value = value;
        form.appendChild(input);
    });
}

previewRules.addEventListener("click", function(e) {
    var line = e.target.closest(".oracle-line");
    if (!line) {
        return;
    }
    var idx = line.dataset.idx;
    var on = picked();
    setPicked(on.indexOf(idx) === -1 ? on.concat([idx]) : on.filter(function(value) {
        return value !== idx;
    }));
    form.requestSubmit();
});

/*
    one question at a time. every submit parks a server thread for as long as
    the matcher takes, up to 90s on a cold wake, and a wake measures 7 to 13s
    with nothing else on screen. the line clicks, the sort and apply all
    submit through here
*/
var go = form.querySelector(".custom-go button");
var goLabel = go.textContent;
var submitting = false;
var waiting = null;

form.addEventListener("submit", function(e) {
    if (submitting) {
        e.preventDefault();
        return;
    }
    submitting = true;
    go.disabled = true;
    go.textContent = "Finding the closest cards...";
    if (!waiting) {
        waiting = el("span", "custom-note", go.parentNode,
                     "If the matcher was asleep it takes about ten seconds to wake.");
    }
    waiting.hidden = false;
});

//a page restored from the back-forward cache comes back mid submit
window.addEventListener("pageshow", function(e) {
    if (e.persisted) {
        submitting = false;
        go.disabled = false;
        go.textContent = goLabel;
        if (waiting) {
            waiting.hidden = true;
        }
    }
});

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
    var body = new URLSearchParams(asked);
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
