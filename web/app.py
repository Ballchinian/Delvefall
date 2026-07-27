#the actual website. the old version loaded a 90mb embedding matrix into
#memory at startup, this one just asks postgres. the embeddings live in the
#database and pgvector does the similarity math right where the data is, so
#this process stays tiny and never touches torch

import io
import re
import os
import csv
import math
import mimetypes
import time
import uuid
import json
import random
import hashlib
import secrets
import datetime
import unicodedata
import urllib.request
from urllib.parse import quote, urlencode
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, redirect, abort, make_response, url_for, Response
from flask_compress import Compress
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from db import pool
from prefix_words import PREFIX_WORDS
#the copies web/ does not own, kept in one file so tools/check_sync.py has one
#place to compare against the rest of the repo. see mirror.py for the list
from mirror import (REMINDER_KEYWORDS, reminder_is_the_rule, clean_line, line_weight,
                    EMBED_COLUMNS, embed_column, EMBED_COL,
                    concept_display, concept_raw_gate, mech_display)
#who a visitor is for a day, without keeping anything that says who they are.
#the report limiter and the import limiter identify people through this too
import visitors
from visitors import client_ip, visitor_token, _utc_day
from views.meta import bp as meta_bp

#say what a .js file is rather than asking the machine we happen to be on.
#python reads its mime table from the host: linux says text/javascript, but a
#windows box reads the registry and plenty of them answer text/plain.
#
#that used to be survivable, because a classic <script> sniffs the body and
#runs it regardless. it is NOT survivable now that the pages load
#<script type="module">: module scripts are strictly mime checked per spec,
#and a browser hard refuses text/plain with nothing rendered and one console
#line to explain it. this made the site look broken on a windows dev box and
#fine on railway, which is the worst shape a bug can take
mimetypes.add_type("text/javascript", ".js")

app = Flask(__name__)

#railway terminates tls one proxy in front of this app, so without this
#flask believes every request was plain http on an internal hostname. the
#canonical and og:url tags embed request.url_root, and those must say https
#on the real domain or google treats every page as its http twin
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

#one canonical domain: once CANONICAL_HOST names the real domain, every other
#host 301s to it, https and all. unset means no redirect, so this ships safely
#before dns is ready. only GET/HEAD move, and railway's healthcheck host is
#left alone so the deploy still passes its check
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().rstrip("/").lower()


@app.before_request
def force_canonical_host():
    if not CANONICAL_HOST or request.method not in ("GET", "HEAD"):
        return
    if request.host.lower() in (CANONICAL_HOST, "healthcheck.railway.app"):
        return
    url = "https://" + CANONICAL_HOST + request.path
    if request.query_string:
        url += "?" + request.query_string.decode()
    return redirect(url, code=301)


#gzip for every text response (html, json, css, js). the search page and the
#/more payloads are prose-heavy and shrink several times over
Compress(app)

#static files may cache for a year because static_url below stamps a content
#hash onto every url the templates emit: changing a file changes its url, so
#a stale cache can never serve an old stylesheet against a new page
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 365

#a lid on any request body, checked by werkzeug before it reads the stream.
#DECK_MAX_CHARS below looks like it already does this and it does not: it
#trims the text after request.form has parsed the whole body into memory, so
#the paste box is capped and the process is not.
#
#1mb rather than something tighter because /unique/cards really does post a
#seen list of up to 4000 uuids, about 170kb, and the paste box takes 60000
#chars. both sit well under it, and a 5mb paste gets a 413 without being read
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

_static_hash = {}


@app.template_global()
def static_url(filename):
    v = _static_hash.get(filename)
    if v is None:
        with open(os.path.join(app.static_folder, filename), "rb") as f:
            v = hashlib.md5(f.read()).hexdigest()[:8]
        _static_hash[filename] = v
    return url_for("static", filename=filename) + "?v=" + v


_MANA_TOKEN = re.compile(r"\{([^}]+)\}")


#the mana cost as scryfall's symbol svgs: {2}{W/U} becomes two imgs, named
#the way the files in static/symbols are named (WU.svg). tokens with no file
#and the text between tokens ({W} // {U} on split cards) stay as text
@app.template_filter()
def mana(cost):
    if not cost:
        return ""
    out = []
    last = 0
    for m in _MANA_TOKEN.finditer(cost):
        out.append(escape(cost[last:m.start()]))
        try:
            url = static_url("symbols/" + m.group(1).replace("/", "") + ".svg")
        except OSError:
            out.append(escape(m.group(0)))
        else:
            out.append(Markup('<img src="%s" alt="%s" width="16" height="16">') % (url, m.group(0)))
        last = m.end()
    out.append(escape(cost[last:]))
    return Markup("").join(out)


#the same symbols for the javascript side: rules text that arrives as json
#(the /more results, the unique dealer) is rendered by manaFill in cards.js,
#and this token -> cache-busted url map is what it renders from. built once,
#the symbols folder doesn't change while the app runs
_mana_urls = None


@app.template_global()
def mana_urls():
    global _mana_urls
    if _mana_urls is None:
        _mana_urls = {fn[:-4]: static_url("symbols/" + fn)
                      for fn in sorted(os.listdir(os.path.join(app.static_folder, "symbols")))
                      if fn.endswith(".svg")}
    return _mana_urls

#user reports from the results page (see the /feedback route). the table
#really lives in common/schema.sql, but that file ships with the ingest and
#railway only deploys the web folder, so the web app makes sure its own
#table exists, same reasoning as clean_line being copied below. names are
#snapshotted next to the ids because cards can vanish from the cards table
#before a report gets reviewed, and no foreign keys for the same reason
with pool.connection() as _conn:
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id            bigserial PRIMARY KEY,
            kind          text NOT NULL,
            anchor_id     uuid NOT NULL,
            anchor_name   text NOT NULL,
            expected_id   uuid,
            expected_name text,
            got_id        uuid,
            got_name      text,
            expected_pct  int,
            got_pct       int,
            reason        text NOT NULL DEFAULT '',
            picked_lines  text NOT NULL DEFAULT '',
            filters       text NOT NULL DEFAULT '',
            embed_model   text NOT NULL DEFAULT '',
            ip            text NOT NULL DEFAULT '',
            status        text NOT NULL DEFAULT 'pending',
            created_at    timestamptz DEFAULT now()
        )
    """)
    #privacy-preserving visitor counting. same reason as the feedback table:
    #these live in common/schema.sql too, but railway only deploys web/, so
    #the app makes sure they exist. what each holds is explained at
    #todays_salt/count_visit below
    _conn.execute("CREATE TABLE IF NOT EXISTS visit_salt (day date PRIMARY KEY, salt text NOT NULL)")
    _conn.execute("""CREATE TABLE IF NOT EXISTS visit_seen (
        day   date NOT NULL,
        token text NOT NULL,
        PRIMARY KEY (day, token)
    )""")
    _conn.execute("CREATE TABLE IF NOT EXISTS visit_daily (day date PRIMARY KEY, uniques int NOT NULL)")
    #reports filed before the token change stored a real ip, and /privacy says
    #plainly that an ip address is never stored, so the old rows have to go or
    #that page is not telling the truth about what is on disk. length tells
    #them apart with nothing left over: a token is a sha256 hex digest, exactly
    #64 characters, and no address of either family reaches that. the rate
    #limit only ever looks an hour back, so clearing them costs nothing.
    #
    #this is in common/schema.sql too. it runs here as well so it lands on the
    #next deploy instead of waiting for an ingest, and after the first run it
    #matches no rows
    _conn.execute("UPDATE feedback SET ip = '' WHERE ip <> '' AND length(ip) <> 64")

#the review page at /admin only exists when this is set in the environment
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

#where the tip jar lives. ko-fi hosts the payment side entirely, so this is a
#plain link out and no money, card details or account ever touch this server.
#not an environment variable: it is a public url that never changes, and
#hiding a constant in railway only means the next person cannot find it
KOFI_URL = "https://ko-fi.com/ballchinian"

#what /support says the money is for. a real number is the persuasion, and a
#small one is the point: "support us" asks to be trusted, "£10 a month for the
#database and the domain" can be checked against the bill
RUNNING_COST = "about £10 a month"

#the display columns the frontend needs, so every query grabs the same set
CARD_FIELDS = "oracle_id, name, mana_cost, type_line, oracle_text, image, scryfall_uri, price_usd, price_eur, layout, image_back, edhrec_rank, salt, released_at"

#the choices in the type filter dropdown. also acts as a whitelist so
#nothing weird from the url ends up inside a LIKE pattern
CARD_TYPES = ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land"]

#the /unique page deals this many cards per request. one at a time, its the
#counterpart to scryfall's random card button
UNIQUE_PAGE = 1

#how the dealer picks. it used to take the 100 most unique unseen cards and
#draw from those, which is fine while the pool is deep and wrong as soon as it
#is not: with filters on, or a long trail, the hundredth card can sit miles
#below the first, so a 25% would be followed by a 3% and the page stopped
#looking like it was dealing unique cards at all.
#
#so the window is relative now. whatever the best available card scores, the
#draw happens among cards within UNIQUE_BAND of it, which keeps every deal
#near the top of what is actually left.
#
#the two bounds under it pull against each other on purpose. MIN_POOL widens
#a thin band so the page does not become a fixed running order that every
#visitor walks in the same sequence. MAX_DROP then caps that widening, because
#the top of the concepts axis is one card at 100, then 83, then 81, then a
#crowd at 67: an unbounded "top 25 whatever they score" there deals a 67 and a
#100 in the same breath, which is the exact jumping about this is meant to
#stop. so: prefer the band, widen it when it is lonely, never widen it far
UNIQUE_BAND = 0.05
UNIQUE_MIN_POOL = 25
UNIQUE_MAX_DROP = 0.08
UNIQUE_WINDOW = 80


#the mechanics <-> concepts slider maps its detents to these axis-2 weights
#(a 5% step existed once and changed nothing visible, so it went). results
#are ordered by (1-w) * mech percent + w * concept percent, and once the
#slider moves the badge shows that same blend, so the list always reads in
#descending order of the number on it
BLEND_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)

#the middle detent is where a first-time visitor lands: half rules text, half
#concepts. either pure end is a specialist's view, and someone who has never
#touched the slider is better served by both axes at once
BLEND_DEFAULT = 2


#---- the anchor's side of the concept axis ----

#the searched card's tag vector, which is what every axis-2 query scores
#against. dropping a tag on the page has to drop the inherited rows that only
#existed because of it, so the kept set is rebuilt the way ingest/tags.py
#built it in the first place: start from the tags a human actually typed,
#minus the dropped ones, then climb the tree. the weights come straight from
#card_tags, already carrying the inherited damping, so nothing here has to
#know what that damping is.
#
#the norm is recomputed over whatever survived, and that is the whole point.
#reusing the baked card_tag_norms row would put a shrunken numerator over a
#full-card denominator and quietly deflate every score, which would move the
#cutoff without moving the calibration. with nothing dropped this returns the
#baked norm to the digit, so the default path is a true no-op
#the line -> tag attribution, SHIPPED 2026-07-22. it was dark for months at
#88% precision / 82% recall, on the grounds that a concepts side quietly
#ignoring the right tag is worse than one ignoring nothing. the line-to-tag
#model took it to 94%/82%, and picking a line now moves both axes.
#
#ON BY DEFAULT rather than switched on by a railway variable: a shipped
#feature that depends on remembering an env var disappears the first time one
#gets reset, silently, with the site still returning 200s. set LINE_TAGS=0 to
#turn it off, which is the kill switch if the attribution ever regresses.
#
#with it off every path below falls through to the behaviour that shipped
#before the attribution landed: picking a line moves the rules-text side only,
#and the concepts side reads the whole card. those fallbacks are the ones
#already written for a database whose line_tags was never built, so it stays
#safe on a database the attribution has never run against
LINE_TAGS = os.environ.get("LINE_TAGS", "1").strip().lower() not in ("0", "false", "off", "no", "")

@app.context_processor
def feature_flags():
    #base.html builds the nav for every page, so the flags have to reach every
    #template rather than the handful that pass them explicitly.
    #
    #deck_min rides along because the paste box and the reading both quote the
    #floor, and the hub is rendered from two places with different arguments.
    #passing it by hand meant one of them would eventually say a stale number
    return {"line_tags_on": LINE_TAGS, "kofi_url": KOFI_URL, "running_cost": RUNNING_COST,
            "deck_min": DECK_MIN_FOR_RANK}


def card_has_attribution(conn, oracle_id):
    #does the attribution know anything about this card at all? "this line owns
    #no tags" and "nobody has ever run ingest/attribute.py here" both arrive as
    #an empty result set, and they want opposite handling, so ask the card
    return conn.execute("""
        SELECT 1 FROM line_tags lt JOIN lines l ON l.id = lt.line_id
        WHERE l.oracle_id = %s AND NOT l.whole LIMIT 1
    """, (oracle_id,)).fetchone() is not None


def anchor_vector(conn, oracle_id, dropped, picked=(), forced=()):
    #picked lines narrow the starting set to the tags those lines are about
    #(ingest/attribute.py works out which, card-level tags ride along with
    #every line). without a line selection the starting set is every tag a
    #human typed on the card, which is what it always was. forced tags are
    #added back on top, so a wrong guess by the attribution costs one click
    #rather than the whole line selection
    if picked and LINE_TAGS:
        start = """
            SELECT DISTINCT lt.tag FROM line_tags lt
            JOIN lines l ON l.id = lt.line_id
            WHERE l.oracle_id = %s AND NOT l.whole AND l.line_text = ANY(%s)
              AND NOT (lt.tag = ANY(%s))
            UNION
            SELECT tag FROM card_tags
            WHERE oracle_id = %s AND NOT inherited
              AND tag = ANY(%s) AND NOT (tag = ANY(%s))
        """
        params = (oracle_id, list(picked), list(dropped),
                  oracle_id, list(forced), list(dropped), oracle_id)
    else:
        start = """
            SELECT tag FROM card_tags
            WHERE oracle_id = %s AND NOT inherited AND NOT (tag = ANY(%s))
        """
        params = (oracle_id, list(dropped), oracle_id)
    rows = conn.execute("""
        WITH RECURSIVE kept AS (""" + start + """
            UNION
            SELECT p.tag FROM kept
            JOIN tags t ON t.tag = kept.tag
            CROSS JOIN LATERAL unnest(t.parents) AS p(tag)
        )
        SELECT ct.tag, ct.weight FROM card_tags ct
        JOIN kept ON kept.tag = ct.tag
        WHERE ct.oracle_id = %s
    """, params).fetchall()
    #an empty result here means one of two very different things, and telling
    #them apart is what card_has_attribution is for. either the attribution has
    #never run against this database, in which case falling back to the whole
    #card is right and the alternative is silently muting the concept axis on
    #every search. OR the picked line genuinely is not about anything, which is
    #the normal state of a keyword line: Gishath's "Vigilance, trample, haste"
    #owns none of its card's seven tags, they all belong to the combat damage
    #trigger.
    #
    #in that second case the concept axis has nothing honest to say, so it sits
    #the search out rather than quietly scoring on tags the user was just told
    #do not apply. find_similar reads the empty norm and ranks on rules text
    #alone, which is exactly what someone picking a keyword line is asking for
    if picked and not rows and not card_has_attribution(conn, oracle_id):
        return anchor_vector(conn, oracle_id, dropped)
    tags = [r["tag"] for r in rows]
    weights = [r["weight"] for r in rows]
    norm = math.sqrt(sum(w * w for w in weights))
    return tags, weights, norm


def anchor_chips(conn, oracle_id, dropped, picked=(), forced=()):
    #the chips under the rules text: the tags a human typed on this card,
    #rarest first. inherited ancestors stay out of the list - they are implied
    #by the typed tags rather than said about the card, and showing "removal"
    #next to "removal-destroy" reads as noise. dropping the child takes the
    #parent with it anyway, in anchor_vector.
    #
    #each chip carries WHY it is on or off, because a tag going quiet with no
    #explanation is the thing that reads as a broken page. "off" is a tag the
    #user clicked, "aside" is one the picked lines simply aren't about
    rows = conn.execute("""
        SELECT ct.tag, t.description FROM card_tags ct
        JOIN tags t ON t.tag = ct.tag
        WHERE ct.oracle_id = %s AND NOT ct.inherited
        ORDER BY ct.weight DESC, ct.tag
    """, (oracle_id,)).fetchall()
    on_lines = None
    if picked and LINE_TAGS:
        on_lines = {r["tag"] for r in conn.execute("""
            SELECT DISTINCT lt.tag FROM line_tags lt
            JOIN lines l ON l.id = lt.line_id
            WHERE l.oracle_id = %s AND NOT l.whole AND l.line_text = ANY(%s)
        """, (oracle_id, list(picked))).fetchall()}
        #an empty set is a real answer, not a missing one: a keyword line owns
        #no tags, and setting every chip aside is exactly right for it. only
        #fall back to showing them all when the attribution has never run here,
        #or Gishath's "Vigilance, trample, haste" leaves all seven dinosaur
        #tags lit as though they were about keywords
        if not on_lines and not card_has_attribution(conn, oracle_id):
            on_lines = None
    chips = []
    for r in rows:
        if r["tag"] in dropped:
            state = "off"
        elif on_lines is not None and r["tag"] not in on_lines:
            #put back by hand after the line picker set it aside. it counts
            #like any other live tag, it just wears its own look so the page
            #still shows the picker's guess and your correction to it
            state = "kept" if r["tag"] in forced else "aside"
        else:
            state = "on"
        chips.append({"tag": r["tag"], "description": r["description"], "state": state})
    return chips


def concept_between(conn, oracle_a, oracle_b, dropped=()):
    #the calibrated concept percent between two specific cards, for the
    #feedback path. 0 when either card carries no tags at all. oracle_a is
    #the anchor, so the page's dropped tags apply to it and the report says
    #what the user was actually looking at
    tags, weights, norm = anchor_vector(conn, oracle_a, dropped)
    other = conn.execute("SELECT norm FROM card_tag_norms WHERE oracle_id = %s", (oracle_b,)).fetchone()
    if not tags or other is None:
        return 0
    shared = conn.execute("""
        SELECT coalesce(sum(a.weight * cb.weight), 0) AS s
        FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
        JOIN card_tags cb ON cb.tag = a.tag AND cb.oracle_id = %s
    """, (tags, weights, oracle_b)).fetchone()["s"]
    return concept_display(shared / (norm * other["norm"]))


def find_card(query):
    #one query instead of up to four round trips: every way a name can match
    #(exact, starts-with, anywhere, trigram-fuzzy) becomes a tier and the
    #best-tiered card wins. inside the substring tiers alphabetical order
    #decides (trigram closeness would favor short names, "delver" must find
    #Delver of Secrets, not Delver's Torch), the fuzzy tier goes closest
    #first - its alphabetical CASE key is NULL, which sorts after every real
    #name. the % operator means "similar enough to bother" (so garbage
    #queries still return nothing) and <-> sorts by closest. %% because
    #psycopg uses % for parameters
    q = query.strip()
    with pool.connection() as conn:
        return conn.execute("""
            SELECT """ + CARD_FIELDS + """,
                   CASE WHEN lower(name) = lower(%s) THEN 0
                        WHEN name ILIKE %s THEN 1
                        WHEN name ILIKE %s THEN 2
                        ELSE 3 END AS tier
            FROM cards
            WHERE lower(name) = lower(%s) OR name ILIKE %s OR name ILIKE %s OR name %% %s
            ORDER BY tier, CASE WHEN name ILIKE %s THEN name END, name <-> %s, name
            LIMIT 1
        """, (q, q + "%", "%" + q + "%", q, q + "%", "%" + q + "%", q, "%" + q + "%", q)).fetchone()


#all the url params past q and offset live in these little readers. home()
#and /more both use them, so the load more button sees exactly the same
#filters and picked lines as the page it's glued onto

def rank_label(rank):
    #edhrec's popularity rank next to the price, 1 being the most played card
    #in the format. plenty of cards are unranked (nobody plays them, or
    #they're too new to have a rank yet), those just show nothing
    return "#" + str(rank) if rank is not None else ""


def salt_label(salt):
    #on EVERY card that has a score, not just the salty ones: the number is
    #only useful if its absence means "nobody voted" rather than "below some
    #bar you cannot see". two decimals to match the deck pages, and because
    #most of the pool lives between 0.07 and 0.38 where one decimal collapses
    #half the range into "0.2"
    return "" if salt is None else "%.2f" % salt


#a year, in days, and the SAME one the board's sql divides by. the age column
#there is seconds over 31557600, which is 365.25 days, so a card cannot read as
#12.4 years on one page and 12.5 on another
YEAR_DAYS = 365.25


def age_label(released):
    #how long ago this card was FIRST printed, the fourth number on the row
    #under a card. it used to be the one metric with no reading of its own on
    #the results grid: the date sorts reordered the page and nothing on any card
    #said why, because there was nothing there to say it with.
    #
    #the word "years" is not decoration. a bare "12.4" sitting between a price
    #and a #rank has to say what KIND of number it is before it says anything
    #else, which is the same reason the salt figure wears a mark.
    #
    #released_at is scryfall's EARLIEST printing, so a reprint does not make an
    #old card new. that is the whole point of the measurement and the reason a
    #deck stuffed with reprints still reads old. a card with no date shows
    #nothing at all, exactly like an unpriced or unvoted one: absent is not zero
    if released is None:
        return ""
    return "%.1f years" % ((datetime.date.today() - released).days / YEAR_DAYS)


CURRENCY_SIGNS = {"usd": "$", "eur": "€", "gbp": "£"}

#the same three, spelled out, for any control that offers the choice rather
#than just printing the sign. pounds carry the caveat in the label because
#scryfall quotes dollars and euros only and ours is derived from both
CURRENCY_LABELS = [("usd", "$ dollars"), ("eur", "€ euros"), ("gbp", "£ pounds (approx.)")]

#pounds are derived, not sourced: scryfall prices in dollars and euros only,
#so the gbp figure is each known price converted and averaged, and the ui
#says approximate because it is. the rates are the ecb's daily reference
#rates via frankfurter.app (no key needed), refreshed daily, which is also
#how often the prices themselves move. the seeds hold whenever the fetch
#fails, so a rate api outage can never break a page
_gbp_rates = {"usd": 0.74, "eur": 0.86, "at": 0.0}


def gbp_rates():
    now = time.time()
    if now - _gbp_rates["at"] > 60 * 60 * 24:
        #the clock moves before the fetch, so a dead rate api gets retried
        #daily instead of stalling every request behind the timeout
        _gbp_rates["at"] = now
        try:
            with urllib.request.urlopen("https://api.frankfurter.app/latest?from=GBP&to=USD,EUR", timeout=3) as r:
                rates = json.load(r)["rates"]
            _gbp_rates["usd"] = 1.0 / rates["USD"]
            _gbp_rates["eur"] = 1.0 / rates["EUR"]
        except Exception:
            pass
    return _gbp_rates["usd"], _gbp_rates["eur"]


def price_col(currency):
    #the sql for the price in the chosen currency, everywhere a query
    #filters or sorts on one. dollars and euros are real columns. pounds
    #are computed on the spot, and the coalesce pair does the averaging
    #without a CASE: with both prices known each side is one of them, with
    #one known both sides collapse to it, with neither the whole thing is
    #NULL, exactly how the real columns behave for an unpriced card. the
    #rates are our own floats, not user input, so building them into the
    #string is safe
    if currency == "gbp":
        ru, re_ = gbp_rates()
        u = "c.price_usd * " + str(round(ru, 6))
        e = "c.price_eur * " + str(round(re_, 6))
        return "((coalesce(" + u + ", " + e + ") + coalesce(" + e + ", " + u + ")) / 2)"
    return "c.price_usd" if currency == "usd" else "c.price_eur"


def price_in(c, currency):
    #one already-fetched row's price in the chosen currency, as a float,
    #None when the card has no usable price there. the python twin of
    #price_col, for code that holds the row rather than a query
    if currency == "gbp":
        ru, re_ = gbp_rates()
        known = [float(c[col]) * rate for col, rate in (("price_usd", ru), ("price_eur", re_))
                 if c[col] is not None]
        return sum(known) / len(known) if known else None
    p = c["price_usd"] if currency == "usd" else c["price_eur"]
    return None if p is None else float(p)


def price_label(c, currency):
    #the price string under a card, in whichever currency the toggle picked.
    #empty when the card has no price there.
    #
    #ALWAYS two decimal places. printing the stored number as it came back
    #wrote "$0.2" for a twenty cent card, because that is what str() does to a
    #Decimal that happens to end in a zero, and a money column where some rows
    #have two digits and some have one reads as a bug in the number rather than
    #a bug in the formatting. pounds were already pinned this way and the other
    #two are now
    p = price_in(c, currency)
    return "" if p is None else CURRENCY_SIGNS[currency] + "%.2f" % p


def sideways(layout, type_line):
    #battles and split cards are printed sideways, so their frames offer the
    #rotate button. battles dont get their own layout from scryfall (theyre
    #transform cards), but Battle always leads the type line
    return layout == "split" or "Battle" in (type_line or "")


#---- the filter box compiler ----
#scryfall style syntax with parentheses, or/and and negation, compiled into
#one sql condition over the cards table:
#  o:word / o:"a phrase"   rules text contains it       t:creature   type line word
#  id:wug                  identity fits inside, like deckbuilding. id:c colorless
#  otag:removal            the community tag, straight from our own daily
#                          mirror of scryfall's tagger data
#  is:dfc is:split         card layout. is:gamechanger for the edh watchlist
#  f:commander             legal in commander. banned:commander for the reverse
#  usd>=1 eur<5 mv=2       price and mana value, cmc works for mv, eur too,
#                          and a bare price<5 follows the currency toggle
#  salt>=1.5               edhrec's salt score, 0 to about 3. cards nobody
#                          voted on have none and fail any salt comparison
#  - before anything negates it, words side by side mean and, "or" means or,
#  parens group: (o:draw or o:scry) -t:creature usd<5
#anything unrecognisable is skipped, a typo never breaks the search

FQ_TOKEN = re.compile(r"""
    (?P<paren>[()])
  | (?P<kw>and|or)(?=[\s()]|$)
  | (?P<neg>-)
  | (?P<cfield>usd|eur|gbp|price|salt|mv|cmc)\s*(?P<op>>=|<=|=|>|<)\s*(?P<num>\d+(?:\.\d+)?)
  | (?P<key>[a-z]+):(?:"(?P<qval>[^"]*)"|(?P<val>[^\s()]+))
  | (?P<junk>[^\s()]+)
