#---- crawler plumbing: robots.txt and the sitemap ----
#the two files nobody visits and every crawler reads. no html, no templates,
#and nothing here is on the path of a page a person waits for

import re
import time
from urllib.parse import quote

from flask import Blueprint, Response, request

from db import pool

bp = Blueprint("meta", __name__)

#every card's search page is a landing page, but crawlers can only find
#them by walking result pages link by link. the sitemap hands over the
#whole list of canonical card urls in one file. the names are cached for a
#day (they change on the ingest's schedule, not the request's), the xml is
#rebuilt per request because it embeds whichever host the request came in on
_sitemap_names = {"names": [], "made": 0.0}


@bp.route("/sitemap.xml")
def sitemap():
    #the precon board is app.py's, and app.py registers this blueprint, so
    #importing it up top would close the circle. asked for here instead, once
    #per sitemap build, which is a request a day at most
    from app import PRECON_SORTS, PRECON_DEFAULT, precon_board

    now = time.time()
    if not _sitemap_names["names"] or now - _sitemap_names["made"] > 60 * 60 * 24:
        with pool.connection() as conn:
            _sitemap_names["names"] = [r["name"] for r in conn.execute("SELECT name FROM cards ORDER BY name")]
        _sitemap_names["made"] = now
    root = request.url_root
    #one date for every url, and it is the day the ingest last finished rather
    #than today. a sitemap that swears all 31k pages changed this morning is a
    #sitemap google stops believing, and it is not even true: a card page only
    #moves when the scores behind it are recomputed. meta carries that date
    #already, so nothing new has to be stored to say it honestly
    #the date is checked into shape rather than escaped, because escape()
    #hands back Markup and "<lastmod>" + Markup escapes the LEFT side, which
    #would put &lt;lastmod&gt; in the file. a yyyy-mm-dd that matches this
    #pattern has no xml special characters in it by definition
    stamp = ""
    try:
        with pool.connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'scryfall_updated_at'").fetchone()
        day = (row["value"] or "")[:10] if row else ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            stamp = "<lastmod>" + day + "</lastmod>"
    except Exception:
        pass
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in ("", "unique", "deck", "precons", "guide", "privacy", "support"):
        out.append("<url><loc>" + root + page + "</loc>" + stamp + "</url>")
    #every ranking of the board is its own page with its own title, heading and
    #sentence, so every one of them is worth crawling: "the cheapest commander
    #precons" and "the precons with the oldest cards" are different questions
    #people type, and one page answering all ten answers none of them. the
    #default sort is /precons above and is not repeated here, or google meets
    #the same board at two addresses. the era cuts are deliberately absent: they
    #canonicalise back to their sort, being a filter on one ranking rather than
    #a ranking of their own. the keys are plain lowercase words from the
    #constant, so nothing here needs escaping
    for s in PRECON_SORTS:
        if s["key"] != PRECON_DEFAULT["key"]:
            out.append("<url><loc>" + root + "precons?sort=" + quote(s["key"]) + "</loc>" + stamp + "</url>")
    #one page per precon. they are server rendered and each one is about a
    #deck people search by name, so they are worth crawling. the slugs are
    #mtgjson filenames (letters, digits and underscores) so nothing here
    #needs escaping, but quote() runs anyway rather than trusting that
    for r in precon_board():
        out.append("<url><loc>" + root + "precons/" + quote(r["slug"]) + "</loc>" + stamp + "</url>")
    for name in _sitemap_names["names"]:
        #quote() with its defaults mirrors the urlencode filter building the
        #canonicals in search.html, so these are the urls the pages declare.
        #it also percent-encodes every xml-special character, & included, so
        #the raw name never needs xml escaping
        out.append("<url><loc>" + root + "search?q=" + quote(name) + "</loc>" + stamp + "</url>")
    out.append("</urlset>")
    #text/xml instead of application/xml so flask-compress gzips it. the
    #protocol caps one sitemap at 50k urls, the card pool sits well under
    return Response("\n".join(out), mimetype="text/xml")


@bp.route("/robots.txt")
def robots():
    #the disallows are the json endpoints the pages fetch, nothing a search
    #result should point at. every human page stays open, and the sitemap
    #line lets crawlers find the card list without a console submission
    return Response("\n".join([
        "User-agent: *",
        "Disallow: /suggest",
        "Disallow: /more",
        "Disallow: /unique/",
        #a pasted list is nobody's business and there is no url to index
        #anyway, the page is a post result. belt and braces with its noindex
        "Disallow: /deck/read",
        "Disallow: /deck/found",
        "Sitemap: " + request.url_root + "sitemap.xml",
    ]) + "\n", mimetype="text/plain")
