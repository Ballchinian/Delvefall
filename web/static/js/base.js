/*
    every page carries this: the search box's autocomplete, the keyboard half of
    the div-buttons, the nav menu, and the ctrl-click rule.

    a FILE and not an inline block, which it was until 2026-08-26: 8.8kb of it
    rode along in the html of all 31k pages, uncompressible against itself and
    re-sent on every hit. out here it is fetched once and cached for a year.

    a plain script tag rather than defer, in the same spot the block sat: the
    inline scripts in the pages' own {% block scripts %} run in document order,
    and defer would put every one of them in front of wireSuggest
*/

/*
    autocomplete, shared by the search bar and the report box on the
    results page.

    answers can arrive out of order on a slow connection, so each
    request takes a number and stale answers get dropped instead of
    painting over fresh ones
*/
//only for a box with no id of its own: aria-controls needs one to point at
var suggestBoxes = 0;

function wireSuggest(input, box, pick) {
    var timer;
    var seq = 0;      //stale answers carry an old number and get ignored
    var active = -1;  //which suggestion the arrow keys are on

    //the listbox half of a combobox. without these the dropdown is a div
    //nobody is told about and the arrow keys move an invisible highlight
    if (!box.id) {
        box.id = "suggest-" + (++suggestBoxes);
    }
    box.setAttribute("role", "listbox");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", box.id);

    function hide() {
        box.style.display = "none";
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    }

    function mark() {
        box.querySelectorAll(".suggestion").forEach(function(el, i) {
            el.classList.toggle("active", i == active);
            el.setAttribute("aria-selected", i == active ? "true" : "false");
        });
        //the highlight is a class, so this is what says it out loud
        if (active < 0) {
            input.removeAttribute("aria-activedescendant");
        } else {
            input.setAttribute("aria-activedescendant",
                box.querySelectorAll(".suggestion")[active].id);
        }
    }

    input.addEventListener("input", function() {
        clearTimeout(timer);
        var q = input.value.trim();
        if (q.length < 2) {
            hide();
            return;
        }
        //small delay so we dont spam the server on every single keypress
        timer = setTimeout(function() {
            var mine = ++seq;
            fetch("/suggest?q=" + encodeURIComponent(q))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (mine != seq) {
                        return;  //something newer is already in flight
                    }
                    box.innerHTML = "";
                    active = -1;
                    if (data.names.length == 0) {
                        hide();
                        return;
                    }
                    data.names.forEach(function(name, i) {
                        var div = document.createElement("div");
                        div.className = "suggestion";
                        //aria-activedescendant points at an id, so each row needs one
                        div.id = box.id + "-" + i;
                        div.setAttribute("role", "option");
                        div.setAttribute("aria-selected", "false");
                        div.textContent = name;
                        div.onclick = function() {
                            hide();
                            pick(name);
                        };
                        box.appendChild(div);
                    });
                    box.style.display = "block";
                    input.setAttribute("aria-expanded", "true");
                })
                .catch(hide);
        }, 150);
    });

    input.addEventListener("keydown", function(e) {
        if (box.style.display != "block") {
            return;
        }
        var n = box.querySelectorAll(".suggestion").length;
        if (e.key == "ArrowDown" || e.key == "ArrowUp") {
            e.preventDefault();
            active = e.key == "ArrowDown" ? (active + 1) % n : (active - 1 + n) % n;
            mark();
        } else if (e.key == "Enter" && active >= 0) {
            e.preventDefault();
            var name = box.querySelectorAll(".suggestion")[active].textContent;
            hide();
            pick(name);
        } else if (e.key == "Escape") {
            hide();
        }
    });

    //clicking anywhere else closes the dropdown
    document.addEventListener("click", function(e) {
        if (!box.contains(e.target) && e.target != input) {
            hide();
        }
    });
}

/* a div carrying role="button" gets a mouse click for free and nothing
   else, so the keyboard half is supplied once, here. Space is
   preventDefault'd or the page scrolls under the press.
   real <button>s never reach this: they are not [role=button] */
document.addEventListener("keydown", function(e) {
    if (e.key != "Enter" && e.key != " ") {
        return;
    }
    var el = e.target.closest('[role="button"][tabindex]');
    if (!el) {
        return;
    }
    e.preventDefault();
    el.click();
});

//closes on escape or a click elsewhere. the home page has no header,
//hence the guard
var navMenu = document.querySelector(".nav-menu");
if (navMenu) {
    document.addEventListener("click", function(e) {
        if (navMenu.open && !navMenu.contains(e.target)) {
            navMenu.open = false;
        }
    });
    document.addEventListener("keydown", function(e) {
        if (e.key == "Escape") {
            navMenu.open = false;
        }
    });
}

var searchInput = document.querySelector(".search-form input");
wireSuggest(searchInput, document.getElementById("suggestions"), function(name) {
    searchInput.value = name;
    document.querySelector(".search-form").submit();
});

//press / to jump to the search bar, like scryfall. not while typing
//somewhere else, / is a legal character in text
document.addEventListener("keydown", function(e) {
    if (e.key != "/" || e.ctrlKey || e.metaKey || e.altKey) {
        return;
    }
    var t = e.target;
    if (t.tagName == "INPUT" || t.tagName == "TEXTAREA" || t.isContentEditable) {
        return;
    }
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
});

/*
    one rule for every card and precon link on the site: a plain click
    goes further INTO delvefall, ctrl (cmd on a mac) opens where the
    thing came from. scryfall for a card, the official decklist for a
    precon.

    it used to run the other way round, which spent every page's
    ranking signal on scryfall instead of on this site's own card
    pages, and hijacked ctrl-click into a SAME TAB navigation.

    delegated on the document, so it covers links the dealer, load
    more and the swap queue build later
*/
function scryfallSearch(name) {
    //an exact-name search rather than the card's permalink, so a link
    //only needs the name it is already printing. scryfall sends a
    //single result straight to the card
    return "https://scryfall.com/search?q=" + encodeURIComponent('!"' + name + '"');
}

document.addEventListener("click", function(e) {
    if (!e.ctrlKey && !e.metaKey) {
        return;
    }
    var link = e.target.closest("a[data-card], a[data-source]");
    if (!link) {
        return;
    }
    e.preventDefault();
    //noopener because this is someone else's page in a tab we opened
    window.open(link.dataset.source || link.dataset.scryfall
                    || scryfallSearch(link.dataset.card),
                "_blank", "noopener");
});
