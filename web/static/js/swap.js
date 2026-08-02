//the swap tool. reads its whole session out of the #swap-data island
//deck/swap.html renders, and needs manaFill from cards.js, which base.html
//loads above the scripts block. type="module" defers, which keeps that order

//bare specifiers, resolved by base.html's import map, so these arrive
//content-hashed rather than frozen unstamped in the year-long static cache
import { el, cardLink, resultCard, pairCard } from "dom";
import { wireReports } from "report";
//the end of a session is /deck/view's change blocks, so /deck/view's painter
//draws them. rebuild goes the other way, /deck/view needs it to put a card back
import { paintChanges, rebuild, addedList, carryList } from "changes";
//the shelf, through the one file that owns it: a second copy of the key here
//would be a second idea of which entry a deck is
import { find, patch } from "decks";
(function () {
    var dataEl = document.getElementById("swap-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);
    if (!D.queue.length) return;

    /*
        the deck grows and never shrinks. a card swapped IN has to be excluded
        from every later suggestion or the tool offers it twice, and a card
        swapped OUT has to stay excluded, or the next card's list suggests the
        thing just taken out. one list does both jobs
    */
    var deck = D.deck.slice();
    var at = 0;

    /* which saved deck this is, carried in a hidden field. it used to be found
       by matching the decklist against every entry two ways, because the key
       WAS the list, and the list moves during a session. an id does not */
    var entry = find(D.did);

    /* every swap this deck has EVER had, accumulating across sessions: only
       putting one back by hand takes it out. the ones carried in are already
       applied to the list the page is holding, which rebuild has to account
       for */
    var swaps = (entry && entry.swaps ? entry.swaps.slice() : []);

    /* where this session started in that list. "Just the new cards" is a
       shopping list, so it holds THIS visit's swaps: carried ones were copied
       and bought a visit ago. everything ever swapped is /deck/view's job.
       never trim `swaps` itself to get this, rebuild() replays all of them */
    var carried = swaps.length;

    /* the deck as IMPORTED, which is what a rebuild starts from. the list this
       page holds already has the carried swaps in it, so replaying them onto it
       would look for cards that left long ago */
    var baseList = (entry && entry.text) || D.text;

    /* the queue is deep and the SESSION is the batch: reaching the end offers
       the next batch rather than finishing */
    var limit = Math.min(D.batch, D.queue.length);

    /*
        every card's replacements once asked for. undefined means not asked,
        "pending" means in flight, an array means answered, and an EMPTY array
        is a real answer rather than a failure: nothing in the game does this
        card's job and moves the deck the right way
    */
    var cache = {};
    var nothing = [];

    /* enough to stay in front of someone reading a card without opening twelve
       connections to say hello */
    var LOOKAHEAD = 3;

    var $ = function (id) { return document.getElementById(id); };
    var options = $("swap-options"), note = $("swap-note");
    var skipBtn = $("swap-skip"), backBtn = $("swap-back");

    /*
        every decision this session has made, so the walk runs backwards too.

        each entry is the index it was made AT, which is NOT at-1 when it lands:
        show() steps silently over cards nothing could replace, so walking back
        by subtraction would stop on dead ends the forward walk hid
    */
    var trail = [];

    /* what the pickers were told about the card ON SCREEN only, cleared when
       the queue moves. the same three names /search puts in its url, because
       they reach the same two functions on the server */
    var picks = {lines: [], notags: [], yestags: []};

    function clearPicks() {
        picks = {lines: [], notags: [], yestags: []};
    }

    /* the difference between "nothing in the game does this" and "nothing does
       this ONCE YOU SAID that". the two get opposite behaviour in render() */
    function picked() {
        return !!(picks.lines.length || picks.notags.length || picks.yestags.length);
    }

    /* the card PLUS what the pickers were told, so narrowing to one line asks a
       new question rather than being handed the whole card's answer back */
    function keyFor(card) {
        return card.oracle_id + "|" + picks.lines.join(",") + "|" +
            picks.notags.join(",") + "|" + picks.yestags.join(",");
    }

    /* HTML, rendered by the server from the same partial /search draws its
       searched card with, so there is one description of this panel and not two */
    var panels = {};

    /* what each answer held back for costing the wrong amount. beside the list
       rather than inside it, because it is a fact about the ANSWER: three cards
       having turned eleven away is a different answer from three that turned
       none away, and the list alone cannot say which */
    var held = {};

    /* cached whichever way it comes back, so the walk and the look-ahead never
       ask twice and an empty answer is not retried forever */
    function load(i, force) {
        var card = D.queue[i];
        if (!card) return Promise.resolve();
        var key = i === at ? keyFor(card) : card.oracle_id + "|||";
        if (!force && cache[key] !== undefined) return Promise.resolve();
        cache[key] = "pending";
        return fetch("/deck/swap/cards", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({card: card.oracle_id, deck: deck, colors: D.colors,
                                  axis: D.axis, dir: D.dir,
                                  /* the look-ahead fetches the UNPICKED
                                     answer, which is what a card opens on */
                                  lines: i === at ? picks.lines : [],
                                  notags: i === at ? picks.notags : [],
                                  yestags: i === at ? picks.yestags : []})
        }).then(function (r) { return r.json(); }).then(function (j) {
            var cards = j.cards || [];
            cache[key] = cards;
            if (j.panel) panels[key] = j.panel;
            held[key] = {n: j.offband || 0, lo: j.mv_lo, hi: j.mv_hi};
            /* only the PLAIN question counts: narrowing to one line and finding
               nothing is the user's filter, not a fact about the card */
            if (!cards.length && key === card.oracle_id + "|||" && nothing.indexOf(card) === -1) {
                nothing.push(card);
            }
            /* the page may have been waiting on exactly this */
            if (i === at) show();
        }).catch(function () {
            /* leave it uncached so moving on and coming back can retry */
            delete cache[key];
            if (i === at) note.textContent = "Could not reach the card database. Try again in a moment.";
        });
    }

    function prefetch() {
        var n = 0;
        for (var i = at + 1; i < limit && n < LOOKAHEAD; i++) {
            if (cache[D.queue[i].oracle_id + "|||"] === undefined) { load(i); n++; }
        }
    }

    function show() {
        /* walk past anything known to have nowhere to go. silent, because those
           cards are named together at the end. judged on the PLAIN answer,
           since that is what the queue moves on */
        while (at < limit) {
            var known = cache[D.queue[at].oracle_id + "|||"];
            if (Array.isArray(known) && !known.length) { at++; continue; }
            break;
        }
        if (at >= limit) return finish();
        /* after the loop above, so this is the card on screen and not the one
           the walk started from */
        $("swap-at").textContent = at + 1;
        if (backBtn) backBtn.hidden = !trail.length;

        var card = D.queue[at];
        var key = keyFor(card);
        var out = $("swap-out-card");
        options.innerHTML = "";

        /* until the first answer lands there is no panel to draw, so the plain
           picture stands in */
        if (panels[key]) {
            out.innerHTML = panels[key];
            wirePanel(out);
        } else if (!out.querySelector(".searched-card")) {
            out.innerHTML = "";
            out.appendChild(build(card));
        }
        enhanceCardFrames(out);

        var got = offerable(cache[key]);
        if (Array.isArray(got)) {
            render(got, held[key]);
        } else {
            note.textContent = "Looking for replacements…";
            load(at);
        }
        prefetch();
    }

    /* what a reload does on /search: a click re-asks for this card's
       replacements with the narrower question attached, which is the same round
       trip the page already makes per card */
    function wirePanel(root) {
        root.querySelectorAll(".oracle-line").forEach(function (line) {
            line.onclick = function () {
                var idx = line.dataset.idx;
                var i = picks.lines.indexOf(idx);
                if (i === -1) picks.lines.push(idx); else picks.lines.splice(i, 1);
                repick();
            };
        });
        /* two lists because they answer two questions: notags is "ignore this",
           yestags is "the line picker guessed wrong, put it back" */
        root.querySelectorAll(".tag-chip").forEach(function (chip) {
            chip.onclick = function () {
                var state = chip.dataset.state;
                var key = (state === "aside" || state === "kept") ? "yestags" : "notags";
                var list = picks[key];
                var i = list.indexOf(chip.dataset.tag);
                if (i === -1) list.push(chip.dataset.tag); else list.splice(i, 1);
                repick();
            };
        });
        /* rewired every time and not once at load: the panel is redrawn on
           every card and every pick, and the old handlers went out with it */
        if (reports) {
            reports.fillTags(root);
            var link = root.querySelector("#report-tag");
            if (link) link.onclick = function (e) {
                e.preventDefault();
                reports.open("tag", null);
            };
        }
    }

    function repick() {
        note.textContent = "Looking for replacements…";
        options.innerHTML = "";
        if (moreBtn) moreBtn.hidden = true;
        load(at, true).then(function () { show(); });
    }

    /*
        anchorName is set for candidates and EMPTY for the outgoing card. it is
        what turns a bare figure into a verdict ("cheaper than Stasis"), and its
        absence is why the card leaving carries no arrows.

        the flag rides the same flag: a report says "this is a bad match for
        that", so the card being matched against has nothing to flag
    */
    function build(c, anchorName) {
        return resultCard(c, anchorName, {flag: !!anchorName});
    }

    /* the query string is BUILT rather than read, because this page is a POST
       result with no url of its own. it carries exactly what /feedback already
       reads, so the server needed no new shape, only the from=swap marker */
    var reports = wireReports({
        grid: options,
        query: function () {
            var p = new URLSearchParams();
            p.set("q", D.queue[at].name);
            if (picks.lines.length) p.set("lines", picks.lines.join(","));
            if (picks.notags.length) p.set("notags", picks.notags.join(","));
            if (picks.yestags.length) p.set("yestags", picks.yestags.join(","));
            //a complaint about a PROPOSED card, not about a search result
            p.set("from", "swap");
            return p.toString();
        }
    });

    /* revealed a batch of D.offer at a time out of the whole answer the server
       already sent: the query scanned two hundred rows per line either way, so
       reaching the bottom costs no round trip.
       `shown` is per card and resets in render() */
    var shown = 0;
    var moreBtn = $("swap-options-more");

    function paintOptions(cards) {
        var outName = D.queue[at].name;
        for (var i = options.children.length; i < Math.min(shown, cards.length); i++) {
            var c = cards[i];
            var card = build(c, outName);
            /* its own button rather than making the whole card a target, which
               would fight the card link inside it */
            var take_btn = el("button", "swap-take", card, "Swap this in");
            take_btn.type = "button";
            take_btn.addEventListener("click", (function (pick) {
                return function () { take(pick); };
            })(c));
            options.appendChild(card);
        }
        var left = cards.length - options.children.length;
        if (moreBtn) {
            moreBtn.hidden = left <= 0;
            moreBtn.textContent = left > 0
                ? "Show " + Math.min(D.offer, left) + " more" + (left > D.offer ? "" : " (the last)")
                : "";
        }
        enhanceCardFrames(options);
    }

    /* without this the tool answers "one card" and looks out of ideas, when it
       turned eleven away for costing the wrong amount */
    function costNote(h) {
        if (!h || !h.n || h.lo === null || h.lo === undefined) return "";
        return " " + h.n + (h.n === 1 ? " other match was" : " other matches were")
            + " left out for costing outside " + Math.max(0, h.lo) + " to " + h.hi
            + ": what a card does is not what it costs, and the slot has a curve.";
    }

    /* the cache is filled by the LOOK-AHEAD, up to three cards before you get
       there, so an answer can predate a swap made since: the server excluded
       the deck as it stood when it was asked. filtered on the way out rather
       than by refetching, or every swap costs three round trips. a reverted
       card leaves `deck` and becomes offerable again, which is right */
    function offerable(cards) {
        if (!Array.isArray(cards)) return cards;
        return cards.filter(function (c) { return deck.indexOf(c.oracle_id) === -1; });
    }

    function render(cards, h) {
        options.innerHTML = "";
        if (!cards.length) {
            /* WHY it is empty decides what happens next. empty on the card's own
               answer is a fact about the card, so the queue moves on. emptied by
               the PICKERS is the user's own filter, so it stays put and says so */
            if (!picked()) { at++; return show(); }
            note.textContent = "Nothing matches with those lines and tags."
                + costNote(h) + " Widen it above, or keep the card you have.";
            if (moreBtn) moreBtn.hidden = true;
            return;
        }
        note.textContent = "Pick one to swap it in, or keep the card you have."
            + costNote(h);
        shown = D.offer;
        paintOptions(cards);
    }

    if (moreBtn) moreBtn.addEventListener("click", function () {
        var got = offerable(cache[keyFor(D.queue[at])]);
        if (!Array.isArray(got)) return;
        shown = Math.min(shown + D.offer, got.length);
        paintOptions(got);
    });

    function take(c) {
        /* the WHOLE card on both sides, not the names: the review draws them as
           pictures and there is no url to ask about the outgoing one again */
        swaps.push({out: D.queue[at], in: c, match: c.match});
        deck.push(c.oracle_id);
        trail.push({at: at, took: true});
        /* on the decision, not at the end of the batch: this tool is built to be
           walked a card at a time and left */
        remember();
        at++;
        clearPicks();
        show();
    }

    /* a swap is unwound the same way revert() does it below, or one decision
       could be undone two ways with two results. the card that went OUT is not
       requeued: it never left the queue, and the trail holds its index */
    function back() {
        if (!trail.length) return;
        var step = trail.pop();
        if (step.took) {
            var s = swaps.pop();
            var at_in = deck.indexOf(s["in"].oracle_id);
            if (at_in > -1) deck.splice(at_in, 1);
            /* undoing a swap is a decision too, and the shelf has to lose it */
            remember();
        }
        at = step.at;
        clearPicks();
        /* going back means the walk is live again */
        $("swap-done").hidden = true;
        $("swap-batch-note").hidden = true;
        $("swap-live").hidden = false;
        show();
    }

    /* the card that went out is NOT requeued: rewinding the queue would reorder
       everything decided after this point. the swap just stops existing */
    function revert(i) {
        var s = swaps[i];
        var at_in = deck.indexOf(s["in"].oracle_id);
        if (at_in > -1) deck.splice(at_in, 1);
        swaps.splice(i, 1);
        //putting a CARRIED one back shortens the block this session starts
        //after, and without this the new list loses its first card
        if (i < carried) carried--;
        /* the step has to go too, or going back afterwards unwinds a swap that
           is no longer there. matched on the CARD, never on position: the
           review's order and the trail's agree today and nothing enforces it.
           a swap carried in from an earlier session has no step here, and the
           loop finding nothing is right */
        for (var t = 0; t < trail.length; t++) {
            if (trail[t].took && D.queue[trail[t].at] === s.out) {
                trail[t].took = false;
                break;
            }
        }
        finish();
    }

    skipBtn.addEventListener("click", function () {
        trail.push({at: at, took: false});
        at++;
        clearPicks();
        show();
    });
    if (backBtn) backBtn.addEventListener("click", back);

    /* where the next batch starts and what was decided by then. finish()
       compares against these to tell "that did nothing" apart from "that checked
       twelve cards and none had anywhere to go" */
    var batchFrom = null;
    var batchSwaps = 0;

    $("swap-keep-going").addEventListener("click", function () {
        batchFrom = limit;
        batchSwaps = swaps.length;
        limit = Math.min(limit + D.batch, D.queue.length);
        $("swap-checked").textContent = limit;
        $("swap-more").hidden = true;
        $("swap-done").hidden = true;
        $("swap-batch-note").hidden = true;
        /* finish() rebuilds it from the full list, so leaving it up during the
           batch shows a stale answer next to live cards */
        $("swap-nothing").hidden = true;
        $("swap-live").hidden = false;
        show();
    });

    /* bound once, NOT in finish(): that runs per batch, so binding there stacked
       a listener each time and redrew the frames once per batch on one click */
    $("swap-nothing-box").addEventListener("toggle", function () {
        if (this.open) enhanceCardFrames(this);
    });

    function finish() {
        /* the end of a BATCH, not necessarily of the queue */
        var more_left = D.queue.length - limit;
        if (more_left > 0) {
            $("swap-more-left").textContent = Math.min(D.batch, more_left);
            $("swap-more").hidden = false;
        } else {
            /* without this branch the button vanished silently when the queue ran
               out, and was reported as broken */
            $("swap-more").hidden = true;
        }
        /* the walk stopped on the last card, which is the whole batch */
        $("swap-at").textContent = Math.min(at, limit);

        /* a batch that found nothing puts the page back exactly where it was, so
           without a word here the button reads as broken */
        var say = "";
        if (batchFrom !== null) {
            var walked = limit - batchFrom;
            var got = swaps.length - batchSwaps;
            say = got
                ? "Checked " + walked + " more card" + (walked === 1 ? "" : "s")
                  + " and found " + got + " swap" + (got === 1 ? "" : "s") + "."
                : "Checked " + walked + " more card" + (walked === 1 ? "" : "s")
                  + ". Nothing in the game does what any of them do and moves the deck "
                  + D.goal + ", so there was nothing to offer. They are listed below.";
            batchFrom = null;
        }
        /* on EVERY finish and not only after a press: "there is nothing more to
           load" is the fact the vanishing button failed to communicate */
        if (more_left <= 0) {
            say += (say ? " " : "") + "That is every card in this deck worth checking, all "
                + D.queue.length + " of them. There are no more to load.";
        }
        if (say) {
            $("swap-batch-note").textContent = say;
            $("swap-batch-note").hidden = false;
        }
        $("swap-live").hidden = true;
        var done = $("swap-done");
        done.hidden = false;

        /* named together rather than one dead end at a time on the way through */
        if (nothing.length) {
            /* the heading says no card does what these do, which the mana value
               band can turn into a lie, so the count that makes it one goes
               next to it */
            var costly = nothing.filter(function (c) {
                var h = held[c.oracle_id + "|||"];
                return h && h.n;
            }).length;
            var costEl = $("swap-nothing-cost");
            if (costEl) {
                costEl.textContent = costly
                    ? (costly === 1 ? "One of them has" : costly + " of them have")
                      + " matches that do the job at a different mana value, held"
                      + " back because a slot has a curve."
                    : "";
            }
            var box = $("swap-nothing"), list = $("swap-nothing-list");
            var pics = $("swap-nothing-cards");
            list.innerHTML = "";
            pics.innerHTML = "";
            nothing.forEach(function (c) {
                el("li", "swap-made-row", list).appendChild(cardLink(c.name, "swap-made-out"));
                /* no anchor name: there is no card it lost to */
                pics.appendChild(build(c, ""));
            });
            box.hidden = false;
        }

        /* build and not pairCard: a card weighed against another carries its
           match percent and verdicts, which is this page's question alone.
           rebuilt from the deck as IMPORTED, because the list this page holds
           would apply the carried swaps twice */
        var built = rebuild(baseList, swaps);
        /* THIS VISIT on both blocks, matching the new cards box beside it. the
           whole history is /deck/view's, and the note below points at it */
        var mine = swaps.slice(carried);
        paintChanges({swaps: mine, added: addedList(mine),
                      newList: built, text: D.text, goal: D.goal},
                     {draw: build,
                      //offset back into the full list, which is what a revert acts on
                      onRevert: function (i) { revert(i + carried); },
                      addedNote: "The cards this session added, on their own.",
                      note: carried
                          ? carried + " earlier change" + (carried === 1 ? "" : "s")
                            + " to this deck " + (carried === 1 ? "is" : "are")
                            + " not listed here. View it has every one."
                          : ""});

        /* a deck the shelf could not take (full, or private browsing) has no
           /deck/view holding its list, so this is the only copy there is */
        if (!entry) {
            var listBox = $("deck-list-box");
            if (listBox) listBox.hidden = false;
        }

        /* the fold is server rendered from the deck that ARRIVED, so every swap
           has left a tile showing a card no longer in it */
        repaintDeck();

        /* jinja rendered every way on with the list the session opened on,
           because at build time that is the only list there is. this is the
           moment the new one exists */
        carryList(built);

        remember();
    }

    /* only what the review needs to draw a card, picking being over by now */
    function keep(c) {
        /* the verdicts ride along: the server worked them out against the card
           being replaced. only the card coming IN carries them, since the one
           going out is what they were measured against */
        return {oracle_id: c.oracle_id, name: c.name, image: c.image,
                image_back: c.image_back || "",
                sideways: !!c.sideways, flip: !!c.flip,
                scryfall_uri: c.scryfall_uri, price: c.price,
                rank: c.rank, salt: c.salt, age: c.age,
                price_vs: c.price_vs || "", rank_vs: c.rank_vs || "",
                salt_vs: c.salt_vs || "", age_vs: c.age_vs || ""};
    }

    /*
        the session, onto the same localStorage shelf the hub keeps. the server
        stores nothing.

        RUNS ON EVERY DECISION, not at the end of a batch: it used to wait for
        finish(), so walking away mid session lost every swap made in it.

        the two lists are COMPUTED here rather than read off the page, because
        the boxes holding them are drawn by finish() and mid session hold the
        last batch's answer or nothing
    */
    function remember() {
        /* no entry means this deck is not on the shelf: reached from a precon, or
           deleted from the hub in another tab. the session still works, it just
           has nowhere to be written */
        if (!entry) return;
        patch(D.did, {
            swaps: swaps.map(function (s) {
                return {out: keep(s.out), "in": keep(s["in"])};
            }),
            goal: D.goal,
            newList: rebuild(baseList, swaps),
            added: addedList(swaps)
        });
    }

    /* walks from the ORIGINAL tile every time rather than patching the last
       paint, which is what makes a revert work: putting a card back is this
       running again with one fewer swap in the list */
    var bornTiles = null;

    function repaintDeck() {
        var grid = document.querySelector(".deck-card-fold .deck-card-grid");
        if (!grid) return;
        /* kept as MARKUP, captured before anything is rewritten, so a revert
           puts the server's own tile back rather than a redrawing of it */
        if (!bornTiles) {
            bornTiles = {};
            Array.prototype.slice.call(grid.children).forEach(function (t) {
                t.dataset.born = t.dataset.oid;
                bornTiles[t.dataset.oid] = t.outerHTML;
            });
        }
        var byOut = {};
        swaps.forEach(function (s) { byOut[s.out.oracle_id] = s; });

        Array.prototype.slice.call(grid.children).forEach(function (tile) {
            var born = tile.dataset.born;
            var swap = byOut[born];
            var showing = tile.dataset.oid;
            /* already right, either way round */
            if (swap ? showing === swap["in"].oracle_id : showing === born) return;

            var fresh;
            if (swap) {
                fresh = pairCard(swap["in"]);
                fresh.dataset.oid = swap["in"].oracle_id || "";
                el("span", "deck-card-swapped", fresh.querySelector(".result-name"), "*")
                    .title = "swapped in for " + swap.out.name;
            } else {
                var holder = document.createElement("div");
                holder.innerHTML = bornTiles[born] || "";
                fresh = holder.firstElementChild;
                if (!fresh) return;
            }
            fresh.dataset.born = born;
            /* is-over is a fact about POSITION, and a swap does not move a tile */
            if (tile.classList.contains("is-over")) fresh.classList.add("is-over");
            tile.replaceWith(fresh);
        });
        enhanceCardFrames(grid);
    }

    /* the copy buttons are wired by paintChanges, with the rest of the partial */

    show();
})();
