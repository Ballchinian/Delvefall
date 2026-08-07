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

#the NAMES are cached per tier for a day, changing on the ingest's schedule
#rather than the request's. the XML is rebuilt per request, embedding whichever
#host the request arrived on
_names = {}


def tier_names(tier):
    hit = _names.get(tier["key"])
    now = time.time()
    if hit and now - hit["made"] < 60 * 60 * 24:
        return hit["names"]
    if tier["hi"] is None:
        sql = ("SELECT name FROM cards WHERE edhrec_rank >= %s OR edhrec_rank IS NULL"
               " ORDER BY edhrec_rank NULLS LAST, name")
        args = (tier["lo"],)
    else:
        sql = "SELECT name FROM cards WHERE edhrec_rank BETWEEN %s AND %s ORDER BY edhrec_rank, name"
        args = (tier["lo"], tier["hi"])
    with pool.connection() as conn:
        names = [r["name"] for r in conn.execute(sql, args)]
    _names[tier["key"]] = {"names": names, "made": now}
    return names


def xml(lines):
    #text/xml and NOT application/xml, so flask-compress gzips it
    return Response("\n".join(lines), mimetype="text/xml")


def urlset(locs):
    #NO lastmod anywhere, deliberately. it was the ingest's own day stamped onto
    #all 31k urls at once, and google treats the field as all or nothing:
    #identical dates everywhere are the signal it uses to decide a site's are
    #invented, and it discounts them sitewide after that. nothing here knows when
    #a card page really moved. cards.updated_at cannot stand in either, it is
    #rewritten every run because prices move daily. a column that only turned on
    #a text_hash change would be a real one
    return (['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
            + ["<url><loc>" + loc + "</loc></url>" for loc in locs]
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
    return [root + "search?q=" + quote(name) for name in tier_names(tier)]


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
        return xml(urlset(page_locs()))
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
