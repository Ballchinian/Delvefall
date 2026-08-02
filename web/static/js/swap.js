//the swap tool. reads its whole session out of the #swap-data island
//deck/swap.html renders, and needs manaFill from cards.js, which base.html
//loads above the scripts block. type="module" defers, which keeps that order

//bare specifiers, resolved by base.html's import map, so these arrive
//content-hashed rather than frozen unstamped in the year-long static cache
import { el, cardLink, resultCard } from "dom";
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

    /* wired before the empty-queue bail below, so a deck with nothing to move
       can still pick another metric. the submit button is the no-js fallback */
    var axisForm = document.querySelector(".deck-swap-axis");
    if (axisForm) {
        var axisGo = document.getElementById("swap-axis-go");
        if (axisGo) axisGo.hidden = true;
        document.getElementById("swap-axis-pick").addEventListener("change", function () {
            axisForm.requestSubmit();
        });
    }
    if (!D.queue.length) return;

    /*
        the deck grows and never shrinks. a card swapped IN has to be excluded
        from every later suggestion or the tool offers it twice, and a card
        swapped OUT has to stay excluded, or the next card's list suggests the
        thing just taken out. one list does both jobs
    */
    var deck = D.deck.slice();

    /* which saved deck this is, carried in a hidden field. it used to be found
       by matching the decklist against every entry two ways, because the key
       WAS the list, and the list moves during a session. an id does not */
    var entry = find(D.did);

    /* every swap this deck has EVER had, accumulating across sessions: only
       putting one back by hand takes it out. the ones carried in are already
       applied to the list the page is holding, which rebuild has to account
       for */
    var swaps = (entry && entry.swaps ? entry.swaps.slice() : []);

    /* the deck as IMPORTED, which is what a rebuild starts from. the list this
       page holds already has the carried swaps in it, so replaying them onto it
       would look for cards that left long ago */
    var baseList = (entry && entry.text) || D.text;

    /* the saved walk, kept per AXIS: a different metric is a different queue, so
       arriving on one starts a new one. the only other reset is the button */
    var session = (entry && entry.session && entry.session.axis === D.axis &&
                   entry.session.dir === D.dir) ? entry.session : null;

    /*
        THE WALK IS A FIXED LIST, settled when it started.

        the server sorts the deck as it stands now, so rebuilding the queue every
        visit reordered it under the trail: the position, the count and every step
        back pointed at a different card than the visit before, and a walk twelve
        cards in reopened at "card 34 of 36".

        the cards swapped OUT during the walk are put back in their places off the
        shelf. they have left the deck, so the server cannot send them, and
        without them a step back lands on the wrong card or nowhere
    */
    var queue = D.queue;
    if (session && session.order) {
        var byId = {};
        D.queue.forEach(function (c) { byId[c.oracle_id] = c; });
        //the shelf's own objects, so revert() can still match a swap on identity
        swaps.forEach(function (s) {
            if (!byId[s.out.oracle_id]) byId[s.out.oracle_id] = s.out;
        });
        queue = session.order.map(function (id) { return byId[id]; }).filter(Boolean);
    }
    if (!queue.length) return;

    /* everything saved is a CARD ID, so a queue that lost a card (the list edited
       elsewhere) shifts nothing: the ids that survive still resolve */
    var index = {};
    queue.forEach(function (c, i) { index[c.oracle_id] = i; });

    var at = 0;

    /* where this WALK started in the swap list, not where this page load did:
       "your swaps" is the walk's, so reopening a finished one still shows what it
       did. never trim `swaps` itself to get it, rebuild() replays all of them */
    var carried = swaps.length;

    /* the queue is deep and the BATCH is what a sitting offers: reaching the end
       offers the next batch rather than finishing */
    var limit = Math.min(D.batch, queue.length);

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
        every decision the walk has made, so it runs backwards too, across visits
        as well as within one.

        each entry is the index it was made AT, which is NOT at-1 when it lands:
        show() steps silently over cards nothing could replace, so walking back
        by subtraction would stop on dead ends the forward walk hid
    */
    var trail = [];

    /*
        the saved walk, put back. everything comes off ids and is resolved against
        the queue built above, so an id that no longer resolves drops out instead
        of shifting the ones that do.

        an empty `at` is a walk that reached the end of its batch, which lands on
        the review rather than on a card
    */
    if (session) {
        if (session.carried !== undefined) carried = session.carried;
        limit = Math.min(Math.max(session.limit || 0, D.batch), queue.length);
        at = index[session.at] !== undefined ? index[session.at] : limit;
        trail = (session.trail || []).map(function (t) {
            return {at: index[t.id], took: t.took};
        }).filter(function (t) { return t.at !== undefined; });
        nothing = (session.nothing || []).map(function (id) { return queue[index[id]]; })
                                         .filter(Boolean);
    }

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
        var card = queue[i];
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
                //a dead end is part of the walk, so it has to survive leaving
                remember();
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
            if (cache[queue[i].oracle_id + "|||"] === undefined) { load(i); n++; }
        }
    }

    function show() {
        /* walk past anything known to have nowhere to go. silent, because those
           cards are named together at the end. judged on the PLAIN answer,
           since that is what the queue moves on */
        while (at < limit) {
            var known = cache[queue[at].oracle_id + "|||"];
            if (Array.isArray(known) && !known.length) { at++; continue; }
            break;
        }
        if (at >= limit) return finish();
        /* after the loop above, so this is the card on screen and not the one
           the walk started from */
        $("swap-at").textContent = at + 1;
        $("swap-live").hidden = false;
        if (backBtn) backBtn.hidden = !trail.length;
        /* the loop above can have moved the place without a decision being made,
           so the save has to follow the render and not only the button */
        remember();

        var card = queue[at];
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
            p.set("q", queue[at].name);
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
        var outName = queue[at].name;
        for (var i = options.children.length; i < Math.min(shown, cards.length); i++) {
            var c = cards[i];
            var card = build(c, outName);
            /* its own button rather than making the whole card a target, which
               would fight the card link inside it */
            var take_btn = el("button", "swap-take", card, "Swap this in");
            take_btn.type = "button";
            /* twelve buttons reading "Swap this in" are twelve identical stops
               in a tab order. the visible words stay inside the label */
            take_btn.setAttribute("aria-label", "Swap this in, " + c.name + ", replacing "
                                  + outName);
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
        var got = offerable(cache[keyFor(queue[at])]);
        if (!Array.isArray(got)) return;
        shown = Math.min(shown + D.offer, got.length);
        paintOptions(got);
    });

    /*
        the card being decided, brought back only when it is NOT on screen.

        no breakpoint decides this, the viewport does: on a wide screen the card
        and its options fit together, nothing is off screen and nothing moves,
        which is what keeps the cursor over the button it just pressed. on a
        phone the card is a screen above the option that was taken, so it comes
        up. never called from revert(), whose button is inside the block it
        would scroll away from
    */
    var SMOOTH = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function bringUp() {
        var live = $("swap-live");
        var node = live.hidden ? $("swap-done") : live;
        if (!node) return;
        var top = node.getBoundingClientRect().top;
        if (top >= 0 && top <= window.innerHeight) return;
        window.scrollTo({top: Math.max(0, window.scrollY + top - 12),
                         behavior: SMOOTH ? "smooth" : "auto"});
    }

    function take(c) {
        /* the WHOLE card on both sides, not the names: the review draws them as
           pictures and there is no url to ask about the outgoing one again */
        swaps.push({out: queue[at], in: c, match: c.match});
        deck.push(c.oracle_id);
        trail.push({at: at, took: true});
        at++;
        clearPicks();
        show();
        bringUp();
    }

    /*
        a swap is unwound the same way revert() does it below, or one decision
        could be undone two ways with two results.

        the card that went OUT is not requeued: it never left the QUEUE, which is
        fixed for the walk, and the trail holds its index. that is what lets this
        step back into a decision made a visit ago
    */
    function back() {
        if (!trail.length) return;
        var step = trail.pop();
        if (step.took) {
            /* the trail and the swap list are both in decision order, so the
               swap being unwound is the last one this walk made */
            var s = swaps.pop();
            var at_in = deck.indexOf(s["in"].oracle_id);
            if (at_in > -1) deck.splice(at_in, 1);
        }
        at = step.at;
        clearPicks();
        /* going back means the walk is live again */
        $("swap-done").hidden = true;
        $("swap-live").hidden = false;
        show();
        bringUp();
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
            if (trail[t].took && queue[trail[t].at] === s.out) {
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
        bringUp();
    });
    if (backBtn) backBtn.addEventListener("click", back);

    /*
        the second of the two ways to clear a walk, and the guarded one. the
        other is picking a different metric, which arrives as a new page.

        it forgets the PLACE and not the swaps: those are the deck's now, and
        putting one back is its own control on every pair above
    */
    var restartBtn = $("swap-restart");

    function markPlace() {
        if (restartBtn) restartBtn.hidden = !(at || trail.length);
    }

    if (restartBtn) restartBtn.addEventListener("click", function () {
        if (!window.confirm("Start again from the worst card?\n\nEvery swap you have "
                            + "already made stays in the deck. What is forgotten is your "
                            + "place in the walk, so the cards you kept get offered "
                            + "again.")) return;
        /* the queue itself is resettled here: a walk started again is started
           against the deck AS IT NOW STANDS, swaps and all */
        queue = D.queue;
        index = {};
        queue.forEach(function (c, i) { index[c.oracle_id] = i; });
        trail = [];
        nothing = [];
        cache = {};
        at = 0;
        carried = swaps.length;
        limit = Math.min(D.batch, queue.length);
        $("swap-checked").textContent = limit;
        $("swap-done").hidden = true;
        $("swap-nothing").hidden = true;
        $("swap-more").hidden = true;
        $("swap-live").hidden = false;
        clearPicks();
        remember();
        show();
        bringUp();
    });

    $("swap-keep-going").addEventListener("click", function () {
        limit = Math.min(limit + D.batch, queue.length);
        $("swap-checked").textContent = limit;
        $("swap-more").hidden = true;
        $("swap-done").hidden = true;
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
        var more_left = queue.length - limit;
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
        /* THIS WALK on both blocks, matching the new cards box beside it, and
           the walk rather than the page load so reopening a finished one still
           shows what it did. everything the deck has ever had is /deck/view's */
        var mine = swaps.slice(carried);
        paintChanges({swaps: mine, added: addedList(mine),
                      newList: built, text: D.text, goal: D.goal},
                     {draw: build,
                      //offset back into the full list, which is what a revert acts on
                      onRevert: function (i) { revert(i + carried); }});

        /* a deck the shelf could not take (full, or private browsing) has no
           /deck/view holding its list, so this is the only copy there is */
        if (!entry) {
            var listBox = $("deck-list-box");
            if (listBox) listBox.hidden = false;
        }

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
        var built = rebuild(baseList, swaps);
        /* every form on the page carries the deck AS IT STANDS, mid session as
           well: without this, "back to this deck" and the metric picker hand
           back the list the session opened on and the swaps are walked again */
        carryList(built);
        markPlace();
        /* no entry means this deck is not on the shelf: reached from a precon, or
           deleted from the hub in another tab. the session still works, it just
           has nowhere to be written, which is also why the whole list stays on
           screen for it, see finish() */
        if (!entry) return;
        patch(D.did, {
            swaps: swaps.map(function (s) {
                return {out: keep(s.out), "in": keep(s["in"])};
            }),
            goal: D.goal,
            newList: built,
            added: addedList(swaps),
            /*
                the walk as a save file: the list itself, where in it you are,
                every decision and every dead end, all keyed by card id.

                NOT indexes: they only mean anything against the order they were
                taken in, which is exactly what `order` is here to pin
            */
            session: {
                axis: D.axis, dir: D.dir, limit: limit, carried: carried,
                order: queue.map(function (c) { return c.oracle_id; }),
                //empty means the walk reached the end of its batch
                at: queue[at] ? queue[at].oracle_id : "",
                trail: trail.map(function (t) {
                    return {id: queue[t.at].oracle_id, took: t.took};
                }),
                nothing: nothing.map(function (c) { return c.oracle_id; })
            }
        });
    }

    /* the copy buttons are wired by paintChanges, with the rest of the partial */

    //a resumed walk can open deeper than one batch
    $("swap-checked").textContent = limit;
    markPlace();
    show();
    /* only now is the page worth looking at: it opens on the loader, because
       working out where you are is the first thing this does and the page
       resolving a card at a time in front of you reads as a fault */
    $("swap-loading").hidden = true;
})();
