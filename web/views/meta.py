#---- crawler plumbing: robots.txt and the sitemap ----

import time
from urllib.parse import quote

from flask import Blueprint, Response, abort, request

from db import pool

bp = Blueprint("meta", __name__)

#the card pool split by how played the card is. google reports coverage PER
#SITEMAP, and one file of 31k urls can only ever answer "some of them", which is
#the number that cannot be acted on. split, the same report becomes a diagnosis:
#a top tier that indexes over a tail that does not is a crawl budget answer, all
#three stalling together is a site authority one.
#
#2000 is a crawl priority order and NOT a demand cliff, which this used to say it
#was. of the 21 cards search console had recorded a "cards like X" query for by
#2026-08, 11 sit in the top tier, 6 in played and 4 down in the tail (Tolarian
#Terror, Goblin Charbelcher, Balance, Moat). half the demand is outside the top
#tier, so dropping a sitemap to save crawl budget drops earning pages with it
CARD_TIERS = [
    {"key": "cards-top", "lo": 1, "hi": 2000},
    {"key": "cards-played", "lo": 2001, "hi": 10000},
    #open ended, and it carries the unranked with it: 303 cards hold no rank at
    #all, which is the least played there is
    {"key": "cards-tail", "lo": 10001, "hi": None},
]
CARD_TIER_BY_KEY = {t["key"]: t for t in CARD_TIERS}
SITEMAP_KEYS = ["pages"] + [t["key"] for t in CARD_TIERS]

#the rows are cached per tier for a day, changing on the ingest's schedule
#rather than the request's. the XML is rebuilt per request, embedding whichever
#host the request arrived on
_rows = {}


def tier_rows(tier):
    #(name, lastmod) per card. a DATE and not a timestamp: the ingest runs once a
    #day, so the clock time would be noise dressed up as precision
    hit = _rows.get(tier["key"])
    now = time.time()
    if hit and now - hit["made"] < 60 * 60 * 24:
        return hit["rows"]
    if tier["hi"] is None:
        sql = ("SELECT name, text_changed_at FROM cards WHERE edhrec_rank >= %s OR edhrec_rank IS NULL"
               " ORDER BY edhrec_rank NULLS LAST, name")
        args = (tier["lo"],)
    else:
        sql = ("SELECT name, text_changed_at FROM cards WHERE edhrec_rank BETWEEN %s AND %s"
               " ORDER BY edhrec_rank, name")
        args = (tier["lo"], tier["hi"])
    with pool.connection() as conn:
        rows = [(r["name"], r["text_changed_at"].date().isoformat() if r["text_changed_at"] else None)
                for r in conn.execute(sql, args)]
    _rows[tier["key"]] = {"rows": rows, "made": now}
    return rows


def xml(lines):
    #text/xml and NOT application/xml, so flask-compress gzips it
    return Response("\n".join(lines), mimetype="text/xml")


