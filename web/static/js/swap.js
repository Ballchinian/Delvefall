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
import { el } from "dom";
(function () {
    var dataEl = document.getElementById("swap-data");
    if (!dataEl) return;
    var D = JSON.parse(dataEl.textContent);
    if (!D.queue.length) return;

    /* one card name, drawn the way every card name on this site is drawn: a
       link into delvefall, ctrl-click out to scryfall. the handler for that
       lives in base.html and keys off data-card, so anything carrying it gets
       the behaviour without wiring anything up */
    function cardLink(name, cls) {
        var a = document.createElement("a");
        a.className = cls;
        a.href = "/search?q=" + encodeURIComponent(name);
        a.dataset.card = name;
        a.textContent = name;
        return a;
    }

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
    var skipBtn = $("swap-skip");

    /*
        ask for one card's replacements, once. the result is cached whichever
        way it comes back, so walking forwards and the look-ahead never ask
        the same question twice, and an empty answer is remembered as an
        answer rather than retried forever
    */
    function load(i) {
        var card = D.queue[i];
        if (!card || cache[card.oracle_id] !== undefined) return Promise.resolve();
        cache[card.oracle_id] = "pending";
        return fetch("/deck/swap/cards", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({card: card.oracle_id, deck: deck, colors: D.colors,
                                  axis: D.axis, dir: D.dir})
        }).then(function (r) { return r.json(); }).then(function (j) {
            var cards = j.cards || [];
            cache[card.oracle_id] = cards;
            if (!cards.length) {
                nothing.push(card);
            }
            /* the answer may have arrived for the card being looked at, in
               which case the page was waiting on exactly this */
            if (i === at) show();
        }).catch(function () {
            /* leave it uncached so moving on and coming back can retry */
            delete cache[card.oracle_id];
            if (i === at) note.textContent = "Could not reach the card database. Try again in a moment.";
        });
    }

    function prefetch() {
        var n = 0;
        for (var i = at + 1; i < limit && n < LOOKAHEAD; i++) {
            if (cache[D.queue[i].oracle_id] === undefined) { load(i); n++; }
        }
    }

    function show() {
        /* walk past anything already known to have nowhere to go. the skip is
           silent here because those cards are named together at the end, and
           stopping on each one to say "nothing" would be twelve dead ends */
        while (at < limit) {
            var known = cache[D.queue[at].oracle_id];
            if (Array.isArray(known) && !known.length) { at++; continue; }
            break;
        }
        if (at >= limit) return finish();
        /* said here rather than on every state change, because this is the one
           function that knows which card is actually on screen. at has already
           stepped over the dead ends above, so this is the card being looked
           at and not the card the loop started from */
        $("swap-at").textContent = at + 1;

        var card = D.queue[at];
        $("swap-out-figure").textContent = card.figure;
        var out = $("swap-out-card");
        out.innerHTML = "";
        out.appendChild(build(card));
        enhanceCardFrames(out);
        options.innerHTML = "";

        var got = cache[card.oracle_id];
        if (Array.isArray(got)) {
            render(got);
        } else {
            note.textContent = "Looking for replacements…";
            load(at);
        }
        prefetch();
    }

    /*
        one card, drawn the way the results grid draws one. the card leaving
        and the cards that could replace it go through here together: if they
        were built by two functions the comparison would eventually be between
        two different presentations of the same numbers, which is the way a
        page starts lying without anyone editing it

        anchorName is set for candidates and empty for the outgoing card. it
        is what turns a bare figure into a verdict ("cheaper than Stasis"),
        and its absence is why the card leaving carries no arrows: a card
        compared against itself has nothing to say
    */
    function build(c, anchorName) {
        var div = document.createElement("div");
        div.className = "result";

        var frame = el("div", "card-frame", div);
        frame.dataset.sideways = c.sideways ? "1" : "";
        frame.dataset.flip = c.flip ? "1" : "";
        frame.dataset.back = c.image_back || "";
        var link = el("a", "", frame);
        link.href = "/search?q=" + encodeURIComponent(c.name);
        link.dataset.card = c.name;
        link.dataset.scryfall = c.scryfall_uri;
        link.title = "search " + c.name + " here. ctrl-click to open it on scryfall";
        var img = el("img", "", link);
        img.src = c.image;
        img.alt = c.name;
        img.width = 488;
        img.height = 680;
        img.loading = "lazy";

        var name = el("div", "result-name", div, c.name + " ");
        if (c.match !== undefined) el("span", "percent", name, c.match + "%");

        if (c.price || c.rank || c.salt) {
            var row = el("div", "result-price", div);
            var figure = el("span", "price-figure " + (c.price_vs || ""), row, c.price);
            if (c.price_vs) {
                figure.title = c.price_vs.replace("-", " ") + " than " + anchorName;
                el("span", "price-vs", figure, c.price_vs.indexOf("cheaper") > -1 ? "↓" : "↑");
            }
            if (c.rank) {
                var rank = el("span", "result-rank", row, c.rank);
                rank.title = "play rate: edhrec's rank for how often this card is played in " +
                    "commander, where #1 is the most played card in the format";
                if (c.rank_vs) {
                    el("span", "rank-vs", rank, c.rank_vs == "more-played" ? "↑" : "↓")
                        .title = (c.rank_vs == "more-played" ? "more" : "less") + " played than " + anchorName;
                }
            }
            /* empty means no score at all, not that the card is mild */
            if (c.salt) {
                var salt = el("span", "result-salt " + (c.salt_vs || ""), row);
                el("i", "salt-mark", salt).setAttribute("aria-hidden", "true");
                salt.appendChild(document.createTextNode(c.salt));
                if (c.salt_vs) {
                    salt.title = c.salt_vs.replace("-", " ").replace("milder", "less salty") +
                        " than " + anchorName;
                    el("span", "salt-vs", salt, c.salt_vs.indexOf("milder") > -1 ? "↓" : "↑");
                } else {
                    salt.title = "salt " + c.salt + " out of about 3, from edhrec's salt survey, " +
                        "where players vote on the cards they least enjoy facing";
                }
            }
        }
        if (c.their_line) {
            var ml = el("div", "match-line", div);
            manaFill(ml, '"' + c.their_line + '"');
            ml.title = "matches " + anchorName + "'s line: " + c.our_line;
        }
        return div;
    }

    function render(cards) {
        options.innerHTML = "";
        /* an empty list never reaches here: show() walks past those before
           drawing anything, and they are named in the passed-over section */
        if (!cards.length) { at++; return show(); }
        note.textContent = "Pick one to swap it in, or keep the card you have.";
        var outName = D.queue[at].name;
        cards.forEach(function (c) {
            var card = build(c, outName);
            /* the picture stays a link to scryfall like everywhere else on the
               site, so the swap gets its own button rather than making the
               whole card a target that fights the link inside it */
            var take_btn = el("button", "swap-take", card, "Swap this in");
            take_btn.type = "button";
            take_btn.addEventListener("click", function () { take(c); });
            options.appendChild(card);
        });
        enhanceCardFrames(options);
    }

    function take(c) {
        /* the WHOLE card on both sides, not just the names. the review at the
           end draws them as pictures and offers to put one back, and neither
           is possible from a name: the outgoing card has already left the
           screen by then and there is no url to ask about it again */
        swaps.push({out: D.queue[at], in: c, match: c.match});
        deck.push(c.oracle_id);
        at++;
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
        finish();
    }

    skipBtn.addEventListener("click", function () { at++; show(); });

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
        if (limit < D.queue.length) {
            $("swap-more-left").textContent = Math.min(D.batch, D.queue.length - limit);
            $("swap-more").hidden = false;
        }

        /* say what the batch just did. a batch that found nothing puts the page
           back exactly where it was, so without a word here the button reads as
           broken: it is the one outcome the screen cannot show by itself */
        if (batchFrom !== null) {
            var walked = limit - batchFrom;
            var got = swaps.length - batchSwaps;
            var note = $("swap-batch-note");
            if (!got) {
                note.textContent = "Checked " + walked + " more card"
                    + (walked === 1 ? "" : "s") + ". Nothing in the game does what any of "
                    + "them do and moves the deck " + D.goal + ", so there was nothing to "
                    + "offer. They are listed below."
                    + (limit < D.queue.length ? " There are more further down the queue."
                                              : "");
            } else {
                note.textContent = "Checked " + walked + " more card"
                    + (walked === 1 ? "" : "s") + " and found " + got + " swap"
                    + (got === 1 ? "" : "s") + ".";
            }
            note.hidden = false;
            batchFrom = null;
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
            var row = el("div", "swap-pair", pairs);

            var left = el("div", "swap-pair-side swap-pair-out", row);
            el("span", "swap-pair-label", left, "Out");
            left.appendChild(build(s.out));

            el("div", "swap-pair-arrow", row, "→");

            var right = el("div", "swap-pair-side swap-pair-in", row);
            el("span", "swap-pair-label", right, "In");
            right.appendChild(build(s["in"]));

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
        }
        $("swap-output").value = rebuild();
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
                        return {name: c.name, image: c.image, image_back: c.image_back || "",
                                sideways: !!c.sideways, flip: !!c.flip,
                                scryfall_uri: c.scryfall_uri, price: c.price,
                                rank: c.rank, salt: c.salt};
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