""", re.IGNORECASE | re.VERBOSE)


def fq_term(key, value):
    #one key:value into (sql, params), or None for keys we don't speak (yet)
    key = key.lower()
    if key in ("o", "oracle"):
        return "c.oracle_text ILIKE %s", ["%" + value + "%"]
    if key in ("t", "type"):
        return "c.type_line ILIKE %s", ["%" + value + "%"]
    if key == "id":
        letters = "".join(ch for ch in value.upper() if ch in "WUBRG")
        if letters:
            return "c.color_identity ~ %s", ["^[" + letters + "]*$"]
        if "C" in value.upper():
            return "c.color_identity = ''", []
        return None
    if key in ("is", "layout"):
        #only the layout side of scryfall's is:. an unknown value (is:permanent,
        #is:reserved...) falls through to None and is skipped, never matched to
        #an empty set, same as any other key we don't speak
        v = value.lower()
        if v == "dfc":
            #a real two-sided card, the layouts that print a back face
            return "c.layout IN ('transform', 'modal_dfc', 'meld')", []
        if v in ("mdfc", "modal"):
            return "c.layout = 'modal_dfc'", []
        if v == "gamechanger":
            return "c.game_changer = true", []
        #the layouts that actually occur in the cards table. battle and token
        #are deliberately absent: battles arrive from scryfall as transform
        #cards and tokens never enter the database, so both would silently
        #match nothing instead of being skipped like any other unknown value
        if v in ("normal", "split", "flip", "transform", "modal_dfc", "meld",
                 "leveler", "class", "case", "saga", "adventure", "mutate",
                 "prototype", "prepare"):
            return "c.layout = %s", [v]
        return None
    if key in ("f", "format", "legal", "banned"):
        #commander is the only format whose legality we track
        if value.lower() in ("commander", "edh"):
            return "c.legal_commander = " + ("false" if key == "banned" else "true"), []
        return None
    if key in ("otag", "tag", "oracletag", "function"):
        #tagger tags form a hierarchy and the taggings sit on the leaves
        #(otag:removal itself tags nothing, spot-removal and friends do), so
        #the match walks the family tree downward, same as scryfall does
        return ("""EXISTS (SELECT 1 FROM card_tags ct WHERE ct.oracle_id = c.oracle_id AND ct.tag IN (
                     WITH RECURSIVE fam AS (
                         SELECT tag FROM tags WHERE tag = %s
                         UNION
                         SELECT t.tag FROM tags t JOIN fam f ON f.tag = ANY(t.parents)
                     ) SELECT tag FROM fam))""", [value.lower()])
    return None


def compile_fq(fq, currency="usd"):
    #tokenize then a little recursive descent. fail-soft on purpose: skipped
    #tokens and unbalanced parens degrade to a smaller filter, never a 500
    tokens = []
    for m in FQ_TOKEN.finditer(fq or ""):
        if m.group("paren"):
            tokens.append((m.group("paren"), None))
        elif m.group("kw"):
            tokens.append((m.group("kw").lower(), None))
        elif m.group("neg"):
            tokens.append(("-", None))
        elif m.group("cfield"):
            cf = m.group("cfield").lower()
            #usd, eur and gbp always mean themselves, the bare word price
            #follows the currency toggle
            col = {"usd": "c.price_usd", "eur": "c.price_eur", "gbp": price_col("gbp"),
                   "price": price_col(currency), "salt": "c.salt"}.get(cf, "c.cmc")
            tokens.append(("term", (col + " " + m.group("op") + " %s", [float(m.group("num"))])))
        elif m.group("key"):
            value = m.group("qval") if m.group("qval") is not None else m.group("val")
            tokens.append(("term", fq_term(m.group("key"), value)))
        #bare words fall through and are ignored
    pos = [0]

    def peek():
        return tokens[pos[0]][0] if pos[0] < len(tokens) else None

    def take():
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_unary():
        kind, payload = take()
        if kind == "-":
            inner = parse_unary()
            return ("NOT (" + inner[0] + ")", inner[1]) if inner else None
        if kind == "(":
            expr = parse_or()
            if peek() == ")":
                take()
            #keep the user's grouping in the sql, AND binds tighter than OR
            return ("(" + expr[0] + ")", expr[1]) if expr else None
        if kind == "term":
            return payload  #already (sql, params), or None for unknown keys
        return None  #stray ) or keyword, skip it

    def parse_and():
        parts = []
        while peek() not in (None, ")", "or"):
            if peek() == "and":
                take()
                continue
            unit = parse_unary()
            if unit:
                parts.append(unit)
        if not parts:
            return None
        sql = " AND ".join(p[0] for p in parts)
        return sql, [x for p in parts for x in p[1]]

    def parse_or():
        parts = []
        unit = parse_and()
        if unit:
            parts.append(unit)
        while peek() == "or":
            take()
            unit = parse_and()
            if unit:
                parts.append(unit)
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        sql = " OR ".join("(" + p[0] + ")" for p in parts)
        return sql, [x for p in parts for x in p[1]]

    parts = []
    while pos[0] < len(tokens):
        expr = parse_or()
        if expr:
            parts.append(expr)
        elif peek() is not None:
            take()  #stray token, keep moving
    if not parts:
        return None, []
    sql = " AND ".join("(" + p[0] + ")" for p in parts)
    return sql, [x for p in parts for x in p[1]]


def read_filters():
    f = {"errors": []}
    #the color checkboxes arrive as repeated params like colors=W&colors=U.
    #only real color letters get through, which matters because they end up
    #inside a regex below
    letters = ""
    for c in request.args.getlist("colors"):
        if len(c) == 1 and c in "WUBRG" and c not in letters:
            letters += c
    f["colors"] = letters
    #how the picked colors apply: at most (fits within, the deckbuilding
    #question, and the only behaviour before the mode existed), exactly
    #these, or including these
    mode = request.args.get("cmode", "")
    f["cmode"] = mode if mode in ("exact", "include") else "atmost"
    f["pmin"] = read_number("pmin", "minimum price", f["errors"])
    f["pmax"] = read_number("pmax", "maximum price", f["errors"])
    f["mvmin"] = read_number("mvmin", "minimum mana value", f["errors"])
    f["mvmax"] = read_number("mvmax", "maximum mana value", f["errors"])
    f["smin"] = read_number("smin", "minimum salt", f["errors"])
    f["smax"] = read_number("smax", "maximum salt", f["errors"])
    #an inverted range used to hand back an empty page with no explanation,
    #which read as the site breaking rather than the bounds disagreeing.
    #the filter still applies exactly as typed, the page just says why
    #nothing can match
    if f["pmin"] is not None and f["pmax"] is not None and f["pmin"] > f["pmax"]:
        f["errors"].append("your minimum price is above your maximum, so no card can fit between them")
    if f["mvmin"] is not None and f["mvmax"] is not None and f["mvmin"] > f["mvmax"]:
        f["errors"].append("your minimum mana value is above your maximum, so no card can fit between them")
    if f["smin"] is not None and f["smax"] is not None and f["smin"] > f["smax"]:
        f["errors"].append("your minimum salt is above your maximum, so no card can fit between them")
    #any of the picked types matches: an Artifact Creature answers to
    #Artifact, to Creature, and to both together. the whitelist stands in
    #for escaping, nothing else reaches the ILIKE patterns
    f["types"] = [t for t in request.args.getlist("type") if t in CARD_TYPES]
    f["cmdr"] = request.args.get("cmdr") == "1"
    f["gc"] = request.args.get("gc") == "1"
    #flipped from the launch version: most visitors are commander players, so
    #cards that arent legal stay hidden unless this asks for them. old shared
    #links with legal=1 wanted exactly what the default now does, so they
    #still mean the same thing
    f["illegal"] = request.args.get("illegal") == "1"
    #which currency the price bounds (and the filter box's bare price) mean
    f["cur"] = read_currency()
    #the filter box rides in as fq, compiled here so every page that reads
    #filters understands it. it stacks with the widgets (both apply)
    f["fq_sql"], f["fq_params"] = compile_fq(request.args.get("fq", ""), f["cur"])
    return f


def read_number(name, label, errors):
    #a number box's value, None when empty. junk (a doctored url, pasted
    #text) used to vanish silently, so a filter that "didn't work" gave no
    #hint why; now the page says what was ignored
    s = request.args.get(name, "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        errors.append('"' + s + '" is not a number, so your ' + label + ' was ignored')
        return None


def tier_cut(blend):
    #where the strong tier ends, in calibrated display units. the "hide
    #below X%" box that exposed this went away: a knob for "how similar" on
    #a similarity site was bloat, and its real job (keeping the price sorts
    #meaningful) is done by the split itself, since everything under the cut
    #pages in behind the weaker-matches button instead of joining the
    #sorts. 80 at both ENDS of the slider: pure mechanics pins the model's
    #real quality boundary there (same set of cards the old raw-90 cutoff
    #kept), and pure concepts shows the calibrated concept score, where good
    #matches also read 80+. the mixed detents show an average of two axes,
    #and averages rarely reach 80, so they sit at 70.
    #
    #since the slider was fixed at the middle this only ever returns 70. the
    #branch stays because it is the reason 70 is right, and deleting it would
    #leave a bare number nobody could argue with
    return 70 if 0 < blend < len(BLEND_WEIGHTS) - 1 else 80


#the sort is a FIELD plus a DIRECTION rather than one entry per combination.
#as one list it had grown to nine options, and half of them were the same idea
#backwards: "price low to high" and "price high to low" are not two things to
#choose between, they are one thing and a switch. scryfall splits them the
#same way, which is the control this audience already knows.
#
#asc/desc read as the CONCEPT named in the label, not as the column underneath:
#ascending play rate is least played, even though it is descending edhrec rank.
#nobody sees the words asc and desc, they see the sentence in the option
SORT_FIELDS = {
    "best":   {"label": "Best match"},
    "price":  {"label": "Price", "default": "asc",
               "asc": ("cheap", "cheapest first"),
               "desc": ("pricey", "priciest first")},
    "played": {"label": "Play rate", "default": "desc",
               "asc": ("obscure", "least played first"),
               "desc": ("played", "most played first")},
    #"Card age" and not "Release date". the two were the same measurement under
    #two names, one here and one on the precon board, and a metric that is
    #called something different depending on which page you met it on is two
    #metrics as far as anybody reading is concerned. the board's name won
    #because the readings underneath it are the catchy half: oldest and newest
    #cards is what somebody actually wants, and "release date" was never going
    #to be said out loud
    "released": {"label": "Card age", "default": "desc",
                 "asc": ("old", "oldest first"),
                 "desc": ("new", "newest first")},
    "salt":   {"label": "Salt", "default": "desc",
               "asc": ("mild", "least salty first"),
               "desc": ("salty", "saltiest first")},
}

#every value the sort took before the split. old links and old bookmarks still
#carry them, and they cost one dict to keep working forever. note that "played"
#is deliberately in both vocabularies and means the same thing in each
SORT_LEGACY = {
    "cheap": ("price", "asc"), "pricey": ("price", "desc"),
    "played": ("played", "desc"), "obscure": ("played", "asc"),
    "new": ("released", "desc"), "old": ("released", "asc"),
    "salty": ("salt", "desc"), "mild": ("salt", "asc"),
    #the release-date field was briefly called age, before the label and the
    #url were made to agree with each other
    "age": ("released", "desc"),
}


def read_sort_parts():
    #the two controls' values, which is what the page renders from
    field = request.args.get("sort", "best")
    direction = request.args.get("dir", "")
    if direction not in ("asc", "desc"):
        direction = ""
    if field in SORT_LEGACY:
        was_field, was_dir = SORT_LEGACY[field]
        #an explicit direction still wins, so flipping the toggle on a page
        #reached from an old link does what it looks like it does
        return was_field, (direction or was_dir)
    if field not in SORT_FIELDS:
        field = "best"
    return field, (direction or SORT_FIELDS[field].get("default", "desc"))


def read_sort():
    #the single key the ranking code has always spoken
    field, direction = read_sort_parts()
    pair = SORT_FIELDS[field].get(direction)
    return pair[0] if pair else "best"


#which figure on a card the page is currently ABOUT, as the class its container
#wears. every card on this site carries the same readings in the same places -
#one badge beside the name and four numbers under it - and the only thing a sort
#changes is which of the five is in ink and which four sit back in grey. that is
#all it changes, which is the point: a card does not gain or lose a number
#depending on how the page happens to be ordered, so the row reads the same
#everywhere and the eye still knows where to land.
#
#the badge is the site's OWN number, the one nothing outside Delvefall could
#tell you: the match percent on a search, the originality score on a deck page.
#the other four (price, play rate, salt, card age) are facts the world supplied.
#a badge is never a sort on the deck pages and never absent on a search, so one
#class covers both.
#
#BOTH vocabularies land here on purpose. /search calls the age field "released"
#and the precon board calls the same metric "age"; they are one idea with two
#url spellings, and the page that renders them should not have to know that
FOCUS_CLASS = {
    "best": "focus-badge", "original": "focus-badge",
    "price": "focus-price",
    "played": "focus-rank",
    "released": "focus-age", "age": "focus-age",
    "salt": "focus-salt",
}


def focus_class(key):
    #an unknown key focuses nothing rather than guessing, which leaves every
    #figure grey. that is the honest rendering of a grid with no chosen stat
    #(the deck-as-cards grids), not a fallback that has gone wrong
    return FOCUS_CLASS.get(key, "")


def read_currency():
    #usd, eur or gbp, for every price the site shows, filters and sorts on.
    #the url wins, then the remembered cookie, then dollars. scryfall only
    #prices the first two; pounds are derived (see gbp_rates)
    cur = request.args.get("cur")
    if cur is None:
        cur = request.cookies.get("cur", "usd")
    return cur if cur in CURRENCY_SIGNS else "usd"


@app.after_request
def remember_currency(resp):
    #any request that names a currency makes it the remembered one, so the
    #toggle sticks no matter which page it was flipped on (/search submits
    #its form, /unique deals and trail-walks through fetch, the precon board
    #and the deck pages link it).
    #
    #a COOKIE rather than localStorage, and it has to be. every price on this
    #site is rendered by the server: the precon board sums real money in sql,
    #and the pound figure is derived PER CARD from whichever of the two prices
    #that card carries, so it is not the dollar total times a rate and cannot
    #be recomputed in the browser from what is on the page. localStorage never
    #reaches the server, so the choice would arrive one render too late and the
    #board would paint in dollars and then correct itself, or cost a round trip
    #on every load. this is the one preference on the site the SERVER needs to
    #know, which is why it is the one kept in a cookie rather than next to the
    #seen cards and the recent decks
    cur = request.args.get("cur")
    if cur in CURRENCY_SIGNS:
        resp.set_cookie("cur", cur, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


def currency_urls():
    #this same page in each of the three currencies, for the toggle. built off
    #the request's own args so a page does not have to know what its own url
    #looks like, and so every other control on it survives the flip
    out = {}
    for code in CURRENCY_SIGNS:
        args = request.args.to_dict(flat=True)
        args["cur"] = code
        out[code] = request.path + "?" + urlencode(args)
    return out


def read_blend():
    #FIXED AT THE MIDDLE, 2026-07-22. the slider is gone from the page.
    #
    #it was the site's most misunderstood control: a friend's review read it as
    #an either/or and suggested replacing it with a radio, which would have
    #deleted the feature rather than explained it. the answer turned out to be
    #that the choice never needed making. an even blend of the two axes is
    #better than either end on its own, and better than any other detent, so
    #the honest move is to stop asking and just do it.
    #
    #the machinery underneath is deliberately left alone: BLEND_WEIGHTS,
    #tier_cut and the two-axis scoring all still work off this number, so
    #reviving the slider means putting the input back and restoring the four
    #lines below, not rebuilding the ranking. a stale blend= in an old link is
    #ignored rather than honoured, which is what makes every shared url agree
    #about what it shows
    return BLEND_DEFAULT


def read_picked():
    #the lines param holds indexes into the searched card's rules text, like
    #"0,2" for the first and third line, set by clicking lines on the page
    picked = set()
    for part in request.args.get("lines", "").split(","):
        if part.strip().isdigit():
            picked.add(int(part.strip()))
    return picked


def read_dropped():
    #the notags param holds tag slugs the user switched off on the page, like
    #"donate-token,modal". dropped rather than kept on purpose: the default
    #(the whole card) needs no param at all, shared urls stay short, and a
    #card that picks up a new community tag tomorrow gets it included instead
    #of silently excluded by yesterday's list
    dropped = set()
    for part in request.args.get("notags", "").split(","):
        part = part.strip()
        if part:
            dropped.add(part)
    return dropped


def read_forced():
    #the yestags param is the mirror of notags: tags the line picker set aside
    #that the user put back by hand. attribution is inference, so it will drop
    #a tag it shouldn't now and then, and without this the only way back is to
    #unpick the line and lose the whole narrowing
    forced = set()
    for part in request.args.get("yestags", "").split(","):
        part = part.strip()
        if part:
            forced.add(part)
    return forced


def build_lines(card, picked_idx):
    #the searched card's rules text as individual lines for the line picker.
    #searchable means the cleaned line is real text that lives in the lines
    #table (reminder-only lines clean down to nothing and cant be picked).
    #returns the display list and the cleaned texts of the picked lines
    shown = []
    picked = []
    for idx, raw in enumerate(card["oracle_text"].split("\n")):
        cleaned = clean_line(raw, card["name"])
        searchable = len(cleaned) >= 3
        selected = searchable and idx in picked_idx
        if selected:
            picked.append(cleaned)
        shown.append({"idx": idx, "text": raw, "searchable": searchable, "selected": selected})
    return shown, picked


def filter_sql(filters):
    #turns the filters into conditions on the cards table. returns a snippet
    #starting with AND so it glues straight onto the candidate query, plus
    #its parameters. filtering inside that query matters: the LIMIT applies
    #after the filter, so narrow searches dig deeper into the rankings
    #instead of cutting down an already cut off list
    where = ""
    params = []
    if filters["colors"]:
        #three readings of a color pick, the mode select decides. safe to
        #build into a regex/pattern because read_filters only lets WUBRG
        #through. "at most" is fits-within, like deckbuilding: every letter
        #of the card's identity must be one of the picked colors, and
        #colorless always fits. "including" wants every picked color
        #present, extras welcome. "exactly" is both at once, said as two
        #conditions so nothing rests on the stored letter order
        if filters["cmode"] in ("atmost", "exact"):
            where += " AND c.color_identity ~ %s"
            params.append("^[" + filters["colors"] + "]*$")
        if filters["cmode"] in ("include", "exact"):
            for letter in filters["colors"]:
                where += " AND c.color_identity LIKE %s"
                params.append("%" + letter + "%")
    #the bounds compare in whichever currency the toggle shows, so what you
    #filter on is always the number printed under the cards
    pcol = price_col(filters.get("cur", "usd"))
    if filters["pmin"] is not None:
        where += " AND " + pcol + " >= %s"
        params.append(filters["pmin"])
    if filters["pmax"] is not None:
        #cards with no known price fail both comparisons, so any price filter
        #quietly drops them, which is what a budget search wants
        where += " AND " + pcol + " <= %s"
        params.append(filters["pmax"])
    if filters["mvmin"] is not None:
        where += " AND c.cmc >= %s"
        params.append(filters["mvmin"])
    if filters["mvmax"] is not None:
        where += " AND c.cmc <= %s"
        params.append(filters["mvmax"])
    #salt behaves exactly like price: a card nobody voted on fails both
    #comparisons, so any salt bound quietly drops the ~250 cards with no
    #score. that is the right answer for a minimum ("show me salty cards")
    #and a defensible one for a maximum, since an unvoted card is unproven
    #rather than known-mild. the widget's tooltip says so
    if filters["smin"] is not None:
        where += " AND c.salt >= %s"
        params.append(filters["smin"])
    if filters["smax"] is not None:
        where += " AND c.salt <= %s"
        params.append(filters["smax"])
    if filters["types"]:
        #any picked type matches, so an Artifact Creature shows up whether
        #Artifact, Creature or both are ticked
        where += " AND c.type_line ILIKE ANY(%s)"
        params.append(["%" + t + "%" for t in filters["types"]])
    if filters["cmdr"]:
        #commander targets. both words have to be in the FRONT face's type
        #line ("Legendary Creature - Elf Warrior"), matching them separately
        #also catches things like "Legendary Enchantment Creature". front
        #face only: a double-faced type line carries both faces joined by //
        #and only the front decides who can lead a deck (Invasion of Theros
        #is a Battle whose back face is a Legendary Enchantment Creature)
        where += " AND split_part(c.type_line, '//', 1) ILIKE %s AND split_part(c.type_line, '//', 1) ILIKE %s"
        params.append("%Legendary%")
        params.append("%Creature%")
    if filters["gc"]:
        where += " AND NOT c.game_changer"
    if not filters["illegal"]:
        where += " AND c.legal_commander"
    if filters.get("fq_sql"):
        #the compiled filter box, one boolean expression over the cards row
        where += " AND (" + filters["fq_sql"] + ")"
        params.extend(filters["fq_params"])
    return where, params


#a result's price against the searched card's. the arrow is the message and
#the colour is how big the move is: a "much" verdict needs BOTH a doubling
#(or halving) and a real gap in money, because 25p against 10p is 2.5x and
#nobody would call it much more expensive
PRICE_MUCH_RATIO = 2.0
PRICE_MUCH_GAP = 1.0

#edhrec ranks are ordinal over the whole format, so two cards 40 places apart
#are equally played in any sense that matters. only a fifth of a rank apart
#either way earns an arrow
RANK_BAND = 0.2


def price_verdict(price, anchor):
    if anchor is None or price is None or anchor <= 0:
        return ""
    if price == anchor:
        return ""
    much = abs(price - anchor) >= PRICE_MUCH_GAP and (
        price >= anchor * PRICE_MUCH_RATIO or price <= anchor / PRICE_MUCH_RATIO)
    if price < anchor:
        return "much-cheaper" if much else "cheaper"
    return "much-pricier" if much else "pricier"


def rank_verdict(rank, anchor):
    #rank 1 is the most played card in the format, so a SMALLER number means
    #more played and the arrow points up for it
    if anchor is None or rank is None:
        return ""
    if abs(rank - anchor) < anchor * RANK_BAND:
        return ""
    return "more-played" if rank < anchor else "less-played"


#salt is judged on the GAP alone, no ratio test. price needs one because 25p
#against 10p is 2.5x and nobody would call it much more expensive, but salt is
#an average of votes rather than an amount of something: 0.1 against 0.2 is
#double and means nothing, while half a point is half a point wherever it
#lands. the pool's whole interquartile range is 0.31, so 0.4 is a gap wider
#than the middle half of every card in the game, and 0.1 is the point below
#which two cards are just the same card
SALT_BAND = 0.1
SALT_MUCH_GAP = 0.4

#a year, because a year is the unit two cards are contemporary in: four sets a
#year means a six month gap says nothing about whether a card is from the same
#era as the one you searched. no MUCH gap to go with it, since there is no
#colour on this one to earn (see below)
AGE_BAND_DAYS = 365.25


def salt_verdict(salt, anchor):
    #which side of the searched card this one sits on for annoyance, in the
    #same four states the price verdict uses: a small move gets the arrow
    #alone, a big one earns colour. green for less salt and red for more,
    #matching money, because a colour that means "worse" in one row and
    #nothing in the next is a colour nobody learns to read.
    #
    #the play-rate arrow stays colourless and that is not an inconsistency:
    #more played is not better or worse, where more annoying is
    if anchor is None or salt is None:
        return ""
    diff = salt - anchor
    if abs(diff) < SALT_BAND:
        return ""
    much = abs(diff) >= SALT_MUCH_GAP
    if diff < 0:
        return "much-milder" if much else "milder"
    return "much-saltier" if much else "saltier"


def age_verdict(released, anchor):
    #which side of the searched card this one was printed. it is the fourth
    #arrow and it took the longest to arrive, because the row had no age figure
    #for an arrow to sit on until one was added.
    #
    #TWO states where the other three have four. price and salt each have a
    #better end, so a big move there earns colour; older is not better than
    #newer any more than more-played is better than less, so this returns a
    #direction and nothing else. same call the play rate arrow already makes,
    #and the rule the guide now states: colour means one end is better
    if anchor is None or released is None:
        return ""
    diff = (anchor - released).days
    if abs(diff) < AGE_BAND_DAYS:
        return ""
    #the anchor is the LATER date, so this card was printed first
    return "older" if diff > 0 else "newer"


#everything under the cut used to be one undivided pile that the sorts ran
#over whole, which made "cheapest first" useless the moment you opened it: the
#cheapest card in a pile that reaches down to 0% is a 0% card, so the sort
#answered a question nobody asked. the pile is now cut into 10 point bands and
#only one is ever on the page at a time, so a sort inside it is a sort among
#cards that match about as well as each other
WEAK_BAND = 10


def band_of(score):
    return int(score // WEAK_BAND) * WEAK_BAND


#how each step down gets described. plain english rather than a percent range
#because the range means different things at different slider positions, and
#nobody reading "60 to 69%" knows whether that is nearly good or hopeless.
#past the ladder every further step is "weaker again", which is honest: by
#then the only thing worth saying is that it keeps going down
BAND_WORDS = ("weaker matches", "weaker still", "weaker again")


def band_words(step):
    return BAND_WORDS[min(step, len(BAND_WORDS)) - 1]


def find_similar(oracle_id, picked, filters, min_pct, sort, offset=0, how_many=20, band=None, blend=0.0,
                 currency="usd", dropped=(), forced=(), anchor_price=None, anchor_rank=None,
                 anchor_salt=None, anchor_released=None):
    #every candidate card keeps all its matching line pairs now instead of
    #just the best one, so results can show "+2 more matching lines".
    #
    #cards split around min_pct: the strong ones are the real results, and
    #everything under the line waits in 10 point bands behind a button that
    #names the band it is about to show. band=None is the strong tier, an
    #int is that band's lower edge
    pairs_by_card = {}  #other card's oracle_id -> list of (weighted score, real similarity, our line, their line)
    prices = {}         #other card's oracle_id -> price in the chosen currency, for the price sorts
    ranks = {}          #other card's oracle_id -> edhrec rank, for the played sorts
    dates = {}          #other card's oracle_id -> first printing's date, for the newest sort
    salts = {}          #other card's oracle_id -> edhrec salt score, for the salt sorts
    where, fparams = filter_sql(filters)
    #the column the price sorts read, matching the currency the page prints
    pcol = price_col(currency)
    #the query card's lines are already embedded in the database, so the
    #model never runs at search time. grab them with their idf counts in one
    #go, on a briefly borrowed connection
    with pool.connection() as conn:
        #the IS NOT NULL matters only during a column trial: cards ingested
        #after the backfill have no v2 vector yet, and a NULL anchor would ride
        #into the scan below and NULL every similarity. on the live column the
        #NOT NULL constraint makes it free. a card whose lines are all
        #unfilled degrades to the no-searchable-lines path, same as vanilla
        qlines = conn.execute("""
            SELECT l.line_text, l.""" + EMBED_COL + """ AS embedding, coalesce(s.count, 1) AS count
            FROM lines l LEFT JOIN line_stats s ON s.line_text = l.line_text
            WHERE l.oracle_id = %s AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL
        """, (oracle_id,)).fetchall()

    #if the user picked lines on the page, only search with those
    if picked:
        chosen = []
        for ql in qlines:
            if ql["line_text"] in picked:
                chosen.append(ql)
        if chosen:
            qlines = chosen

    def hunt(ql):
        #one line's nearest neighbor walk through the hnsw index, ~10-20ms
        #where the exact scan it replaced measured 200-250ms. <=> is cosine
        #distance, so similarity is 1 minus it. grab way more than we need
        #since a bunch will get merged per card.
        #
        #one query per line on purpose. the obvious "one big query" (the
        #anchor's lines CROSS JOIN LATERAL the scan) was built and measured
        #at 2.3x SLOWER: with the anchor embedding as a lateral outer column
        #postgres detoasts the ~3kb vector again for every one of the 61k
        #distance evaluations, while a bound parameter gets detoasted once.
        #
        #no l.id tiebreak on the ORDER BY: a second sort key pushes the
        #planner off the index and back onto the full scan. the 400 cut
        #stays deterministic anyway, walking an unchanged graph returns the
        #same rows in the same order, and only the ingest changes the graph
        with pool.connection() as c:
            return c.execute("""
                SELECT l.oracle_id, l.line_text, l.face, 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim, """ + pcol + """ AS price, c.edhrec_rank, c.released_at, c.salt
                FROM lines l JOIN cards c ON c.oracle_id = l.oracle_id
                WHERE l.oracle_id <> %s AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL""" + where + """
                ORDER BY l.""" + EMBED_COL + """ <=> %s
                LIMIT 400
            """, [ql["embedding"], oracle_id] + fparams + [ql["embedding"]]).fetchall()

    #multi-line cards pay for their scans side by side instead of one after
    #the other, each hunt on its own pooled connection. the main thread
    #holds NO connection while they run (holding one while workers wait on
    #the pool is how a pool deadlocks), and 3 workers keeps a connection
    #free for /suggest even when two searches land at once. map preserves
    #line order, so results merge exactly as the sequential loop did
    if len(qlines) > 1:
        with ThreadPoolExecutor(max_workers=min(3, len(qlines))) as ex:
            per_line = list(ex.map(hunt, qlines))
    else:
        per_line = [hunt(ql) for ql in qlines]

    for ql, matches in zip(qlines, per_line):
        w = line_weight(ql["count"])
        for m in matches:
            if m["oracle_id"] not in pairs_by_card:
                pairs_by_card[m["oracle_id"]] = []
            pairs_by_card[m["oracle_id"]].append((m["sim"] * w, m["sim"], ql["line_text"], m["line_text"], m["face"]))
            prices[m["oracle_id"]] = m["price"]
            ranks[m["oracle_id"]] = m["edhrec_rank"]
            dates[m["oracle_id"]] = m["released_at"]
            salts[m["oracle_id"]] = m["salt"]

    with pool.connection() as conn:
        #sort each card's pairs so pairs[0] is its best one, then rank the
        #cards by that best pair
        ranked = []
        for oid, pairs in pairs_by_card.items():
            pairs.sort(reverse=True)
            ranked.append((oid, pairs))
        ranked.sort(key=lambda x: x[1][0][0], reverse=True)

        #the concepts side of the slider. one promise keeps it honest: the
        #badge is (1-w) * mech + w * concept, and the min-match line cuts on
        #that SAME number, so nothing under the cutoff ever shows above the
        #fold no matter which axis it leaned on
        concept_raw = {}
        #the anchor's vector arrives as two arrays instead of a subquery over
        #card_tags, because the user can now switch tags off: the kept set and
        #its norm are decided in anchor_vector and both queries just read them.
        #an empty vector (every tag dropped, or an untagged card) means the
        #concept side has nothing to say, so it sits the round out rather than
        #dividing by a zero norm
        atags, aweights, anorm = anchor_vector(conn, oracle_id, dropped, picked, forced) if blend > 0 else ([], [], 0.0)
        #NO ANCHOR VECTOR MEANS THE CONCEPT AXIS SITS OUT ENTIRELY, rather than
        #scoring every candidate at zero and dragging the blend down with it.
        #that used to be unreachable, since an anchor with no tags has no
        #concept side to speak of anyway. picking a keyword line reaches it: the
        #line owns no tags, so there is no vector, and the old behaviour halved
        #every card's score and returned nothing at all above the cutoff.
        #ranking on rules text alone is both what survives and what the person
        #who clicked "Vigilance, trample, haste" was asking for
        if blend > 0 and atags:
            have = {oid for oid, pairs in ranked}
            if atags:
                #cards the lines never found, injected as candidates when their
                #concept score alone is worth considering at the current cutoff,
                #through the same filters as everything else
                rows = conn.execute("""
                    WITH anchor AS (
                        SELECT * FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
                    )
                    SELECT ct.oracle_id, """ + pcol + """ AS price, c.edhrec_rank, c.released_at,
                           sum(a.weight * ct.weight) / (%s * nc.norm) AS raw
                    FROM card_tags ct
                    JOIN anchor a ON a.tag = ct.tag
                    JOIN cards c ON c.oracle_id = ct.oracle_id
                    JOIN card_tag_norms nc ON nc.oracle_id = ct.oracle_id
                    WHERE ct.oracle_id <> %s""" + where + """
                    GROUP BY ct.oracle_id, """ + pcol + """, c.edhrec_rank, c.released_at, nc.norm
                    HAVING sum(a.weight * ct.weight) / (%s * nc.norm) >= %s
                    ORDER BY raw DESC
                    LIMIT 300
                """, [atags, aweights, anorm, oracle_id] + fparams + [anorm, concept_raw_gate(min_pct)]).fetchall()
                for r in rows:
                    concept_raw[r["oracle_id"]] = r["raw"]
                    prices.setdefault(r["oracle_id"], r["price"])
                    ranks.setdefault(r["oracle_id"], r["edhrec_rank"])
                    dates.setdefault(r["oracle_id"], r["released_at"])

                #every mechanical candidate needs its concept score too, the
                #blend weighs both axes for everyone
                ids = [oid for oid in have if oid not in concept_raw]
                if ids:
                    for r in conn.execute("""
                        WITH anchor AS (
                            SELECT * FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
                        )
                        SELECT ct.oracle_id,
                               sum(a.weight * ct.weight) / (%s * nc.norm) AS raw
                        FROM card_tags ct
                        JOIN anchor a ON a.tag = ct.tag
                        JOIN card_tag_norms nc ON nc.oracle_id = ct.oracle_id
                        WHERE ct.oracle_id = ANY(%s)
                        GROUP BY ct.oracle_id, nc.norm
                    """, (atags, aweights, anorm, ids)).fetchall():
                        concept_raw[r["oracle_id"]] = r["raw"]

            #pure concept finds carry no line pairs, their badge is w * concept
            for oid in concept_raw:
                if oid not in have:
                    ranked.append((oid, []))

            def blended(entry):
                oid, pairs = entry
                mech = mech_display(pairs[0][1]) if pairs else 0
                return (1 - blend) * mech + blend * concept_display(concept_raw.get(oid, 0.0))
            ranked.sort(key=blended, reverse=True)
            gate_score = blended
        else:
            def gate_score(entry):
                return mech_display(entry[1][0][1])

        #split at the minimum match line. the number that decides which side
        #a card lands on is exactly the number its badge will show (rounded
        #the same way, so a 79.6 that badges as 80 passes). everything under
        #the line is filed into its 10 point band rather than one pile
        strong = []
        bands = {}
        for entry in ranked:
            score = round(gate_score(entry))
            if score >= min_pct:
                strong.append(entry)
            else:
                bands.setdefault(band_of(score), []).append(entry)
        wanted = strong if band is None else bands.get(band, [])

        #the alternate sorts happen after the filters, the ranking and the
        #tier split, so the percent keeps meaning what it always meant and
        #weak cards can never leapfrog strong ones. cards with no price sink
        #to the bottom of the price sorts (same for no date on the newest
        #sort), and ties fall back to the badge score, which also covers
        #concept-found cards with no line pairs
        if sort in ("cheap", "pricey"):
            priced = []
            unpriced = []
            for entry in wanted:
                if prices[entry[0]] is None:
                    unpriced.append(entry)
                else:
                    priced.append(entry)
            if sort == "cheap":
                priced.sort(key=lambda x: (float(prices[x[0]]), -gate_score(x)))
            else:
                priced.sort(key=lambda x: (-float(prices[x[0]]), -gate_score(x)))
            wanted = priced + unpriced
        elif sort in ("played", "obscure"):
            #edhrec rank, 1 = the format's most played card. no rank reads
            #as nobody plays it, so unranked cards sink on the played sort
            #and float on the obscure one
            worst = 10 ** 9
            flip = 1 if sort == "played" else -1
            wanted = sorted(wanted, key=lambda x: (flip * (ranks.get(x[0]) or worst), -gate_score(x)))
        elif sort in ("new", "old"):
            #first printing's release date, as an ordinal so one flip serves
            #both directions. dateless cards sink either way, and date ties
            #land best badge first
            dated = []
            undated = []
            for entry in wanted:
                if dates[entry[0]] is None:
                    undated.append(entry)
                else:
                    dated.append(entry)
            flip = -1 if sort == "new" else 1
            dated.sort(key=lambda x: (flip * dates[x[0]].toordinal(), -gate_score(x)))
            wanted = dated + undated
        elif sort in ("salty", "mild"):
            #a card nobody voted on has no salt, which is not the same as
            #being mild, so it sinks on BOTH directions rather than being
            #claimed as the least annoying card in the results. same call the
            #price and date sorts make about their own missing values.
            #.get because concept-found cards never went through the line
            #scan that fills these maps
            salted = []
            unsalted = []
            for entry in wanted:
                if salts.get(entry[0]) is None:
                    unsalted.append(entry)
                else:
                    salted.append(entry)
            flip = -1 if sort == "salty" else 1
            salted.sort(key=lambda x: (flip * float(salts[x[0]]), -gate_score(x)))
            wanted = salted + unsalted

        has_more = len(wanted) > offset + how_many
        page = wanted[offset:offset + how_many]

        #what to offer once this tier runs out: the next band down that
        #actually holds cards. empty bands are skipped rather than offered
        #and then found empty, so the button never lies about what is left.
        #
        #the band's percent range is deliberately NOT sent. the cutoff moves
        #with the slider (80 at the ends, 70 in the middle), so "from 70 to
        #79%" means a different thing depending on where the slider sits, and
        #a skipped empty band makes the numbers jump about on top of that.
        #step is what the caller words: 1 is the first drop below the line,
        #2 the one after, and the wording ladder lives in the page
        next_band = None
        if not has_more:
            edge = min_pct if band is None else band
            ladder = sorted(bands, reverse=True)
            below = [lo for lo in ladder if lo < edge]
            if below:
                lo = below[0]
                next_band = {"lo": lo, "count": len(bands[lo]),
                             "words": band_words(ladder.index(lo) + 1)}

        #one query for the display info of just the cards on this page
        info = {}
        ids = [oid for oid, pairs in page]
        if ids:
            for row in conn.execute("SELECT " + CARD_FIELDS + " FROM cards WHERE oracle_id = ANY(%s)", (ids,)):
                info[row["oracle_id"]] = row

        #the tags each page card shares with the anchor, rarest first - the
        #chips that explain why the concepts side ranked a card where it did.
        #they read off the same kept vector the scoring used, so a tag the
        #user switched off never turns up as the reason for a match
        chips = {}
        if blend > 0 and atags and ids:
            for r in conn.execute("""
                SELECT ct.oracle_id, ct.tag FROM card_tags ct
                JOIN unnest(%s::text[], %s::real[]) AS a(tag, weight) ON a.tag = ct.tag
                WHERE ct.oracle_id = ANY(%s)
                ORDER BY a.weight * ct.weight DESC
            """, (atags, aweights, ids)).fetchall():
                chips.setdefault(r["oracle_id"], []).append(r["tag"])

    results = []
    for oid, pairs in page:
        c = info[oid]
        concept_pct = concept_display(concept_raw[oid]) if oid in concept_raw else 0
        more = []
        if pairs:
            score, sim, our_line, their_line, their_face = pairs[0]
            mech_pct = mech_display(sim)
            concept_only = False
            #the extra pairs behind the "+n more matching lines" hint. pairs that
            #reuse a line already shown get skipped, so the count means genuinely
            #different abilities matched, not the same ability matching twice
            used_ours = [our_line]
            used_theirs = [their_line]
            for p in pairs[1:]:
                if p[2] in used_ours or p[3] in used_theirs:
                    continue
                used_ours.append(p[2])
                used_theirs.append(p[3])
                more.append('"' + p[3] + '" (' + str(mech_display(p[1])) + '%) matches your "' + p[2] + '"')
        else:
            #a pure concept match: no line of rules text got it here
            our_line = ""
            their_line = ""
            their_face = 0
            mech_pct = 0
            concept_only = True
        #the badge is the SAME number the ordering and the cutoff use, which is
        #the promise that makes the list read in descending order and nothing
        #under the gate appear above the fold. the two ingredients ride in the
        #tooltip.
        #
        #the atags check is what keeps that promise when a keyword line is
        #picked: there is no anchor vector, so the ranking dropped to rules text
        #alone above, and blending a zero concept score in here would badge a
        #perfect textual match as 50% while the gate let it through on 100.
        #the condition has to match the one guarding the ranking exactly
        if blend > 0 and atags:
            percent = int(round((1 - blend) * mech_pct + blend * concept_pct))
        else:
            percent = mech_pct
        price = price_label(c, currency)
        #the four little arrows: which side of the searched card this result
        #sits on for money, for how much the format plays it, for annoyance and
        #for when it was printed. a comparison is the one thing these numbers
        #honestly support on their own, and every tooltip names the card being
        #compared against
        price_vs = price_verdict(price_in(c, currency), anchor_price)
        rank_vs = rank_verdict(c["edhrec_rank"], anchor_rank)
        salt_vs = salt_verdict(c["salt"], anchor_salt)
        age_vs = age_verdict(c["released_at"], anchor_released)
        #a match that lives on the back face shows that side first, so the
        #line printed under the card is on the picture the user is looking
        #at (the ulvenwald lesson). the front face keeps the flip button
        image = c["image"]
        image_back = c["image_back"] or ""
        matched_back = their_face == 1 and bool(image_back)
        if matched_back:
            image, image_back = image_back, image
        results.append({
            "oracle_id": str(oid),  #the report flag needs to say which card it's flagging
            "name": c["name"],
            "mana_cost": c["mana_cost"],
            "type_line": c["type_line"],
            "image": image,
            "image_back": image_back,
            "matched_back": matched_back,
            "sideways": sideways(c["layout"], c["type_line"]),
            "flip": c["layout"] == "flip",
            "scryfall_uri": c["scryfall_uri"],
            "percent": percent,
            #the tooltip only claims to break a blend apart when there was one
            "blended": blend > 0 and bool(atags),
            "mech_pct": mech_pct,
            "concept_only": concept_only,
            "concept_pct": concept_pct,
            "concept_tags": ", ".join(chips.get(oid, [])[:3]),
            "our_line": our_line,
            "their_line": their_line,
            "price": price,
            "price_vs": price_vs,
            "rank": rank_label(c["edhrec_rank"]),
            "rank_vs": rank_vs,
            "salt": salt_label(c["salt"]),
            "salt_vs": salt_vs,
            #an arrow like the three above it, but never a colour: older and
            #newer are not better and worse, so there is a direction to point
            #and no verdict to spend green or red on
            "age": age_label(c["released_at"]),
            "age_vs": age_vs,
            "more_count": len(more),
            "more_text": "\n".join(more),
        })
    return results, has_more, next_band


#the pool of much-played cards the home page scatters as ghost chips when
#the visitor has no search history yet. lands sit out (searching one is a
#dull first impression), one query an hour, and a database hiccup just
#means an empty pool, the landing page never 500s over garnish
_seed_cache = {"at": 0.0, "names": []}


def chip_seeds():
    if time.time() - _seed_cache["at"] > 3600:
        try:
            with pool.connection() as conn:
                rows = conn.execute("""
                    SELECT name FROM cards
                    WHERE edhrec_rank IS NOT NULL AND type_line NOT LIKE '%%Land%%'
                    ORDER BY edhrec_rank LIMIT 40
                """).fetchall()
            _seed_cache["names"] = [r["name"] for r in rows]
        except Exception:
            pass
        _seed_cache["at"] = time.time()
    return _seed_cache["names"]


@app.route("/")
def home():
    #the landing page. search moved to /search when this page arrived, but
    #the launch thread links look like /?q=..., so anything with a query
    #gets forwarded there with its whole query string intact
    if request.args.get("q"):
        return redirect("/search?" + request.query_string.decode(), code=301)
    return render_template("home.html", seeds=chip_seeds())


@app.route("/search")
def search():
    query = request.args.get("q", "")
    if not query:
        return redirect("/")

    card = find_card(query)
    if card is None:
        return render_template("search.html", query=query, not_found=True)

    #the searched card's picture gets the same rotate/flip/transform frame
    #as everything else, the template just needs the two flags
    card = dict(card)
    card["sideways"] = sideways(card["layout"], card["type_line"])
    card["flip"] = card["layout"] == "flip"

    filters = read_filters()
    #the anchor's own price and rank, printed under its type line: every
    #result's arrows are measured against these, so they have to be visible
    card["price"] = price_label(card, filters["cur"])
    card["rank"] = rank_label(card["edhrec_rank"])
    #under its own key, NOT over card["salt"]: the raw number is what every
    #result is compared against below, and price and rank each keep their
    #source column for the same reason. age is the same shape again, over
    #released_at, and it was the one figure the anchor did not print: every
    #result now carries an age arrow, so the thing being compared to has to
    #be on the page like the other three are
    card["salt_text"] = salt_label(card["salt"])
    card["age"] = age_label(card["released_at"])
    blend = read_blend()
    min_pct = tier_cut(blend)
    sort = read_sort()
    sort_field, sort_dir = read_sort_parts()
    card_lines, picked = build_lines(card, read_picked())
    dropped = read_dropped()
    forced = read_forced()

    #the tag chips only mean anything while the concepts side is switched on,
    #so at detent 0 (pure rules text) they stay off the page rather than
    #sitting there as a control that changes nothing
    with pool.connection() as conn:
        chips = anchor_chips(conn, card["oracle_id"], dropped, picked, forced) if blend > 0 and LINE_TAGS else []

    results, has_more, next_band = find_similar(card["oracle_id"], picked, filters, min_pct, sort,
                                                blend=BLEND_WEIGHTS[blend], currency=filters["cur"],
                                                dropped=dropped, forced=forced,
                                                anchor_price=price_in(card, filters["cur"]),
                                                anchor_rank=card["edhrec_rank"],
                                                anchor_salt=card["salt"],
                                                anchor_released=card["released_at"])
    resp = make_response(render_template("search.html", query=query, card=card, card_lines=card_lines,
                                         picked_count=len(picked), results=results, has_more=has_more,
                                         next_band=next_band, min_pct=min_pct, errors=filters["errors"],
                                         blend=blend, cur=filters["cur"], types=CARD_TYPES,
                                         tag_chips=chips, dropped_count=sum(1 for c in chips if c["state"] == "off"),
                                         aside_count=sum(1 for c in chips if c["state"] == "aside"),
                                         line_tags_on=LINE_TAGS,
                                         sort_fields=SORT_FIELDS, sort_field=sort_field,
                                         sort_dir=sort_dir,
                                         #off the RESOLVED field, so ?sort=salty
                                         #from an old bookmark and the control's
                                         #own ?sort=salt&dir=desc focus the same
                                         #figure
                                         focus=focus_class(sort_field)))
    #the blend cookie is gone with the slider. it is actively DELETED rather
    #than left alone, or anyone who moved the slider before today keeps a
    #stale preference in their browser forever, invisible and doing nothing
    if request.cookies.get("blend") is not None:
        resp.delete_cookie("blend", samesite="Lax")
    return resp


@app.route("/guide")
def guide():
    #the how-it-works page. the demo card is fetched live so its picture
    #stays current, and the page just skips the demo if it ever vanishes.
    #a transform card on purpose, so the legend can point at the transform
    #button the card-frame overlay puts on two-faced cards
    demo = find_card("Delver of Secrets")
    return render_template("guide.html", demo=demo)


#how many cards the standing list under the dealer names. the dealer is the
#page for a person and it is javascript, so a crawler reading /unique met a
#title, one paragraph and an empty div: 213 words and not a single card name,
#on the page whose entire subject is which cards are unique. /precons has been
#server rendered from the start for this exact reason and it is the page that
#ranks. a hundred is enough to be a real answer to the question and enough
#internal links to matter, without turning the page into a table nobody reads
UNIQUE_TOP = 100

_unique_top = {"at": 0.0, "rows": []}


def unique_top():
    #cached an hour like the precon board, and for the same reason: the scores
    #only move when the ingest reruns and the list is identical for everyone.
    #
    #pure rules-text uniqueness rather than the blend the dealer uses. the
    #blend is a slider the visitor moves, and a page google reads once needs
    #one fixed meaning. this is also the number the h1 makes a claim about
    if _unique_top["rows"] and time.time() - _unique_top["at"] < 3600:
        return _unique_top["rows"]
    try:
        with pool.connection() as conn:
            rows = [dict(r) for r in conn.execute("""
                SELECT name, uniqueness, unique_line
                FROM cards
                WHERE uniqueness IS NOT NULL AND coalesce(unique_line, '') <> ''
                ORDER BY uniqueness DESC, name
                LIMIT %s
            """, (UNIQUE_TOP,)).fetchall()]
    except Exception:
        #whatever was there last stays, and the clock is not touched, so the
        #next visitor tries again rather than being served an empty list for
        #an hour
        return _unique_top["rows"]
    _unique_top["at"] = time.time()
    _unique_top["rows"] = rows
    return rows


@app.route("/unique")
def unique():
    return render_template("unique.html", types=CARD_TYPES, blend=read_blend(), cur=read_currency(),
                           top=unique_top(), top_n=UNIQUE_TOP)


@app.route("/privacy")
def privacy():
    #plain-english, and short because there is genuinely little to say: the
    #site keeps almost nothing. linked from the footer
    return render_template("privacy.html")


@app.route("/support")
def support():
    #the tip jar, and deliberately a page rather than a widget. ko-fi ships a
    #floating button and an iframe panel, and both are the third party script
    #and the sticky bar this site decided against when it decided against ads,
    #so the only thing that crosses over is an href
    return render_template("support.html")


#a deck is original because of its WEIRDEST cards, not its average card. the
#mean over a whole list is dominated by the mana base and the removal suite
#that every deck shares, and it squashes the spread between first and last
#from 0.143 to 0.103.
#
#a FRACTION of each deck rather than a fixed count, because precons hold 53 to
#66 nonland cards and a fixed top 20 scored a small deck on 38% of itself
#against a big one's 30%. worse, the gap grew with the count: at top 50 a
#53 card deck had to include nearly all its weak tail while a 66 card deck
#dropped its worst 16, and bigger decks scored higher for it (r=+0.34 against
#deck size, against +0.26 at top 20). a fraction is size independent by
#construction and takes that to +0.19.
#
#HALF, and it is fixed. it was a third, adjustable between a third and the
#whole list from the url, and the control went because it was a control with
#one right answer, same as the blend slider and the similarity knob before it.
#
#half rather than a third because a third of a commander deck is about the
#lands: 100 cards is roughly 36 of them, so reading a third means reading
#almost nothing but the mana base's neighbours, and the handful above it are
#the staples every deck brings. half reaches past both and into the cards that
#actually tell one deck from another, which is the thing being measured.
#
#reading deeper does not make the number more ACCURATE, and that was measured:
#every step costs discrimination (spread 0.143 at a third, 0.103 using every
#card) because the cards being added are the ones every deck shares. the
#ranking itself barely moves either, the ends not at all. so the setting only
#ever decided the middle of the board, which is not a decision worth handing to
#a visitor, and half is the reading that holds
PRECON_TOP_FRAC = 0.5

#the eras the leaderboard can be cut down to. originality correlates with
#release year at r=+0.46, partly because design space genuinely fills up (an
#old card has had fifteen years of imitators, and imitated is the opposite of
#unique). the ranking still separates decks INSIDE one era, so rather than
#pretend the effect isn't there, the page says so and lets you rank like
#against like. bounds are inclusive
PRECON_ERAS = [
    ("all", "All precons", None, None),
    ("early", "2011-2019", 2011, 2019),
    ("mid", "2020-2022", 2020, 2022),
    ("recent", "2023 on", 2023, 9999),
]

#BASIC lands are left out of the salt tally, and nothing else is. this is not
#a judgement about the votes: the salt on Island is real data about how
#players feel about Island, and it stays untouched in the database. it is that
#a DECK-LEVEL SUM cannot use it fairly, because how many basics a deck holds
#is a fact about its mana base, not about how annoying it is to play against.
#
#measured over the 166 precons, and the giveaway is that the distortion runs
#in OPPOSITE DIRECTIONS depending on an arbitrary choice of arithmetic:
#
#  counting distinct cards  r = +0.29 against the number of basic land types
#  counting every copy      r = -0.15 against the same thing
#
#so a five colour deck was being charged salt for being five colours, and
#under the other rule a mono deck was charged for running thirty Islands.
#nothing about either is a property of the deck. basics were 11% of the
#average total distinct, 30% counting copies, all of it noise.
#
#BASIC only, never lands in general. The Tabernacle at Pendrell Vale (2.68),
#Gaea's Cradle (2.17), Glacial Chasm (1.99) and Strip Mine (1.48) are among
#the saltiest cards in the game and they stay counted.
SALT_SKIP_BASICS = True


def is_basic_land(type_line):
    #'Basic Land - Island' and 'Basic Snow Land - Forest', but NOT the one
    #'Basic Creature - Shapeshifter' in the card pool, which is why this asks
    #for both words rather than just the first
    t = type_line or ""
    return t.startswith("Basic") and "Land" in t


#the same rule as is_basic_land, for the queries that aggregate in postgres.
#it and the python one have to agree or a deck's tally would disagree with the
#board it is ranked against
SALT_BASIC_SQL = "(c.type_line LIKE 'Basic%%' AND c.type_line LIKE '%%Land%%')"

#one query, both numbers. originality is the mean of the top N nonland
#uniqueness scores; salt is the plain sum over everything the rule above
#leaves in. each carries its own top 3 cards, because whichever column the
#board is sorted by, the row should show what MADE that number
PRECON_SQL = """
WITH scored AS (
    SELECT dc.deck_slug, c.name, c.uniqueness,
           row_number() OVER (PARTITION BY dc.deck_slug ORDER BY c.uniqueness DESC) AS n,
           count(*) OVER (PARTITION BY dc.deck_slug) AS held
    FROM deck_cards dc
    JOIN cards c ON c.oracle_id = dc.oracle_id
    WHERE c.uniqueness IS NOT NULL
      AND c.type_line NOT LIKE '%%Land%%'
),
rolled AS (
    --the fraction becomes a per-deck count here, so every deck is scored on
    --the same share of itself. greatest(1, ...) so a deck of one card still
    --gets a score rather than dividing by nothing
    SELECT deck_slug, avg(uniqueness) AS originality
    FROM scored WHERE n <= greatest(1, round(held * %s)) GROUP BY deck_slug
),
salted AS (
    SELECT dc.deck_slug, c.name, c.salt,
           row_number() OVER (PARTITION BY dc.deck_slug ORDER BY c.salt DESC) AS sn
    FROM deck_cards dc
    JOIN cards c ON c.oracle_id = dc.oracle_id
    WHERE c.salt IS NOT NULL""" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else "") + """
),
salt_rolled AS (
    SELECT deck_slug, sum(salt) AS salt FROM salted GROUP BY deck_slug
),
--money counts EVERYTHING, basics included, unlike salt. the two are different
--kinds of number: salt is an opinion about a card and nine Islands are not
--nine times the annoyance, where price is an amount of money and a deck's
--cost genuinely includes the lands you have to own to play it
priced AS (
    SELECT dc.deck_slug, c.name, __PRICE__ AS price,
           row_number() OVER (PARTITION BY dc.deck_slug ORDER BY __PRICE__ DESC NULLS LAST) AS pn
    FROM deck_cards dc JOIN cards c ON c.oracle_id = dc.oracle_id
),
price_rolled AS (
    SELECT deck_slug, sum(price) AS price FROM priced GROUP BY deck_slug
),
--how staple-heavy a deck is. the MEDIAN rather than the mean, because
--edhrec_rank is ordinal over the whole format and one card at rank 31000
--drags a mean somewhere no card in the deck actually sits. nonland, matching
--the originality convention: every deck runs Command Tower and it says
--nothing about which deck this is
plays AS (
    SELECT dc.deck_slug, c.name, c.edhrec_rank,
           row_number() OVER (PARTITION BY dc.deck_slug ORDER BY c.edhrec_rank) AS rn
    FROM deck_cards dc JOIN cards c ON c.oracle_id = dc.oracle_id
    WHERE c.edhrec_rank IS NOT NULL AND c.type_line NOT LIKE '%%Land%%'
),
play_rolled AS (
    SELECT deck_slug, percentile_cont(0.5) WITHIN GROUP (ORDER BY edhrec_rank) AS play_median
    FROM plays GROUP BY deck_slug
),
--age off the FIRST printing date, so a reprint does not make an old card new.
--basics are out for the same reason they are out of the salt tally: thirty
--Islands at three decades each is ~900 years that say nothing about a deck
aged AS (
    SELECT dc.deck_slug, c.name, c.released_at,
           extract(epoch FROM (now() - c.released_at)) / 31557600.0 AS years,
           row_number() OVER (PARTITION BY dc.deck_slug ORDER BY c.released_at) AS an
    FROM deck_cards dc JOIN cards c ON c.oracle_id = dc.oracle_id
    WHERE c.released_at IS NOT NULL""" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else "") + """
),
age_rolled AS (
    SELECT deck_slug, sum(years) AS age_total, avg(years) AS age_mean, count(*) AS age_cards
    FROM aged GROUP BY deck_slug
)
SELECT d.slug, d.name, d.code, d.release_date, d.source, r.originality,
       sr.salt, pr.price, plr.play_median,
       ar.age_total, ar.age_mean, ar.age_cards,
       (SELECT array_agg(s.name ORDER BY s.n) FROM scored s
         WHERE s.deck_slug = d.slug AND s.n <= 3) AS drivers,
       (SELECT array_agg(s2.name ORDER BY s2.sn) FROM salted s2
         WHERE s2.deck_slug = d.slug AND s2.sn <= 3) AS salt_drivers,
       (SELECT array_agg(p.name ORDER BY p.pn) FROM priced p
         WHERE p.deck_slug = d.slug AND p.pn <= 3) AS price_drivers,
       (SELECT array_agg(pl.name ORDER BY pl.rn) FROM plays pl
         WHERE pl.deck_slug = d.slug AND pl.rn <= 3) AS play_drivers,
       (SELECT array_agg(a.name ORDER BY a.an) FROM aged a
         WHERE a.deck_slug = d.slug AND a.an <= 3) AS age_drivers,
       (SELECT array_agg(c2.name ORDER BY c2.name) FROM deck_cards dc2
          JOIN cards c2 ON c2.oracle_id = dc2.oracle_id
         WHERE dc2.deck_slug = d.slug AND dc2.is_commander) AS leaders
