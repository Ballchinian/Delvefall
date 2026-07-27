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
//results grid renders server side. it deliberately does NOT do match percents
//or the against-this-card verdicts: those belong to a card being COMPARED with
//another, which is the swap tool's own richer builder
export function pairCard(c) {
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
        if (c.price) el("span", "price-figure", row, c.price);
        if (c.rank) el("span", "result-rank", row, c.rank);
        if (c.salt) el("span", "result-salt", row, c.salt);
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
    right.appendChild(draw(swap["in"]));
    return row;
}
