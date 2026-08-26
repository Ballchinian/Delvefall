/*
    the rotate / flip / transform controls. any .card-frame with these gets wired:
      data-sideways="1"  battles and split cards. they START vertical so the grid
                         stays uniform, "rotate" turns them readable
      data-flip="1"      kamigawa flip cards, turned 180
      data-back="url"    double faced. backs are always upright, so transforming
                         DROPS any rotation

    pages that add frames after load call enhanceCardFrames again; the wired
    marker keeps reruns free
*/
function enhanceCardFrames(root) {
    root.querySelectorAll(".card-frame").forEach(function(frame) {
        if (frame.dataset.wired) {
            return;
        }
        frame.dataset.wired = "1";
        var sideways = frame.dataset.sideways == "1";
        var flip = frame.dataset.flip == "1";
        var back = frame.dataset.back || "";
        if (!sideways && !flip && !back) {
            return;  //a plain card, nothing to offer
        }
        var img = frame.querySelector("img");
        var overlay = document.createElement("div");
        overlay.className = "card-overlay";

        var rot = null;
        if (sideways || flip) {
            rot = document.createElement("button");
            rot.textContent = flip ? "↻ flip" : "↻ rotate";
            rot.onclick = function() {
                frame.classList.toggle(flip ? "flipped" : "sideways");
            };
            overlay.appendChild(rot);
        }

        if (back) {
            var front = img.src;
            var showingBack = false;
            var backImg = null;
            //the button only appears on hover, so a fetch on mouseenter has
            //usually arrived before any click
            var preload = function() {
                if (!backImg) {
                    backImg = new Image();
                    backImg.src = back;
                }
            };
            frame.addEventListener("mouseenter", preload, { once: true });

            var showFace = function() {
                img.src = showingBack ? back : front;
                frame.classList.remove("flipped");
                frame.classList.remove("sideways");
                if (rot) {
                    rot.style.display = showingBack ? "none" : "";
                }
            };
            var turn = document.createElement("button");
            turn.textContent = "⇄ transform";
            turn.onclick = function() {
                showingBack = !showingBack;
                preload();
                if (showingBack && !backImg.complete) {
                    //hold the front until the back is ready: swapping to a
                    //still-loading image is a blank frame
                    backImg.onload = function() {
                        if (showingBack) {
                            showFace();
                        }
                    };
                } else {
                    showFace();
                }
            };
            overlay.appendChild(turn);
        }

        frame.appendChild(overlay);
    });
}

/*
    the client twin of app.py's mana filter, for rules text arriving as json.
    built as DOM NODES, so a line full of quotes cannot break out of the markup.
    the token -> url map rides in as window.MANA_URLS, and a token with no entry
    stays text, same as the server side
*/
function manaFill(el, text) {
    var re = /\{([^}]+)\}/g;
    var last = 0;
    var m;
    while ((m = re.exec(text)) !== null) {
        var url = (window.MANA_URLS || {})[m[1].replace(/\//g, "")];
        if (!url) {
            continue;
        }
        el.appendChild(document.createTextNode(text.slice(last, m.index)));
        var img = document.createElement("img");
        img.src = url;
        img.alt = m[0];
        img.width = 16;
        img.height = 16;
        el.appendChild(img);
        last = m.index + m[0].length;
    }
    el.appendChild(document.createTextNode(text.slice(last)));
}

/*
    the figures on a card tile explain themselves on hover, and until 2026-08-26
    each tile carried its own copy of the sentence: at 361 cards a precon page
    shipped the same four sentences 361 times, 149kb of the 831kb it weighed.

    the text sits here once and is written onto an element the first time a
    pointer reaches it, so the native tooltip and the tap bubble below both read
    it exactly as they always have.

    this is the HOVER half only. the legend in standing.html is the half that
    needs no script, which is the rule that partial is built on: with javascript
    off the page still says what every figure means, it just says it in one place
    instead of on every tile
*/
var CARD_TIPS = {
    originality: "originality: one minus how close this card's nearest match anywhere in Magic gets, so a card at 0.30 has something out there 70% like it",
    rank: "play rate: edhrec's rank for how often this card is played in commander, where #1 is the most played card in the format",
    //no figure in the sentence, unlike the per-tile copy it replaces: the card's
    //own salt is printed beside the mark, so one string serves every tile
    salt: "salt out of about 3, from edhrec's salt survey, where players vote on the cards they least enjoy facing",
    age: "card age: how long ago this card was first printed, counted from its earliest printing, so a reprint does not make an old card new"
};

function fillCardTip(el) {
    if (el && el.dataset.tip && !el.title) {
        el.title = CARD_TIPS[el.dataset.tip] || "";
    }
}

//pointerover and not mouseover: one event covers the mouse and the first touch,
//and it lands long before the second a native tooltip waits before showing
document.addEventListener("pointerover", function(e) {
    fillCardTip(e.target.closest("[data-tip]"));
});

/*
    title tooltips do not exist on touch screens, and the ones on results carry
    real information, so a tap shows the title in a bubble instead. mice keep the
    native tooltips and never enter this path
*/
document.addEventListener("click", function(e) {
    if (window.matchMedia("(hover: hover)").matches) {
        return;
    }
    var open = document.querySelector(".tap-tip");
    var el = e.target.closest(".match-line, .more-lines, .concept-tags, .result-rank, .percent, .price-vs, .rank-vs");
    //a tap fires no pointerover on some browsers, so the title may not be filled
    //in yet when the guard below asks for it
    fillCardTip(el);
    if (open) {
        var same = open.anchorEl == el;
        open.remove();
        if (same) {
            return;
        }
    }
    //links and buttons keep working: /unique's "what comes closest?" link lives
    //inside a .more-lines
    if (!el || !el.title || e.target.closest("a, button")) {
        return;
    }
    var tip = document.createElement("div");
    tip.className = "tap-tip";
    tip.textContent = el.title;
    tip.anchorEl = el;
    el.after(tip);
});

document.addEventListener("DOMContentLoaded", function() {
    enhanceCardFrames(document);
});