FROM decks d
JOIN rolled r ON r.deck_slug = d.slug
LEFT JOIN salt_rolled sr ON sr.deck_slug = d.slug
LEFT JOIN price_rolled pr ON pr.deck_slug = d.slug
LEFT JOIN play_rolled plr ON plr.deck_slug = d.slug
LEFT JOIN age_rolled ar ON ar.deck_slug = d.slug
ORDER BY r.originality DESC, d.name
"""

#what the board can be ranked by. FIVE numbers, TEN readings, because every one
#of them is a number with a direction rather than two different numbers:
#cheapest and priciest are one sum read from either end. the card search splits
#its sorts the same way and for the same reason, so this is the control the
#audience already has.
#
#"best" is which way the COLUMN runs to put the flattering reading first, and
#it is not decoration: most played is the LOWEST median rank, because rank 1 is
#the most played card in the format. everything else is better when bigger.
#
#"means" is the sentence the page prints when it is showing this number, and it
#has to say what the FIGURE means, not what the idea means. a reader who meets
#"19.4 years" or "#1204" with no scale cannot tell a high score from a low one,
#and a leaderboard nobody can read is a leaderboard nobody believes.
#
#the SCALE that goes with it is deliberately not written down here. it was, for
#an afternoon, and every one of the five numbers was already drifting: age is
#now() minus a printing date so it grows daily, prices move daily, and the ends
#of the board move whenever mtgjson publishes a precon the daily ingest then
#picks up. a range typed into a constant is a claim with an expiry date on it,
#so the page reads its own top and bottom row instead. that also makes it true
#of the ERA cut on screen rather than of the whole board
#how long a precon counts as new, and it is not a guess: EDHREC's salt survey
#runs ONCE A YEAR, so a card printed since the last one has had no chance to be
#voted on. that is the longest of the settling windows the numbers here depend
#on, so it sets the mark for all of them.
#
#measured 2026-07-26 over the 166 precons, and this is a real effect rather
#than a disclaimer for its own sake:
#
#  cards first printed inside a year   mean salt 0.059   (n=2568)
#  cards older than that               mean salt 0.291   (n=28906)
#
#a FIFTH of the salt, on 98.5% coverage, so the votes are not missing, they
#have not been cast. at deck level that is 18.7 salt against 23.4, and the
#newest four precons run 11.0 to 15.4 against a board average of 23.4. play
#rate does the same thing more gently (a median of #5216 against #4188) because
#edhrec's rank counts decks built and that accumulates.
#
#prices move too, but NOT reliably in one direction: new precons average $76
#against $88, so release hype and reprint gluts pull opposite ways and the
#honest thing to say is that the figure is today's, not that it is high
PRECON_NEW_DAYS = 365

PRECON_METRICS = [
    {
        "key": "original", "figure": "originality", "drivers": "drivers",
        "label": "Originality",
        #NO swap axis on EITHER reading, deliberately, and this is the second
        #time that call has
        #been made. uniqueness is a contradiction as a sort (see the note in
        #TODO) so there is nothing here to move a deck along, and the nearest
        #honest thing, "cards fewer people play", was offered for about an hour
        #and read as a non sequitur: a button saying "make this deck less
        #played" under a panel about originality looks like the wrong button on
        #the wrong panel, because it is. so the offer is absent here rather than
        #approximated, same as everywhere else on this site where the honest
        #answer to "can you do X" turned out to be no
        "decimals": 3, "best": "desc", "cards": "Most original cards",
        "noun": "originality",
        "settling": "A new deck reads as more original than it will look in five years, and that is half real: design space fills up, so a card printed today has had nobody to copy it yet.",
        "means": "Every card scores 0 to 1: one minus how close its nearest match "
                 "anywhere in Magic gets, so 0.30 means something out there is 70% "
                 "like it. A deck's figure is the average across its most original "
                 "half of nonland cards, so it climbs by holding cards with less "
                 "competition, never by holding more cards.",
        "desc": {
            "key": "original", "label": "Most original", "first": "most original",
            "more": "more original", "swap": None,
            "cards": "Most original cards",
            "h1": "The most original Commander precons",
            "lede": "Every preconstructed Commander deck, ranked by how unusual its "
                    "cards are. Not how strong, not how expensive, and not how "
                    "popular: <strong>how little the rest of Magic looks like "
                    "it</strong>. A card scores high here when nothing else in the "
                    "game does what it does.",
            "meta": "Every preconstructed Commander deck ranked by how original its "
                    "cards are, measured against every Magic card ever printed. See "
                    "which precons play cards nothing else in the game resembles.",
        },
        "asc": {
            "key": "unoriginal", "label": "Least original", "first": "least original",
            "more": "less original", "swap": None,
            "cards": "Least original cards",
            "h1": "The least original Commander precons",
            "lede": "Every preconstructed Commander deck, ranked from the ones built "
                    "almost entirely out of <strong>cards the rest of the format "
                    "also plays</strong>. Familiar is not the same as bad: these are "
                    "the decks a new player will recognise most of.",
            "meta": "Every preconstructed Commander deck ranked from least original "
                    "first: the decks built out of the format's usual suspects, "
                    "measured against every Magic card ever printed.",
        },
    },
    {
        "key": "salt", "figure": "salt", "drivers": "salt_drivers",
        "label": "Salt",
        "decimals": 1, "best": "desc", "cards": "Saltiest cards",
        "noun": "salt",
        "settling": "A new deck reads milder than it is, and this is the biggest gap on the board. EDHREC's survey runs once a year, so cards printed since the last one have had no chance to be voted on: they average 0.06 salt against 0.29 for everything older. Read a new deck's salt as a floor.",
        "means": "EDHREC's annual survey asks players which cards they least enjoy "
                 "facing, scoring each 0 to about 3: Stasis is 3.06, Rhystic Study "
                 "2.73, Mind Stone a flat 0. A deck's figure is those scores added "
                 "up, so it gets there either through a few famous offenders or a "
                 "long tail of mildly irritating ones. The one number here that is "
                 "an opinion rather than a measurement.",
        "desc": {
            "key": "salt", "label": "Saltiest", "first": "saltiest",
            "more": "saltier", "swap": ("salt", "asc"),
            "cards": "Saltiest cards",
            "h1": "The saltiest Commander precons",
            "lede": "Every preconstructed Commander deck, ranked by how much its "
                    "cards annoy people. This is the one ranking here built on "
                    "<strong>opinion rather than measurement</strong>: it comes from "
                    "EDHREC's salt survey, where players vote on the cards they "
                    "least enjoy facing.",
            "meta": "Every preconstructed Commander deck ranked by how much its "
                    "cards annoy people, from EDHREC's salt survey. See which "
                    "precons are built on the cards players least enjoy facing.",
        },
        "asc": {
            "key": "mild", "label": "Mildest", "first": "mildest",
            "more": "milder", "swap": ("salt", "desc"),
            "cards": "Mildest cards",
            "h1": "The mildest Commander precons",
            "lede": "Every preconstructed Commander deck, ranked from the ones "
                    "<strong>nobody minds losing to</strong>. Low salt is the good "
                    "news if you are handing a deck to someone at a table that has "
                    "to keep liking each other afterwards.",
            "meta": "Every preconstructed Commander deck ranked from the least salty "
                    "first, using EDHREC's salt survey. The precons that annoy a "
                    "table least.",
        },
    },
    {
        "key": "price", "figure": "price", "drivers": "price_drivers",
        "label": "Price",
        "decimals": 2, "best": "desc", "cards": "Priciest cards",
        "noun": "of cards",
        "settling": "A new deck's price is the one still moving, and it does not run one way: release hype pushes up, the reprint glut of a freshly opened set pushes down. Today's figure is exactly that, today's.",
        "means": "The cheapest paper printing of every card, added together: what "
                 "the hundred cards cost to own as singles, not what the sealed box "
                 "sells for. That is why one reserved list card can put a deck above "
                 "four decks of staples. Basic lands count toward the total but are "
                 "left out of the card list below, since thirty Islands are not what "
                 "anyone means by a deck's cheapest cards.",
        "desc": {
            "key": "price", "label": "Most expensive", "first": "most expensive",
            "more": "worth more", "swap": ("price", "asc"),
            "cards": "Priciest cards",
            "h1": "The most expensive Commander precons",
            "lede": "Every preconstructed Commander deck, ranked by what its cards "
                    "are worth as singles. <strong>The cheapest paper printing of "
                    "each card, added up</strong>, refreshed from Scryfall daily.",
            "meta": "Every preconstructed Commander deck ranked by what its cards "
                    "cost as singles, using the cheapest paper printing of each and "
                    "prices refreshed from Scryfall daily.",
        },
        "asc": {
            "key": "cheap", "label": "Cheapest", "first": "cheapest",
            "more": "worth less", "swap": ("price", "desc"),
            "cards": "Cheapest cards",
            "h1": "The cheapest Commander precons",
            "lede": "Every preconstructed Commander deck, ranked from the ones whose "
                    "cards are <strong>worth the least as singles</strong>. Useful "
                    "backwards: a cheap list is a cheap deck to rebuild, and a "
                    "cheap deck to borrow ideas from.",
            "meta": "Every preconstructed Commander deck ranked from the cheapest "
                    "first, by what its cards cost as singles at the cheapest paper "
                    "printing of each.",
        },
    },
    {
        "key": "played", "figure": "play_median", "drivers": "play_drivers",
        #"Play rate", the name /search's sort already uses and the name every
        #tooltip on the site already says. it was "Played cards" here, which
        #was both a second name for one metric and nearly its own readings'
        #names ("most played cards", "least played cards") a word short
        "label": "Play rate",
        "decimals": 0, "best": "asc", "cards": "Most played cards",
        "noun": "median play rate",
        "settling": "A new deck reads as less played than it will be. EDHREC's rank counts how many decks run a card, and that accumulates: precons from the last year average a median of #5216 against #4188 for the rest, mostly the format not having got round to them.",
        "means": "EDHREC ranks every card by how many Commander decks run it, #1 "
                 "being the most played in the format. A deck's figure is the median "
                 "rank across its nonland cards, so #1200 means half this deck sits "
                 "inside the format's twelve hundred most played cards. A smaller "
                 "number is the deck built out of staples.",
        "desc": {
            "key": "played", "label": "Most played cards", "first": "most played cards",
            "more": "more played", "swap": ("played", "asc"),
            "cards": "Most played cards",
            "h1": "The Commander precons with the most played cards",
            "lede": "Every preconstructed Commander deck, ranked by how much of it "
                    "the format actually plays. <strong>The median EDHREC rank of "
                    "its nonland cards</strong>, so the decks at the top are the "
                    "ones built from cards everybody already runs.",
            "meta": "Every preconstructed Commander deck ranked by how played its "
                    "cards are, using the median EDHREC rank of its nonland cards. "
                    "The precons built out of format staples.",
        },
        "asc": {
            "key": "obscure", "label": "Least played cards", "first": "least played cards",
            "more": "less played", "swap": ("played", "desc"),
            "cards": "Least played cards",
            "h1": "The Commander precons with the least played cards",
            "lede": "Every preconstructed Commander deck, ranked from the ones whose "
                    "cards <strong>almost nobody else runs</strong>. The median "
                    "EDHREC rank of its nonland cards, read from the far end: these "
                    "decks are where the cards you have never seen live.",
            "meta": "Every preconstructed Commander deck ranked from least played "
                    "first, by the median EDHREC rank of its nonland cards. The "
                    "precons full of cards nobody else runs.",
        },
    },
    {
        "key": "age", "figure": "age_mean", "drivers": "age_drivers",
        "label": "Card age",
        "decimals": 1, "best": "desc", "cards": "Oldest cards",
        "noun": "a card on average",
        "settling": "This is the one number a new deck does not distort, because being new is the thing it measures. It still climbs on its own: every figure here is counted from today, so the whole board ages a year every year.",
        "means": "How long ago each card was first printed, averaged across the "
                 "deck. A reprint does not make an old card new, so a deck published "
                 "last year and stuffed with reprints still reads old. The total "
                 "underneath is every card's age added together; the ranking uses "
                 "the average, because a sum quietly rewards the bigger deck for "
                 "being bigger.",
        "desc": {
            "key": "age", "label": "Oldest cards", "first": "oldest",
            "more": "older", "swap": ("released", "desc"),
            "cards": "Oldest cards",
            "h1": "The Commander precons with the oldest cards",
            "lede": "Every preconstructed Commander deck, ranked by <strong>how far "
                    "back its cards were first printed</strong>. Not when the deck "
                    "came out: when the cards in it did, averaged across the list.",
            "meta": "Every preconstructed Commander deck ranked by how old its cards "
                    "are, measured from each card's first printing rather than from "
                    "the date the deck shipped.",
        },
        "asc": {
            "key": "new", "label": "Newest cards", "first": "newest",
            "more": "newer", "swap": ("released", "asc"),
            "cards": "Newest cards",
            "h1": "The Commander precons with the newest cards",
            "lede": "Every preconstructed Commander deck, ranked from the ones built "
                    "from <strong>cards the game printed most recently</strong>. "
                    "Measured from each card's first printing, so a pile of "
                    "reprints does not count as new.",
            "meta": "Every preconstructed Commander deck ranked from the newest "
                    "cards first, measured from each card's first printing rather "
                    "than the date the deck shipped.",
        },
    },
]

#the flat list the board's nav, its urls and the standings walk: one entry per
#metric per direction, ten in all. built rather than typed so a metric cannot
#gain a reading on one page and not the other, which is the drift the single
#PRECON_SORTS list was there to prevent in the first place
PRECON_SORTS = []
for _m in PRECON_METRICS:
    for _d in ("desc", "asc"):
        PRECON_SORTS.append(dict(_m[_d], dir=_d, metric=_m,
                                 figure=_m["figure"], drivers=_m["drivers"],
                                 decimals=_m["decimals"], cards=_m["cards"],
                                 means=_m["means"], settling=_m["settling"]))
PRECON_SORT_BY_KEY = {s["key"]: s for s in PRECON_SORTS}
#the default reading of each metric, which is what the detail pages open on and
#what an unqualified link means
PRECON_DEFAULT = PRECON_SORTS[0]


def sort_column_order(sort):
    #which way the COLUMN runs for this reading. the metric knows which
    #direction of its own number is the flattering one, and the reading either
    #wants that end or the other, so this is one xor rather than a table
    best = sort["metric"]["best"]
    return best if sort["dir"] == "desc" else ("asc" if best == "desc" else "desc")


def read_precon_sort():
    #an unknown sort falls back to originality rather than 404ing, same as
    #every other url reader here
    return PRECON_SORT_BY_KEY.get(request.args.get("sort", ""), PRECON_DEFAULT)


def figure_units(key, cur):
    #the figure's units. price needs the sign of whichever currency the toggle
    #is showing, age needs a word or "12.4" means nothing, play rate needs the
    #hash that says "rank" everywhere else on the site
    return ({"price": CURRENCY_SIGNS[cur], "played": "#"}.get(key, ""),
            " years" if key == "age" else "")

#same shape as the seed cache: the board is identical for everyone and only
#moves when the ingest reruns, so it is worth an hour of not asking.
#
#the query costs ~600ms against railway from home, measured 2026-07-26. it was
#~130ms when it computed two numbers, and five aggregates over deck_cards is what
#the other 470 bought. that is far too much to pay per visit and nothing to pay
#once an hour, which is the whole reason this cache exists, but it does mean a
#cold board is a visibly slow page rather than an imperceptibly slow one.
#
#keyed by currency, and only the three in CURRENCY_SIGNS can ever get in, so
#three entries is the ceiling and the url cannot grow this without bound. it
#used to be keyed by depth too, and dropping that control took the cache from
#twelve possible entries to three
_precon_cache = {}


def precon_board(currency="usd"):
    #keyed by currency because the price total is a real sum in ONE currency
    #rather than a number that can be converted afterwards: pounds are derived
    #per CARD from whichever of the two prices that card has, so a pound total
    #is not the dollar total times a rate
    hit = _precon_cache.get(currency)
    if hit and time.time() - hit["at"] < 3600:
        return hit["rows"]
    try:
        with pool.connection() as conn:
            #filled at query time, never baked into the constant: price_col
            #builds the pound expression out of the DAY'S rates, and a module
            #level string would freeze whatever they were at import
            sql = PRECON_SQL.replace("__PRICE__", price_col(currency))
            rows = [dict(r) for r in conn.execute(sql, (PRECON_TOP_FRAC,)).fetchall()]
    except Exception:
        return hit["rows"] if hit else []
    _precon_cache[currency] = {"at": time.time(), "rows": rows}
    return rows


@app.route("/deck")
def deck():
    #the lens's front door, and now the first thing the site is FOR rather
    #than a page you navigate to. one nav item, both inputs, and the precon
    #board reached from under them rather than sitting beside them
    return deck_hub()


@app.route("/precons")
def precons():
    #the leaderboard, and the reason the deck lens can say anything: a score
    #on its own is not a sentence, "more original than every precon but two"
    #is, and that needs a fair population to sit against. fully server
    #rendered, unlike the /unique dealer, so a crawler meets the actual decks
    want = request.args.get("era", "all")
    era = next((e for e in PRECON_ERAS if e[0] == want), PRECON_ERAS[0])
    _, _, lo, hi = era
    sort = read_precon_sort()
    skey = sort["figure"]
    order = sort_column_order(sort)

    cur = read_currency()
    #the settling window can be taken off the board entirely. it is a view
    #control like the era cut, not a different measurement: the decks are still
    #new and their numbers are still unsettled, this just stops them standing
    #between decks whose numbers have finished moving
    hide_new = request.args.get("new") == "hide"
    fresh = datetime.date.today() - datetime.timedelta(days=PRECON_NEW_DAYS)
    rows = []
    new_here = 0
    for r in precon_board(cur):
        year = r["release_date"].year if r["release_date"] else 0
        if lo is not None and not (lo <= year <= hi):
            continue
        #a deck with no salt at all cannot be placed on a salt board, and
        #sorting None against floats would raise rather than degrade
        if r.get(skey) is None:
            continue
        #new decks are marked, because three of the five numbers below are
        #still settling on them and a reader deserves to know which rows those
        #are before drawing a conclusion from where they landed
        is_new = bool(r["release_date"] and r["release_date"] > fresh)
        new_here += 1 if is_new else 0
        if is_new and hide_new:
            continue
        rows.append(dict(r, year=year, figure=float(r[skey]), new=is_new,
                         cards=r.get(sort["drivers"]) or []))
    #ascending when the reading wants the SMALLER number first, which is now
    #every metric read backwards plus "most played" read forwards: rank 1 is
    #the most played card in the format
    rows.sort(key=lambda r: (r["figure"] if order == "asc" else -r["figure"], r["name"]))

    #the bar under each score is relative to the cut on screen, not to the
    #whole board: inside one era the spread is narrower, and a bar that only
    #ever fills a third of the way says nothing about which deck is which
    if rows:
        top = max(r["figure"] for r in rows)
        floor = min(r["figure"] for r in rows)
        span = top - floor
        for i, r in enumerate(rows, 1):
            r["place"] = i
            #the bar tracks the RANKING, not the raw number, so on an
            #ascending board the fullest bar is still the deck at the top
            share = ((r["figure"] - floor) / span) if span else 1.0
            if order == "asc":
                share = 1.0 - share
            #every bar keeps a visible stub, or the last row reads as a
            #missing value rather than as the least original deck
            r["fill"] = 8 + 92 * share if span else 100
    prefix, suffix = figure_units(sort["metric"]["key"], cur)
    #the range this reading actually covers, read off the board rather than
    #remembered. it is the first and last row on screen, so it follows the era
    #cut and the currency toggle and it cannot go stale
    span = {"top": rows[0]["figure"], "bottom": rows[-1]["figure"]} if rows else None
    return render_template("precons/board.html", rows=rows, eras=PRECON_ERAS, era=era[0],
                           sorts=PRECON_SORTS, sort=sort, cur=cur, span=span,
                           metrics=PRECON_METRICS, hide_new=hide_new,
                           new_here=new_here, new_days=PRECON_NEW_DAYS,
                           cur_urls=currency_urls(), cur_labels=CURRENCY_LABELS,
                           prefix=prefix, suffix=suffix)


#how many cards a panel names as the evidence for its number. enough to read
#as evidence, short enough that nobody scrolls a 100 row table looking for the
#point.
#how many cards any list on this site reveals at a time. ONE number, because
#every list that does this should do it identically: the standing panels, the
#deck grid on /deck/view and on a precon page. a fix to one batching control is
#then a fix to all of them, and a reader who has learned what the button does
#in one place has learned it everywhere.
#
#16 rather than 12: four rows of four on the results grid's own column count
DECK_SECTION = 16

#and how far the pictures go when somebody opens them and keeps asking. the
#tool is working, so there is no reason to stop them at twelve: "load more"
#reveals another DECK_SECTION until this runs out.
#
#48 is about half a commander deck, which is where every one of these lists
#stops meaning anything anyway. originality only scores the top half, salt and
#age drop basic lands, play rate drops all lands, so by this depth the rows are
#the cards every deck shares. the whole batch is fetched with the page and
#revealed by the button rather than fetched on click: /deck/read is a POST
#result with no url to ask again at, and one query that returns 48 rows costs
#the same as one that returns 12
DECK_EVIDENCE_MAX = 48

#what "the cards that made this number" means, per metric, as sql. every
#predicate here is a TRANSCRIPTION of the matching CTE in PRECON_SQL and has to
#stay one: a card the ranking did not count must never turn up in the evidence
#for it, or the page is showing its working and the working is wrong.
#
#__PRICE__ is filled at query time from the day's rates, same as the board
DECK_EVIDENCE = {
    "original": {"where": "c.uniqueness IS NOT NULL AND c.type_line NOT LIKE '%%Land%%'",
                 "order": "c.uniqueness DESC", "value": "c.uniqueness", "decimals": 2},
    "salt": {"where": "c.salt IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
             "order": "c.salt DESC", "value": "c.salt", "decimals": 2},
    #the one place the evidence deliberately does NOT match the ranking, and it
    #is worth being explicit about. the price TOTAL counts basic lands, because
    #a deck's cost includes the lands you have to own. the price LIST does not,
    #because the list is read from both ends now and the cheap end of a
    #commander deck is thirty Islands: a column of basics is not what anybody
    #means by "the cheapest cards in this deck".
    #
    #an omission, never an addition. every card listed is one the total counted;
    #it is the reverse that stops being true, which is the safe direction to
    #break the rule in
    "price": {"where": "__PRICE__ IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
              "order": "__PRICE__ DESC", "value": "__PRICE__", "decimals": 2},
    "played": {"where": "c.edhrec_rank IS NOT NULL AND c.type_line NOT LIKE '%%Land%%'",
               "order": "c.edhrec_rank", "value": "c.edhrec_rank", "decimals": 0},
    "age": {"where": "c.released_at IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
            "order": "c.released_at", "value": "extract(epoch FROM (now() - c.released_at)) / 31557600.0",
            "decimals": 1},
}


def metric_cards(conn, oracle_ids, key, currency, limit=DECK_EVIDENCE_MAX):
    #the cards that made one of the five numbers, in the order that made it,
    #carrying everything a card frame needs. the list reads as names by default
    #and opens into pictures, so this asks for the pictures either way rather
    #than running a second query when someone expands it.
    #
    #BOTH ENDS come back in ONE list, ordered from the top. the panels flip
    #between "saltiest" and "mildest", and rendering a second list for the
    #other end doubled a page that was already 388kb of html: the flipped
    #reading is the same cards read backwards, so the page holds them once and
    #the browser reorders. that is also why the cap is applied per END rather
    #than to the query, and why a deck small enough for the two slices to
    #overlap simply keeps everything
    ev = DECK_EVIDENCE[key]
    price = price_col(currency)
    #uniqueness comes back for EVERY panel, not just the originality one. it is
    #the badge beside the card's name wherever a card is drawn on these pages,
    #the same slot the match percent fills on a search, and it holds still while
    #the panels change underneath it. the four numbers under the card are the
    #ones the world supplied; this is the one Delvefall worked out
    sql = """
        SELECT c.oracle_id, c.name, c.type_line, c.mana_cost, c.layout,
               c.image, c.image_back, c.scryfall_uri, c.edhrec_rank, c.salt,
               c.price_usd, c.price_eur, c.released_at, c.uniqueness,
               (""" + ev["value"].replace("__PRICE__", price) + """) AS value
        FROM cards c
        WHERE c.oracle_id = ANY(%s::uuid[]) AND (""" + ev["where"].replace("__PRICE__", price) + """)
        ORDER BY """ + ev["order"].replace("__PRICE__", price) + """, c.name
        LIMIT %s
    """
    try:
        #twice the cap, because both ends are wanted and the slice below takes
        #one from each. a deck shorter than that keeps every card it has
        rows = conn.execute(sql, ([str(o) for o in oracle_ids], limit * 2)).fetchall()
    except Exception:
        return []
    #the two ends, deduped by keeping the middle out. on a commander deck the
    #slices usually overlap and this is the whole list, which is the cheap case
    #and the useful one
    if len(rows) > limit * 2:
        rows = list(rows[:limit]) + list(rows[-limit:])
    prefix, suffix = figure_units(key, currency)
    out = []
    for r in rows:
        c = dict(r)
        c["sideways"] = sideways(c["layout"], c["type_line"])
        c["flip"] = c["layout"] == "flip"
        c["price_label"] = price_label(c, currency)
        c["rank_label"] = rank_label(c["edhrec_rank"])
        c["salt_label"] = "%.2f" % c["salt"] if c["salt"] is not None else ""
        c["age_label"] = age_label(c["released_at"])
        #two decimals, the same as the ordered list this grid sits under and the
        #same as the originality panel's own card figures. NOT the three the
        #deck's overall figure carries: that one is separating 166 precons from
        #each other, where a card is just saying roughly how unusual it is
        c["badge"] = ("%.2f" % c["uniqueness"]) if c["uniqueness"] is not None else ""
        value = float(c["value"]) if c["value"] is not None else 0.0
        #the card's own reading of the number the panel is about, printed the
        #same way the deck's figure above it is, so the two are obviously the
        #same measurement at two scales
        c["figure"] = prefix + ("%.*f" % (ev["decimals"], value)) + suffix
        out.append(c)
    return out


_deck_ids_cache = {}


def precon_ids(slug):
    #which cards a precon holds, cached for an hour like everything else about
    #the board: it only moves when the ingest reruns, and five metric queries
    #per page view should not each start by asking the same question
    hit = _deck_ids_cache.get(slug)
    if hit and time.time() - hit["at"] < 3600:
        return hit["ids"]
    try:
        with pool.connection() as conn:
            ids = [r["oracle_id"] for r in
                   conn.execute("SELECT oracle_id FROM deck_cards WHERE deck_slug = %s", (slug,)).fetchall()]
    except Exception:
        return hit["ids"] if hit else []
    _deck_ids_cache[slug] = {"at": time.time(), "ids": ids}
    return ids


def deck_uniqueness(oracle_ids):
    #every nonland card in the pile with its originality score, which is the
    #one figure the pasted path has to work out for itself: the other four come
    #back from deck_metrics as single numbers, and this one is an average over
    #a SLICE of the deck, so the slice has to be picked here.
    #
    #the predicate matches PRECON_SQL's scored CTE exactly. it used to come off
    #the all-pairs lens query, which additionally required a card to have rules
    #LINES; that made no difference (uniqueness is derived from lines, so a card
    #without any has none) but it did mean two different rules for one number
    if not oracle_ids:
        return []
    try:
        with pool.connection() as conn:
            return [dict(r) for r in conn.execute("""
                SELECT oracle_id, name, type_line, uniqueness AS global_u
                FROM cards
                WHERE oracle_id = ANY(%s::uuid[])
                  AND uniqueness IS NOT NULL AND type_line NOT LIKE '%%Land%%'
                ORDER BY uniqueness DESC
            """, ([str(o) for o in oracle_ids],)).fetchall()]
    except Exception:
        return []


def originality_of(cards, frac=PRECON_TOP_FRAC):
    #the same number the leaderboard ranks on, so a pasted list and a precon
    #are measured identically: the mean of the top FRACTION of nonland cards.
    #a fraction rather than a count matters more here than on the board,
    #because a pasted list can be any size at all
    #an unscored card is SKIPPED, not counted as a zero. the board's query
    #drops them the same way (uniqueness IS NOT NULL), and the two have to
    #agree or a pasted list gets ranked against a population measured by a
    #different rule. only a card the ingest has never scored lands here, which
    #is a narrow window, but it is the one card that would drag a whole deck
    #down for the crime of being new
    vals = sorted((c["global_u"] for c in cards if c["global_u"] is not None), reverse=True)
    if not vals:
        return 0.0
    keep = max(1, round(len(vals) * frac))
    vals = vals[:keep]
    return sum(vals) / len(vals)


def deck_salt(oracle_ids):
    #the salt tally: what this pile of cards is worth on edhrec's annoyance
    #poll. counted per DISTINCT card, not per copy. salt is how much a card
    #annoys the table and nine Islands are not nine times the annoyance of one,
    #and it is also the only way this can agree with the board, which counts a
    #precon the same way
    if not oracle_ids:
        return 0.0
    basic = (" AND NOT " + SALT_BASIC_SQL) if SALT_SKIP_BASICS else ""
    try:
        with pool.connection() as conn:
            row = conn.execute("""
                SELECT sum(c.salt) AS total FROM cards c
                WHERE c.oracle_id = ANY(%s::uuid[]) AND c.salt IS NOT NULL""" + basic,
                               ([str(o) for o in oracle_ids],)).fetchone()
    except Exception:
        return 0.0
    return float(row["total"]) if row and row["total"] is not None else 0.0


def deck_panels(conn, oracle_ids, figures, board, cur, slug=None):
    #one panel per metric, and the SAME five panels whether the deck came out
    #of the precon table or out of somebody's paste box. that is the entire
    #point of this being one function: /precons/<slug> and /deck/read are the
    #same page about different decks, and two builders would slowly turn them
    #into two different pages about the same thing.
    #
    #each panel carries BOTH readings of its number and shows one. they are the
    #same standing counted from opposite ends, so this is not two measurements,
    #it is one with a switch on it, which is the same shape the board's "from
    #the" control has and the same shape /search's sorts have.
    #
    #the CARDS are not duplicated for the second reading. they are the same
    #cards read backwards, the page already runs to 388kb of html, and a second
    #copy of five card lists is the version that stops loading on a phone. one
    #list goes out, ordered from the top, and the browser reverses it
    panels = []
    for m in PRECON_METRICS:
        figure = figures.get(m["key"])
        figure = None if figure is None else float(figure)
        readings = {}
        for d in ("desc", "asc"):
            #"better" is the COLUMN direction, so the flipped reading walks the
            #board the other way. it is the metric's own best for the top
            #reading and the opposite for the bottom one, which is the one xor
            #that keeps play rate from reading backwards
            best = m["best"] if d == "desc" else ("asc" if m["best"] == "desc" else "desc")
            stand = deck_standing(board, m["figure"], best, figure, slug=slug)
            if stand is None:
                break
            r = m[d]
            readings[d] = dict(stand, label=r["label"], reading=r["first"],
                               sort_key=r["key"], more=r["more"],
                               cards_label=r["cards"],
                               #the offer is the axis pointing AWAY from the end
                               #on screen. reading "saltiest" and being offered
                               #"saltier" is the tool agreeing with you rather
                               #than helping, which is what it used to do
                               swap=({"axis": r["swap"][0], "dir": r["swap"][1],
                                      "goal": SWAP_AXES[r["swap"]]["goal"]}
                                     if r["swap"] else None))
        if len(readings) != 2:
            continue
        prefix, suffix = figure_units(m["key"], cur)
        panels.append({"key": m["key"], "readings": readings,
                       #which of the five figures this panel puts in ink. the
                       #cards below it carry all five either way, exactly as
                       #they do on a search: the panel changes which one the
                       #eye lands on and nothing else about the row
                       "focus": focus_class(m["key"]),
                       "figure": figure, "decimals": m["decimals"],
                       "means": m["means"], "settling": m["settling"],
                       "cards_label": m["cards"], "noun": m["noun"],
                       "prefix": prefix, "suffix": suffix,
                       "cards": metric_cards(conn, oracle_ids, m["key"], cur),
                       #the sum is the memorable fact and the mean is the one
                       #the ranking can honestly use, so age prints both and
                       #every other metric prints one
                       "total_years": figures.get("age_total") if m["key"] == "age" else None,
                       "age_cards": figures.get("age_cards") if m["key"] == "age" else None})
    return panels


@app.route("/precons/<slug>")
def precon(slug):
    #one deck read through the lens, and the SAME view a pasted list gets. the
    #precons are 166 worked examples of what the paste box does, which is what
    #makes them a standing test of it rather than a second implementation
    cur = read_currency()
    board = precon_board(cur)
    deck_row = next((r for r in board if r["slug"] == slug), None)
    if deck_row is None:
        abort(404)

    #which panel opens. it is the sort the visitor arrived on, so clicking a
    #deck off the salt board lands on its salt standing rather than on a page
    #about originality that never mentions why they clicked. a reversed reading
    #(mild, cheap, obscure) opens its own metric's panel: they are one number.
    #the arrival key is kept as well as the metric, so the way back is the
    #board they were actually on rather than its other end
    arrived = read_precon_sort()
    opened = arrived["metric"]["key"]

    ids = precon_ids(slug)
    #every figure comes off the BOARD ROW rather than being added up again
    #here. postgres already summed these as real, python would sum them as
    #float64, and on a 62 card deck the two land about 7e-07 apart: nothing
    #anywhere except against the deck's own entry in the board, where it
    #decided whether the deck came out saltier than itself
    figures = {"original": deck_row["originality"], "salt": deck_row["salt"],
               "price": deck_row["price"], "played": deck_row["play_median"],
               "age": deck_row["age_mean"], "age_total": deck_row["age_total"],
               "age_cards": deck_row["age_cards"]}
    with pool.connection() as conn:
        panels = deck_panels(conn, ids, figures, board, cur, slug=slug)
    year = deck_row["release_date"].year if deck_row["release_date"] else 0
    #a deck still inside the settling window carries the note on every panel
    #whose number is affected, rather than a blanket disclaimer nobody reads
    is_new = bool(deck_row["release_date"] and deck_row["release_date"] >
                  datetime.date.today() - datetime.timedelta(days=PRECON_NEW_DAYS))
    #the deck itself, drawn by the same partial /deck/view uses, plus the plain
    #list the "run it through the lens" button posts. the list is built from the
    #card names rather than stored: it only has to be something parse_decklist
    #can read back, and one name per line is exactly that
    with pool.connection() as conn:
        cards = deck_cards(conn, ids, cur)
    decklist = "\n".join("1 " + c["name"] for c in cards)
    return render_template("precons/deck.html", deck=deck_row, year=year, panels=panels,
                           opened=opened, back=arrived["key"], cur=cur, is_new=is_new,
                           cur_urls=currency_urls(), cur_labels=CURRENCY_LABELS,
                           section=DECK_SECTION, cards=cards, decklist=decklist,
                           counted=len(ids), total=len(board))


#----- the paste box: someone else's decklist, read through the same lens -----

#lines that are structure rather than cards. exporters write these as section
#headings and a decklist is not obliged to have any of them.
#
#tested against the line with its bracketed bits already taken off, not against
#the raw line, because archidekt writes the section SIZE into the heading
#("Commander (1)", "Creatures (30)") where moxfield and mtgo write it bare. the
#bare form was the only one this ever saw, so every archidekt export with
#categories switched on reported one unmatched card per section
DECK_HEADERS = re.compile(r"^(deck|decklist|sideboard|commander|companion|maybeboard|"
                          r"considering|tokens?|creatures?|lands?|instants?|sorcer(?:y|ies)|"
                          r"artifacts?|enchantments?|planeswalkers?|battles?|"
                          r"ramp|removal|draw|utility|other)\b[:\s]*$", re.I)
#"1 ", "1x ", "4x " at the front of a line
DECK_COUNT = re.compile(r"^(\d+)\s*[xX]?\s+")
#everything the exporters bolt on AFTER the name: (SET) 123, *F*, [Category]
DECK_TRAILERS = re.compile(r"\s*(\([^)]*\)|\[[^\]]*\]|\*[^*]*\*|<[^>]*>)\s*")
#a collector number left stranded once its set code is gone. NOT applied
#blind: twelve real cards end in a digit (Pip-Boy 3000, Overseer of Vault 76),
#so this is only tried after the whole name has failed to match
DECK_TRAILING_NUM = re.compile(r"\s+\d+\s*$")
#mtgo marks its sideboard per line rather than under a heading, so a .txt
#straight out of the client carries "SB: 3 Swords to Plowshares"
DECK_SIDEBOARD = re.compile(r"^SB:\s*", re.I)
#deckstats hangs the category off the END of the line as "#!Ramp". no card name
#contains a hash, so taking one off the tail cannot cost a match
DECK_HASH_TAIL = re.compile(r"\s+#.*$")

#the two exports that are not lists of lines at all. both are recognised by
#their own first bytes rather than by a control the user has to set, because a
#paste box that asks which exporter you used is a paste box with a wrong answer
#in it
#
#mtgo's .dek is xml, one self closing element per card. read with a regex
#rather than an xml parser on purpose: this is a hostile string from a text
#box, and every stdlib xml parser has entity expansion behaviour worth not
#thinking about. the two attributes are all this needs
MTGO_DEK_CARD = re.compile(r"<Cards\b[^>]*?\bName=\"([^\"]+)\"", re.I)
MTGO_DEK_QTY = re.compile(r"\bQuantity=\"(\d+)\"", re.I)

#the cap on a pasted list. the pair query is all-pairs over the LINES of the
#list, so cost climbs with the square: ~250 lines (a commander deck) measured
#160-215ms, and letting someone paste a 5000 line file would be handing out a
#way to tie up the database. a commander deck is 100 cards and the biggest
#constructed sideboard-and-all is well under this
DECK_MAX_CARDS = 250
#and a cap on the raw text before it is even split, so an enormous paste is
#rejected without walking it
DECK_MAX_CHARS = 60000

#below this many nonland cards the precon comparison is not offered. scoring
#on a FRACTION means a short list is at least measured on the same share of
#itself as the decks it is ranked against, so this is no longer about unequal
#counts. it is about noise: a third of a six card list is two cards, and a
#two card mean says nothing about a deck. the SECTIONS still work at any size,
#being statements about the list itself rather than about where it stands
DECK_MIN_FOR_RANK = 20


def deck_norm(name):
    #match a name the way a human reads it: case, accents and the two kinds of
    #apostrophe all stop mattering. NFKD splits an accented letter into letter
    #plus combining mark, then dropping the marks leaves plain ascii, which is
    #what lets a list typed without accents find Grima Wormtongue
    name = name.replace("’", "'").replace("‘", "'")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return " ".join(name.lower().split())


#how long a good index is trusted for, and how long a FAILED rebuild waits
#before trying again. one clock for both meant a rebuild that threw still
#bought itself the full hour, so a cold start that missed left an empty index
#looking fresh and every paste for the next hour came back "none of those
#lines matched a card". the short wait is still a wait though, because a
#database that is properly down should not be asked once per request
NAME_INDEX_TTL = 3600
NAME_INDEX_RETRY = 60

_name_index = {"at": 0.0, "map": {}, "ttl": 0.0}


def name_index():
    #every name a decklist might write, normalised, pointing at an oracle id.
    #~33k keys for 31k cards, a couple of megabytes, rebuilt hourly like the
    #other caches. doing it in memory rather than in sql is what keeps a 100
    #card list to ZERO round trips for matching, and it puts normalisation
    #somewhere it can be read
    if time.time() - _name_index["at"] > _name_index["ttl"] and pool is not None:
        try:
            with pool.connection() as conn:
                rows = conn.execute("SELECT oracle_id, name FROM cards").fetchall()
            idx = {}
            #a two-faced card gets a key per face, because exporters write
            #"Delver of Secrets" where the database has the full
            #"Delver of Secrets // Insectile Aberration". full names go in
            #SECOND so they always win a collision with a face
            for r in rows:
                if "//" in r["name"]:
                    for part in r["name"].split("//"):
                        idx.setdefault(deck_norm(part), r["oracle_id"])
            for r in rows:
                idx[deck_norm(r["name"])] = r["oracle_id"]
            _name_index["map"] = idx
            _name_index["ttl"] = NAME_INDEX_TTL
        except Exception:
            #keep whatever map we already had, but come back for it soon
            _name_index["ttl"] = NAME_INDEX_RETRY
        _name_index["at"] = time.time()
    return _name_index["map"]


def csv_to_lines(text):
    #archidekt and moxfield both offer a CSV export beside the text one, and it
    #is a spreadsheet rather than a decklist: a header row naming the columns,
    #then one row per card with the name somewhere in the middle. splitting on
    #commas by hand cannot read it, because half the commander names in the
    #game contain a comma and the exporters quote those fields.
    #
    #returns None when this is not a csv, so the caller falls through to the
    #line parser untouched. the test is a header row that NAMES a name column,
    #which no decklist line can accidentally look like
    head = ""
    for raw in text.splitlines():
        if raw.strip():
            head = raw
            break
    #the cheap test first, on the header line alone. half the commander names
    #in the game contain a comma, so "there is a comma in the first line" is
    #true of ordinary decklists too, and without this every paste starting with
    #a legendary creature would be run through a csv parse to learn nothing
    if not any(c.strip().strip('"').lower() == "name" for c in head.split(",")):
        return None
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows:
        return None
    cols = [c.strip().lower() for c in rows[0]]
    if "name" not in cols:
        return None
    at = cols.index("name")
    #"quantity" is archidekt's word and "count" is moxfield's. neither is
    #required: a csv with no count column is still a list of cards, and the
    #lens drops counts on the way in anyway
    qty_at = next((cols.index(c) for c in ("quantity", "count") if c in cols), None)
    lines = []
    for row in rows[1:]:
        if len(row) <= at:
            continue
        name = row[at].strip()
        if not name:
            continue
        qty = "1"
        if qty_at is not None and len(row) > qty_at and row[qty_at].strip().isdigit():
            qty = row[qty_at].strip()
        lines.append(qty + " " + name)
    return "\n".join(lines) if lines else None


def dek_to_lines(text):
    #mtgo's own .dek save file, which is xml. same contract as csv_to_lines:
    #None means this was not one, and the line parser gets the text unchanged
    if "<Cards" not in text:
        return None
    lines = []
    for m in re.finditer(r"<Cards\b[^>]*>", text, re.I):
        tag = m.group(0)
        name = MTGO_DEK_CARD.match(tag)
        if not name:
            continue
        qty = MTGO_DEK_QTY.search(tag)
        lines.append((qty.group(1) if qty else "1") + " " + name.group(1))
    return "\n".join(lines) if lines else None


def parse_decklist(text):
    #returns (matched oracle ids, names we could not find). deliberately blind
    #to WHICH board a card is in: the lens reads the whole pile, and a
    #commander deck has no sideboard anyway.
    #
    #matching is EXACT on the normalised name, never fuzzy. find_card guesses
    #because a human is watching one result and can retype; here a wrong guess
    #would sit silently in a hundred rows pretending to be someone's deck
    idx = name_index()
    found, missing = [], []
    seen = set()
    text = text[:DECK_MAX_CHARS]
    #the two exports that arrive as a file rather than as a list get turned
    #into one before anything else looks at them, so there is still exactly one
    #line parser and it is the one that has been tested
    text = csv_to_lines(text) or dek_to_lines(text) or text
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        #mtgo writes its sideboard per line instead of under a heading, and
        #deckstats writes the category onto the end of the line. both are
        #wrapping paper around a name and a count
        line = DECK_HASH_TAIL.sub("", DECK_SIDEBOARD.sub("", line)).strip()
        if not line:
            continue
        #the line as typed and the line with a leading count taken off, in that
        #order. a number at the front is almost always a count and occasionally
        #part of the name, and taking it off blind turned "1996 World Champion"
        #into a lookup for "World Champion". the trailing number already got
        #this care, the front of the line never did.
        #
        #trying the untouched line first can only ADD matches: for it to hit,
        #a card has to really be named with digits in front
        whole = DECK_TRAILERS.sub(" ", line).strip()
        #the heading test runs HERE rather than on the raw line, so a heading
        #carrying its own count ("Commander (1)") is still a heading
        if DECK_HEADERS.match(whole):
            continue
        m = DECK_COUNT.match(line)
        counted = DECK_TRAILERS.sub(" ", line[m.end():]).strip() if m else ""
        tries = [t for t in (whole, counted) if t]
        if not tries:
            continue
        oid = None
        for t in tries:
            oid = idx.get(deck_norm(t))
            if oid is not None:
                break
        if oid is None:
            #only now as a name with a collector number stuck on the end, so
            #the twelve cards whose names really do end in a digit are never
            #truncated into nothing
            for t in tries:
                trimmed = DECK_TRAILING_NUM.sub("", t).strip()
                if trimmed and trimmed != t:
                    oid = idx.get(deck_norm(trimmed))
                    if oid is not None:
                        break
        if oid is None:
            if len(missing) < 40:
                #the count is off by now, so this reads back as the card name
                #the line was asking for
                missing.append(tries[-1])
            continue
        #counts are dropped on purpose: nine Islands say nothing about a
        #deck's ideas that one Island does not, and the lens is about ideas
        if oid in seen:
            continue
        seen.add(oid)
        found.append(oid)
        if len(found) >= DECK_MAX_CARDS:
            break
    return found, missing


#how many precons sit either side of the deck in each standing. enough to see
#what it landed between, short enough that five of these on one page is still
#a page. the whole board is one click away on /precons
DECK_WINDOW = 3


def deck_metrics(conn, oracle_ids, currency):
    #the deck's price, play rate and age, computed EXACTLY as PRECON_SQL
    #computes them for a precon. that is the entire requirement here: a
    #standing is a comparison, and a comparison between two numbers that were
    #arrived at differently is not a comparison at all. every predicate below
    #is a transcription of the matching CTE, and if one moves both must.
    #
    #deck_cards holds one row per DISTINCT card, and a pasted list drops its
    #counts on the way in, so both sides are already counting the same way
    #SALT_BASIC_SQL already carries its percent signs DOUBLED, because every
    #query using it is parameterised and psycopg reads a lone % as the start of
    #a placeholder. it goes in untouched
    basic = SALT_BASIC_SQL
    ids = [str(o) for o in oracle_ids]
    row = conn.execute("""
        SELECT
          (SELECT sum(""" + price_col(currency) + """) FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[])) AS price,
          (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY c.edhrec_rank) FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.edhrec_rank IS NOT NULL
              AND c.type_line NOT LIKE '%%Land%%') AS play_median,
          (SELECT avg(extract(epoch FROM (now() - c.released_at)) / 31557600.0) FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.released_at IS NOT NULL
              AND NOT """ + basic + """) AS age_mean,
          (SELECT sum(extract(epoch FROM (now() - c.released_at)) / 31557600.0) FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.released_at IS NOT NULL
              AND NOT """ + basic + """) AS age_total,
          (SELECT count(*) FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.released_at IS NOT NULL
              AND NOT """ + basic + """) AS age_cards
    """, (ids, ids, ids, ids, ids)).fetchone()
    return dict(row) if row else {}


def deck_standing(board, key, best, figure, slug=None):
    #where the deck lands on the board, and who it landed between.
    #
    #"better" is the metric's own direction rather than bigger-is-better, which
    #is the whole reason the board learned one: on play rate a SMALLER median
    #is more played, and a standing that got that backwards would tell someone
    #their pile of staples was the most obscure deck in the format.
    #
    #a precon passes its SLUG and is already a row here, so it is located
    #rather than inserted. a pasted deck has no slug and gets dropped in at the
    #position its figure earns, making the population one bigger. both come
    #back in the same shape, because the two pages that read this are the same
    #page and the only difference between them is which deck is being read
    if figure is None:
        return None
    rows = [r for r in board if r.get(key) is not None]
    rows.sort(key=lambda r: (float(r[key]) if best == "asc" else -float(r[key]), r["name"]))

    if slug is not None:
        at = next((i for i, r in enumerate(rows) if r["slug"] == slug), None)
        if at is None:
            return None
        window = []
        for i in range(max(0, at - DECK_WINDOW), min(len(rows), at + DECK_WINDOW + 1)):
            r = rows[i]
            window.append({"place": i + 1, "name": r["name"], "slug": r["slug"],
                           "figure": float(r[key]), "you": i == at})
        return {"place": at + 1, "beaten": len(rows) - at - 1,
                "of": len(rows), "window": window}

    better = 0
    for r in rows:
        v = float(r[key])
        if (v < figure) if best == "asc" else (v > figure):
            better += 1
        else:
            break
    #places are counted off the slice indices, never looked up by value: two
    #decks can hold the identical figure, and asking a list where a row "is"
    #would then hand back the first of them for both
    window = []
    start = max(0, better - DECK_WINDOW)
    for i in range(start, better):
        r = rows[i]
        window.append({"place": i + 1, "name": r["name"], "slug": r["slug"],
                       "figure": float(r[key]), "you": False})
    window.append({"place": better + 1, "name": "Your deck", "slug": None,
                   "figure": figure, "you": True})
    for i in range(better, min(len(rows), better + DECK_WINDOW)):
        r = rows[i]
        #everything below the deck shifts down one, because the deck is now
        #sitting above them
        window.append({"place": i + 2, "name": r["name"], "slug": r["slug"],
                       "figure": float(r[key]), "you": False})
    #"of" counts the deck itself in, so the sentence reads 12th of 167 whether
    #the deck was already on the board or has just been dropped onto it
    return {"place": better + 1, "beaten": len(rows) - better,
            "of": len(rows) + 1, "window": window}


def deck_hub(error=None, pasted="", url="", missing=None):
    #the front door, rendered the same way whether it is being visited or
    #being returned to with a complaint. one function so an error state can
    #never drift into looking like a different page
    board = precon_board()
    return render_template("deck/hub.html", deck_count=len(board),
                           example=board[0] if board else None,
                           error=error, pasted=pasted, url=url, missing=missing)


def deck_identity():
    #what to call this deck. it rides the FORM, like the list itself, because
    #there is no session to keep it in and that is the whole design.
    #
    #it has to be carried by every form on every page of the lens or the name
    #is lost the moment you go back to change something: the importer knew the
    #commander, the page after it printed the commander, and then the reading
    #called the same deck "72 cards" because nothing had passed the name on
    commander = " ".join(request.form.get("commander", "").split())[:200]
    name = " ".join(request.form.get("name", "").split())[:200]
    return (name or commander), commander


def deck_leaders(conn, oracle_ids):
    #every card in the list that could BE the commander: front face legendary
    #creatures, the same test the search's "commanders only" filter uses. a
    #commander deck holds one or two, so this is usually the answer rather than
    #a list anyone has to search, and the picker falls back to the whole list
    #when a pile of cards has no legend in it at all
    try:
        return [r["name"] for r in conn.execute("""
            SELECT name FROM cards
            WHERE oracle_id = ANY(%s::uuid[])
              AND split_part(type_line, '//', 1) ILIKE %s
              AND split_part(type_line, '//', 1) ILIKE %s
            ORDER BY name
        """, ([str(o) for o in oracle_ids], "%Legendary%", "%Creature%")).fetchall()]
    except Exception:
        return []


def deck_cards(conn, oracle_ids, currency):
    #every card in a deck, ready to be drawn by partials/deckcards.html. it is
    #the one query behind both the view page and the precon page, so a deck
    #looks the same wherever it is shown.
    #
    #the labels come off the same helpers the results grid and the swap grid
    #use rather than being formatted here, which is what keeps a price on this
    #page reading identically to the same card's price on a search.
    #
    #DISTINCT cards, not copies: parse_decklist folds a list down to the cards
    #it holds, so thirty seven Forests arrive here as one Forest and there is
    #no count to print. that is the right grid for "did this import whole",
    #and the exact list with its counts is on the same page to copy
    try:
        rows = conn.execute("""
            SELECT oracle_id, name, type_line, layout, image, image_back,
                   scryfall_uri, price_usd, price_eur, edhrec_rank, salt,
                   released_at
            FROM cards WHERE oracle_id = ANY(%s::uuid[])
            ORDER BY name
        """, ([str(o) for o in oracle_ids],)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        c = dict(r)
        c["sideways"] = sideways(c["layout"], c["type_line"])
        c["flip"] = c["layout"] == "flip"
        c["price_label"] = price_label(c, currency)
        c["rank_label"] = rank_label(c["edhrec_rank"])
        c["salt_label"] = salt_label(None if c["salt"] is None else float(c["salt"]))
        c["age_label"] = age_label(c["released_at"])
        out.append(c)
    return out


def deck_names(conn, oracle_ids):
    #every card in the list, for the picker to filter when the deck holds no
    #legendary creature (a brew pasted without its commander, a cube, a pile)
    try:
        return [r["name"] for r in conn.execute(
            "SELECT name FROM cards WHERE oracle_id = ANY(%s::uuid[]) ORDER BY name",
            ([str(o) for o in oracle_ids],)).fetchall()]
    except Exception:
        return []


#the three pages below are rendered from a POST and have no url of their own,
#which is the privacy decision and it stays: a pasted list is nobody's business
#and there is nothing to come back to. answering a bare GET with a 405 was
#never part of that decision though, it is just what werkzeug does when no
#rule matches. a back button, a bookmark or a link someone shared all arrive
#as a GET, so they get the front door with the paste box on it
@app.route("/deck/open", methods=["GET"])
@app.route("/deck/read", methods=["GET"])
@app.route("/deck/swap", methods=["GET"])
@app.route("/deck/view", methods=["GET"])
def deck_post_only():
    return redirect("/deck")


@app.route("/deck/open", methods=["POST"])
def deck_open():
    #where both inputs land. the importer and the paste box are separate
    #controls on purpose (Ethan's call, and it is right): one box sniffing at
    #its own contents is the version where validating is hardest and the error
    #messages are worst. two inputs means each one checks exactly one shape.
    #
    #they converge HERE, immediately, and everything downstream sees a pasted
    #list either way. the import path's whole job is turning a url into text
    text = request.form.get("list", "")
    url = request.form.get("url", "").strip()
    #a name the page already knew, coming back round: the recent-decks list and
    #the "read another deck" links all repost through here, and without this
    #the second visit to the same list forgets what the deck was called
    name, commander = deck_identity()
    if url:
        site = import_site(url)
        if not site:
            return deck_hub(error="That doesn't look like an Archidekt or Moxfield deck "
                                  "link. They look like archidekt.com/decks/1234567 and "
                                  "moxfield.com/decks/aBcDeFgH.", url=url)
        if not import_allowed(import_token()):
            #one message for both lids on purpose. "you have imported a lot"
            #and "the site has imported a lot" are different facts but the same
            #instruction, and the paste box below answers either one
            return deck_hub(error="Too many deck imports just now, so we're giving "
                                  "them a rest. Try again in a minute, or paste the "
                                  "list below and carry on.", url=url)
        try:
            text, found, deck_name = site["fetch"](site["id"])
        except Exception:
            #deliberately one message for every failure mode. the site being
            #down, the deck being private and their api changing shape are the
            #same event to someone holding a link that did not work, and the
            #paste box underneath is the answer to all three
            return deck_hub(error="Couldn't fetch that deck from " + site["name"] + ". It "
                                  "may be private, or they may be having a moment. "
                                  "Pasting the list below always works.", url=url)
        #the importer knows which card was flagged as the commander, which is
        #the one thing a pasted list cannot say. it only PRESELECTS the picker
        #though: the page still shows what it decided, so a wrong guess is one
        #click to fix rather than a title nobody can change
        commander = commander or (found[0] if found else "")
        name = name or commander or deck_name
    if not text.strip():
        return deck_hub(error="Paste a decklist, or give an Archidekt or Moxfield link.")

    ids, missing = parse_decklist(text)
    if not ids:
        return deck_hub(error="None of those lines matched a card.",
                        pasted=text[:DECK_MAX_CHARS], url=url, missing=missing)
    #what did not match is a ONE TIME question, asked when a deck arrives. a
    #deck coming back round (out of this browser's recent list, or off a "back
    #to this deck" link) has already been through it, and the answer was
    #whatever the user did about it then. asking again on every visit turns a
    #useful check into a nag about eleven lines they have already decided to
    #live with.
    #
    #nothing was stored either way: a miss only ever becomes a row in the
    #feedback table if the user actively resolves it (see /deck/found), so
    #forgetting them here means forgetting them everywhere
    if request.form.get("seen"):
        missing = []
    with pool.connection() as conn:
        leaders = deck_leaders(conn, ids)
        #a deck with exactly one legend in it has already answered the
        #question, so it is filled in rather than asked. anything else gets the
        #picker with the candidates in it
        if not commander and len(leaders) == 1:
            commander = leaders[0]
        picker = leaders or deck_names(conn, ids)
    name = name or commander
    #the two modes, offered rather than assumed. it costs a click and buys the
    #confirmation that the list arrived intact, which is the thing an IMPORT
    #most needs: a link that silently read 40 of your 100 cards is the failure
    #nobody notices until the numbers look wrong
    #which shelf entry this deck belongs to, when it came off the shelf. it is
    #the list as first imported, and the browser keys its saved decks on it, so
    #a deck reopened after a swap session is recognised as the same deck rather
    #than saved again as a second one. empty for a fresh paste or import, which
    #is the browser's cue to key on the list itself
    return render_template("deck/modes.html", pasted=text[:DECK_MAX_CHARS],
                           origin=request.form.get("origin", "")[:DECK_MAX_CHARS],
                           matched=len(ids), missing=missing,
                           deck_name=name, commander=commander,
                           leaders=leaders, picker=picker,
                           swap_axes=SWAP_AXES, swap_default=SWAP_DEFAULT)


@app.route("/deck/view", methods=["POST"])
def deck_view():
    #the deck itself, as its cards. the third of the three modes and the one
    #that answers "did this arrive whole", which is the question an IMPORT
    #most needs and the one the other two answer only by implication.
    #
    #it renders the same partial /precons/<slug> does, so a deck someone
    #pasted and a deck that shipped in a box are shown by one piece of code
    #rather than by two that agree until somebody edits one of them.
    #
    #what CHANGED is deliberately not computed here and cannot be: a swap
    #session never reaches the server, so the only record of it is the shelf in
    #the visitor's own browser. the page carries its origin and the script
    #fills those blocks in from there
    text = request.form.get("list", "")
    ids, missing = parse_decklist(text)
    if not ids:
        return deck_hub(error=("None of those lines matched a card." if text.strip()
                               else "Paste a decklist first."),
                        pasted=text[:DECK_MAX_CHARS], missing=missing)
    if request.form.get("seen"):
        missing = []
    cur = read_currency()
    name, commander = deck_identity()
    with pool.connection() as conn:
        cards = deck_cards(conn, ids, cur)
    return render_template("deck/view.html", cards=cards, matched=len(ids),
                           section=DECK_SECTION,
                           missing=missing, cur=cur, deck_name=name,
                           commander=commander, pasted=text[:DECK_MAX_CHARS],
                           origin=request.form.get("origin", "")[:DECK_MAX_CHARS])


@app.route("/deck/read", methods=["POST"])
def deck_read():
    #the pasted list, read and thrown away. nothing is stored and there is no
    #url to come back to, which is the product decision from the start: a lens
    #over someone else's list, not a deck builder with accounts and saves
    text = request.form.get("list", "")
    ids, missing = parse_decklist(text)
    if not ids:
        return deck_hub(error=("None of those lines matched a card." if text.strip()
                               else "Paste a decklist first."),
                        missing=missing, pasted=text[:DECK_MAX_CHARS])

    cur = read_currency()
    name, commander = deck_identity()
    scored = deck_uniqueness(ids)

    #the number only means something against the precons, which is what the
    #whole calibration set was for. a list too short to compare fairly gets no
    #ranking at all, rather than a placing that quietly comes from averaging
    #six cards against a hundred
    board = precon_board(cur)
    ranked = len(scored) >= DECK_MIN_FOR_RANK

    panels = []
    if ranked:
        with pool.connection() as conn:
            figures = deck_metrics(conn, ids, cur)
            figures["original"] = originality_of(scored)
            figures["salt"] = deck_salt(ids)
            figures["played"] = figures.get("play_median")
            figures["age"] = figures.get("age_mean")
            #the same builder the precon pages use, so the two readings cannot
            #drift into being two different pages about the same measurement
            panels = deck_panels(conn, ids, figures, board, cur)

    #what "change it" offers, keyed by the READING on screen rather than by the
    #metric: "most expensive" offers cheaper and "cheapest" offers pricier,
    #because the useful move is always away from the end you are looking at.
    #originality offers nothing either way and the panel hides the block
    swaps = {}
    for p in panels:
        for d, r in p["readings"].items():
            if r["swap"]:
                swaps[r["sort_key"]] = r["swap"]
    return render_template("deck/read.html", panels=panels, opened=PRECON_METRICS[0]["key"],
                           counted=len(scored), matched=len(ids), missing=missing,
                           total=len(board), ranked=ranked, min_cards=DECK_MIN_FOR_RANK,
                           cur=cur, deck_name=name, commander=commander, swaps=swaps,
                           section=DECK_SECTION,
                           #passed straight through: the Change it form below
                           #posts to /deck/swap and the key has to survive the hop
                           origin=request.form.get("origin", "")[:DECK_MAX_CHARS],
                           #the currency control here is a form rather than
                           #links: this page has no url of its own to flip
                           cur_post=True, cur_labels=CURRENCY_LABELS,
                           #handed straight back so the swap tool can be reached
                           #from a reading without pasting twice. it rides the
                           #page rather than a session for the same reason as
                           #everything else here: there is nothing to store
                           pasted=text[:DECK_MAX_CHARS], swap_axes=SWAP_AXES,
                           swap_default=SWAP_DEFAULT)


@app.route("/deck/found", methods=["POST"])
def deck_found():
    #a line the parser could not match, matched by hand by the person holding
    #the list. two things come out of that and both are worth having.
    #
    #they get the card, added to their own list right there rather than being
    #told to go and edit the paste and start again. and WE get the pair: what
    #they typed against what they meant. a line a human could resolve and the
    #parser could not is a parser bug with a worked example already attached,
    #which is exactly the shape the rest of the feedback queue is in.
    #
    #it goes through the same table and the same review page as every other
    #report, so there is one queue rather than a second half-built one
    body = request.get_json(silent=True) or {}
    raw = " ".join(str(body.get("raw", "")).split())[:200]
    want = " ".join(str(body.get("name", "")).split())[:200]
    if not want:
        return {"ok": False, "msg": "Pick a card first."}
    card = find_card(want)
    if card is None:
        return {"ok": False, "msg": 'No card called "' + want + '", check the spelling?'}
    try:
        ip = visitor_token(client_ip())
        with pool.connection() as conn:
            #the same gentle lid the report bar has. there is no login, so this
            #is all the abuse control there is, and a window of an hour means
            #the token rotating at midnight only ever resets it
            recent = conn.execute("""SELECT count(*) AS n FROM feedback
                                     WHERE ip = %s AND ip <> ''
                                       AND created_at > now() - interval '1 hour'""",
                                  (ip,)).fetchone()["n"]
            if recent < 40:
                conn.execute("""INSERT INTO feedback (kind, anchor_id, anchor_name, reason, ip)
                                VALUES ('deckline', %s, %s, %s, %s)""",
                             (card["oracle_id"], card["name"], raw, ip))
    except Exception:
        #the card still goes into their list. logging it is our business, not
        #theirs, and a full disk here must not cost them the reading
        pass
    return {"ok": True, "name": card["name"]}


#----- importing a decklist from a url -----

#archidekt and moxfield. NEITHER publishes a supported public api: archidekt
#calls its own open beta and documents nothing, and moxfield asks third parties
#to write in for access and to identify themselves in the User-Agent, which is
#why ours names the site and links to it. so both of these can stop working
#without warning, and everything below is written for that day: a failure says
#so in words and the paste box is right there underneath, because an importer
#that takes the page down with it when somebody else ships a change is worse
#than no importer at all
ARCHIDEKT_URL = re.compile(r"^https?://(?:www\.)?archidekt\.com/(?:decks|api/decks)/(\d{1,12})", re.I)
#moxfield deck ids are a short opaque string rather than a number, and they
#turn up as /decks/<id> on the site and /v2/decks/all/<id> on the api. the
#character class is the allowlist that keeps this from becoming a path: no
#slashes, no dots, no percent signs
MOXFIELD_URL = re.compile(r"^https?://(?:www\.)?moxfield\.com/decks/([A-Za-z0-9_-]{1,40})", re.I)

#a slow third party must not become a slow page, and a big response must not
#become our memory problem. a 100 card deck's json runs about 400kb
DECK_IMPORT_TIMEOUT = 10
DECK_IMPORT_MAX_BYTES = 8 * 1024 * 1024


def import_site(url):
    #which site this link belongs to and what its deck id is, or None.
    #
    #this is the whole security design and it is worth being explicit: the
    #user's url is NEVER fetched. an id is pulled out of it and OUR url is
    #built from that id, so there is no redirect to follow, no host to
    #revalidate and no way to point this at localhost or a cloud metadata
    #endpoint. a domain allowlist in front of a fetch of user input is the
    #version of this that keeps being a vulnerability.
    #
    #adding a second site changed nothing about that, which is the test a
    #design like this has to pass: each pattern names one host and captures one
    #id out of a character class that cannot hold a slash
    url = (url or "").strip()
    for pattern, name, fetch in ((ARCHIDEKT_URL, "Archidekt", archidekt_deck),
                                 (MOXFIELD_URL, "Moxfield", moxfield_deck)):
        m = pattern.match(url)
        if m:
            return {"id": m.group(1), "name": name, "fetch": fetch}
    return None


#the importer is the only thing on this site that makes an outbound request on
#a visitor's command, so it is the only thing that needs a lid on it.
#
#TWO lids, and the SECOND one is the one that matters. a per visitor limit
#stops one person looping, which is the obvious threat and the smaller one.
#it does nothing for us, because archidekt sees ONE address for every import
#this site ever makes: railway's. a hundred people importing once each looks
#exactly like one machine hammering them, so the aggregate needs its own cap
#or a busy afternoon gets our address blocked and the importer stops working
#for everybody.
#
#in memory, so it is per process and resets on deploy. that is the right
#weight for this: the job is to stop a runaway, not to enforce a quota, and
#a rate limiter that needs its own table to protect somebody else's server is
#more machinery than the problem deserves
IMPORT_PER_TOKEN = 15
IMPORT_TOKEN_WINDOW = 600
IMPORT_GLOBAL = 60
IMPORT_GLOBAL_WINDOW = 60

#how many visitors' allowances are tracked at once. it is a memory bound, not
#a policy: at any real traffic level the expiry below clears entries long
#before this is reached
IMPORT_TOKENS_KEPT = 2000

_import_hits = {}
_import_all = []


def import_allowed(token):
    #checked only when an import is actually about to GO OUT. a flood of
    #malformed urls never reaches here and costs nothing, so it should not
    #burn anyone's allowance either
    global _import_all
    now = time.time()
    _import_all = [t for t in _import_all if now - t < IMPORT_GLOBAL_WINDOW]
    if len(_import_all) >= IMPORT_GLOBAL:
        return False
    hits = [t for t in _import_hits.get(token, []) if now - t < IMPORT_TOKEN_WINDOW]
    if token and len(hits) >= IMPORT_PER_TOKEN:
        _import_hits[token] = hits
        return False
    if token:
        hits.append(now)
        _import_hits[token] = hits
        if len(_import_hits) > IMPORT_TOKENS_KEPT:
            #expired entries first, because dropping those costs nothing:
            #their allowance had already run out
            for k in [k for k, v in _import_hits.items()
                      if not v or now - v[-1] > IMPORT_TOKEN_WINDOW]:
                _import_hits.pop(k, None)
            #and a hard cap behind it, because evicting only the expired ones
            #bounds this by "distinct visitors inside one window" rather than
            #by a number, which is not a bound at all. the oldest go, so the
            #allowance handed back belongs to whoever imported longest ago,
            #and the GLOBAL lid still holds the line that actually matters
            if len(_import_hits) > IMPORT_TOKENS_KEPT:
                for k, _ in sorted(_import_hits.items(), key=lambda kv: kv[1][-1]
                                   )[:len(_import_hits) - IMPORT_TOKENS_KEPT]:
                    _import_hits.pop(k, None)
    _import_all.append(now)
    return True


def import_token():
    #the same one-way daily fingerprint the visit counter and the feedback lid
    #use, so no new way of identifying anyone is introduced for this. if the
    #database is unreachable the salt cannot be read, and the global cap alone
    #carries the load rather than the importer failing shut
    try:
        return visitor_token(client_ip())
    except Exception:
        return ""


#the same identification on every outbound request, because moxfield asks
#third parties to say who they are and archidekt has no opinion. one constant
#so the two can never disagree about who is calling
IMPORT_AGENT = "Delvefall/1.0 (+https://delvefall.com)"


def import_json(url):
    #one outbound GET, capped in time and in bytes, decoded as json. both
    #importers go through here so neither can forget a lid
    req = urllib.request.Request(url, headers={"User-Agent": IMPORT_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=DECK_IMPORT_TIMEOUT) as r:
        raw = r.read(DECK_IMPORT_MAX_BYTES + 1)
    if len(raw) > DECK_IMPORT_MAX_BYTES:
        raise ValueError("deck too large")
    return json.loads(raw.decode("utf-8"))


def moxfield_deck(deck_id):
    #(decklist text, commander names, deck name), same contract as archidekt's.
    #
    #moxfield splits the deck into named boards rather than tagging each card,
    #so the commander is whatever sits in the "commanders" board and the
    #maybeboard and sideboard are simply other boards this does not read. that
    #is a cleaner shape than archidekt's categories and it means the two
    #importers agree on what a deck IS without agreeing on anything else
    data = import_json("https://api2.moxfield.com/v2/decks/all/%s" % deck_id)
    boards = data.get("boards") or {}
    lines, commanders = [], []
    for board in ("commanders", "companions", "mainboard"):
        cards = ((boards.get(board) or {}).get("cards") or {})
        #a dict keyed by moxfield's own card id, so the values are what matter
        for entry in list(cards.values())[:DECK_MAX_CARDS]:
            name = ((entry.get("card") or {}).get("name") or "").strip()
            if not name:
                continue
            if board == "commanders":
                commanders.append(name)
            try:
                qty = max(1, int(entry.get("quantity") or 1))
            except (TypeError, ValueError):
                qty = 1
            lines.append("%d %s" % (qty, name))
    if not lines:
        raise ValueError("no cards")
    return "\n".join(lines[:DECK_MAX_CARDS]), commanders, (data.get("name") or "").strip()


def archidekt_deck(deck_id):
    #(decklist text, commander names, deck name), or raises.
    #
    #it hands back TEXT and lets parse_decklist do the matching, rather than
    #resolving names to cards here. that parser is tested across every export
    #shape these sites produce, and a second matching path would be a second
    #thing to get wrong and a second thing to keep in step. the importer's
    #entire job is turning a url into the same thing a paste is
    data = import_json("https://archidekt.com/api/decks/%s/" % deck_id)

    lines, commanders = [], []
    for entry in (data.get("cards") or [])[:DECK_MAX_CARDS]:
        inner = entry.get("card") or {}
        name = ((inner.get("oracleCard") or {}).get("name") or "").strip()
        if not name:
            continue
        #archidekt marks the commander with a category, which is the one thing
        #a pasted list cannot tell us. worth carrying: it is the correct source
        #for a deck's colour identity, where the union of every card's identity
        #is only ever an approximation of it
        cats = entry.get("categories") or []
        if "Commander" in cats:
            commanders.append(name)
        #maybeboard and sideboard cards are not in the deck. archidekt keeps
        #them in the same list and distinguishes them by category, so importing
        #the lot would quietly read someone's shortlist as part of their deck
        if "Maybeboard" in cats or "Sideboard" in cats:
            continue
        try:
            qty = max(1, int(entry.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        lines.append("%d %s" % (qty, name))
    if not lines:
        raise ValueError("no cards")
    return "\n".join(lines), commanders, (data.get("name") or "").strip()


#----- the swap tool: the lens with a hand on it -----

#the axis the page opens on, and for now the only one it offers. the machinery
#below is generic over all eight (four fields, two directions each, the same
#four the search sort has), because it is one code path and writing it for one
#axis would have meant writing it twice. what is deliberately NOT generic yet
#is the interface: the loop is the risky part of this feature, not the axes,
#so it gets proven on one before the other seven go on a control
SWAP_DEFAULT = ("salt", "asc")


def deck_swappable(conn, oracle_ids, currency):
    #every card in the list that could be swapped at all, with the columns the
    #axes read. cards with no rules lines are dropped here rather than later:
    #matching happens on LINES, so a card without any can never produce a
    #suggestion, and queueing one walks the user to an empty page with no
    #explanation for why that card and not another
    return [dict(r) for r in conn.execute("""
        SELECT DISTINCT c.oracle_id, c.name, c.type_line, c.mana_cost, c.cmc,
               c.image, c.image_back, c.layout, c.scryfall_uri, c.edhrec_rank,
               c.released_at, c.salt, c.price_usd, c.price_eur,
               """ + price_col(currency) + """ AS price
        FROM cards c
        WHERE c.oracle_id = ANY(%s::uuid[])
          AND EXISTS (SELECT 1 FROM lines l WHERE l.oracle_id = c.oracle_id
                      AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL)
    """, ([str(o) for o in oracle_ids],)).fetchall()]


def deck_colors(conn, oracle_ids):
    #what the deck can cast, as the union of its cards' colour identities.
    #
    #the union rather than the COMMANDER's identity, which is the stricter and
    #more correct reading, because parse_decklist is deliberately blind to
    #which board a card is in and cannot say which line was the commander. the
    #union is the safe direction to be wrong in: it can only ever be as wide as
    #cards the deck is already playing. one illegal card in a pasted list
    #widens it, which is worth fixing the day the parser learns about sections
    row = conn.execute("""
        SELECT string_agg(DISTINCT letter, '') AS letters
        FROM cards c, regexp_split_to_table(c.color_identity, '') AS letter
        WHERE c.oracle_id = ANY(%s::uuid[])
    """, ([str(o) for o in oracle_ids],)).fetchone()
    return (row["letters"] or "") if row else ""

#the axes a deck can be moved along, and they are deliberately the SAME four
#fields the search sort offers, read the same way: the direction names the
#CONCEPT you want more of, never the column underneath. that is not tidiness.
#it is the model already learned on /search, and inventing a second vocabulary
#for the same four ideas is the nine-combinations mistake wearing a new hat.
#
#"best" is absent because it is not an axis. there is no such thing as moving
#a deck toward better matching.
#
#"better" is which way the COLUMN moves for a card the user would call an
#improvement, and it is not the same question as the label. play rate is where
#the two come apart: "less played" is ascending play rate but DESCENDING
#edhrec_rank, because rank 1 is the most played card in the format. get this
#backwards and the tool confidently suggests Sol Ring to someone asking for
#something more obscure
SWAP_AXES = {
    ("price", "asc"):     {"goal": "cheaper",     "better": "lower"},
    ("price", "desc"):    {"goal": "pricier",     "better": "higher"},
    ("played", "asc"):    {"goal": "less played", "better": "higher"},
    ("played", "desc"):   {"goal": "more played", "better": "lower"},
    ("released", "asc"):  {"goal": "older",       "better": "lower"},
    ("released", "desc"): {"goal": "newer",       "better": "higher"},
    ("salt", "asc"):      {"goal": "less salty",  "better": "lower"},
    ("salt", "desc"):     {"goal": "saltier",     "better": "higher"},
}

#the card column each axis reads. price is None because it depends on the
#currency the page is showing, and resolving it anywhere but price_col would
#be a second place for the three currencies to disagree
SWAP_COLUMNS = {"price": None, "played": "edhrec_rank",
                "released": "released_at", "salt": "salt"}


def swap_column(field, currency):
    return price_col(currency) if field == "price" else "c." + SWAP_COLUMNS[field]


#the match a suggestion has to clear before the page will offer it. 80 is not
#a strictness setting picked to feel safe, it is the calibrated boundary the
#display score was pinned to, so it is simply where a real match starts.
#
#there is NO looser pass and no strict-mode toggle. this had a "show weaker
#matches" button borrowed from /search's band walking, on the reasoning that
#an empty list needs an escape hatch. the better reasoning is that an empty
#list IS the answer: a card with nothing above 80 has nothing that does its
#job, and offering something worse is the TOOL lowering its standards rather
#than the user choosing to. so a card with no suggestions is skipped, and the
#page says which cards it skipped instead of letting them vanish.
#
#that also makes four controls this site has now deleted for having one right
#answer, after the blend slider, the uniqueness bar and the search threshold
SWAP_GATE = 80

#how many cards the queue offers BEFORE asking whether to keep going. it used
#to be how many it offered full stop, and stopping a working tool at twelve was
#the wrong call: somebody who has walked twelve cards and wants a thirteenth is
#exactly the person this is for.
#
#so it is a batch now, not a lid. the page holds SWAP_DEEP cards in queue order
#and reveals them a batch at a time, which costs one extra column of json and
#no extra database work: the candidates for a card are still fetched only when
#the user actually reaches it
SWAP_QUEUE = 12

#the real end of the queue. the whole deck is still not worth scanning, because
#on any axis only the tail is worth acting on, but 48 is deep enough that
#nobody reaches it by accident and shallow enough that the json stays small
SWAP_DEEP = 48

#how many replacements are offered per card. enough to choose from, few enough
#to read without scrolling, and past about six the tail is padding anyway
SWAP_OFFER = 5

#how far a replacement's mana value may sit from the card leaving. similarity
#is on RULES TEXT, so a two mana rock and a six mana rock score identically on
#the ability that makes them rocks. on /search that is browsing and the user
#judges. here the page is proposing a card for a specific slot, and a curve is
#a real constraint that the text cannot see
SWAP_MV_BAND = 2

#how close to the card's OWN rarest line another of its lines has to be before
#it is worth anchoring on too. 0.9 keeps genuine second abilities and drops
#riders: a card whose two lines are equally distinctive gets searched on both,
#a card carrying one real ability plus a keyword everybody has gets searched
#on the ability. see the anchoring note in swap_candidates for what this is
#actually protecting against
SWAP_ANCHOR_FRAC = 0.9

#a floor on the matched pair with BOTH sides weighted by how many cards carry
#the line, the same arithmetic the in-deck pairing uses. it survives anchoring
#as a backstop rather than the main defence: anchoring decides which of OUR
#lines is worth searching, this catches a candidate answering a rare line of
#ours with a line of theirs that half the format shares.
#
#deliberately low, and 0.75 is the value it was tried at first. at that value
#it was not a backstop but a second gate, and it removed every mana rock in the
#game from
#"find me a less played Sol Ring", whose correct answers are all mana rocks
#sharing one very common line. an exclusion that fires on the honest case is
#worse than the bug it was added for.
#
#always an EXCLUSION, never the number on screen: the badge stays the display
#score and the list still reads in descending order of the figure the user can
#actually see, which is the promise the whole site runs on
SWAP_PAIR_CUT = 0.2


def swap_queue(cards, field, direction):
    #the order the tool walks the deck in: the cards FURTHEST from where the
    #user wants to go, worst first, because that is where a swap buys the most.
    #
    #it is the exact inverse of "better". one flag drives both, which is what
    #keeps the queue and the suggestions from ever disagreeing about which way
    #is up on an axis.
    #
    #a card with no value on the axis drops out rather than sorting as zero: an
    #unpriced card is unknown, not free, and it would otherwise head up the
    #"make this cheaper" queue forever
    axis = SWAP_AXES[(field, direction)]
    key = "price" if field == "price" else SWAP_COLUMNS[field]
    rows = [c for c in cards if c.get(key) is not None]
    #basics can never be swapped into anything and deck_swappable has already
    #dropped them for having no rules lines. belt and braces, because a queue
    #built off any other source would put nine Islands at the top of a salt
    #list on the strength of the protest votes they carry
    rows = [c for c in rows if not is_basic_land(c.get("type_line") or "")]
    rows.sort(key=lambda c: c[key], reverse=(axis["better"] == "lower"))
    return rows[:SWAP_DEEP]


def swap_card_json(c, currency, anchor=None):
    #one card on the swap page, in the same shape and the same words the
    #results grid uses. the card leaving and every card that could take its
    #place go through here, so the two sides can never drift apart: whatever
    #the outgoing card says about its price is what a candidate says about
    #its own, and the comparison between them means something because both
    #numbers came out of the same function.
    #
    #anchor is the card being replaced. given one, every figure also carries
    #its verdict AGAINST that card, which is the whole question a swap asks
    #and exactly what the search page already computes against the searched
    #card. no new vocabulary: cheaper, pricier, milder, saltier, more played
    price = price_in(c, currency)
    salt = None if c["salt"] is None else float(c["salt"])
    out = {
        "oracle_id": str(c["oracle_id"]), "name": c["name"],
        "type_line": c["type_line"] or "", "mana_cost": c["mana_cost"] or "",
        "image": c["image"], "image_back": c["image_back"] or "",
        "scryfall_uri": c["scryfall_uri"],
        "sideways": sideways(c["layout"], c["type_line"]),
        "flip": c["layout"] == "flip",
        "price": price_label(c, currency),
        "rank": rank_label(c["edhrec_rank"]),
        "salt": salt_label(salt),
        #the fourth number, and it replaces a bare printing year that nothing
        #on the page ever drew. same reading, same words, same slot as on every
        #other grid on the site
        "age": age_label(c["released_at"]),
    }
    if anchor is not None:
        out["price_vs"] = price_verdict(price, price_in(anchor, currency))
        out["rank_vs"] = rank_verdict(c["edhrec_rank"], anchor["edhrec_rank"])
        out["salt_vs"] = salt_verdict(salt, None if anchor["salt"] is None else float(anchor["salt"]))
    return out


def swap_figure(card, field, currency="usd"):
    #the number that put this card in the queue, said the way the rest of the
    #site says it. the point is that the user can see WHY they are being shown
    #this card, so a queue nobody agrees with is arguable rather than mysterious
    if field == "price":
        v = card.get("price")
        return None if v is None else CURRENCY_SIGNS[currency] + ("%.2f" % float(v))
    if field == "played":
        v = card.get("edhrec_rank")
        return None if v is None else "play rate " + rank_label(v)
    if field == "released":
        #years old, not the year printed on it. a bare "1994" is a fact about
        #the card and "31.6 years" is the reading the rest of the site ranks,
        #sorts and prints, so this says the same thing the same way.
        #None rather than age_label's empty string, so all four branches answer
        #a missing figure the same way and the caller keeps one thing to check
        v = card.get("released_at")
        return None if v is None else age_label(v)
    v = card.get("salt")
    return None if v is None else "salt %.2f" % float(v)


def swap_candidates(conn, card, deck_ids, colors, field, direction, currency="usd"):
    #what could take this card's slot. one nearest neighbour walk per line of
    #the outgoing card, exactly as /search does, with the deck's own
    #constraints folded into the WHERE so the LIMIT bites after them rather
    #than before: a narrow deck digs deeper into the rankings instead of
    #thinning out a list that was already cut off
    axis = SWAP_AXES[(field, direction)]
    col = swap_column(field, currency)
    qlines = conn.execute("""
        SELECT l.line_text, l.""" + EMBED_COL + """ AS embedding, coalesce(s.count, 1) AS count
        FROM lines l LEFT JOIN line_stats s ON s.line_text = l.line_text
        WHERE l.oracle_id = %s AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL
    """, (card["oracle_id"],)).fetchall()
    if not qlines:
        return []

    #anchor on what makes this card THIS card: its rarest lines, not whichever
    #of them happens to match something best.
    #
    #this is the other half of the Stasis problem and the half that matters.
    #"one matching ability is enough" is right for /search, where the user is
    #browsing and judging, and wrong for a slot replacement, where the ability
    #that matched has to be the ability the user is replacing. Stasis matched
    #Sunken City perfectly on its upkeep tax while the untap lock, the entire
    #reason anyone plays or hates the card, went unexamined.
    #
    #RELATIVE to the card's own best line, never an absolute bar. Sol Ring is
    #one common line and nothing else, so its defining line IS the common one
    #and mana rocks are the honest answer. an absolute cut threw all of them
    #out and returned nothing at all, which is worse than the bug it fixed
    top_w = max(line_weight(ql["count"]) for ql in qlines)
    qlines = [ql for ql in qlines if line_weight(ql["count"]) >= SWAP_ANCHOR_FRAC * top_w]

    where = ""
    params = []
    #never suggest a card the deck is already running. commander is singleton,
    #so without this the best answer for your Counterspell is reliably the
    #Arcane Denial sitting four rows below it
    where += " AND c.oracle_id <> ALL(%s::uuid[])"
    params.append([str(o) for o in deck_ids])
    #the deck's colour identity, read the deckbuilding way: every letter of the
    #card's identity has to be one the deck can already produce, and colourless
    #always fits. without it most of the list is unplayable and the tool looks
    #like it has not read the deck
    if colors is not None:
        where += " AND c.color_identity ~ %s"
        params.append("^[" + colors + "]*$")
    where += " AND c.legal_commander"
    #a land slot stays a land slot. the text similarity cannot see the
    #difference, and offering a creature for a land is the single most obvious
    #way for a suggestion to read as broken
    where += " AND (c.type_line ILIKE %s) = %s"
    params.append("%Land%")
    params.append(bool("Land" in (card["type_line"] or "")))
    if card.get("cmc") is not None:
        where += " AND abs(c.cmc - %s) <= %s"
        params.append(card["cmc"])
        params.append(SWAP_MV_BAND)
    #and the axis itself, as an EXCLUSION rather than a sort applied later.
    #this is the one the notes warned about: similarity finds the same EFFECT,
    #and the effect is what people voted salt on, so the neighbours of a salty
    #card are salty too and merely sorting them puts the least bad offender at
    #the top of a list of offenders. the same reasoning holds on every axis,
    #since a "cheaper" list whose best entry costs more is not cheaper at all.
    #a NULL fails the comparison and drops out, which is right: a card nobody
    #has priced or voted on cannot be shown to be an improvement
    here = card.get("price" if field == "price" else SWAP_COLUMNS[field])
    if here is None:
        return []
    where += " AND " + col + (" < %s" if axis["better"] == "lower" else " > %s")
    params.append(here)

    pairs_by_card, meta = {}, {}
    for ql in qlines:
        w = line_weight(ql["count"])
        rows = conn.execute("""
            SELECT l.oracle_id, l.line_text, 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim,
                   coalesce(s.count, 1) AS their_count,
                   c.name, c.type_line, c.mana_cost, c.cmc, c.image, c.image_back,
                   c.layout, c.scryfall_uri, c.edhrec_rank, c.released_at, c.salt,
                   c.price_usd, c.price_eur,
                   """ + price_col(currency) + """ AS price
            FROM lines l JOIN cards c ON c.oracle_id = l.oracle_id
            LEFT JOIN line_stats s ON s.line_text = l.line_text
            WHERE l.oracle_id <> %s AND NOT l.whole
              AND l.""" + EMBED_COL + """ IS NOT NULL""" + where + """
            ORDER BY l.""" + EMBED_COL + """ <=> %s
            LIMIT 200
        """, [ql["embedding"], card["oracle_id"]] + params + [ql["embedding"]]).fetchall()
        for m in rows:
            best = pairs_by_card.get(m["oracle_id"])
            #weighted BOTH ways for the ranking and the cut, raw for the number
            #on screen. one common line on either side is enough to make a
            #perfect match meaningless, so both sides have to earn it
            score = (m["sim"] * w * line_weight(m["their_count"]),
                     m["sim"], ql["line_text"], m["line_text"])
            if best is None or score[0] > best[0]:
                pairs_by_card[m["oracle_id"]] = score
                meta[m["oracle_id"]] = m

    out = []
    for oid, (weighted, raw, ours, theirs) in pairs_by_card.items():
        pct = mech_display(raw)
        if pct < SWAP_GATE or weighted < SWAP_PAIR_CUT:
            continue
        #every figure carried against the card LEAVING, which is the anchor
        #here in exactly the way the searched card is the anchor on /search
        row = swap_card_json(meta[oid], currency, anchor=card)
        row.update({"match": pct, "their_line": theirs, "our_line": ours})
        out.append(row)
    #ranked by the number printed on them, which is the promise the whole site
    #runs on. the axis is not a tiebreak here because it is already a gate:
    #everything in this list is a genuine improvement, so the only open
    #question left is which one does the job best
    out.sort(key=lambda c: -c["match"])
    return out[:SWAP_OFFER]


def read_axis():
    #the axis off the request, falling back to the default rather than
    #erroring: an unknown field is a stale link, not an attack, and the
    #tool has a sensible thing to do with one.
    #
    #a "goal" of "price:asc" is the same thing said in one field, which is what
    #the picker on the modes page sends. it has to be one control because the
    #choice is one choice: "cheaper" is a field AND a direction, and two
    #dropdowns would let somebody pick "price" and "newer" and mean nothing.
    #the pair is still accepted, because every link and form already sends it
    goal = request.values.get("goal", "")
    if goal.count(":") == 1:
        f, d = goal.split(":")
        if (f, d) in SWAP_AXES:
            return f, d
    field = request.values.get("axis", SWAP_DEFAULT[0])
    direction = request.values.get("dir", "")
    if (field, direction) not in SWAP_AXES:
        direction = SWAP_DEFAULT[1] if field == SWAP_DEFAULT[0] else ""
    if (field, direction) not in SWAP_AXES:
        return SWAP_DEFAULT
    return field, direction


def read_deck_ids(raw):
    #the deck the page is holding, back from the browser. validated as uuids
    #and capped, because it arrives as user input and goes into a uuid[] cast:
    #a bad value would be a 500 rather than a wrong answer, but a 500 is still
    #a page someone sees
    ids = []
    for s in (raw or [])[:DECK_MAX_CARDS]:
        try:
            ids.append(str(uuid.UUID(str(s))))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


@app.route("/deck/swap", methods=["POST"])
def deck_swap():
    #the same pasted list as /deck/read, walked card by card instead of read
    #in one go. nothing is stored here either: the page carries the deck in the
    #browser and every request states its own deck, so there is no session to
    #resume and nothing to clean up. that is the same promise the lens made,
    #and it is the reason this can stay a lens rather than becoming a builder
    text = request.form.get("list", "")
    field, direction = read_axis()
    ids, missing = parse_decklist(text)
    if not ids:
        return render_template("deck/hub.html", deck_count=len(precon_board()),
                               example=(precon_board() or [None])[0],
                               error=("None of those lines matched a card." if text.strip()
                                      else "Paste a decklist first."),
                               missing=missing, pasted=text[:DECK_MAX_CHARS])
    cur = read_currency()
    with pool.connection() as conn:
        cards = deck_swappable(conn, ids, cur)
        colors = deck_colors(conn, ids)
        #the whole deck, for the fold at the foot of the page. deciding whether
        #to cut a card means knowing what else is in there, and until now the
        #only way to look was the back button. the same partial /deck/view and
        #the precon pages draw, off the same function, so a deck being walked
        #and a deck being read show the same grid
        all_cards = deck_cards(conn, ids, cur)
    #flattened here rather than picked apart in the template: the page hands
    #the whole queue to the browser as json, and building that out of five
    #jinja map() filters was a second place for the field names to drift
    queue = []
    for c in swap_queue(cards, field, direction):
        #the same shape a candidate arrives in, so the card leaving is drawn by
        #the same code that draws the ones that could replace it. no anchor: it
        #IS the anchor, and a card compared against itself says nothing
        row = swap_card_json(c, cur)
        row["figure"] = swap_figure(c, field, cur) or ""
        queue.append(row)
    name, commander = deck_identity()
    return render_template("deck/swap.html", queue=queue, deck_ids=[str(i) for i in ids],
                           colors=colors, axis=field, direction=direction,
                           #the axis IS the chosen stat here, so the page inks
                           #the figure it is moving and greys the other three.
                           #never the badge: the match percent on a candidate is
                           #the gate it cleared, not the thing being improved
                           focus=focus_class(field),
                           goal=SWAP_AXES[(field, direction)]["goal"],
                           matched=len(ids), missing=missing, cur=cur,
                           deck_name=name, commander=commander, batch=SWAP_QUEUE,
                           cards=all_cards, section=DECK_SECTION,
                           pasted=text[:DECK_MAX_CHARS],
                           #the shelf key, so a finished session writes itself
                           #onto the deck it belongs to rather than looking for
                           #an entry under the list it happens to be holding
                           origin=request.form.get("origin", "")[:DECK_MAX_CHARS])


@app.route("/deck/swap/cards", methods=["POST"])
def deck_swap_cards():
    #one card's replacements, asked for as the user reaches it. computed on
    #demand rather than for the whole queue up front: twelve nearest neighbour
    #walks to open a page is most of a second of database for eleven cards the
    #user may never scroll to, and they can be fetched while the current one is
    #being read instead
    body = request.get_json(silent=True) or {}
    field, direction = read_axis()
    if (body.get("axis"), body.get("dir")) in SWAP_AXES:
        field, direction = body["axis"], body["dir"]
    deck_ids = read_deck_ids(body.get("deck"))
    try:
        oid = str(uuid.UUID(str(body.get("card"))))
    except (ValueError, AttributeError, TypeError):
        abort(400)
    colors = body.get("colors")
    if colors is not None:
        colors = "".join(ch for ch in str(colors).upper() if ch in "WUBRG")
    cur = read_currency()
    with pool.connection() as conn:
        #aliased c because price_col hands back a c-qualified column name, so
        #every query that reads a price has to call the table the same thing
        #price_usd and price_eur come along because price_in reads the raw
        #columns: this row is the ANCHOR every candidate's verdict is measured
        #against, so it has to answer the same questions a candidate does
        row = conn.execute("SELECT c.oracle_id, c.name, c.type_line, c.cmc, c.edhrec_rank, "
                           "c.released_at, c.salt, c.price_usd, c.price_eur, " + price_col(cur) +
                           " AS price FROM cards c WHERE c.oracle_id = %s",
                           (oid,)).fetchone()
        if row is None:
            abort(404)
        cards = swap_candidates(conn, dict(row), deck_ids, colors, field, direction,
                                currency=cur)
    #an empty list is a real answer here, not a miss, so it comes back as one
    #rather than as an error the page has to interpret
    return {"cards": cards, "gate": SWAP_GATE, "axis": field, "dir": direction}


def card_json(c, currency):
    #one dealt (or revisited) card the way the /unique frontend wants it.
    #layout and image_back are what let the page offer the rotate and
    #turn-over buttons
    price = price_label(c, currency)
    return {
        "oracle_id": str(c["oracle_id"]),
        "name": c["name"],
        "mana_cost": c["mana_cost"],
        "type_line": c["type_line"],
        "image": c["image"],
        "image_back": c["image_back"] or "",
        "sideways": sideways(c["layout"], c["type_line"]),
        "flip": c["layout"] == "flip",
        "scryfall_uri": c["scryfall_uri"],
        "price": price,
        "rank": rank_label(c["edhrec_rank"]),
        "salt": salt_label(c["salt"]),
        "age": age_label(c["released_at"]),
        "percent": int(round((c.get("blended_u") if c.get("blended_u") is not None else (c["uniqueness"] or 0)) * 100)),
        "unique_line": c["unique_line"] or "",
    }


@app.route("/unique/cards", methods=["POST"])
def unique_cards():
    #deals UNIQUE_PAGE random cards whose uniqueness clears the bar, skipping
    #ones the browser has already been shown. the filters ride in on the query
    #string like everywhere else, but the seen list arrives as a json body
    #because after enough dealing it outgrows what a url can carry. its a
    #random draw from everything that qualifies, not the top of a ranking, so
    #every press feels like a fresh pack
    filters = read_filters()
    body = request.get_json(silent=True) or {}
    seen = []
    #the browser caps its list at 2000, the [-4000:] is the server not
    #taking its word for it: newest entries win, a hand-rolled megalist
    #can't make the query chew through millions of uuids
    for s in body.get("seen", [])[-4000:]:
        #only real uuids get through to the query, anything else in
        #localStorage was not put there by us
        try:
            seen.append(str(uuid.UUID(str(s))))
        except ValueError:
            pass

    where, fparams = filter_sql(filters)
    #no uniqueness bar: the dealer works from whatever is left rather than
    #from a number anyone has to learn. the slider decides which KIND of
    #unique it is ranking on: rules-text isolation, tag-space isolation, or a
    #mix. cards with no searchable lines stay excluded, untagged cards count
    #as 0 on the concept side
    w = BLEND_WEIGHTS[read_blend()]
    blended = "((1 - %s) * c.uniqueness + %s * coalesce(c.concept_uniqueness, 0))"
    cond = """
        FROM cards c
        WHERE c.uniqueness IS NOT NULL
          AND NOT (c.oracle_id = ANY(%s::uuid[]))""" + where
    params = [seen] + fparams
    with pool.connection() as conn:
        remaining = conn.execute("SELECT count(*) AS n" + cond, params).fetchone()["n"]
        #the shortlist first, ids and scores only. picking from it here rather
        #than in sql keeps the band rule (see UNIQUE_BAND) in one readable
        #place, and costs a second round trip for one card's worth of columns
        shortlist = conn.execute("SELECT c.oracle_id, " + blended + " AS u" + cond +
                                 " ORDER BY u DESC LIMIT %s",
                                 [w, w] + params + [UNIQUE_WINDOW]).fetchall()
        picked = []
        if shortlist:
            best = shortlist[0]["u"]
            near = [r for r in shortlist if r["u"] >= best - UNIQUE_BAND]
            if len(near) < UNIQUE_MIN_POOL:
                #reach further down the list for company, but not past the
                #point where the extra cards stop being "the most unique
                #ones left". the best card always clears this itself, so the
                #pool can never come back empty
                near = [r for r in shortlist[:UNIQUE_MIN_POOL] if r["u"] >= best - UNIQUE_MAX_DROP]
            picked = random.sample(near, min(UNIQUE_PAGE, len(near)))
        rows = []
        if picked:
            rows = conn.execute("SELECT " + CARD_FIELDS + ", uniqueness, unique_line, " + blended +
                                " AS blended_u FROM cards c WHERE c.oracle_id = ANY(%s)",
                                [w, w, [r["oracle_id"] for r in picked]]).fetchall()

    cards = []
    cur = read_currency()
    for c in rows:
        cards.append(card_json(c, cur))
    #remaining counts whats left AFTER this deal, so the frontend knows when
    #the well is dry without another request
    return {"cards": cards, "remaining": remaining - len(cards)}


@app.route("/unique/card")
def unique_card():
    #one card the browser has already been dealt, looked up by id for the
    #back/forward history arrows on /unique. same shape as a fresh deal so
    #the frontend renders both identically. cards can vanish from the
    #database between visits (scryfall drops them, filters tighten), so
    #null just means "this history entry died"
    try:
        oid = str(uuid.UUID(request.args.get("id", "")))
    except ValueError:
        return {"card": None}
    with pool.connection() as conn:
        #the trail arrows show the same blended number a fresh deal would,
        #using the remembered slider position
        w = BLEND_WEIGHTS[read_blend()]
        c = conn.execute("SELECT " + CARD_FIELDS + """, uniqueness, unique_line,
                            ((1 - %s) * uniqueness + %s * coalesce(concept_uniqueness, 0)) AS blended_u
                          FROM cards WHERE oracle_id = %s""",
                         (w, w, oid)).fetchone()
    if c is None:
        return {"card": None}
    return {"card": card_json(c, read_currency())}


#the load more button on the results page calls this and gets json back. it
#receives the page's whole query string, so filters and picked lines apply
@app.route("/more")
def more():
    query = request.args.get("q", "")
    #fail-soft like every other url reader, a doctored offset shouldn't 500
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    card = find_card(query)
    if card is None:
        return {"results": [], "has_more": False, "next_band": None}
    card_lines, picked = build_lines(card, read_picked())
    #which band of weaker matches to page through, absent for the strong tier
    try:
        band = int(request.args["band"])
    except (KeyError, ValueError):
        band = None
    blend = read_blend()
    filters = read_filters()
    results, has_more, next_band = find_similar(card["oracle_id"], picked, filters, tier_cut(blend), read_sort(), offset,
                                                band=band, blend=BLEND_WEIGHTS[blend], currency=filters["cur"],
                                                dropped=read_dropped(), forced=read_forced(),
                                                anchor_price=price_in(card, filters["cur"]),
                                                anchor_rank=card["edhrec_rank"],
                                                anchor_salt=card["salt"],
                                                anchor_released=card["released_at"])
    return {"results": results, "has_more": has_more, "next_band": next_band}


#---- user feedback: "a card is missing" / "this card shouldn't be here" ----

def best_sim(conn, anchor_id, other_id, picked):
    #the calibrated percent the results page prints next to the other card.
    #the winning pair is chosen by WEIGHTED similarity, exactly like the
    #ranking (a bare max would disagree with the page: boots and greaves
    #share near-identical Equip lines at raw .99 that the idf weighting
    #buries), and the number returned is that pair's real similarity. None
    #means the other card has no searchable lines at all
    sql = """
        SELECT 1 - (a.""" + EMBED_COL + """ <=> b.""" + EMBED_COL + """) AS sim,
               coalesce(s.count, 1) AS count
        FROM lines a
        JOIN lines b ON b.oracle_id = %s AND NOT b.whole AND b.""" + EMBED_COL + """ IS NOT NULL
        LEFT JOIN line_stats s ON s.line_text = a.line_text
        WHERE a.oracle_id = %s AND NOT a.whole AND a.""" + EMBED_COL + """ IS NOT NULL
    """
    params = [other_id, anchor_id]
    if picked:
        sql += " AND a.line_text = ANY(%s)"
        params.append(list(picked))
    best = None
    for r in conn.execute(sql, params):
        weighted = line_weight(r["count"]) * r["sim"]
        if best is None or weighted > best[0]:
            best = (weighted, r["sim"])
    if best is None:
        return None
    return mech_display(best[1])


def filter_reasons(card, filters):
    #why the current filters hide this card, said in the user's language.
    #mirrors filter_sql condition by condition; an empty list means the
    #filters let the card through and something else explains its absence
    reasons = []
    if filters["colors"]:
        #the same three modes as filter_sql, each with its own words
        identity = set(card["color_identity"])
        picked = set(filters["colors"])
        shown = card["color_identity"] or "colorless"
        if filters["cmode"] == "exact" and identity != picked:
            reasons.append("its colour identity (" + shown + ") isn't exactly the colours you picked")
        elif filters["cmode"] == "include" and not picked <= identity:
            reasons.append("its colour identity (" + shown + ") doesn't include every colour you picked")
        elif filters["cmode"] == "atmost" and not identity <= picked:
            reasons.append("its colour identity (" + shown + ") doesn't fit the colours you picked")
    #the same currency the bounds filtered on, so the number quoted back is
    #the one the user was comparing against
    cur = filters.get("cur", "usd")
    price = price_in(card, cur)
    if (filters["pmin"] is not None or filters["pmax"] is not None) and price is None:
        reasons.append("it has no listed price, and any price filter hides unpriced cards")
    elif filters["pmin"] is not None and price < filters["pmin"]:
        reasons.append("its price (" + price_label(card, cur) + ") is under your minimum")
    elif filters["pmax"] is not None and price > filters["pmax"]:
        reasons.append("its price (" + price_label(card, cur) + ") is over your maximum")
    if filters["mvmin"] is not None and float(card["cmc"]) < filters["mvmin"]:
        reasons.append("its mana value (" + str(card["cmc"]) + ") is under your minimum")
    if filters["mvmax"] is not None and float(card["cmc"]) > filters["mvmax"]:
        reasons.append("its mana value (" + str(card["cmc"]) + ") is over your maximum")
    if filters["types"]:
        tl = (card["type_line"] or "").lower()
        if not any(t.lower() in tl for t in filters["types"]):
            reasons.append("its type line doesn't include " + " or ".join(filters["types"]))
    if filters["cmdr"]:
        #front face only, mirroring filter_sql: the back face can't lead a deck
        tl = (card["type_line"] or "").split("//")[0].lower()
        if "legendary" not in tl or "creature" not in tl:
            reasons.append("it can't be a commander and \"commanders only\" is on")
    if filters["gc"] and card["game_changer"]:
        reasons.append("it's a game changer and \"hide game changers\" is on")
    if not filters["illegal"] and not card["legal_commander"]:
        reasons.append("it isn't commander-legal, and those stay hidden unless \"include illegal\" is ticked")
    return reasons


@app.route("/feedback", methods=["POST"])
def feedback():
    #the report bar on the results page posts here. the page's whole query
    #string rides along exactly like /more does, so the report is judged
    #against the same anchor, picked lines, filters and cutoff the user was
    #actually looking at.
    #
    #two kinds: 'missing' (a good card that should have been in the results,
    #a future pairs.md entry) and 'misplaced' (a bad card that shouldn't be
    #here, with the user's reason in their own words, a future triplets.md
    #negative). nobody is asked to name a replacement card, most players
    #couldn't quote one on the spot. missing reports get diagnosed before
    #anything is stored: when a filter is what's hiding the card, the user
    #learns that on the spot and the review queue never hears about it,
    #because that's not the model's fault
    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "")
    if kind not in ("missing", "misplaced", "tag"):
        return {"ok": False, "stored": False, "msg": "That report didn't make sense to the server, sorry."}

    card = find_card(request.args.get("q", ""))
    if card is None:
        return {"ok": False, "stored": False, "msg": "Lost track of which card you searched, try reloading the page."}

    reason = str(body.get("reason", "")).strip()[:500]

    filters = read_filters()
    blend = read_blend()
    min_pct = tier_cut(blend)
    _, picked = build_lines(card, read_picked())
    dropped = read_dropped()

    #the ip is stored only as the day's one-way token, same as the visit
    #counter: enough to spot one source flooding reports within an hour,
    #nothing that survives as a real address.
    #
    #read BEFORE the connection is borrowed rather than inside it. the first
    #report of a day reaches todays_salt() through here, which borrows a
    #connection of its own, and the pool only holds four. four reports landing
    #together on a day boundary would each sit on one and wait for a fifth
    ip = visitor_token(client_ip())

    with pool.connection() as conn:
        #a gentle lid, there's no login so this is all the abuse control there
        #is. the window is 1 hour so the token rotating at midnight only ever
        #RESETS the lid, never carries a stale grudge, which is exactly what a
        #spam limiter should do
        recent = conn.execute("SELECT count(*) AS n FROM feedback WHERE ip = %s AND ip <> '' AND created_at > now() - interval '1 hour'",
                              (ip,)).fetchone()["n"]
        if recent >= 20:
            return {"ok": False, "stored": False, "msg": "That's a lot of reports for one hour. Thank you, but please come back later."}

        #which model's numbers this report is about, straight from the ingest's bookkeeping
        row = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
        model = row["value"] if row else ""
        snap = dict(filters)
        snap["min"] = min_pct
        snap["sort"] = read_sort()
        #the slider position changes what the numbers the user saw MEANT
        #(blended past detent 0), so it rides in the snapshot too
        snap["blend"] = blend
        #same reasoning for switched-off tags: a concept percent scored
        #against a reduced tag vector is not the one the full card would
        #give, and a report is unreadable later without knowing which
        if dropped:
            snap["notags"] = sorted(dropped)
        #scale marker: reports from before 2026-07-15 stored raw-cosine
        #percents, everything after stores calibrated display percents
        snap["cal"] = 1

        if kind == "missing":
            expected_name = str(body.get("expected", "")).strip()[:200]
            expected = find_card(expected_name) if expected_name else None
            if expected is None:
                return {"ok": False, "stored": False, "msg": 'Couldn\'t find a card called "' + expected_name + '", check the spelling?'}
            if expected["oracle_id"] == card["oracle_id"]:
                return {"ok": False, "stored": False, "msg": expected["name"] + " is the card you searched for."}
            expected_pct = best_sim(conn, card["oracle_id"], expected["oracle_id"], picked)
            if expected_pct is None:
                return {"ok": False, "stored": False, "msg": expected["name"] + " has no rules text the matcher can search, so it can never appear."}
            #the number quoted back is the one the page badges: past detent 0
            #that is (1-w) * mech + w * concept, and answering in pure mech
            #contradicts what the user is looking at (a 100% mech match badges
            #50% at the middle detent, and "it's already there at 100%" reads
            #as the site denying its own page). the database keeps the mech
            #percent, the snapshot keeps the concept half, so the review can
            #still take the blend apart
            w = BLEND_WEIGHTS[blend]
            shown_pct = expected_pct
            if w > 0:
                cpct = concept_between(conn, card["oracle_id"], expected["oracle_id"], dropped)
                snap["concept_pct"] = cpct
                shown_pct = int(round((1 - w) * expected_pct + w * cpct))
            full = conn.execute("""SELECT color_identity, price_usd, price_eur, cmc, type_line, game_changer, legal_commander, oracle_text
                                   FROM cards WHERE oracle_id = %s""", (expected["oracle_id"],)).fetchone()
            reasons = filter_reasons(full, filters)
            #the filter box is one compiled expression, so the honest check
            #is asking the database whether this card survives it
            if filters.get("fq_sql") and not conn.execute(
                    "SELECT 1 FROM cards c WHERE c.oracle_id = %s AND (" + filters["fq_sql"] + ")",
                    [expected["oracle_id"]] + filters["fq_params"]).fetchone():
                reasons.append("your filter query hides it")
            if reasons:
                return {"ok": True, "stored": False,
                        "msg": expected["name"] + " matches at " + str(shown_pct) + "%, but your filters hide it: " + "; ".join(reasons) + "."}
            if shown_pct >= min_pct:
                return {"ok": True, "stored": False,
                        "msg": expected["name"] + " is in the results at " + str(shown_pct) + "%, it may just be further down the list."}
            #a real gap: nothing hides the card, the model just scores it under the cutoff
            conn.execute("""INSERT INTO feedback (kind, anchor_id, anchor_name, expected_id, expected_name,
                                                  expected_pct, reason, picked_lines, filters, embed_model, ip)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                         (kind, card["oracle_id"], card["name"], expected["oracle_id"], expected["name"],
                          expected_pct, reason, "\n".join(picked), json.dumps(snap), model, ip))
            return {"ok": True, "stored": True,
                    "msg": "Thanks for the input. Reports like this grade the next model."}

        #tag: the line picker got an attribution wrong. WHICH WAY IT IS WRONG IS
        #NOT ASKED, it is looked up: the tag is either on the picked line right
        #now or it is not, and that decides whether the complaint is "you set
        #this aside and the line IS about it" or "you kept this and the line is
        #NOT about it". asking the user would be a second thing to get right,
        #and the answer is already in the database
        if kind == "tag":
            tag = str(body.get("tag", "")).strip()[:100]
            if not tag:
                return {"ok": False, "stored": False, "msg": "Pick which tag looks wrong first."}
            if not conn.execute("""SELECT 1 FROM card_tags WHERE oracle_id = %s AND tag = %s
                                   AND NOT inherited""", (card["oracle_id"], tag)).fetchone():
                return {"ok": False, "stored": False,
                        "msg": "That tag isn't on " + card["name"] + ", try reloading the page."}
            if not picked:
                return {"ok": False, "stored": False,
                        "msg": "Highlight the line you think this tag belongs to (or doesn't) first."}
            on_line = conn.execute("""
                SELECT 1 FROM line_tags lt JOIN lines l ON l.id = lt.line_id
                WHERE l.oracle_id = %s AND NOT l.whole AND l.line_text = ANY(%s) AND lt.tag = %s
            """, (card["oracle_id"], list(picked), tag)).fetchone() is not None
            snap["tag_was"] = "kept" if on_line else "aside"
            conn.execute("""INSERT INTO feedback (kind, anchor_id, anchor_name, tag, reason,
                                                  picked_lines, filters, embed_model, ip)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                         (kind, card["oracle_id"], card["name"], tag, reason,
                          "\n".join(picked), json.dumps(snap), model, ip))
            #lead with what the USER is claiming, not with what the picker
            #thinks. saying "the picker thinks that line IS about X" back to
            #someone who just told you it is not reads as the site arguing
            if on_line:
                said = "Logged: you say that line is NOT about " + tag + ", the picker kept it."
            else:
                said = "Logged: you say that line IS about " + tag + ", the picker set it aside."
            return {"ok": True, "stored": True,
                    "msg": said + " Disagreements like this become the labelled cards "
                           "the line picker is graded against."}

        #misplaced: the flagged card plus a few words on why it doesn't belong
        try:
            got_id = str(uuid.UUID(str(body.get("got_id", ""))))
        except ValueError:
            return {"ok": False, "stored": False, "msg": "Lost track of which result you flagged, try reloading the page."}
        got = conn.execute("SELECT oracle_id, name FROM cards WHERE oracle_id = %s", (got_id,)).fetchone()
        if got is None:
            return {"ok": False, "stored": False, "msg": "Lost track of which result you flagged, try reloading the page."}
        if not reason:
            return {"ok": False, "stored": False, "msg": "Say a few words about why it's a bad match first."}

        got_pct = best_sim(conn, card["oracle_id"], got["oracle_id"], picked)
        if blend > 0:
            #the badge the user flagged was blended, so keep the concept half
            #on file - the review needs it to route the report to an axis
            snap["concept_pct"] = concept_between(conn, card["oracle_id"], got["oracle_id"], dropped)
        conn.execute("""INSERT INTO feedback (kind, anchor_id, anchor_name, got_id, got_name,
                                              got_pct, reason, picked_lines, filters, embed_model, ip)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (kind, card["oracle_id"], card["name"], got["oracle_id"], got["name"],
                      got_pct, reason, "\n".join(picked), json.dumps(snap), model, ip))
        return {"ok": True, "stored": True,
                "msg": "Logged. " + got["name"] + " shows at " + str(got_pct) +
                       "% right now, and reports like this become the test cases the matcher is graded against."}


