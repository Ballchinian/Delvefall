//what a swap session did, painted onto partials/deckchanges.html.
//
//ONE painter for both pages. /deck/view and the end of /deck/swap were drawing
//the same three blocks from the same four shelf fields with two builders, which
//is how they ended up disagreeing about what the heading said and about whether
//you could put a card back.
//
//it takes the state rather than reading the shelf itself, because the two
//callers hold it differently: the swap page has a live session in memory that
//changes as you walk it, /deck/view has an entry it looked up. the shapes are
//the same four fields either way, which is the whole reason this works.

import { el, cardLink, pairCard, swapPair, fitText } from "dom";

var $ = function (id) { return document.getElementById(id); };

//the deck's list with a set of swaps applied, starting from the list as it was
//imported.
//
//shared with /deck/view, which needs the same arithmetic to put a card back:
//undoing a swap means rebuilding the list without it, and rebuilding from the
//current list would leave the card that was put back in there twice.
/*
    the name part of one line: the count off the front, the exporter's trailers
    off the back. the same shapes parse_decklist strips server side, so a line
    reads here as the card it names and nothing else
*/
var LINE_SB = /^\s*SB:\s*/i;
var LINE_COUNT = /^\s*\d+\s*[xX]?\s+/;
var LINE_TRAILERS = /\s*(\([^)]*\)|\[[^\]]*\]|\*[^*]*\*|<[^>]*>)\s*/g;
var LINE_HASH = /\s+#.*$/;

function nameOf(line) {
    return line.replace(LINE_HASH, "").replace(LINE_SB, "").replace(LINE_COUNT, "")
               .replace(LINE_TRAILERS, " ").trim().toLowerCase();
}

export function rebuild(text, swaps) {
    text = text || "";
    (swaps || []).forEach(function (s) {
        var out = s.out.name, into = s["in"].name;
        var want = out.toLowerCase();
        var lines = text.split("\n");
        var hit = -1;
        /*
            THE LINE THAT IS THAT CARD, not the first line the name appears
            anywhere inside. it used to scan for a substring, which rewrote the
            wrong card whenever one name contained another and the longer one
            came first. exports grouped by type put them in exactly that order:
            with Fog Bank under creatures and Fog under instants, swapping out
            Fog turned "1 Fog Bank" into "1 Moment's Peace Bank" and left the
            real Fog in the deck. swapping Opt produced "Brainstormimus Prime".
            both are cards that do not exist, in somebody's exported list
        */
        for (var i = 0; i < lines.length; i++) {
            if (nameOf(lines[i]) === want) { hit = i; break; }
        }
        /* only when no line IS that card: a face name, or a shape nameOf cannot
           read. a substring is a guess, so it is what we fall back to rather
           than what we start from */
        if (hit === -1) {
            for (i = 0; i < lines.length; i++) {
                //case insensitive, because an export may not match our
                //capitalisation and the parser normalised it away anyway
                if (lines[i].toLowerCase().indexOf(want) !== -1) { hit = i; break; }
            }
        }
        if (hit === -1) {
            //a name we cannot find in the raw text (a face name, or a collector
            //number wedged in the middle). say so rather than dropping the swap
            //on the floor
            text += "\n# swap by hand: " + out + " -> " + into;
        } else {
            var re = new RegExp(out.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
            lines[hit] = lines[hit].replace(re, into);
            text = lines.join("\n");
        }
    });
    return text;
}

//the cards a set of swaps brought in, as a decklist. one copy each, because
//that is what a swap is: the card leaving took one slot and the card arriving
//takes it back
export function addedList(swaps) {
    return (swaps || []).map(function (s) { return "1 " + s["in"].name; }).join("\n");
}

/*
    point every form that carries this deck onward at the deck AS IT NOW STANDS.

    a deck travels in a hidden field, because it has no url. jinja fills those
    fields with the list the PAGE was posted, which is the only list the server
    knows about, and a deck that has been through the swap tool has moved on
    from it in a place the server never hears about.

    left unset, the back link and the mode rows hand out the deck as it was
    before the session: swap Wheel of Fortune for Incendiary Command, walk back
    in through any of them, and the tool offers you Wheel of Fortune to change
    again, because that genuinely is the deck it was given.

    every field and not just the mode rows. "back to this deck" means the deck,
    and after a session the deck is the one with the swaps in it.
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

//one copier for both boxes. it selects the text either way, so the fallback
//message is true: the clipboard api is blocked on http origins and in some
//browsers, and by then the textarea is already selected
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
    draw the three blocks.

    state is {swaps, added, newList, goal, text}: the four the shelf keeps plus
    the list the deck was imported as, which is what rebuild works from.

    opts.onRevert, when given, hangs a "put it back" on every pair and calls
    back with the index. the caller owns what undoing means, because it differs:
    the swap page has a queue and a trail to unwind as well, /deck/view has only
    the shelf. both then call this again with the new state.

    opts.note is the sentence over the list, and only /deck/view has one worth
    printing. on the swap page the swaps are what you just spent the session
    making, and counting them back is the page narrating your own last move.
*/
export function paintChanges(state, opts) {
    opts = opts || {};
    var swaps = state.swaps || [];

    var box = $("deck-changes");
    if (box) {
        var list = $("deck-changes-list");
        var pairs = $("deck-changes-pairs");
        //rebuilt from scratch rather than patched: a revert changes the
        //indexes of everything after it, and one path that is always right
        //beats two that have to agree
        list.innerHTML = "";
        pairs.innerHTML = "";
        $("deck-changes-note").textContent = opts.note || "";
        swaps.forEach(function (s, i) {
            var li = el("li", "swap-made-row", list);
            li.appendChild(cardLink(s.out.name, "swap-made-out"));
            el("span", "swap-made-arrow", li, "→");
            li.appendChild(cardLink(s["in"].name, "swap-made-in"));

            var row = swapPair(pairs, s, opts.draw || pairCard);
            /* on the name row AND on the picture, because they are read at
               different moments: the list is the scan, the pair is the second
               look you take when you are not sure. the pair's names the card,
               since by then you are looking at two of them */
            if (opts.onRevert) {
                undo(li, "put it back", i, opts.onRevert);
                undo(row, "Put " + s.out.name + " back", i, opts.onRevert);
            }
        });
        box.hidden = !swaps.length;
        //the frames only exist once the fold has been built, and
        //enhanceCardFrames marks what it has done, so opening and closing it
        //repeatedly is safe
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
        fitText($("deck-added"));
    }

    var listBox = $("deck-list");
    if (listBox) {
        if (state.newList) listBox.value = state.newList;
        /* the list on the page is whatever this deck is holding now. say so
           when that is not what was imported, because "the whole list" is
           ambiguous on a deck that has been changed and the difference is the
           whole point of having opened this page.
           BOTH branches, because putting the last swap back makes the deck the
           one that was imported again, and a note left saying "with the swaps
           above applied" would be describing swaps that are no longer there */
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