def urlset(rows):
    #(loc, lastmod) pairs, and a None lastmod emits NOTHING rather than a stand
    #in. google treats the field as all or nothing: identical dates across a file
    #are the signal it uses to decide a site's are invented, and it discounts
    #them sitewide after that. cards.text_changed_at is the one date here that is
    #real, so a card that has never been seen to change keeps its silence
    return (['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
            + ["<url><loc>" + loc + "</loc>"
               + ("<lastmod>" + lastmod + "</lastmod>" if lastmod else "")
               + "</url>" for loc, lastmod in rows]
            + ['</urlset>'])


def page_locs():
    #app.py registers this blueprint, so importing it up top closes the circle.
    #once per sitemap build, which is a request a day at most
    from app import PRECON_SORTS, PRECON_DEFAULT, precon_board

    root = request.url_root
    locs = [root + p for p in ("", "unique", "deck", "precons", "guide", "privacy", "support")]
    #every ranking is its own page answering its own question, so all ten are
    #worth crawling. the DEFAULT sort is /precons above and is not repeated, or
    #google meets the same board at two addresses. the era cuts are absent, being
    #a filter on one ranking and canonicalising back to it
    locs += [root + "precons?sort=" + quote(s["key"])
             for s in PRECON_SORTS if s["key"] != PRECON_DEFAULT["key"]]
    #the slugs are mtgjson filenames (letters, digits, underscores) so nothing
    #here needs escaping, but quote() runs anyway rather than trusting that
    locs += [root + "precons/" + quote(r["slug"]) for r in precon_board()]
    return locs


def card_locs(tier):
    root = request.url_root
    #quote()'s defaults mirror the urlencode filter building the canonicals in
    #search.html, so these ARE the urls the pages declare. it also percent-encodes
    #every xml special, & included, so no xml escaping
    return [(root + "search?q=" + quote(name), lastmod) for name, lastmod in tier_rows(tier)]


@bp.route("/sitemap.xml")
def sitemap():
    #an INDEX now rather than the whole list. robots.txt points here and this is
    #the address already submitted to search console, so it stays the one door
    #and the children are found through it
    root = request.url_root
    return xml(['<?xml version="1.0" encoding="UTF-8"?>',
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
               + ["<sitemap><loc>" + root + "sitemap-" + key + ".xml</loc></sitemap>"
                  for key in SITEMAP_KEYS]
               + ['</sitemapindex>'])


@bp.route("/sitemap-<key>.xml")
def sitemap_part(key):
    if key == "pages":
        #hand written pages and the precon boards, none of which has a date of
        #its own worth trusting: the boards move whenever a card's price does
        return xml(urlset((loc, None) for loc in page_locs()))
    tier = CARD_TIER_BY_KEY.get(key)
    if tier is None:
        abort(404)
    return xml(urlset(card_locs(tier)))


@bp.route("/robots.txt")
def robots():
    #the disallows are the json endpoints the pages fetch, nothing a search result
    #should point at. every human page stays open
    return Response("\n".join([
        "User-agent: *",
        "Disallow: /suggest",
        "Disallow: /more",
        "Disallow: /unique/",
        #belt and braces with the noindex: a post result has no url to index
        "Disallow: /deck/read",
        "Disallow: /deck/found",
        #the index, which names the four parts. only this one is advertised
        "Sitemap: " + request.url_root + "sitemap.xml",
    ]) + "\n", mimetype="text/plain")


#llmstxt.org's shape: an h1, a blockquote, then linked sections. what an agent
#fetching the site cold would otherwise have to infer from 31k near-identical
#card pages, which is what the site is FOR and which of its numbers mean what.
#
#it earns its place as an index and not as a pitch: every line here is a page
#that exists or a fact about where the data came from. google confirmed june 2026
#that this file does nothing for search or ai overviews, so nothing below is
#written at a ranking
@bp.route("/llms.txt")
def llms():
    root = request.url_root
    return Response("""# Delvefall

> Finds Magic: the Gathering cards by what their rules text does, rather than by
> the words it uses. Every card's rules lines are embedded separately and matched
> line against line, so "destroy target creature" finds the removal and not the
> other cards that happen to say "target". It also scores how unusual a card's
> text is against the rest of the game, and reads a Commander decklist for
> originality, salt, price, card age and play rate against all %d official
> precons.

No account, no syntax to learn, no ads. Type a card name.

## What the numbers mean

- Originality: one minus how close a card's nearest match anywhere in Magic gets,
  so a card at 0.30 has something out there 70%% like it.
- Salt: EDHREC's salt survey, players voting on the cards they least enjoy
  facing, roughly 0 to 3.
- Play rate: EDHREC's rank for how often a card is played in Commander, where #1
  is the most played card in the format.
- Card age: counted from a card's earliest printing, so a reprint does not make
  an old card new.

## Pages

- [Card search](%ssearch?q=Swords+to+Plowshares): every card that does the same
  thing as the named one, ranked by how close, with prices and alternatives. One
  page per card, %s of them. The query string is the card's exact name.
- [The most unique cards](%sunique): the cards whose abilities nothing else in
  the game comes close to.
- [Deck lens](%sdeck): paste a Commander decklist, or import one from Moxfield or
  Archidekt, and read it against every precon.
- [Commander precons ranked](%sprecons): all %d of them by originality, salt,
  price, play rate and age, each ranking its own page.
- [How it works](%sguide): what the site does and what every number on a result
  means.
- [Privacy](%sprivacy): no accounts, no tracking cookies, no IP addresses kept.

## Crawling

- [Sitemap index](%ssitemap.xml): four parts, the hand written pages and then the
  card pages split into three tiers by how played the card is.
- [robots.txt](%srobots.txt): the json endpoints the pages fetch are disallowed,
  every human page is open.

## Where the data comes from

- Card data and images: [Scryfall](https://scryfall.com).
- Concept tags: [Scryfall Tagger](https://tagger.scryfall.com), applied by hand
  by its volunteers.
- Play rate and salt: [EDHREC](https://edhrec.com).
- Precon decklists: [MTGJSON](https://mtgjson.com).

Unofficial Fan Content. Not approved or endorsed by Wizards of the Coast.
""" % (precon_total(), root, "{:,}".format(card_total()), root, root, root,
       precon_total(), root, root, root, root),
                    mimetype="text/plain")


def card_total():
    #off the sitemap tiers rather than its own count(*): they partition the whole
    #table between them, they are cached for a day already, and a figure that
    #disagreed with the sitemaps would be the one number here worth doubting
    return sum(len(tier_rows(t)) for t in CARD_TIERS)


def precon_total():
    #the same board /precons ranks, so the file cannot claim a count the site
    #does not show. cached an hour at its own end
    from app import precon_board

    return len(precon_board())
