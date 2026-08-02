//holds your place across a reload. /search reloads on every control it owns,
//because the url IS the search, and a reload costs you your scroll position.

var KEY = "delvefall_place";

//an OFFSET, not a scroll position: the page comes back a different length.
//takes a landmark selector rather than the control, which can reflow when its
//state changes
export function hold(sel) {
    var node = document.querySelector(sel);
    if (!node) return;
    try {
        sessionStorage.setItem(KEY, JSON.stringify({
            path: location.pathname, sel: sel,
            top: node.getBoundingClientRect().top
        }));
    } catch (e) {
        //storage off or full. the reload lands at the top, as it always did
    }
}

export function keep() {
    var saved;
    try {
        saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
        //read ONCE, used or not: a refresh or a back button is not the reload
        //this was held for, and opening halfway down for no visible reason is
        //worse than opening at the top
        sessionStorage.removeItem(KEY);
    } catch (e) {
        return;
    }
    if (!saved || saved.path !== location.pathname) return;
    //landmark gone (different card, panel not drawn this time): stay at the top
    var node = document.querySelector(saved.sel);
    if (!node) return;
    window.scrollTo(0, Math.max(0, window.scrollY + node.getBoundingClientRect().top - saved.top));
}