#---- the review side of the feedback loop ----

def admin_allowed():
    #no ADMIN_KEY in the environment means no admin pages anywhere, and a
    #wrong key 404s instead of 403 so the page doesn't admit it exists
    return ADMIN_KEY != "" and request.args.get("key", "") == ADMIN_KEY


def report_markdown(r, line_texts, n):
    #one accepted report in the shape pairs.md uses, ready to paste (the
    #separators mirror that file exactly). missing reports become should-match
    #entries (the anchor and the good card), misplaced reports become
    #should-NOT entries (the anchor, the bad card and the user's reason).
    #promotion into triplets.md happens by hand at review time. the anchor
    #quotes only the picked lines when the report came from a line-picked
    #search
    def q(lines):
        if not lines:
            return "`(card no longer in the database)`"
        return " + ".join("`" + t + "`" for t in lines)

    if r["picked_lines"]:
        anchor_lines = r["picked_lines"].split("\n")
    else:
        anchor_lines = line_texts.get(r["anchor_id"], [])
    day = r["created_at"].strftime("%Y-%m-%d")

    #a report filed with the slider away from mechanics was judging blended
    #numbers, and probably belongs in axis2.md rather than pairs.md. the
    #stored pcts stay mechanical either way, this note carries the rest
    mode = ""
    try:
        snap = json.loads(r["filters"] or "{}")
    except ValueError:
        snap = {}
    if snap.get("blend"):
        try:
            at = str(int(BLEND_WEIGHTS[int(snap["blend"])] * 100)) + "% concepts"
        except (ValueError, IndexError):
            at = "detent " + str(snap["blend"])
        mode = "; slider at " + at + " (user saw blended numbers"
        if "concept_pct" in snap:
            mode += ", concept score " + str(snap["concept_pct"]) + "%"
        mode += ") - consider axis2.md"

    #a tag report is not a pairs.md entry at all. it belongs in the LABELS dict
    #in finetune/exam_attribution.py, keyed by card name and LINE INDEX, so it
    #is emitted in that shape instead: the index the picked line actually has,
    #and which way the disagreement runs. the line index is what the eval reads,
    #and it is not stored on the report (the text is), so it is looked up here
    #a decklist line the parser could not match. it is not an eval entry at
    #all: nothing about the model went wrong, the line reader did, so it is
    #emitted as what it is, a list of shapes parse_decklist should have read
    if r["kind"] == "deckline":
        return "    " + repr(r["reason"] or "") + "  # " + r["anchor_name"] + "  (" + day + ")\n"

    if r["kind"] == "tag":
        idx = "?"
        for i, t in enumerate(line_texts.get(r["anchor_id"], [])):
            if anchor_lines and t == anchor_lines[0]:
                idx = str(i)
                break
        try:
            was = json.loads(r["filters"] or "{}").get("tag_was", "?")
        except ValueError:
            was = "?"
        verb = "should NOT be on" if was == "kept" else "SHOULD be on"
        out = "    #" + r["anchor_name"] + " line " + idx + ": " + r["tag"] + " " + verb + " it"
        out += "  (user report " + day + ")\n"
        if r["reason"]:
            out += "    #  they said: " + r["reason"] + "\n"
        out += '    "' + r["anchor_name"] + '": {' + idx + ": {...}},  #" + r["tag"] + "\n"
        return out

    out = str(n) + ".\n"
    out += "    **Anchor:** " + r["anchor_name"] + " - " + q(anchor_lines) + "\n"
    if r["kind"] == "misplaced":
        out += "    **NOT:** " + (r["got_name"] or "?") + " - " + q(line_texts.get(r["got_id"], [])) + "\n"
        out += "    *user report " + day + "; the flagged card showed at " + str(r["got_pct"]) + "% mech" + mode + "; reason: " + r["reason"] + "*\n"
    else:
        out += "    **Match:** " + (r["expected_name"] or "?") + " - " + q(line_texts.get(r["expected_id"], [])) + "\n"
        note = "user report " + day + "; scored " + str(r["expected_pct"]) + "% mech against the cutoff" + mode
        if r["reason"]:
            note += "; reason: " + r["reason"]
        out += "    *" + note + "*\n"
    return out


