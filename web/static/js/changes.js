//what a swap session did, painted onto partials/deckchanges.html.
//
//ONE painter for both pages, or they disagree about the heading and about
//whether you can put a card back. it takes the STATE rather than reading the
//shelf, because the callers hold it differently: the swap page has a live
//session in memory, /deck/view has an entry it looked up.

import { el, cardLink, pairCard, swapPair, fitText } from "dom";

var $ = function (id) { return document.getElementById(id); };

/* the same shapes parse_decklist strips server side, so a line reads here as
   the card it names and nothing else */
var LINE_SB = /^\s*SB:\s*/i;
var LINE_COUNT = /^\s*\d+\s*[xX]?\s+/;
var LINE_TRAILERS = /\s*(\([^)]*\)|\[[^\]]*\]|\*[^*]*\*|<[^>]*>)\s*/g;
var LINE_HASH = /\s+#.*$/;

function nameOf(line) {
    return line.replace(LINE_HASH, "").replace(LINE_SB, "").replace(LINE_COUNT, "")
               .replace(LINE_TRAILERS, " ").trim().toLowerCase();
}

/* the original text with the names SUBSTITUTED, never a list regenerated from
   our own data: the paste path drops duplicate counts on the way in, so a
   rebuilt list would hand back somebody's 30 basics as one line each. this way
   every count, section header and bit of their formatting stays put */
export function rebuild(text, swaps) {
    text = text || "";
    (swaps || []).forEach(function (s) {
        var out = s.out.name, into = s["in"].name;
        var want = out.toLowerCase();
        var lines = text.split("\n");
        var hit = -1;
        /*
            THE LINE THAT IS THAT CARD, not the first line the name appears
            inside. a substring scan rewrote the wrong card whenever one name
            contained another and the longer came first, which is exactly how
            exports grouped by type order them: swapping Fog turned "1 Fog Bank"
            into "1 Moment's Peace Bank", and Opt produced "Brainstormimus
            Prime". both are cards that do not exist
        */
        for (var i = 0; i < lines.length; i++) {
            if (nameOf(lines[i]) === want) { hit = i; break; }
        }
        /* a substring is a GUESS, so it is the fallback and never the start:
           reached only for a face name or a shape nameOf cannot read */
        if (hit === -1) {
            for (i = 0; i < lines.length; i++) {
                //case insensitive: an export may not match our capitalisation
                if (lines[i].toLowerCase().indexOf(want) !== -1) { hit = i; break; }
            }
        }
        if (hit === -1) {
            //say so rather than dropping the swap on the floor
            text += "\n# swap by hand: " + out + " -> " + into;
        } else {
            var re = new RegExp(out.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
            lines[hit] = lines[hit].replace(re, into);
            text = lines.join("\n");
        }
    });
    return text;
}

//one copy each: a swap is one slot leaving and one taking it back
export function addedList(swaps) {
    return (swaps || []).map(function (s) { return "1 " + s["in"].name; }).join("\n");
}

/*
    a deck travels in a hidden field, having no url, and jinja fills those with
    the list the page was POSTED: the only list the server knows. left unset, the
    back link and the mode rows hand out the deck as it was before the session,
    so swapping Wheel of Fortune and walking back in offers you Wheel of Fortune
    to change again.

    EVERY field, not just the mode rows: "back to this deck" means the deck
*/
export function carryList(text) {
    if (!text) return;
    document.querySelectorAll('input[name="list"], textarea[name="list"]')
        .forEach(function (f) { f.value = text; });
}

//a "put it back" hung off whatever row it belongs to
function undo(parent, label, i, fn) {
    var b = el("button", "swap-undo", parent, label);
    b.type = "button";
    b.addEventListener("click", function () { fn(i); });
}

//selects the text either way, so the fallback message is TRUE: the clipboard api
//is blocked on http origins and in some browsers
function wireCopy(btnId, boxId, said) {
    var btn = $(btnId);
    if (!btn || btn.dataset.wired) return;
    btn.dataset.wired = "1";
    btn.addEventListener("click", function () {
        var out = $(boxId);
        out.select();
        navigator.clipboard.writeText(out.value).then(function () {
            btn.textContent = said || "Copied";
        }).catch(function () { btn.textContent = "Press Ctrl+C"; });
    });
}

/*
    state is {swaps, added, newList, goal, text}: the four the shelf keeps plus
    the list the deck was IMPORTED as, which is what rebuild works from.

    opts.onRevert hangs a "put it back" on every pair and calls back with the
    index. the caller owns what undoing means, because it differs: the swap page
    has a queue and a trail to unwind too, /deck/view has only the shelf.

    opts.note is the sentence over the list, and only /deck/view has one worth
    printing. opts.addedNote is the one over the new cards, which /deck/swap
    reworded because its box holds one session rather than the whole deck

    state.added is NOT always the shelf's copy: /deck/swap passes this session's
    slice, /deck/view the lot
*/
export function paintChanges(state, opts) {
    opts = opts || {};
    var swaps = state.swaps || [];

    var box = $("deck-changes");
    if (box) {
        var list = $("deck-changes-list");
        var pairs = $("deck-changes-pairs");
        //rebuilt from scratch, never patched: a revert changes the indexes of
        //everything after it
        list.innerHTML = "";
        pairs.innerHTML = "";
        $("deck-changes-note").textContent = opts.note || "";
        swaps.forEach(function (s, i) {
            var li = el("li", "swap-made-row", list);
            li.appendChild(cardLink(s.out.name, "swap-made-out"));
            el("span", "swap-made-arrow", li, "→");
            li.appendChild(cardLink(s["in"].name, "swap-made-in"));

            var row = swapPair(pairs, s, opts.draw || pairCard);
            /* on the name row AND on the picture. the pair's names the card,
               since by then two of them are on screen */
            if (opts.onRevert) {
                undo(li, "put it back", i, opts.onRevert);
                undo(row, "Put " + s.out.name + " back", i, opts.onRevert);
            }
        });
        box.hidden = !swaps.length;
        //enhanceCardFrames marks what it has done, so reopening is safe
        var pics = $("deck-changes-pics");
        if (pics && !pics.dataset.wired) {
            pics.dataset.wired = "1";
            pics.addEventListener("toggle", function () {
                if (pics.open) enhanceCardFrames(pics);
            });
        }
        if (pics && pics.open) enhanceCardFrames(pics);
    }

    var added = state.added !== undefined ? state.added : addedList(swaps);
    var addedBox = $("deck-added-box");
    if (addedBox) {
        $("deck-added").value = added;
        addedBox.hidden = !added;
        //left alone without one, so the markup's own sentence stands
        var addedNote = $("deck-added-note");
        if (addedNote && opts.addedNote) addedNote.textContent = opts.addedNote;
        fitText($("deck-added"));
    }

    var listBox = $("deck-list");
    if (listBox) {
        if (state.newList) listBox.value = state.newList;
        /* BOTH branches: putting the last swap back makes this the imported deck
           again, and a note still saying "with the swaps above applied" would be
           describing swaps that are no longer there */
        var changed = state.newList && state.text && state.newList !== state.text;
        $("deck-list-note").textContent = changed
            ? "The deck as it stands, with the swaps above applied. Ready to paste back "
              + "wherever it came from."
            : "Every line this deck was read from, ready to paste back wherever it came from.";
        fitText(listBox);
    }

    wireCopy("deck-copy-list", "deck-list", "Copied");
    wireCopy("deck-copy-added", "deck-added", "Copied");
}
