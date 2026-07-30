#---- crawler plumbing: robots.txt and the sitemap ----

import re
import time
from urllib.parse import quote

from flask import Blueprint, Response, request

from db import pool

bp = Blueprint("meta", __name__)

#the NAMES are cached for a day, changing on the ingest's schedule rather than
#the request's. the XML is rebuilt per request, embedding whichever host the
#request arrived on
_sitemap_names = {"names": [], "made": 0.0}


@bp.route("/sitemap.xml")
def sitemap():
    #app.py registers this blueprint, so importing it up top closes the circle.
    #once per sitemap build, which is a request a day at most
    from app import PRECON_SORTS, PRECON_DEFAULT, precon_board

    now = time.time()
    if not _sitemap_names["names"] or now - _sitemap_names["made"] > 60 * 60 * 24:
        with pool.connection() as conn:
            _sitemap_names["names"] = [r["name"] for r in conn.execute("SELECT name FROM cards ORDER BY name")]
        _sitemap_names["made"] = now
    root = request.url_root
    #the day the INGEST last finished, never today: a sitemap swearing all 31k
    #pages changed this morning is one google stops believing, and a card page
    #only moves when its scores are recomputed.
    #checked into shape rather than escaped, because escape() hands back Markup
    #and "<lastmod>" + Markup escapes the LEFT side, putting &lt;lastmod&gt; in
    #the file. a yyyy-mm-dd matching this pattern has no xml specials by
    #definition
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
    #every ranking is its own page answering its own question, so all ten are
    #worth crawling. the DEFAULT sort is /precons above and is not repeated, or
    #google meets the same board at two addresses. the era cuts are absent, being
    #a filter on one ranking and canonicalising back to it
    for s in PRECON_SORTS:
        if s["key"] != PRECON_DEFAULT["key"]:
            out.append("<url><loc>" + root + "precons?sort=" + quote(s["key"]) + "</loc>" + stamp + "</url>")
    #the slugs are mtgjson filenames (letters, digits, underscores) so nothing
    #here needs escaping, but quote() runs anyway rather than trusting that
    for r in precon_board():
        out.append("<url><loc>" + root + "precons/" + quote(r["slug"]) + "</loc>" + stamp + "</url>")
    for name in _sitemap_names["names"]:
        #quote()'s defaults mirror the urlencode filter building the canonicals
        #in search.html, so these ARE the urls the pages declare. it also
        #percent-encodes every xml special, & included, so no xml escaping
        out.append("<url><loc>" + root + "search?q=" + quote(name) + "</loc>" + stamp + "</url>")
    out.append("</urlset>")
    #text/xml and NOT application/xml, so flask-compress gzips it. the protocol
    #caps one sitemap at 50k urls, the card pool sits well under
    return Response("\n".join(out), mimetype="text/xml")


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
        "Sitemap: " + request.url_root + "sitemap.xml",
    ]) + "\n", mimetype="text/plain")