@app.route("/admin")
def admin():
    if not admin_allowed():
        abort(404)
    with pool.connection() as conn:
        rows = conn.execute("""SELECT * FROM feedback WHERE status IN ('pending', 'accepted')
                               ORDER BY created_at DESC""").fetchall()
        #one round trip for every card picture and line text the page shows
        ids = set()
        for r in rows:
            ids.add(r["anchor_id"])
            if r["expected_id"]:
                ids.add(r["expected_id"])
            if r["got_id"]:
                ids.add(r["got_id"])
        info = {}
        line_texts = {}
        if ids:
            for c in conn.execute("SELECT oracle_id, name, image FROM cards WHERE oracle_id = ANY(%s)", (list(ids),)):
                info[c["oracle_id"]] = c
            for l in conn.execute("SELECT oracle_id, line_text FROM lines WHERE oracle_id = ANY(%s) AND NOT whole", (list(ids),)):
                line_texts.setdefault(l["oracle_id"], []).append(l["line_text"])

        #daily unique visitors. today is still accumulating in visit_seen, past
        #days are the frozen integer counts, so the two are read separately and
        #stitched newest-first
        today = _utc_day()
        live = conn.execute("SELECT count(*) AS n FROM visit_seen WHERE day = %s", (today,)).fetchone()["n"]
        usage = [{"day": today.isoformat(), "uniques": live, "today": True}]
        for u in conn.execute("SELECT day, uniques FROM visit_daily ORDER BY day DESC LIMIT 60"):
            usage.append({"day": u["day"].isoformat(), "uniques": u["uniques"], "today": False})

    def card_bit(role, oid, name, pct):
        c = info.get(oid)
        return {"role": role, "name": name, "image": c["image"] if c else "", "pct": pct}

    pending = []
    accepted = []
    triplet_md = []
    pair_md = []
    tag_md = []
    deck_md = []
    for r in rows:
        cards = [card_bit("anchor (searched)", r["anchor_id"], r["anchor_name"], None)]
        if r["expected_id"]:
            cards.append(card_bit("should appear", r["expected_id"], r["expected_name"], r["expected_pct"]))
        if r["got_id"]:
            cards.append(card_bit("shouldn't be here", r["got_id"], r["got_name"], r["got_pct"]))
        #a tag report has no second card, its subject is a slug and a direction.
        #the direction was recorded at report time, because the attribution it
        #describes can be rebuilt before anyone reviews it
        tag_was = ""
        if r["kind"] == "tag":
            try:
                tag_was = json.loads(r["filters"] or "{}").get("tag_was", "")
            except ValueError:
                tag_was = ""
        view = {
            "id": r["id"], "kind": r["kind"], "cards": cards, "reason": r["reason"],
            "created": r["created_at"].strftime("%Y-%m-%d %H:%M"),
            "picked": r["picked_lines"].replace("\n", "  |  "),
            #a short prefix of the day token, enough to eyeball two reports as
            #the same source within a day, not a real address. the length check
            #is what makes that true rather than nearly true: a token is 64
            #characters, and the first twelve of anything SHORTER is most of an
            #ip, printed under the word "token"
            "filters": r["filters"], "model": r["embed_model"],
            "ip": (r["ip"] or "")[:12] if len(r["ip"] or "") == 64 else "",
            "tag": r["tag"], "tag_was": tag_was,
        }
        if r["status"] == "pending":
            pending.append(view)
        else:
            accepted.append(view)
            if r["kind"] == "tag":
                tag_md.append(report_markdown(r, line_texts, len(tag_md) + 1))
            elif r["kind"] == "deckline":
                deck_md.append(report_markdown(r, line_texts, len(deck_md) + 1))
            elif r["kind"] == "misplaced":
                triplet_md.append(report_markdown(r, line_texts, len(triplet_md) + 1))
            else:
                pair_md.append(report_markdown(r, line_texts, len(pair_md) + 1))

    return render_template("admin.html", key=ADMIN_KEY, pending=pending, accepted=accepted,
                           triplet_md="\n".join(triplet_md), pair_md="\n".join(pair_md),
                           tag_md="\n".join(tag_md), deck_md="\n".join(deck_md), usage=usage)


