//the builders for markup two or more pages both draw. cards.js is about card
//FRAMES rather than markup in general, which is why this is separate.
//
//the rule: anything two pages both draw belongs here

//text goes in as textContent and NEVER as html, which is why card names out of
//the database can go straight through it
export function el(tag, cls, parent, text) {
    var node = document.createElement(tag);
    node.className = cls;
    if (text !== undefined) node.textContent = text;
    parent.appendChild(node);
    return node;
}

//data-card is what base.html reads to wire the ctrl-click out to scryfall.
//parent is OPTIONAL: leaving it out hands back a detached link rather than
//throwing, which is what one of the two callers wants
export function cardLink(name, cls, parent) {
    var a = document.createElement("a");
    a.className = cls;
    a.href = "/search?q=" + encodeURIComponent(name);
    a.dataset.card = name;
    a.textContent = name;
    if (parent) parent.appendChild(a);
    return a;
}

//ONE result card, for every page that draws one out of json.
//
//`against` is the card this one is measured AGAINST: the searched card on
///search, the card leaving on the swap tool. giving it turns every figure into a
//verdict with arrows; leaving it out draws plain figures, which is what the card
//leaving itself wants.
//
//`opts.anchor` is that card's own figures, so a tooltip can finish the sentence
//("cheaper than Sol Ring at $1.20"). `opts.flag` adds the bad-match button.
//everything else draws when the data is there and is skipped when it is not, so
//one function serves a full search result and a swap saved back with three
//numbers
export function resultCard(c, against, opts) {
    opts = opts || {};
    var anchor = opts.anchor || {};
    var div = document.createElement("div");
    div.className = "result";
    var frame = el("div", "card-frame", div);
    frame.dataset.sideways = c.sideways ? "1" : "";
    frame.dataset.flip = c.flip ? "1" : "";
    frame.dataset.back = c.image_back || "";
    var a = el("a", "", frame);
    a.href = "/search?q=" + encodeURIComponent(c.name);
    a.dataset.card = c.name;
    if (c.scryfall_uri) a.dataset.scryfall = c.scryfall_uri;
    a.title = "search " + c.name + " here. ctrl-click to open it on scryfall";
    var img = el("img", "", a);
    img.src = c.image;
    img.alt = c.name;
    img.width = 488;   //scryfall's normal size, same as the
    img.height = 680;  //server-rendered cards declare
    img.loading = "lazy";
    if (opts.flag && c.oracle_id) {
        var flag = el("button", "report-flag", frame, "?");
        flag.title = "shouldn't be here? report this as a bad match";
        flag.dataset.id = c.oracle_id;
        flag.dataset.name = c.name;
    }

    var name = el("div", "result-name", div);
    el("span", "card-name", name, c.name).title = c.name;
    //`percent` on a search result, `match` on a swap candidate: two names for
    //the badge, and a saved pair has neither
    var pct = c.percent !== undefined ? c.percent : c.match;
    if (pct !== undefined) {
        var badge = el("span", "percent" + (c.concept_only ? " concept" : ""), name, pct + "%");
        if (c.blended) {
            badge.title = "rules text " + c.mech_pct + "%, concepts " + c.concept_pct +
                "%, evenly blended";
        }
    }

    //" at $1.20", when the caller knows what the anchor's own figure was. the
    //swap tool draws the card leaving directly above, so it does not need it
    function at(figure) {
        return figure ? " at " + figure : "";
    }

    if (c.price || c.rank || c.salt || c.age) {
        var row = el("div", "result-price", div);
        if (c.price) {
            var price = el("span", "price-figure " + (against && c.price_vs || ""), row, c.price);
            if (against && c.price_vs) {
                price.title = c.price_vs.replace("-", " ") + " than " + against + at(anchor.price);
                el("span", "price-vs", price, c.price_vs.indexOf("cheaper") > -1 ? "↓" : "↑");
            }
        }
        if (c.rank) {
            var rank = el("span", "result-rank", row, c.rank);
            rank.title = "play rate: edhrec's rank for how often this card is played in " +
                "commander, where #1 is the most played card in the format";
            if (against && c.rank_vs) {
                el("span", "rank-vs", rank, c.rank_vs === "more-played" ? "↑" : "↓")
                    .title = (c.rank_vs === "more-played" ? "more" : "less") + " played than " +
                        against + at(anchor.rank);
            }
        }
        //empty means the card has no score at all, not that it is mild
        if (c.salt) {
            var salt = el("span", "result-salt " + (against && c.salt_vs || ""), row);
            el("i", "salt-mark", salt).setAttribute("aria-hidden", "true");
            salt.appendChild(document.createTextNode(c.salt));
            if (against && c.salt_vs) {
                salt.title = c.salt_vs.replace("-", " ").replace("milder", "less salty") +
                    " than " + against + at(anchor.salt);
                el("span", "salt-vs", salt, c.salt_vs.indexOf("milder") > -1 ? "↓" : "↑");
            } else {
                salt.title = "salt " + c.salt + " out of about 3, from edhrec's salt survey, " +
                    "where players vote on the cards they least enjoy facing";
            }
        }
        //an arrow and NEVER a colour: older and newer are not better and worse,
        //so there is a direction to point and no verdict to spend red on
        if (c.age) {
            var age = el("span", "result-age", row, c.age);
            if (against && c.age_vs) {
                age.title = c.age_vs + " than " + against + at(anchor.age);
                el("span", "age-vs", age, c.age_vs === "older" ? "↑" : "↓");
            } else {
                age.title = "card age: how long ago this card was first printed, counted " +
                    "from its earliest printing, so a reprint does not make an old card new";
            }
        }
    }

    if (c.their_line) {
        var ml = el("div", "match-line", div);
        manaFill(ml, '"' + c.their_line + '"');
        ml.title = (against ? "matches " + against + "'s line: " : "matches your card's line: ") +
            c.our_line + (c.matched_back ? " (printed on the back face, shown here)" : "");
    }
    if (c.more_count) {
        el("div", "more-lines", div, "+" + c.more_count + " more matching " +
            (c.more_count === 1 ? "line" : "lines")).title = c.more_text;
    }
    if (c.concept_tags) {
        //no percentage alongside: the card already prints its match on the badge
        el("div", "concept-tags", div, c.concept_tags).title =
            "community tags shared with " + (against || "your card");
    }
    return div;
}

