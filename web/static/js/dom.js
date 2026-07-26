//the little dom helpers the pages that build cards out of json all needed a
//copy of. they lived three times over, once each in search.html, deck/hub.html
//and deck/swap.html, because no page owned them and cards.js is about card
//FRAMES rather than markup in general. this is the place that owns them.
//
//an es module, so importing it is the whole contract: no globals, no load
//order to get right, and a page that does not import this never pays for it

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
