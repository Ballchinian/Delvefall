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
import { el, cardLink, swapPair, fitText, resultCard } from "dom";
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
            render(got);
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
    /* NO report flag, and that is the one thing on a search result this page
       deliberately does not draw. the flag posts to /feedback with the query
       string of the page it was pressed on, and this page is a POST result with
       no query string to send: the button would render and do nothing, which is
       worse than not offering it. wiring it properly means deciding what a
       report against a SUGGESTION even means, which is its own question */
    function build(c, anchorName) {
        return resultCard(c, anchorName);
    }

    /*
        the whole-deck fold at the foot, kept as the deck STANDS rather than as
        the list arrived. without this it would quietly become a picture of the
        deck you started with, which is the one thing it must not be while the
        page is busy changing that deck.

        it MUTATES the tile in place instead of replacing the node. cardfold.js
        grabbed this grid's children once to batch them, so swapping nodes in
        and out would leave it holding elements no longer on the page and the
        "load 20 more" count would drift away from what is drawn.

        every tile's original markup is kept the first time through, so this can
        redraw from the top on every change: taking a swap, putting one back and
        stepping backwards all land here and all get the same answer, rather
        than three paths that have to agree
    */
    var deckGrid = document.querySelector(".swap-deck-all .deck-card-grid");
    var deckTiles = null;

    function paintDeck() {
        if (!deckGrid) return;
        if (!deckTiles) {
            deckTiles = {};
            Array.prototype.forEach.call(deckGrid.children, function (tile) {
                deckTiles[tile.dataset.oid] = tile.innerHTML;
            });
        }
        var byOut = {};
        swaps.forEach(function (s) { byOut[s.out.oracle_id] = s; });
        Array.prototype.forEach.call(deckGrid.children, function (tile) {
            var oid = tile.dataset.oid;
            var s = byOut[oid];
            tile.classList.toggle("is-swapped", !!s);
            if (!s) {
                /* back to the card the server drew, which is what a put-back
                   has to leave behind */
                if (tile.innerHTML !== deckTiles[oid]) tile.innerHTML = deckTiles[oid];
                return;
            }
            /* the card that took the slot, drawn by the same builder the
               suggestions were, with no anchor: this is the deck as it stands,
               not a comparison, so it carries figures and no verdicts */
            tile.innerHTML = "";
            var card = build(s["in"]);
            while (card.firstChild) tile.appendChild(card.firstChild);
            /* which card used to be here. a tile that silently became a
               different card is a deck list nobody can check against their own */
            el("div", "swap-deck-was", tile, "in for " + s.out.name);
        });
        enhanceCardFrames(deckGrid);
    }

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

    function render(cards) {
        options.innerHTML = "";
        /* an empty list never reaches here: show() walks past those before
           drawing anything, and they are named in the passed-over section */
        if (!cards.length) { at++; return show(); }
        note.textContent = "Pick one to swap it in, or keep the card you have.";
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
        paintDeck();
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
        paintDeck();
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
        paintDeck();
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

        var made = $("swap-made");
        made.innerHTML = "";
        swaps.forEach(function (s, i) {
            var li = el("li", "swap-made-row", made);
            /* both names are LINKS, like every other card name on the site.
               these are the cards a session's whole decision rests on and they
               were the only ones on the page you could not click. data-card
               gets them the same ctrl-click-to-scryfall the rest have */
            li.appendChild(cardLink(s.out.name, "swap-made-out"));
            el("span", "swap-made-arrow", li, "→");
            li.appendChild(cardLink(s["in"].name, "swap-made-in"));

            var undo = el("button", "swap-undo", li, "put it back");
            undo.type = "button";
            undo.addEventListener("click", function () { revert(i); });
        });
        $("swap-summary").textContent = swaps.length
            ? swaps.length + " card" + (swaps.length === 1 ? "" : "s") + " swapped."
            : "You kept every card. Nothing to copy.";

        /*
            the same swaps as PICTURES, folded away. a list of names is the
            fast read and is right most of the time; the pictures are for the
            moment somebody wants to check what they actually did, which is
            exactly when names are the wrong medium.

            the pair is drawn as one row per swap, out on the left and in on
            the right, so the comparison is the layout rather than something
            the reader has to hold in their head. on a narrow screen the pair
            stacks and keeps its labels, which is why the labels exist at all
        */
        var pairs = $("swap-pairs");
        pairs.innerHTML = "";
        $("swap-pairs-box").hidden = !swaps.length;
        swaps.forEach(function (s, i) {
            /* build, not pairCard: a card being weighed against another
               carries its match percent and its verdicts, which is the whole
               question a swap asks and is this page's alone */
            var row = swapPair(pairs, s, build);

            var back = el("button", "swap-undo", row, "Put " + s.out.name + " back");
            back.type = "button";
            back.addEventListener("click", function () { revert(i); });
        });
        enhanceCardFrames(pairs);

        /* the cards that came IN, on their own, in the shape a decklist is in.
           one copy each, because that is what a swap is: the card leaving took
           one slot and the card arriving takes it back */
        if (swaps.length) {
            $("swap-added-count").textContent = swaps.length;
            $("swap-added").value = swaps.map(function (s) { return "1 " + s["in"].name; }).join("\n");
            $("swap-added-box").hidden = false;
            fitText($("swap-added"));
        }
        $("swap-output").value = rebuild();
        /* grown to the whole list rather than scrolling inside twelve rows.
           this is the deliverable of the session and the one thing somebody
           takes away from it, so it is not the place to make them scroll a box
           inside a page */
        fitText($("swap-output"));
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
                        return {name: c.name, image: c.image, image_back: c.image_back || "",
                                sideways: !!c.sideways, flip: !!c.flip,
                                scryfall_uri: c.scryfall_uri, price: c.price,
                                rank: c.rank, salt: c.salt,
                                price_vs: c.price_vs || "", rank_vs: c.rank_vs || "",
                                salt_vs: c.salt_vs || ""};
                    };
                    return {out: keep(s.out), "in": keep(s["in"])};
                });
                x.goal = D.goal;
                x.newList = $("swap-output").value;
                x.added = $("swap-added").value;
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
    function rebuild() {
        var text = D.text || "";
        swaps.forEach(function (s) {
            /* the swap holds whole cards now, and this only ever wanted their
               names. pulled out here rather than at every use below */
            var out = s.out.name, into = s["in"].name;
            var lines = text.split("\n");
            var hit = -1;
            for (var i = 0; i < lines.length; i++) {
                /* case insensitive, because an export may not match our
                   capitalisation and the parser normalised it away anyway */
                if (lines[i].toLowerCase().indexOf(out.toLowerCase()) !== -1) { hit = i; break; }
            }
            if (hit === -1) {
                /* a name we cannot find in the raw text (a face name, or a
                   collector number wedged in the middle). say so rather than
                   dropping the swap on the floor */
                text += "\n# swap by hand: " + out + " -> " + into;
            } else {
                var re = new RegExp(out.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
                lines[hit] = lines[hit].replace(re, into);
                text = lines.join("\n");
            }
        });
        return text;
    }

    /* one copier for both boxes. it selects the text either way, so the
        fallback message is true: the clipboard api is blocked on http origins
        and in some browsers, and by then the textarea is already selected */
    function wireCopy(btnId, boxId, said) {
        $(btnId).addEventListener("click", function () {
            var out = $(boxId);
            out.select();
            navigator.clipboard.writeText(out.value).then(function () {
                $(btnId).textContent = said;
            }).catch(function () {
                $(btnId).textContent = "Press Ctrl+C";
            });
        });
    }
    wireCopy("swap-copy", "swap-output", "Copied");
    wireCopy("swap-copy-added", "swap-added", "Copied");

    show();
})();