//a saved swap pair holds no badge and no matched line, so this is resultCard
//with nothing extra to draw
export function pairCard(c, against) {
    return resultCard(c, against);
}

//one swap, as the card leaving beside the card arriving.
//
//`draw` is passed in because the three pages showing a pair disagree about what
//a card is: the swap tool wants its own builder with the match percent and
//verdicts, the other two want the plain picture. the ROW is what they share.
//
//hands the row back so a caller can hang more off it, which is how the swap tool
//places its "put it back" button
export function swapPair(parent, swap, draw) {
    var row = el("div", "swap-pair", parent);
    var left = el("div", "swap-pair-side swap-pair-out", row);
    el("span", "swap-pair-label", left, "Out");
    left.appendChild(draw(swap.out));
    el("div", "swap-pair-arrow", row, "→");
    var right = el("div", "swap-pair-side swap-pair-in", row);
    el("span", "swap-pair-label", right, "In");
    //the card leaving is what the card arriving is measured against
    right.appendChild(draw(swap["in"], swap.out.name));
    return row;
}

//the rows attribute is a FLOOR, not the size: these sit behind a fold, so
//opening one is already a decision to see the whole list
export function fitText(box) {
    if (!box) return;
    //to zero first, or a box that has grown can never shrink: scrollHeight of an
    //oversized box is its own height, so it only ever ratchets up
    box.style.height = "0";
    box.style.height = box.scrollHeight + "px";
}
