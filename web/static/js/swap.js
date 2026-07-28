//the swap tool: the lens with a hand on it. moved out of
//templates/deck/swap.html unchanged, so this is a relocation and not a
//rewrite. it reads its whole session out of the #swap-data island the
//template renders, and leans on manaFill from cards.js, which base.html
//loads above the scripts block. defer keeps that order: cards.js runs
//while the page parses, this runs once it is parsed and before
//DOMContentLoaded, so nothing it looks up is missing.
//
//a module now, for the el import. type="module" defers on its own, so the
//tag no longer says defer and the order above is unchanged

//a bare specifier, resolved by the import map base.html emits, so this
//picks up dom.js at its content-hashed url rather than an unstamped one
//that the year-long static cache would freeze
import { el, cardLink, resultCard, pairCard } from "dom";
import { wireReports } from "report";
//the end of a session is /deck/view's change blocks, so it is /deck/view's
//painter that draws them. rebuild came the other way: it was this file's and
///deck/view needed it the moment it could put a card back
import { paintChanges, rebuild, addedList, carryList } from "changes";
(function () {
    var dataEl = document.getElementById("swap-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);
    if (!D.queue.length) return;

    /* one card name, drawn the way every card name on this site is drawn: a
       link into delvefall, ctrl-click out to scryfall. the handler for that
       lives in base.html and keys off data-card, so anything carrying it gets
       the behaviour without wiring anything up */
    /*
        the deck grows and never shrinks. a card swapped IN has to be excluded
        from every later suggestion or the tool offers it twice, and a card
        swapped OUT has to stay excluded too, or the next card's list happily
        suggests the thing just taken out. one list does both jobs
    */
    var deck = D.deck.slice();
    var at = 0;
    var swaps = [];

    /*
        how far into the queue this session has agreed to go. it used to be the
        whole queue and the queue used to be twelve cards, which stopped a
        working tool for no reason: somebody who has walked twelve and wants a
        thirteenth is exactly who this is for.

        so the queue is deep and the SESSION is the batch. reaching the end
        offers the next batch rather than finishing, and the count in the
        header says what has been checked rather than promising a total that
        was never the real end of the list
    */
    var limit = Math.min(D.batch, D.queue.length);

    /*
        every card's replacements once they have been asked for. undefined
        means not asked yet, "pending" means in flight, an array means
        answered, and an EMPTY array is a real answer rather than a failure:
        it says nothing in the game does this card's job and moves the deck
        the right way, which is why those cards get skipped instead of being
        offered something worse
    */
    var cache = {};
    var nothing = [];

    /* how far ahead to look. the count only climbs if answers arrive before
       the user does, and three is enough to stay in front of someone reading
       a card without opening twelve connections to say hello */
    var LOOKAHEAD = 3;

    var $ = function (id) { return document.getElementById(id); };
    var options = $("swap-options"), note = $("swap-note");
    var skipBtn = $("swap-skip"), backBtn = $("swap-back");

    /*
        every decision this session has made, in the order it made them, so the
        walk runs backwards as well as forwards.

        it exists because the queue used to be a one way door: one misplaced
        click on "Swap this in" and the only way to reconsider was to reach the
        end of the batch and hunt the pair down in the review. a card at a time
        is the whole shape of this tool, so moving between them has to be
        symmetric.

        each entry is the index it was made AT, which is not the same as at-1
        when it lands: show() steps silently over cards nothing could replace,
        so walking back by subtraction would stop on dead ends the forward walk
        deliberately hid
    */
    var trail = [];

    /*
        what the two pickers on the card leaving have been told, for the card on
        screen only. picking a line or switching a tag off is a statement about
        THIS card ("replace this ability, not that one"), so it means nothing on
        the next one and is cleared when the queue moves.

        the same three names /search puts in its url, because they end up in the
        same two functions on the server
    */
    var picks = {lines: [], notags: [], yestags: []};

    function clearPicks() {
        picks = {lines: [], notags: [], yestags: []};
    }

    /* has the user narrowed anything on the card in front of them. it is the
       difference between "nothing in the game does this" and "nothing does this
       ONCE YOU SAID that", and those two deserve opposite behaviour */
    function picked() {
        return !!(picks.lines.length || picks.notags.length || picks.yestags.length);
    }

    /* the cache key is the card PLUS what the pickers were told, so narrowing
       to one line asks a genuinely new question rather than being handed the
       whole card's answer back out of the cache */
    function keyFor(card) {
        return card.oracle_id + "|" + picks.lines.join(",") + "|" +
            picks.notags.join(",") + "|" + picks.yestags.join(",");
    }

    /* the panel above the suggestions, and the answer to "which of this card's
       abilities am I actually replacing". it arrives as HTML the server
       rendered from the same partial /search draws its searched card with, so
       there is one description of this panel and not two */
    var panels = {};

    /* what each answer held back for costing the wrong amount, keyed the same
       way the cards are. it is kept beside the list rather than inside it
       because it is a fact about the ANSWER and not about any card in it: an
       answer of three cards that turned eleven away is a different answer from
       one that turned none away, and the list alone cannot tell you which */
    var held = {};

    /*
        ask for one card's replacements, once. the result is cached whichever
        way it comes back, so walking forwards and the look-ahead never ask
        the same question twice, and an empty answer is remembered as an
        answer rather than retried forever
    */
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
                                  /* only for the card on screen: the look-ahead
                                     is fetching the UNPICKED answer, which is
                                     what the next card opens on */
                                  lines: i === at ? picks.lines : [],
                                  notags: i === at ? picks.notags : [],
                                  yestags: i === at ? picks.yestags : []})
        }).then(function (r) { return r.json(); }).then(function (j) {
            var cards = j.cards || [];
            cache[key] = cards;
            if (j.panel) panels[key] = j.panel;
            held[key] = {n: j.offband || 0, lo: j.mv_lo, hi: j.mv_hi};
            /* a card with nowhere to go is named at the end, but only when the
               PLAIN question got no answer: narrowing to one line and finding
               nothing is the user's own filter, not a fact about the card */
            if (!cards.length && key === card.oracle_id + "|||" && nothing.indexOf(card) === -1) {
                nothing.push(card);
            }
            /* the answer may have arrived for the card being looked at, in
               which case the page was waiting on exactly this */
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
        /* walk past anything already known to have nowhere to go. the skip is
           silent here because those cards are named together at the end, and
           stopping on each one to say "nothing" would be twelve dead ends.
           judged on the PLAIN answer, since that is what the queue moves on */
        while (at < limit) {
            var known = cache[D.queue[at].oracle_id + "|||"];
            if (Array.isArray(known) && !known.length) { at++; continue; }
            break;
        }
        if (at >= limit) return finish();
        /* said here rather than on every state change, because this is the one
           function that knows which card is actually on screen. at has already
           stepped over the dead ends above, so this is the card being looked
           at and not the card the loop started from */
        $("swap-at").textContent = at + 1;
        /* nothing decided yet means nowhere to go back to, and a control that
           cannot do anything is worse than one that is not there */
        if (backBtn) backBtn.hidden = !trail.length;

        var card = D.queue[at];
        var key = keyFor(card);
        var out = $("swap-out-card");
        options.innerHTML = "";

        /* the panel, with its rules lines and its tag chips. it is the same one
           /search puts above its results, so the tool that PROPOSES a card no
           longer gives you less say over the match than the one that lists
           them. until the first answer lands there is nothing to draw it from,
           so the plain picture stands in */
        if (panels[key]) {
            out.innerHTML = panels[key];
            wirePanel(out);
        } else if (!out.querySelector(".searched-card")) {
            out.innerHTML = "";
            out.appendChild(build(card));
        }
        enhanceCardFrames(out);

        var got = cache[key];
        if (Array.isArray(got)) {
            render(got, held[key]);
        } else {
            note.textContent = "Looking for replacements…";
            load(at);
        }
        prefetch();
    }

    /*
        the panel's two pickers, doing on this page what a reload does on
        /search. the markup is identical, so the classes and the four chip
        states are the ones the css already knows; only what a click MEANS
        differs, because there is no url here to put the answer in.

        a click re-asks for this card's replacements with the narrower question
        attached, which is the same round trip the page already makes per card
    */
    function wirePanel(root) {
        root.querySelectorAll(".oracle-line").forEach(function (line) {
            line.onclick = function () {
                var idx = line.dataset.idx;
                var i = picks.lines.indexOf(idx);
                if (i === -1) picks.lines.push(idx); else picks.lines.splice(i, 1);
                repick();
            };
        });
        /* four states, and clicking one means the obvious opposite of whichever
           it is in. notags is "ignore this", yestags is "the line picker guessed
           wrong, put it back": two lists because they answer two questions */
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
        /* the panel is redrawn whenever the card or the picks change, so its
           link and the report's tag list are rewired every time rather than
           once at load: the old ones went out of the dom with the old panel */
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
        one card, from dom.js, which is the only place on the site that draws
        one now. the card leaving and the cards that could replace it go
        through it together: two builders would eventually be two different
        presentations of the same numbers, which is how a page starts lying
        without anyone editing it.

        anchorName is set for candidates and empty for the outgoing card. it is
        what turns a bare figure into a verdict ("cheaper than Stasis"), and its
        absence is why the card leaving carries no arrows: a card compared
        against itself has nothing to say
    */
    /* the flag is on the SUGGESTIONS and not on the card leaving. a report says
       "this is a bad match for that", so the card being matched against has
       nothing to flag: it is the question, not an answer to it */
    function build(c, anchorName) {
        return resultCard(c, anchorName, {flag: !!anchorName});
    }

    /*
        reports, off the same bar and the same code /search uses.

        the query string is BUILT rather than read, because this page is a POST
        result and has no url of its own. it carries exactly what /feedback
        already knows how to read: which card is being matched against, which of
        its lines are picked, and which tags are switched off. so the server
        needed no new shape for this, only a note saying where it came from
    */
    var reports = wireReports({
        grid: options,
        query: function () {
            var p = new URLSearchParams();
            p.set("q", D.queue[at].name);
            if (picks.lines.length) p.set("lines", picks.lines.join(","));
            if (picks.notags.length) p.set("notags", picks.notags.join(","));
            if (picks.yestags.length) p.set("yestags", picks.yestags.join(","));
            //so a report can be read back knowing it was made about a proposed
            //replacement rather than about a search result
            p.set("from", "swap");
            return p.toString();
        }
    });

    /*
        the suggestions, revealed a batch at a time out of the whole answer the
        server sent. it used to send five and that was the lot.

        the batch is the same D.offer the rest of the site reveals (twelve), and
        the deeper list costs NOTHING extra to fetch: the query already scanned
        two hundred rows per line and threw all but five away at the very end.
        so this is one round trip either way, and reaching the bottom of twelve
        is answered from what the page is already holding.

        `shown` is per card and resets in render(), because twelve into one
        card's list says nothing about the next card's
    */
    var shown = 0;
    var moreBtn = $("swap-options-more");

    function paintOptions(cards) {
        var outName = D.queue[at].name;
        for (var i = options.children.length; i < Math.min(shown, cards.length); i++) {
            var c = cards[i];
            var card = build(c, outName);
            /* the picture stays a link to scryfall like everywhere else on the
               site, so the swap gets its own button rather than making the
               whole card a target that fights the link inside it */
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

    /* the matches that were the right card at the wrong cost, said out loud.
       without it the tool answers "one card" and looks like it has run out of
       ideas, when what actually happened is that it turned eleven away for
       being the wrong thing to put in this slot. that is a judgement worth
       arguing with, and an unstated one cannot be argued with at all */
    function costNote(h) {
        if (!h || !h.n || h.lo === null || h.lo === undefined) return "";
        return " " + h.n + (h.n === 1 ? " other match was" : " other matches were")
            + " left out for costing outside " + Math.max(0, h.lo) + " to " + h.hi
            + ": what a card does is not what it costs, and the slot has a curve.";
    }

    function render(cards, h) {
        options.innerHTML = "";
        if (!cards.length) {
            /*
                nothing to offer, and WHY decides what happens next.

                the card's own answer being empty is a fact about the card, so
                the queue moves on and it gets named at the end. an answer
                emptied by the PICKERS is the user's own doing, and moving them
                off the card they are working on for it would be the page
                undoing their click: they narrowed to one ability, got nothing,
                and want to widen it again. so it says so and stays put, which
                is what /search does with a filter that matches nothing
            */
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
        var got = cache[keyFor(D.queue[at])];
        if (!Array.isArray(got)) return;
        shown = Math.min(shown + D.offer, got.length);
        paintOptions(got);
    });

    function take(c) {
        /* the WHOLE card on both sides, not just the names. the review at the
           end draws them as pictures and offers to put one back, and neither
           is possible from a name: the outgoing card has already left the
           screen by then and there is no url to ask about it again */
        swaps.push({out: D.queue[at], in: c, match: c.match});
        deck.push(c.oracle_id);
        trail.push({at: at, took: true});
        at++;
        clearPicks();
        show();
    }

    /*
        one step back up the trail, undoing whatever was decided there.

        a swap is unwound completely: the card that came in leaves the deck
        list, so it can be offered again, and the pair stops existing. that is
        the same thing "put it back" does in the review at the end, and it has
        to be, or the same decision could be undone two ways with two results.

        the card that went OUT is not requeued, because it never left the queue:
        the trail holds the index it was at, so going back simply stands on it
        again with nothing decided
    */
    function back() {
        if (!trail.length) return;
        var step = trail.pop();
        if (step.took) {
            var s = swaps.pop();
            var at_in = deck.indexOf(s["in"].oracle_id);
            if (at_in > -1) deck.splice(at_in, 1);
        }
        at = step.at;
        clearPicks();
        /* the review is only up once a batch has run out, and going back means
           the walk is live again */
        $("swap-done").hidden = true;
        $("swap-batch-note").hidden = true;
        $("swap-live").hidden = false;
        show();
    }

    /*
        put one back. the card that came in leaves the deck list (so later
        suggestions can offer it again) and the card that went out is NOT
        requeued: the queue is walked once and rewinding it would reorder
        everything decided after this point. the swap simply stops existing,
        which is what "revert" has to mean for the exports to stay true
    */
    function revert(i) {
        var s = swaps[i];
        var at_in = deck.indexOf(s["in"].oracle_id);
        if (at_in > -1) deck.splice(at_in, 1);
        swaps.splice(i, 1);
        /* the trail records the DECISION, so undoing one from the review has to
           take its step with it or going back afterwards would try to unwind a
           swap that is no longer there. matched on the card it was made at,
           never on position: the review's order and the trail's are the same
           today and nothing enforces that */
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

    /* another batch. everything decided so far stays decided: the swaps list,
       the cards nothing could replace and the growing deck are all untouched,
       so this genuinely continues the session rather than restarting it */
    /* where the batch about to run started, and what had been decided by then.
       finish() compares against these to say what the batch turned up, which is
       the difference between "that did nothing" and "that checked twelve cards
       and none of them had anywhere to go" */
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
        /* rebuilt by finish() from the full list, so leaving it up during the
           batch would show a stale answer next to live cards */
        $("swap-nothing").hidden = true;
        $("swap-live").hidden = false;
        show();
    });

    /* bound once, not in finish(): that runs at the end of every batch, so
       binding there stacked another listener each time and redrew the frames
       once per batch on a single click */
    $("swap-nothing-box").addEventListener("toggle", function () {
        if (this.open) enhanceCardFrames(this);
    });

    function finish() {
        /* the end of a BATCH, not necessarily the end of the queue. if the
           deck has more cards worth looking at, say so and offer them rather
           than closing the session on a number that was only ever a batch
           size. the extra cards cost nothing until they are reached: their
           candidates are still fetched one card at a time */
        var more_left = D.queue.length - limit;
        if (more_left > 0) {
            $("swap-more-left").textContent = Math.min(D.batch, more_left);
            $("swap-more").hidden = false;
        } else {
            /* the queue is out. the button was hidden by the press that used up
               the last of it and there was no branch here to say anything, so
               the control somebody had been pressing simply vanished. a button
               that disappears without a word reads as a button that broke,
               which is what it was reported as */
            $("swap-more").hidden = true;
        }
        /* the header still says the card the walk stopped on, which is the
           whole batch once it has been walked */
        $("swap-at").textContent = Math.min(at, limit);

        /* say what the batch just did. a batch that found nothing puts the page
           back exactly where it was, so without a word here the button reads as
           broken: it is the one outcome the screen cannot show by itself */
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
        /* and where that leaves the queue. said on EVERY finish, not only after
           a press, because "there is nothing more to load" is exactly the fact
           the vanishing button was failing to communicate */
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

        /* the cards nothing could replace, named together rather than one
           dead end at a time on the way through */
        if (nothing.length) {
            /* how many of them were not short of an answer but short of one at
               the right cost. the heading above says no card does what these
               do, which the mana value band can turn into a lie, so the count
               that makes it a lie is printed next to it */
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
                /* a link like every other card name on the site. these were the
                   only names on the page you could not click, which made the
                   one group you might want to go and check the one group with
                   nowhere to go from */
                el("li", "swap-made-row", list).appendChild(cardLink(c.name, "swap-made-out"));
                /* no anchor name: there is no card it lost to, which is the
                   whole point of it being in this list */
                pics.appendChild(build(c, ""));
            });
            box.hidden = false;
        }

        /* the swaps, the new cards and the list, all three drawn by the painter
           /deck/view uses, onto the partial they now share.

           build and not pairCard: a card being weighed against another carries
           its match percent and its verdicts, which is the whole question a
           swap asks and is this page's alone. no note, because the swaps are
           what the last twenty minutes were spent making and counting them back
           is the page narrating your own move to you */
        var built = rebuild(D.text, swaps);
        paintChanges({swaps: swaps, added: addedList(swaps),
                      newList: built, text: D.text, goal: D.goal},
                     {draw: build, onRevert: revert});

        /* the deck as it now stands. the fold is server rendered from the deck
           that ARRIVED, so every swap has left a tile showing a card that is no
           longer in it */
        repaintDeck();

        /* every way on from here carries the deck AS IT NOW STANDS, the back
           link included. jinja rendered them with the list the session opened
           on, because at page build time that is the only list there is; this
           is the moment the new one exists */
        carryList(built);

        remember();
    }

    /*
        hand the session back to the deck it belongs to, in this browser.

        without this a swap session evaporates the moment the tab closes, and
        the work it represents (twelve judgement calls about somebody's deck)
        is exactly the kind of thing worth being able to come back to. the
        server still stores nothing: this is the same localStorage shelf the
        hub already keeps, and the deck is found by the TEXT it was read from,
        which is the key that shelf is built on.

        written on every finish, including after a revert, so what is stored is
        always what is on screen rather than a snapshot of an earlier decision
    */
    function remember() {
        var KEY = "delvefall_recent_decks";
        try {
            var decks = JSON.parse(localStorage.getItem(KEY)) || [];
            var found = false;
            /* the shelf is keyed on the list the deck was IMPORTED as, which is
               not the list this page is holding once the deck has been through
               here before. matching on D.text alone meant a second session on
               the same deck found no entry and threw its work away silently */
            var key = D.origin || D.text;
            decks.forEach(function (x) {
                if (x.text !== key) return;
                found = true;
                x.swaps = swaps.map(function (s) {
                    /* only what the review needs to draw a card. the rest of
                       the queue row is about picking, and picking is over */
                    var keep = function (c) {
                        /* the verdicts ride along too. the server worked them
                           out against the card being replaced when it sent the
                           candidate, and they are the whole reading of a swap:
                           without them the review shows two prices and leaves
                           the arithmetic to whoever is looking. only the card
                           coming IN carries them, because the one going out is
                           what they were measured against */
                        return {oracle_id: c.oracle_id, name: c.name, image: c.image,
                                image_back: c.image_back || "",
                                sideways: !!c.sideways, flip: !!c.flip,
                                scryfall_uri: c.scryfall_uri, price: c.price,
                                rank: c.rank, salt: c.salt, age: c.age,
                                price_vs: c.price_vs || "", rank_vs: c.rank_vs || "",
                                salt_vs: c.salt_vs || "", age_vs: c.age_vs || ""};
                    };
                    return {out: keep(s.out), "in": keep(s["in"])};
                });
                x.goal = D.goal;
                x.newList = $("deck-list").value;
                x.added = $("deck-added").value;
                x.at = Date.now();
            });
            if (found) localStorage.setItem(KEY, JSON.stringify(decks));
        } catch (e) {
            /* private browsing, a full quota, or storage switched off. the
               session on screen is unaffected, so this fails quietly */
        }
    }

    /*
        the original text with the names substituted, rather than a list
        rebuilt from our own data. the paste path drops duplicate counts on the
        way in, so a rebuilt list would quietly return someone's 30 basics as
        one line each. substituting leaves every count, every section header
        and every bit of the user's own formatting exactly where it was
    */
    /*
        the deck's fold, brought up to date with the session.

        the grid is rendered by the server from the deck that ARRIVED, so after
        a swap one of its tiles is a card that is no longer in the deck. the
        swap holds both sides whole, which is exactly enough to draw the one
        that replaced it, and it goes through the same builder every other card
        on the site does.

        it walks from the ORIGINAL tile every time rather than patching the last
        paint, which is what makes a revert work: putting a card back is just
        this running again with one fewer swap in the list
    */
    var bornTiles = null;

    function repaintDeck() {
        var grid = document.querySelector(".deck-card-fold .deck-card-grid");
        if (!grid) return;
        /* the deck as it ARRIVED, kept as markup, captured before anything has
           been rewritten. it is what a revert puts back, and keeping the html
           rather than the card data means the restored tile is the server's own
           tile again rather than a redrawing of it that has to agree */
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
            /* already right: swapped and showing the card that came in, or
               untouched and showing the card it was born as */
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
            /* whether it is past the first batch is a fact about its POSITION,
               and swapping a card does not move it */
            if (tile.classList.contains("is-over")) fresh.classList.add("is-over");
            tile.replaceWith(fresh);
        });
        enhanceCardFrames(grid);
    }

    /* the two copy buttons are wired by paintChanges, along with everything
       else on the partial they sit in */

    show();
})();
