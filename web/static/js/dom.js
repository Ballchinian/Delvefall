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

//a card as a picture with its name and figures under it, the same shape the
//results grid renders server side.
//
//`against` is the card this one replaced, and giving it turns every figure into
//a verdict: cheaper, less played, saltier, with the same arrows the results
//page uses against the searched card. it is optional because only the card
//coming IN has anything to be measured against, and because a swap saved
//before the verdicts were stored simply has none to show.
//
//it still does NOT do match percents. those belong to a card being weighed as a
//candidate, which is the swap tool's own richer builder
export function pairCard(c, against) {
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
    img.width = 488;
    img.height = 680;
    img.loading = "lazy";
    el("div", "result-name", div, c.name);
    if (c.price || c.rank || c.salt) {
        var row = el("div", "result-price", div);
        //the same words and the same arrows the results page prints against the
        //searched card, so a swap reads like a search result and not like a
        //second vocabulary for the same three numbers
        if (c.price) {
            var price = el("span", "price-figure " + (against && c.price_vs || ""), row, c.price);
            if (against && c.price_vs) {
                price.title = c.price_vs.replace("-", " ") + " than " + against;
                el("span", "price-vs", price, c.price_vs.indexOf("cheaper") > -1 ? "↓" : "↑");
            }
        }
        if (c.rank) {
            var rank = el("span", "result-rank", row, c.rank);
            rank.title = "play rate: edhrec's rank for how often this card is played in " +
                "commander, where #1 is the most played card in the format";
            if (against && c.rank_vs) {
                el("span", "rank-vs", rank, c.rank_vs === "more-played" ? "↑" : "↓")
                    .title = (c.rank_vs === "more-played" ? "more" : "less") + " played than " + against;
            }
        }
        if (c.salt) {
            var salt = el("span", "result-salt " + (against && c.salt_vs || ""), row);
            el("i", "salt-mark", salt).setAttribute("aria-hidden", "true");
            salt.appendChild(document.createTextNode(c.salt));
            if (against && c.salt_vs) {
                salt.title = c.salt_vs.replace("-", " ").replace("milder", "less salty") +
                    " than " + against;
                el("span", "salt-vs", salt, c.salt_vs.indexOf("milder") > -1 ? "↓" : "↑");
            } else {
                salt.title = "salt " + c.salt + " out of about 3, from edhrec's salt survey, " +
                    "where players vote on the cards they least enjoy facing";
            }
        }
    }
    return div;
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