@app.route("/admin/act", methods=["POST"])
def admin_act():
    if not admin_allowed():
        abort(404)
    try:
        fid = int(request.form.get("id", ""))
    except ValueError:
        abort(400)
    action = request.form.get("action", "")
    #archived is where accepted reports go once they've been copied into the eval files
    if action not in ("accepted", "rejected", "archived", "pending"):
        abort(400)
    with pool.connection() as conn:
        conn.execute("UPDATE feedback SET status = %s WHERE id = %s", (action, fid))
    return redirect("/admin?key=" + ADMIN_KEY)


#the search bar calls this while you type to fill the suggestion dropdown.
#names that start with what you typed come first, then names with it anywhere,
#then trigram matches to catch typos. one query, tiered like find_card: the
#substring tiers read alphabetically, the fuzzy tier closest-first (its
#alphabetical CASE key is NULL, which sorts after every real name). this is
#the hottest route on the site, it fires on every pause in typing
@app.route("/suggest")
def suggest():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return {"names": []}
    p, s = q + "%", "%" + q + "%"
    names = []
    with pool.connection() as conn:
        for row in conn.execute("""
            SELECT name,
                   CASE WHEN name ILIKE %s THEN 0
                        WHEN name ILIKE %s THEN 1
                        ELSE 2 END AS tier
            FROM cards
            WHERE name ILIKE %s OR name ILIKE %s OR name %% %s
            ORDER BY tier, CASE WHEN name ILIKE %s THEN name END, name <-> %s, name
            LIMIT 8
        """, (p, s, p, s, q, s, q)):
            if row["name"] not in names:  #the odd duplicated name collapses to one entry
                names.append(row["name"])
    return {"names": names}


#---- wiring ----
#down here rather than beside the imports, because both of these reach back
#into names this module defines: the visit counter's PAGE_ENDPOINTS are this
#file's endpoints, and the sitemap reads the precon board out of it. by this
#line everything they ask for exists.
#
#the counter goes on after force_canonical_host above, which is the order it
#ran in before it moved out: a request that is about to be 301'd to the
#canonical host should not be counted at its wrong-host address
visitors.register(app)
app.register_blueprint(meta_bp)


if __name__ == "__main__":
    app.run(debug=True)
