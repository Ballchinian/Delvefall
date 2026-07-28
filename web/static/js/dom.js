//the little builders every page that draws cards out of json needed a copy of.
//
//they kept being written again because no page owned them and cards.js is
//about card FRAMES rather than markup in general: el three times over, the
//card picture twice, the out/in row three times. this is the place that owns
//them, and the rule is that anything two pages both draw belongs here.
//
//an es module, so importing it is the whole contract: no globals, no load
//order to get right, and a page that does not import this never pays for it.
//base.html maps the bare name "dom" to the content hashed url, so an import
//cache-busts like every other asset does

//one element, classed, appended, optionally with text. the argument order
//reads like the sentence it builds: make a DIV, class it "row", put it IN
//parent, saying "3". text goes in as textContent and never as html, which is
//why card names out of the database can go straight through it
export function el(tag, cls, parent, text) {
    var node = document.createElement(tag);
    node.className = cls;
    if (text !== undefined) node.textContent = text;
    parent.appendChild(node);
    return node;
}

//a card's name as a link, the way every card name on the site behaves: click
//to search it here, ctrl-click to open it on scryfall. data-card is what
//cards.js reads to wire the second of those.
//
//parent is OPTIONAL, because the two callers want different things: one
//appends as it builds, the other holds the node to place itself. leaving it
//out hands back a detached link rather than throwing
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
//there were four of these: the results grid's load-more, the swap tool's
//candidates, the saved-swap pairs, and the dealer. they agreed only because
//somebody kept making them agree, and they had already drifted: the swap tool's
//cards were missing the age arrow, the "+2 more matching lines" note and the
//shared concept tags, so a suggestion was a thinner reading of a card than a
//search result of the same card. that is the drift this file exists to stop.
//
//`against` is the card this one is being measured AGAINST: the searched card on
///search, the card leaving on the swap tool. giving it turns every figure into a
//verdict with the arrows to match. leaving it out draws the plain figures, which
//is what the card leaving itself wants, since a card compared to itself has
//nothing to say.
//
//`opts.anchor` is that card's own figures, so a tooltip can finish the sentence
//("cheaper than Sol Ring at $1.20"). `opts.flag` adds the bad-match report
//button. everything else is drawn when the data is there and skipped when it is
//not, so one function serves a full search result and a swap saved back when
//only three numbers were stored
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
        //the same words and the same arrows in every grid on the site, so a
        //suggestion reads like a search result rather than like a second
        //vocabulary for the same four numbers
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
        //an arrow like the three above it and never a colour: older and newer
        //are not better and worse, so there is a direction to point and no
        //verdict to spend green or red on
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
        //the tags and what they are, and nothing else. it used to carry
        //"concept match 63%" as well: a second number for a card whose match is
        //already printed on its badge, in units the page never explains. the
        //line tooltip above names the matched line and stops there, and these
        //two labels are the same kind of thing
        el("div", "concept-tags", div, c.concept_tags).title =
            "community tags shared with " + (against || "your card");
    }
    return div;
}

//the plain picture with its figures, no badge and no matched line: what a saved
//swap pair holds. it is resultCard with nothing extra to draw, which is the
//point of there being one of these
export function pairCard(c, against) {
    return resultCard(c, against);
}

//one swap, as the card leaving beside the card arriving.
//
//the card going out is on the left and the one coming in is on the right, so
//the comparison is the layout rather than something the reader has to hold in
//their head. on a narrow screen the pair stacks and keeps its labels, which is
//why the labels exist at all.
//
//draw is the card renderer, because the three pages that show a pair do not
//agree about what a card is: the swap tool wants its own builder with the
//match percent and the verdicts on it, the other two want the plain picture.
//the ROW is what they share, and the row is what this owns.
//
//it hands the row back so a caller can hang more off it, which is how the swap
//tool puts its "put it back" button in the right place
export function swapPair(parent, swap, draw) {
    var row = el("div", "swap-pair", parent);
    var left = el("div", "swap-pair-side swap-pair-out", row);
    el("span", "swap-pair-label", left, "Out");
    left.appendChild(draw(swap.out));
    el("div", "swap-pair-arrow", row, "→");
    var right = el("div", "swap-pair-side swap-pair-in", row);
    el("span", "swap-pair-label", right, "In");
    //the card leaving is what the card arriving gets measured against, which
    //is the second argument both renderers take
    right.appendChild(draw(swap["in"], swap.out.name));
    return row;
}

//a readonly list box grown to fit what is in it.
//
//the rows attribute is a FLOOR, not the size: a decklist is a hundred lines and
//twelve of them in a scrolling box is the list hidden inside its own container.
//these sit behind a fold, so opening one is already a decision to look at the
//whole thing, and the point of opening it is to see the whole thing.
//
//resize: vertical stays on in the css, so it can still be dragged smaller
export function fitText(box) {
    if (!box) return;
    //to zero first, or a box that has already grown can never shrink: scrollHeight
    //of an oversized box is its own height, so it would only ever ratchet up
    box.style.height = "0";
    box.style.height = box.scrollHeight + "px";
}
