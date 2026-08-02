#the actual website. the embeddings live in the database and pgvector does the
#similarity math right where the data is, so this process stays tiny, holds no
#matrix in memory and never touches torch

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
import threading
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
import mirror
from mirror import (REMINDER_KEYWORDS, reminder_is_the_rule, clean_line, line_weight,
                    EMBED_COLUMNS, embed_column, EMBED_COL,
                    concept_display, concept_raw_gate, mech_display)
#who a visitor is for a day, without keeping anything that says who they are.
#the report limiter and the import limiter identify people through this too
import visitors
from visitors import client_ip, visitor_token, _utc_day
from views.meta import bp as meta_bp

#python reads its mime table from the HOST: linux says text/javascript, a
#windows box reads the registry and plenty answer text/plain. <script
#type="module"> is strictly mime checked per spec, so a browser hard refuses
#text/plain and renders nothing. broken on a windows dev box, fine on railway
mimetypes.add_type("text/javascript", ".js")

app = Flask(__name__)

#railway terminates tls one proxy in front, so without this flask believes every
#request was plain http on an internal hostname. the canonical and og:url tags
#embed request.url_root, and those must say https on the real domain
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

#unset means no redirect, so this ships safely before dns is ready. only GET/HEAD
#move, and railway's healthcheck host is left alone or the deploy fails its check
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

#a year is safe only because static_url below stamps a content hash onto every
#url the templates emit
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 365

#checked by werkzeug BEFORE it reads the stream. DECK_MAX_CHARS looks like it
#does this and does not: it trims after request.form has parsed the whole body
#into memory, so the paste box is capped and the process is not.
#1mb because /unique/cards posts a seen list of up to 4000 uuids (~170kb) and the
#paste box takes 60000 chars. a 5mb paste gets a 413 without being read
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

_static_hash = {}


@app.template_global()
def static_url(filename):
    #memoised against the file's MTIME AND SIZE, never its name alone: on the
    #name, an edited file keeps the hash it had at startup and the page goes on
    #emitting ?v=<old> behind a year-long cache, so the fix reaches nobody. it
    #only bites in development, where it is hardest to notice
    path = os.path.join(app.static_folder, filename)
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    hit = _static_hash.get(filename)
    if hit is None or hit[0] != stamp:
        with open(path, "rb") as f:
            v = hashlib.md5(f.read()).hexdigest()[:8]
        _static_hash[filename] = (stamp, v)
    return url_for("static", filename=filename) + "?v=" + _static_hash[filename][1]


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
#and this token -> cache-busted url map is what it renders from
_mana_urls = {"stamp": None, "map": {}}


@app.template_global()
def mana_urls():
    #memoised against the FOLDER for the same reason static_url stats its file:
    #built once, the map pins every symbol to the hash it had then.
    #scandir hands back sizes and mtimes with the names, so the check is one
    #directory walk rather than a stat per file
    folder = os.path.join(app.static_folder, "symbols")
    with os.scandir(folder) as entries:
        stamp = tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                             for e in entries if e.name.endswith(".svg")))
    if _mana_urls["stamp"] != stamp:
        _mana_urls["map"] = {name[:-4]: static_url("symbols/" + name)
                             for name, _, _ in stamp}
        _mana_urls["stamp"] = stamp
    return _mana_urls["map"]

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
    #a 'tag' report's subject is a slug rather than a second card, so it needs a
    #column the CREATE above does not carry. an ALTER here as well as in
    #schema.sql, because a database the ingest has never touched only gets what
    #this block asks for. without it /feedback 500s on a tag report and /admin
    #500s reading the column back
    _conn.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS tag text NOT NULL DEFAULT ''")
    #also in schema.sql, and also here because railway only deploys web/. what
    #each holds is at todays_salt/count_visit below
    _conn.execute("CREATE TABLE IF NOT EXISTS visit_salt (day date PRIMARY KEY, salt text NOT NULL)")
    _conn.execute("""CREATE TABLE IF NOT EXISTS visit_seen (
        day   date NOT NULL,
        token text NOT NULL,
        PRIMARY KEY (day, token)
    )""")
    _conn.execute("CREATE TABLE IF NOT EXISTS visit_daily (day date PRIMARY KEY, uniques int NOT NULL)")
    #/privacy says an ip address is never stored, so any row still holding one has
    #to go. LENGTH tells them apart with nothing left over: a token is a sha256
    #hex digest, exactly 64 characters, and no address of either family reaches
    #that. the rate limit only looks an hour back, so clearing them costs nothing.
    #here as well as in schema.sql, so it lands on the next deploy rather than
    #waiting for an ingest. after the first run it matches no rows
    _conn.execute("UPDATE feedback SET ip = '' WHERE ip <> '' AND length(ip) <> 64")

#the review page at /admin only exists when this is set in the environment
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

#ko-fi hosts the payment side entirely, so no money, card details or account ever
#touch this server. not an env var: a public url that never changes
KOFI_URL = "https://ko-fi.com/ballchinian"

#a real number is the persuasion: "support us" asks to be trusted, "£10 a month"
#can be checked against the bill
RUNNING_COST = "about £10 a month"

#the display columns the frontend needs, so every query grabs the same set
CARD_FIELDS = "oracle_id, name, mana_cost, type_line, oracle_text, image, scryfall_uri, price_usd, price_eur, layout, image_back, edhrec_rank, salt, released_at"

#the choices in the type filter dropdown. also acts as a whitelist so
#nothing weird from the url ends up inside a LIKE pattern
CARD_TYPES = ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land"]

#the /unique page deals this many cards per request. one at a time, its the
#counterpart to scryfall's random card button
UNIQUE_PAGE = 1

#the window is RELATIVE: the draw happens among cards within UNIQUE_BAND of
#whatever the best available one scores. a fixed "top 100 unseen" works only
#while the pool is deep, and with filters on the hundredth card sits miles below
#the first, so a 25% follows a 3%.
#
#the two bounds pull against each other. MIN_POOL widens a thin band, so the page
#is not one running order every visitor walks. MAX_DROP caps that widening: the
#top of the concepts axis is one card at 100, then 83, 81, then a crowd at 67, and
#an unbounded "top 25" there deals a 67 and a 100 in the same breath
UNIQUE_BAND = 0.05
UNIQUE_MIN_POOL = 25
UNIQUE_MAX_DROP = 0.08
UNIQUE_WINDOW = 80


#how the two axes are weighed against each other: results are ordered by
#(1-BLEND) * mech percent + BLEND * concept percent, and the badge shows that
#same number, so the list always reads in descending order of what is printed
#on it.
#
#an even blend beat every other position of the slider this replaced, including
#both pure ends, so the choice never needed making. see web/history.md
BLEND = 0.5


#---- the anchor's side of the concept axis ----

#the searched card's tag vector, what every axis-2 query scores against.
#dropping a tag has to drop the inherited rows that only existed because of it,
#so the kept set is rebuilt the way ingest/tags.py built it: the tags a human
#typed, minus the dropped ones, then climb the tree.
#
#the NORM is recomputed over whatever survived. reusing the baked
#card_tag_norms row puts a shrunken numerator over a full-card denominator and
#deflates every score, moving the cutoff without moving the calibration. with
#nothing dropped it returns the baked norm to the digit
#the line -> tag attribution, at 94% precision / 82% recall.
#
#ON by default rather than switched on by an env var, which disappears the first
#time one gets reset, silently, with the site still returning 200s. LINE_TAGS=0
#is the kill switch if the attribution regresses.
#
#with it off every path below falls through to the fallbacks already written for
#a database whose line_tags was never built: picking a line moves the rules-text
#side only, and the concepts side reads the whole card
LINE_TAGS = os.environ.get("LINE_TAGS", "1").strip().lower() not in ("0", "false", "off", "no", "")

@app.context_processor
def feature_flags():
    #deck_min rides along because the paste box and the reading both quote the
    #floor, and the hub renders from two places with different arguments: passed
    #by hand, one of them eventually says a stale number
    #the axes ride along for the same reason: every deckways row pointing at
    #/deck/swap draws the picker, and a caller passing them by hand can forget
    return {"line_tags_on": LINE_TAGS, "kofi_url": KOFI_URL, "running_cost": RUNNING_COST,
            "deck_min": DECK_MIN_FOR_RANK, "swap_axes": SWAP_AXES,
            "swap_default": SWAP_DEFAULT}


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
    #an empty result means one of TWO things, and card_has_attribution is what
    #tells them apart. either the attribution has never run here, and falling
    #back to the whole card beats silently muting the concept axis on every
    #search. or the picked line genuinely is not about anything, the normal state
    #of a keyword line: Gishath's "Vigilance, trample, haste" owns none of its
    #card's seven tags.
    #in that second case find_similar reads the empty norm and ranks on rules
    #text alone, which is what picking a keyword line is asking for
    if picked and not rows and not card_has_attribution(conn, oracle_id):
        return anchor_vector(conn, oracle_id, dropped)
    tags = [r["tag"] for r in rows]
    weights = [r["weight"] for r in rows]
    norm = math.sqrt(sum(w * w for w in weights))
    return tags, weights, norm


def anchor_chips(conn, oracle_id, dropped, picked=(), forced=()):
    #the tags a human TYPED on this card, rarest first. inherited ancestors stay
    #out: dropping the child takes the parent with it in anchor_vector anyway.
    #each chip carries WHY it is on or off. "off" is a tag the user clicked,
    #"aside" is one the picked lines simply aren't about
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
        #an empty set is a REAL answer: a keyword line owns no tags, so setting
        #every chip aside is right for it. falling back only when the attribution
        #has never run here, or Gishath's "Vigilance, trample, haste" leaves all
        #seven dinosaur tags lit as though they were about keywords
        if not on_lines and not card_has_attribution(conn, oracle_id):
            on_lines = None
    chips = []
    for r in rows:
        if r["tag"] in dropped:
            state = "off"
        elif on_lines is not None and r["tag"] not in on_lines:
            #"kept" counts like any live tag, it just wears its own look, so the
            #page shows the picker's guess and the correction to it
            state = "kept" if r["tag"] in forced else "aside"
        else:
            state = "on"
        chips.append({"tag": r["tag"], "description": r["description"], "state": state})
    return chips


def concept_between(conn, oracle_a, oracle_b, dropped=(), picked=(), forced=()):
    #EVERY control that narrowed the anchor's vector on the page applies here
    #too: dropped tags, picked lines, tags forced back on. the dropped tags alone
    #answered a line-picked search with a percent off the card's FULL tag set, a
    #number the page never printed.
    #
    #NONE AND 0 ARE DIFFERENT ANSWERS. none means the axis sat the round out for
    #want of an anchor vector, which is what a keyword line leaves behind, and
    #find_similar badges on rules text alone in that case: blending a zero in
    #would answer 50% about a card the page badged 100%. 0 means the axis is in
    #play and this card shares none of the anchor's concepts
    tags, weights, norm = anchor_vector(conn, oracle_a, dropped, picked, forced)
    if not tags:
        return None
    other = conn.execute("SELECT norm FROM card_tag_norms WHERE oracle_id = %s", (oracle_b,)).fetchone()
    if other is None:
        return 0
    shared = conn.execute("""
        SELECT coalesce(sum(a.weight * cb.weight), 0) AS s
        FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
        JOIN card_tags cb ON cb.tag = a.tag AND cb.oracle_id = %s
    """, (tags, weights, oracle_b)).fetchone()["s"]
    return concept_display(shared / (norm * other["norm"]))


def find_card(query):
    #one query instead of four round trips: every way a name can match becomes a
    #tier and the best-tiered card wins. inside the substring tiers ALPHABETICAL
    #order decides, because trigram closeness favours short names and "delver"
    #must find Delver of Secrets, not Delver's Torch. the fuzzy tier goes closest
    #first, its alphabetical CASE key being NULL, which sorts after every real
    #name. the % operator means "similar enough to bother", so garbage queries
    #still return nothing. %% because psycopg uses % for parameters
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
    #how long ago this card was first printed, the fourth number on the row
    #under a card, and what the date sorts reorder the page by.
    #
    #the word "years" is not decoration. a bare "12.4" sitting between a price
    #and a #rank has to say what kind of number it is before it says anything
    #else, which is the same reason the salt figure wears a mark.
    #
    #released_at is scryfall's EARLIEST printing, so a reprint does not make an
    #old card new, and a deck stuffed with reprints still reads old. no date
    #shows nothing at all, like an unpriced or unvoted card: absent is not zero
    if released is None:
        return ""
    return "%.1f years" % ((datetime.date.today() - released).days / YEAR_DAYS)


CURRENCY_SIGNS = {"usd": "$", "eur": "€", "gbp": "£"}

CURRENCY_LABELS = [("usd", "$ dollars"), ("eur", "€ euros"), ("gbp", "£ pounds (approx.)")]

#pounds are DERIVED, not sourced: scryfall quotes dollars and euros only, so the
#gbp figure is each known price converted and averaged, which is why the label
#says approximate. the rates are the ecb's dailies via frankfurter.app, and the
#seeds below hold whenever the fetch fails, so an outage cannot break a page
#the same identification on EVERY outbound request this process makes: both deck
#importers and the rate fetch, which frankfurter refuses without one. up here
#rather than beside the importers because the rate fetch needs it first
IMPORT_AGENT = "Delvefall/1.0 (+https://delvefall.com)"

_gbp_rates = {"usd": 0.74, "eur": 0.86, "at": 0.0}


def _fetch_gbp_rates():
    #THE AGENT IS THE WHOLE REQUEST. sent with urllib's default, frankfurter
    #answers 403, so this had never once succeeded: every pound price the site
    #ever printed came from the seeds. the except swallows it and the seeds are
    #close enough to look right (0.74 against a real 0.7526, about 1.7% light),
    #so the failure was invisible
    req = urllib.request.Request("https://api.frankfurter.app/latest?from=GBP&to=USD,EUR",
                                 headers={"User-Agent": IMPORT_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            rates = json.load(r)["rates"]
        _gbp_rates["usd"] = 1.0 / rates["USD"]
        _gbp_rates["eur"] = 1.0 / rates["EUR"]
    except Exception:
        pass


def gbp_rates():
    #NOBODY WAITS ON THIS. the refresh is a background thread and the caller gets
    #whatever is already in hand: yesterday's rates, or the seeds on a process's
    #first call. inline, one visitor a day pays up to three seconds for a number
    #that moves by a fraction of a penny.
    #
    #the CLOCK MOVES BEFORE THE WORK STARTS, which does two jobs: a dead rate api
    #is retried daily rather than per request, and only one thread is ever started
    #per day however many requests arrive together
    now = time.time()
    if now - _gbp_rates["at"] > 60 * 60 * 24:
        _gbp_rates["at"] = now
        threading.Thread(target=_fetch_gbp_rates, daemon=True).start()
    return _gbp_rates["usd"], _gbp_rates["eur"]


def price_col(currency):
    #dollars and euros are real columns, pounds are computed on the spot. the
    #COALESCE PAIR averages without a CASE: both prices known, each side is one
    #of them; one known, both collapse to it; neither, the whole thing is NULL,
    #exactly how the real columns behave for an unpriced card.
    #the rates are our own floats, never user input, so this interpolation is safe
    if currency == "gbp":
        ru, re_ = gbp_rates()
        u = "c.price_usd * " + str(round(ru, 6))
        e = "c.price_eur * " + str(round(re_, 6))
        return "((coalesce(" + u + ", " + e + ") + coalesce(" + e + ", " + u + ")) / 2)"
    return "c.price_usd" if currency == "usd" else "c.price_eur"


def price_in(c, currency):
    #the python twin of price_col, for code holding the row rather than a query
    if currency == "gbp":
        ru, re_ = gbp_rates()
        known = [float(c[col]) * rate for col, rate in (("price_usd", ru), ("price_eur", re_))
                 if c[col] is not None]
        return sum(known) / len(known) if known else None
    p = c["price_usd"] if currency == "usd" else c["price_eur"]
    return None if p is None else float(p)


def price_label(c, currency):
    #ALWAYS two decimal places: printing the stored number as it comes back
    #writes "$0.2" for a twenty cent card, which is what str() does to a Decimal
    #ending in a zero
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
        #the end of the tokens is a REAL place to be standing: a "-" recurses
        #straight back in here for the thing it negates, so a box ending in one
        #(every half typed negation) walked off the end and 500'd the search
        if pos[0] >= len(tokens):
            return None
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
    #an inverted range matches nothing, and an empty page with no explanation
    #reads as the site breaking rather than as the bounds disagreeing. the filter
    #still applies exactly as typed, the page just says why nothing can match
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
    #most visitors are commander players, so cards that arent legal stay hidden
    #unless this asks for them
    f["illegal"] = request.args.get("illegal") == "1"
    #which currency the price bounds (and the filter box's bare price) mean
    f["cur"] = read_currency()
    #the filter box rides in as fq, compiled here so every page that reads
    #filters understands it. it stacks with the widgets (both apply)
    f["fq_sql"], f["fq_params"] = compile_fq(request.args.get("fq", ""), f["cur"])
    return f


def read_number(name, label, errors):
    #a number box's value, None when empty. junk (a doctored url, pasted text)
    #is named on the page rather than dropped, so a filter that "didn't work"
    #says what was ignored
    s = request.args.get(name, "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        errors.append('"' + s + '" is not a number, so your ' + label + ' was ignored')
        return None


#where the strong tier ends, in calibrated display units. nothing on the page
#exposes it: everything under the cut pages in behind the weaker-matches button
#rather than joining the sorts, which is what keeps the price sorts meaningful.
#
#70 and not 80 because the badge is an AVERAGE of two axes, and averages rarely
#reach 80. either pure axis alone would sit at 80, which is where the model's
#real quality boundary is
TIER_CUT = 70


#the sort is a field plus a direction rather than one entry per combination. as
#one list it runs to nine options with half of them the same idea backwards:
#"price low to high" and "price high to low" are not two things to choose
#between, they are one thing and a switch. scryfall splits them the same way,
#which is the control this audience already knows.
#
#asc/desc read as the concept named in the label, not as the column underneath:
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


#which figure on a card the page is ABOUT, as the class its container wears. a
#sort changes only which of the five readings is in ink, never which readings a
#card carries.
#
#BOTH vocabularies land here on purpose: /search calls the age field "released"
#and the precon board calls the same metric "age", and the page rendering them
#should not have to know that
FOCUS_CLASS = {
    "best": "focus-badge", "original": "focus-badge",
    "price": "focus-price",
    "played": "focus-rank",
    "released": "focus-age", "age": "focus-age",
    "salt": "focus-salt",
}


def focus_class(key):
    #an unknown key focuses NOTHING, leaving every figure grey, which is the
    #honest rendering of a grid with no chosen stat rather than a broken fallback
    return FOCUS_CLASS.get(key, "")


def read_currency():
    #usd, eur or gbp, for every price the site shows, filters and sorts on.
    #the url wins, then the remembered cookie, then dollars. scryfall only
    #prices the first two; pounds are derived (see gbp_rates)
    cur = request.args.get("cur")
    if cur is None:
        cur = request.cookies.get("cur", "usd")
    return cur if cur in CURRENCY_SIGNS else "usd"


@app.before_request
def retry_calibration():
    #load_calibration runs once at import, so a worker that booted while the
    #database was unreachable would serve the SEED maps until the next deploy.
    #one boolean per request until it succeeds. the readers look the maps up on
    #the module at call time, so a late load reaches the imported names too
    if not mirror.CALIBRATED:
        mirror.load_calibration()


@app.after_request
def remember_currency(resp):
    #a COOKIE rather than localStorage, and it has to be: every price here is
    #rendered by the SERVER, and the pound figure is derived per card from
    #whichever of the two prices that card carries, so it is not the dollar total
    #times a rate and cannot be recomputed in the browser. localStorage never
    #reaches the server, so the board would paint in dollars and correct itself.
    #the one preference the server needs to know, hence the one in a cookie
    cur = request.args.get("cur")
    if cur in CURRENCY_SIGNS:
        resp.set_cookie("cur", cur, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


def currency_urls():
    #built off the request's own args, so a page need not know its own url and
    #every other control survives the flip.
    #
    #items(multi=True) and NOT to_dict(), which keeps one value per name: the
    #colour and type boxes send theirs repeatedly, so colors=W&colors=U would come
    #back as colors=W and the flip would drop every colour but the first
    out = {}
    keep = [(k, v) for k, v in request.args.items(multi=True) if k != "cur"]
    for code in CURRENCY_SIGNS:
        out[code] = request.path + "?" + urlencode(keep + [("cur", code)])
    return out


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


#salt is judged on the GAP alone, no ratio test: it is an average of votes
#rather than an amount of something, so 0.1 against 0.2 is double and means
#nothing. the pool's whole interquartile range is 0.31, so 0.4 is a gap wider
#than the middle half of every card in the game
SALT_BAND = 0.1
SALT_MUCH_GAP = 0.4

#a year is the unit two cards are contemporary in: four sets a year means a six
#month gap says nothing. no MUCH gap, there being no colour here to earn
AGE_BAND_DAYS = 365.25


def salt_verdict(salt, anchor):
    #four states like the price verdict: a small move gets the arrow alone, a big
    #one earns colour, green for less salt, matching money. the play-rate arrow
    #stays colourless because more played is not better or worse, where more
    #annoying is
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
    #TWO states where the other three have four: price and salt each have a
    #better end, so a big move there earns colour, where older is no better than
    #newer. the rule the guide states is that colour means one end is better
    if anchor is None or released is None:
        return ""
    diff = (anchor - released).days
    if abs(diff) < AGE_BAND_DAYS:
        return ""
    #the anchor is the LATER date, so this card was printed first
    return "older" if diff > 0 else "newer"


#everything under the cut splits into 10 point bands, one on the page at a time,
#so a sort inside it runs among cards that match about as well as each other. as
#one undivided pile, the cheapest card in it is a 0% match
WEAK_BAND = 10


def band_of(score):
    return int(score // WEAK_BAND) * WEAK_BAND


#plain english rather than a percent range: nobody reading "60 to 69%" knows
#whether that is nearly good or hopeless. past the ladder every step is "weaker
#again", by which point the only honest thing to say is that it keeps going down
BAND_WORDS = ("weaker matches", "weaker still", "weaker again")


def band_words(step):
    return BAND_WORDS[min(step, len(BAND_WORDS)) - 1]


def find_similar(oracle_id, picked, filters, min_pct, sort, offset=0, how_many=20, band=None,
                 currency="usd", dropped=(), forced=(), anchor_price=None, anchor_rank=None,
                 anchor_salt=None, anchor_released=None):
    #every candidate keeps ALL its matching line pairs, not just the best, so
    #results can show "+2 more matching lines".
    #
    #cards split around min_pct, and everything under it waits in 10 point bands.
    #band=None is the strong tier, an int is that band's lower edge
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
        #one line's walk through the hnsw index, ~10-20ms where the exact scan it
        #replaced measured 200-250ms. <=> is cosine distance, so similarity is 1
        #minus it.
        #
        #ONE QUERY PER LINE. the obvious "one big query" (the anchor's lines
        #CROSS JOIN LATERAL the scan) measured 2.3x SLOWER: as a lateral outer
        #column, postgres detoasts the ~3kb vector again for every one of the 61k
        #distance evaluations, where a bound parameter is detoasted once.
        #
        #NO l.id tiebreak on the ORDER BY: a second sort key pushes the planner
        #off the index and back onto the full scan. the 400 cut is deterministic
        #anyway, since only the ingest changes the graph
        with pool.connection() as c:
            return c.execute("""
                SELECT l.oracle_id, l.line_text, l.face, 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim, """ + pcol + """ AS price, c.edhrec_rank, c.released_at, c.salt
                FROM lines l JOIN cards c ON c.oracle_id = l.oracle_id
                WHERE l.oracle_id <> %s AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL""" + where + """
                ORDER BY l.""" + EMBED_COL + """ <=> %s
                LIMIT 400
            """, [ql["embedding"], oracle_id] + fparams + [ql["embedding"]]).fetchall()

    #the scans run side by side, each on its own pooled connection. the main
    #thread holds NO connection while they do: holding one while workers wait on
    #the pool is how a pool deadlocks. 3 workers keeps one free for /suggest with
    #two searches in flight, and map preserves line order
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

        #the badge is (1-BLEND) * mech + BLEND * concept and the cutoff cuts on
        #that SAME number, so nothing under it shows above the fold whichever
        #axis a card leaned on
        concept_raw = {}
        #two arrays rather than a subquery over card_tags, because the user can
        #switch tags off: anchor_vector decides the kept set and its norm, and
        #both queries just read them
        atags, aweights, anorm = anchor_vector(conn, oracle_id, dropped, picked, forced)
        #no anchor vector means the concept axis SITS OUT entirely, rather than
        #scoring every candidate at zero and dragging the blend down with it.
        #picking a keyword line is how that happens: the line owns no tags, so
        #scoring it as zero would halve every card's score and return nothing at
        #all above the cutoff
        if atags:
            have = {oid for oid, pairs in ranked}
            #cards the lines never found, injected as candidates when their
            #concept score alone is worth considering at the current cutoff,
            #through the same filters as everything else
            rows = conn.execute("""
                WITH anchor AS (
                    SELECT * FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
                )
                SELECT ct.oracle_id, """ + pcol + """ AS price, c.edhrec_rank, c.released_at, c.salt,
                       sum(a.weight * ct.weight) / (%s * nc.norm) AS raw
                FROM card_tags ct
                JOIN anchor a ON a.tag = ct.tag
                JOIN cards c ON c.oracle_id = ct.oracle_id
                JOIN card_tag_norms nc ON nc.oracle_id = ct.oracle_id
                WHERE ct.oracle_id <> %s""" + where + """
                GROUP BY ct.oracle_id, """ + pcol + """, c.edhrec_rank, c.released_at, c.salt, nc.norm
                HAVING sum(a.weight * ct.weight) / (%s * nc.norm) >= %s
                ORDER BY raw DESC
                LIMIT 300
            """, [atags, aweights, anorm, oracle_id] + fparams + [anorm, concept_raw_gate(min_pct)]).fetchall()
            for r in rows:
                concept_raw[r["oracle_id"]] = r["raw"]
                prices.setdefault(r["oracle_id"], r["price"])
                ranks.setdefault(r["oracle_id"], r["edhrec_rank"])
                dates.setdefault(r["oracle_id"], r["released_at"])
                salts.setdefault(r["oracle_id"], r["salt"])

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
                return (1 - BLEND) * mech + BLEND * concept_display(concept_raw.get(oid, 0.0))
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
            #no salt is not the same as MILD, so an unvoted card sinks on both
            #directions rather than being claimed the least annoying result.
            #the concept injection carries salt like it carries price, rank and
            #date, or a concept find with a real score sinks into the unvoted pile
            #while its own frame prints the number that should have floated it
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

        #the next band down that actually HOLDS cards: empty bands are skipped
        #rather than offered and then found empty.
        #
        #the band's percent range is deliberately NOT sent: a skipped empty band
        #makes the numbers jump about, which reads as a bug even when it is right.
        #step is what the caller words, 1 being the first drop below the line
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

        #read off the SAME kept vector the scoring used, so a tag the user
        #switched off never turns up as the reason for a match
        chips = {}
        if atags and ids:
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
            #pairs reusing a line already shown are skipped, so the count means
            #genuinely different abilities matched
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
        #what makes the list read in descending order.
        #
        #the atags check keeps that promise on a picked keyword line: with no
        #anchor vector the ranking dropped to rules text above, and blending a
        #zero in here would badge a perfect textual match 50% while the gate let
        #it through on 100. it has to match the ranking's condition EXACTLY
        if atags:
            percent = int(round((1 - BLEND) * mech_pct + BLEND * concept_pct))
        else:
            percent = mech_pct
        price = price_label(c, currency)
        #a comparison is the one thing these four numbers honestly support on
        #their own, so every tooltip names the card being compared against
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
            "blended": bool(atags),
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
        #404, not 200, or every typo is an indexable url. the tuple keeps this
        #page: the errorhandler only catches abort() and unmatched paths
        return render_template("search.html", query=query, not_found=True), 404

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
    sort = read_sort()
    sort_field, sort_dir = read_sort_parts()
    card_lines, picked = build_lines(card, read_picked())
    dropped = read_dropped()
    forced = read_forced()

    with pool.connection() as conn:
        chips = anchor_chips(conn, card["oracle_id"], dropped, picked, forced) if LINE_TAGS else []
    #anchorcard.html reads these names, and /deck/swap builds the same set out
    #of anchor_panel(). they are passed explicitly rather than through it here
    #because this route already had every one of them in hand

    results, has_more, next_band = find_similar(card["oracle_id"], picked, filters, TIER_CUT, sort,
                                                currency=filters["cur"],
                                                dropped=dropped, forced=forced,
                                                anchor_price=price_in(card, filters["cur"]),
                                                anchor_rank=card["edhrec_rank"],
                                                anchor_salt=card["salt"],
                                                anchor_released=card["released_at"])
    resp = make_response(render_template("search.html", query=query, card=card, card_lines=card_lines,
                                         picked_count=len(picked), results=results, has_more=has_more,
                                         next_band=next_band, min_pct=TIER_CUT, errors=filters["errors"],
                                         cur=filters["cur"], types=CARD_TYPES,
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
    #the slider's cookie, actively DELETED rather than left alone, or anyone who
    #moved it before 2026-07-22 keeps a stale preference forever, doing nothing
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
    #pure rules-text uniqueness rather than the blend the dealer uses: this is
    #the number the h1 makes a claim about
    if _unique_top["rows"] and time.time() - _unique_top["at"] < 3600:
        return _unique_top["rows"]
    try:
        with pool.connection() as conn:
            rows = [dict(r) for r in conn.execute("""
                SELECT name, uniqueness, unique_line, image
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
    return render_template("unique.html", types=CARD_TYPES, cur=read_currency(),
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


#a deck is original because of its WEIRDEST cards, not its average one: the mean
#over a whole list is dominated by the mana base and the removal every deck
#shares, and squashes the spread between first and last from 0.143 to 0.103.
#
#a FRACTION and not a fixed count, because precons hold 53 to 66 nonland cards:
#a fixed top 20 scored a small deck on 38% of itself against a big one's 30%, and
#the bias grew with the count (r=+0.34 against deck size at top 50, +0.26 at top
#20). a fraction is size independent by construction, and takes that to +0.19.
#
#half rather than a third, because a third of a commander deck is about the
#lands and the staples above them. reading DEEPER does not make it more accurate:
#every step costs discrimination (spread 0.143 at a third, 0.103 using every
#card), and the ranking's ends do not move at all
PRECON_TOP_FRAC = 0.5

#originality correlates with release year at r=+0.46, partly because design space
#genuinely fills up. the ranking still separates decks INSIDE one era, so the
#page says so and lets you rank like against like. bounds are inclusive
PRECON_ERAS = [
    ("all", "All precons", None, None),
    ("early", "2011-2019", 2011, 2019),
    ("mid", "2020-2022", 2020, 2022),
    ("recent", "2023 on", 2023, 9999),
]

#BASIC lands are left out of the salt tally, and nothing else is. not a judgement
#about the votes, which stay untouched in the database: a DECK-LEVEL SUM cannot
#use them fairly, because how many basics a deck holds is a fact about its mana
#base.
#
#the giveaway is that the distortion runs in OPPOSITE DIRECTIONS depending on an
#arbitrary choice of arithmetic, measured over the 166 precons:
#
#  counting distinct cards  r = +0.29 against the number of basic land types
#  counting every copy      r = -0.15 against the same thing
#
#so five colour decks were charged for being five colours, and under the other
#rule mono decks for running thirty Islands. basics were 11% of the average
#distinct total and 30% counting copies, all of it noise.
#
#BASIC only, NEVER lands in general: The Tabernacle at Pendrell Vale (2.68),
#Gaea's Cradle (2.17) and Strip Mine (1.48) stay counted.
SALT_SKIP_BASICS = True


def is_basic_land(type_line):
    #'Basic Land - Island' and 'Basic Snow Land - Forest', but NOT the one
    #'Basic Creature - Shapeshifter' in the pool, hence both words
    t = type_line or ""
    return t.startswith("Basic") and "Land" in t


#the same rule as is_basic_land, in sql. the two HAVE to agree, or a pasted
#deck's tally disagrees with the board it is ranked against
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

#FIVE numbers, TEN readings: cheapest and priciest are one sum read from either
#end, not two different numbers.
#
#"best" is which way the COLUMN runs to put the flattering reading first, and it
#is not decoration: most played is the LOWEST median rank, because rank 1 is the
#most played card in the format. everything else is better when bigger.
#
#"means" has to say what the FIGURE means, not what the idea means: nobody
#meeting "19.4 years" or "#1204" can tell a high score from a low one.
#
#the SCALE is deliberately NOT written down here. it was, for an afternoon, and
#all five were already drifting: age grows daily, prices move daily, and the ends
#of the board move whenever the ingest picks up a new precon. the page reads its
#own top and bottom row instead, which also makes it true of the era on screen
#how long a precon counts as new, and NOT a guess: EDHREC's salt survey runs
#once a year, so a card printed since the last one has had no chance to be voted
#on. the longest settling window the five numbers depend on, so it sets the mark.
#
#measured 2026-07-26 over the 166 precons:
#
#  cards first printed inside a year   mean salt 0.059   (n=2568)
#  cards older than that               mean salt 0.291   (n=28906)
#
#a FIFTH of the salt on 98.5% coverage, so the votes are not missing, they have
#not been cast. at deck level 18.7 against 23.4. play rate does the same more
#gently (#5216 against #4188), edhrec's rank counting decks built.
#
#prices move too but NOT reliably in one direction: new precons average $76
#against $88, so hype and reprint gluts pull opposite ways
PRECON_NEW_DAYS = 365

PRECON_METRICS = [
    {
        "key": "original", "figure": "originality", "drivers": "drivers",
        "label": "Originality",
        #NO swap axis on either reading. uniqueness is a contradiction as a sort,
        #so there is nothing here to move a deck along, and the nearest honest
        #thing ("cards fewer people play") reads as the wrong button on the wrong
        #panel. absent rather than approximated
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
            "meta": "Every Commander precon ranked by how original its cards are, "
                    "measured against every Magic card ever printed. Which precons "
                    "play what nothing else does.",
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
            "meta": "Every Commander precon ranked from least original first: the "
                    "decks built out of the format's usual suspects, against every "
                    "Magic card ever printed.",
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
            "meta": "Every Commander precon ranked by how much its cards annoy "
                    "people, from EDHREC's salt survey. Which precons run the cards "
                    "players least enjoy facing.",
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
            "meta": "Every Commander precon ranked from the least salty first, using "
                    "EDHREC's salt survey. The precons that annoy a table least.",
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
            "meta": "Every Commander precon ranked by what its cards cost as singles, "
                    "using the cheapest paper printing of each, refreshed from "
                    "Scryfall daily.",
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
            "meta": "Every Commander precon ranked from the cheapest first, by what "
                    "its cards cost as singles at the cheapest paper printing of each.",
        },
    },
    {
        "key": "played", "figure": "play_median", "drivers": "play_drivers",
        #"Play rate", the name /search's sort uses and the name every tooltip on
        #the site says. "Played cards" here would be both a second name for one
        #metric and nearly its own readings' names ("most played cards", "least
        #played cards") a word short
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
            "meta": "Every Commander precon ranked by how played its cards are, using "
                    "the median EDHREC rank of its nonland cards. The precons built "
                    "out of staples.",
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
            "meta": "Every Commander precon ranked from least played first, by the "
                    "median EDHREC rank of its nonland cards. The precons full of "
                    "cards nobody runs.",
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
            "meta": "Every Commander precon ranked by how old its cards are, measured "
                    "from each card's first printing rather than the date the deck "
                    "shipped.",
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
            "meta": "Every Commander precon ranked from the newest cards first, "
                    "measured from each card's first printing rather than the date "
                    "the deck shipped.",
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
#three entries is the ceiling and the url cannot grow this without bound
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
    #what the other nine boards will show: this era, since their links keep it,
    #but not this page's row count, since they drop the new=hide cut
    also_total = len(rows) + (new_here if hide_new else 0)
    return render_template("precons/board.html", rows=rows, eras=PRECON_ERAS, era=era[0],
                           sorts=PRECON_SORTS, sort=sort, cur=cur, span=span,
                           metrics=PRECON_METRICS, hide_new=hide_new,
                           new_here=new_here, new_days=PRECON_NEW_DAYS,
                           also_total=also_total,
                           cur_urls=currency_urls(), cur_labels=CURRENCY_LABELS,
                           prefix=prefix, suffix=suffix)


#how many cards ANY list on this site reveals at a time: the standing panels,
#the deck grid on /deck/view and on a precon page. one number, so a fix to one
#batching control is a fix to all of them.
#
#16 rather than 12: four rows of four on the results grid's own column count
DECK_SECTION = 16

#48 is about half a commander deck, which is where these lists stop meaning
#anything: originality scores only the top half, salt and age drop basic lands,
#play rate drops all lands, so by this depth the rows are the cards every deck
#shares. fetched WITH the page and revealed by the button, because /deck/read is
#a POST result with no url to ask again at
DECK_EVIDENCE_MAX = 48

#every predicate here is a TRANSCRIPTION of the matching CTE in PRECON_SQL and
#has to stay one: a card the ranking did not count must never turn up in the
#evidence for it.
#__PRICE__ is filled at query time from the day's rates, same as the board
DECK_EVIDENCE = {
    "original": {"where": "c.uniqueness IS NOT NULL AND c.type_line NOT LIKE '%%Land%%'",
                 "order": "c.uniqueness DESC", "value": "c.uniqueness", "decimals": 2},
    "salt": {"where": "c.salt IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
             "order": "c.salt DESC", "value": "c.salt", "decimals": 2},
    #the ONE place the evidence deliberately does not match the ranking. the
    #price TOTAL counts basic lands, a deck's cost including the lands you must
    #own; the price LIST does not, because it reads from both ends and the cheap
    #end of a commander deck is thirty Islands.
    #an omission, NEVER an addition: every card listed is one the total counted,
    #which is the safe direction to break the rule in
    "price": {"where": "__PRICE__ IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
              "order": "__PRICE__ DESC", "value": "__PRICE__", "decimals": 2},
    "played": {"where": "c.edhrec_rank IS NOT NULL AND c.type_line NOT LIKE '%%Land%%'",
               "order": "c.edhrec_rank", "value": "c.edhrec_rank", "decimals": 0},
    "age": {"where": "c.released_at IS NOT NULL" + (" AND NOT " + SALT_BASIC_SQL if SALT_SKIP_BASICS else ""),
            "order": "c.released_at", "value": "extract(epoch FROM (now() - c.released_at)) / 31557600.0",
            "decimals": 1},
}


def metric_cards(conn, oracle_ids, key, currency, limit=DECK_EVIDENCE_MAX):
    #asks for the pictures either way, rather than a second query when someone
    #expands the list.
    #
    #BOTH ENDS in ONE list, ordered from the top: rendering a second list for the
    #flipped reading doubled a page already at 388kb, and the flipped reading is
    #the same cards backwards. hence the cap applied per END rather than to the
    #query, and a deck small enough for the slices to overlap keeping everything
    ev = DECK_EVIDENCE[key]
    price = price_col(currency)
    #uniqueness comes back for EVERY panel, not just originality: it is the badge
    #beside the name wherever a card is drawn, and it holds still while the panels
    #change underneath it
    sql = """
        SELECT c.oracle_id, c.name, c.type_line, c.mana_cost, c.layout,
               c.image, c.image_back, c.scryfall_uri, c.edhrec_rank, c.salt,
               c.price_usd, c.price_eur, c.released_at, c.uniqueness,
               (""" + ev["value"].replace("__PRICE__", price) + """) AS value
        FROM cards c
        WHERE c.oracle_id = ANY(%s::uuid[]) AND (""" + ev["where"].replace("__PRICE__", price) + """)
        ORDER BY """ + ev["order"].replace("__PRICE__", price) + """, c.name
    """
    try:
        #NO limit on the query: both ends are wanted and the database can only cut
        #one off. asking for twice the cap instead reads the bottom end out of the
        #MIDDLE of the list, so a pile with more than 96 qualifying cards offers
        #rows 49 to 96 as its mildest and cheapest, which they are not
        rows = conn.execute(sql, ([str(o) for o in oracle_ids],)).fetchall()
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


def precon_deck(slug):
    #which cards a precon holds AND how many of each, cached for an hour like
    #everything else about the board: it only moves when the ingest reruns, and
    #five metric queries per page view should not each ask the same question
    hit = _deck_ids_cache.get(slug)
    if hit and time.time() - hit["at"] < 3600:
        return hit
    try:
        with pool.connection() as conn:
            rows = conn.execute("SELECT oracle_id, count FROM deck_cards WHERE deck_slug = %s",
                                (slug,)).fetchall()
    except Exception:
        return hit or {"at": 0, "ids": [], "counts": {}}
    hit = {"at": time.time(), "ids": [r["oracle_id"] for r in rows],
           "counts": {str(r["oracle_id"]): r["count"] for r in rows}}
    _deck_ids_cache[slug] = hit
    return hit


def precon_ids(slug):
    #the lens reads a deck as a set of ideas, so the copies never reach it
    return precon_deck(slug)["ids"]


def deck_uniqueness(oracle_ids):
    #every nonland card in the pile with its originality score, which is the
    #one figure the pasted path has to work out for itself: the other four come
    #back from deck_metrics as single numbers, and this one is an average over
    #a SLICE of the deck, so the slice has to be picked here.
    #
    #the predicate matches PRECON_SQL's scored CTE exactly, so one number is not
    #computed under two different rules. the lens query also requires a card to
    #have rules lines, which changes nothing (uniqueness is derived from lines,
    #so a card without any has none) and is still a second rule
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
    #the same number the leaderboard ranks on, so a pasted list and a precon are
    #measured identically. a fraction rather than a count matters more here,
    #a pasted list being any size at all.
    #an unscored card is SKIPPED, never counted as zero: the board's query drops
    #them the same way, and the two have to agree or a pasted list is ranked
    #against a population measured by a different rule
    vals = sorted((c["global_u"] for c in cards if c["global_u"] is not None), reverse=True)
    if not vals:
        return 0.0
    keep = max(1, round(len(vals) * frac))
    vals = vals[:keep]
    return sum(vals) / len(vals)


def deck_salt(oracle_ids):
    #counted per DISTINCT card, never per copy: nine Islands are not nine times
    #the annoyance of one, and it is the only way this agrees with the board
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
    #the SAME five panels whether the deck came out of the precon table or a
    #paste box: /precons/<slug> and /deck/read are one page about different decks.
    #
    #each panel carries BOTH readings and shows one, being one measurement with a
    #switch on it. the CARDS are not duplicated for the second: they are the same
    #cards backwards, and a second copy of five lists on a 388kb page is the
    #version that stops loading on a phone. the browser reverses them
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
                               #than helping
                               swap=({"axis": r["swap"][0], "dir": r["swap"][1],
                                      "goal": SWAP_AXES[r["swap"]]["goal"]}
                                     if r["swap"] else None))
        if len(readings) != 2:
            continue
        prefix, suffix = figure_units(m["key"], cur)
        panels.append({"key": m["key"], "readings": readings,
                       #the metric's own name, for the "rank by" chips. NOT a
                       #reading's label: "Salt" is the measurement, "Saltiest"
                       #is one end of it and the row beside it picks that
                       "label": m["label"],
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
    #one borrow for both, because both are this page's and the page is drawn
    #once. two blocks running back to back is two trips to the pool for a handler
    #that is never going to let go in between
    with pool.connection() as conn:
        panels = deck_panels(conn, ids, figures, board, cur, slug=slug)
        #the deck's cards, for the plain list the "run it through the lens" and
        #"view it" buttons post. NOT for a grid: this page draws no whole-deck
        #fold, because every standing panel above already opens into its own
        #pictures. the template also reads `cards` as the guard on that block,
        #so a deck with none offers no way on rather than an empty one
        cards = deck_cards(conn, ids, cur)
    year = deck_row["release_date"].year if deck_row["release_date"] else 0
    #a deck still inside the settling window carries the note on every panel
    #whose number is affected, rather than a blanket disclaimer nobody reads
    is_new = bool(deck_row["release_date"] and deck_row["release_date"] >
                  datetime.date.today() - datetime.timedelta(days=PRECON_NEW_DAYS))
    #WITH THE COPIES. deck_cards is distinct cards, so a list written at one
    #apiece hands back 96 of a 100 card precon: the four missing are always basic
    #lands, and what comes back is not a legal deck, let alone theirs
    counts = precon_deck(slug)["counts"]
    decklist = "\n".join("%d %s" % (counts.get(str(c["oracle_id"]), 1), c["name"])
                         for c in cards)
    return render_template("precons/deck.html", deck=deck_row, year=year, panels=panels,
                           opened=opened, back=arrived["key"], cur=cur, is_new=is_new,
                           cur_urls=currency_urls(), cur_labels=CURRENCY_LABELS,
                           cards=cards, decklist=decklist,
                           #the deck's real size, copies and all: a precon is
                           #100 cards and 96 of them are different
                           counted=sum(counts.values()) or len(ids),
                           total=len(board))


#----- the paste box: someone else's decklist, read through the same lens -----

#section headings, which a decklist is not obliged to have.
#
#tested against the line with its bracketed bits ALREADY OFF, never the raw one:
#archidekt writes the section size into the heading ("Creatures (30)") where the
#others write it bare, so every archidekt export with categories on reported one
#unmatched card per section
DECK_HEADERS = re.compile(r"^(deck|decklist|sideboard|commander|companion|maybeboard|"
                          r"considering|tokens?|creatures?|lands?|instants?|sorcer(?:y|ies)|"
                          r"artifacts?|enchantments?|planeswalkers?|battles?|"
                          r"ramp|removal|draw|utility|other)\b[:\s]*$", re.I)
#"1 ", "1x ", "4x " at the front of a line
DECK_COUNT = re.compile(r"^(\d+)\s*[xX]?\s+")
#everything the exporters bolt on AFTER the name: (SET) 123, *F*, [Category]
DECK_TRAILERS = re.compile(r"\s*(\([^)]*\)|\[[^\]]*\]|\*[^*]*\*|<[^>]*>)\s*")
#a collector number stranded once its set code is gone. NOT applied blind:
#twelve real cards end in a digit (Pip-Boy 3000, Overseer of Vault 76), so this
#is only tried after the whole name has failed to match
DECK_TRAILING_NUM = re.compile(r"\s+\d+\s*$")
#mtgo marks its sideboard per line rather than under a heading, so a .txt
#straight out of the client carries "SB: 3 Swords to Plowshares"
DECK_SIDEBOARD = re.compile(r"^SB:\s*", re.I)
#deckstats hangs the category off the END of the line as "#!Ramp". no card name
#contains a hash, so taking one off the tail cannot cost a match
DECK_HASH_TAIL = re.compile(r"\s+#.*$")

#the two exports that are not lists of lines, recognised by their own first
#bytes rather than by a control the user has to set.
#
#mtgo's .dek is xml, read with a REGEX rather than an xml parser: this is a
#hostile string from a text box, and every stdlib xml parser has entity
#expansion behaviour worth not thinking about
MTGO_DEK_CARD = re.compile(r"<Cards\b[^>]*?\bName=\"([^\"]+)\"", re.I)
MTGO_DEK_QTY = re.compile(r"\bQuantity=\"(\d+)\"", re.I)

#the pair query is all-pairs over the LINES, so cost climbs with the square:
#~250 lines measured 160-215ms, and a 5000 line paste would tie up the database
DECK_MAX_CARDS = 250
#and a cap on the raw text before it is even split, so an enormous paste is
#rejected without walking it
DECK_MAX_CHARS = 60000

#below this many nonland cards the precon comparison is not offered. not about
#unequal counts, a fraction already handling that, but about NOISE: half of a
#six card list is three cards, and a three card mean says nothing
DECK_MIN_FOR_RANK = 20


def deck_norm(name):
    #NFKD splits an accented letter into letter plus combining mark, so dropping
    #the marks leaves plain ascii: what lets a list typed without accents find
    #Grima Wormtongue
    name = name.replace("’", "'").replace("‘", "'")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return " ".join(name.lower().split())


#TWO clocks: a good index and a FAILED rebuild. one for both meant a rebuild
#that threw still bought the full hour, so a cold start that missed left an empty
#index looking fresh and every paste came back "none of those lines matched a
#card". still a wait, because a database properly down should not be asked per
#request
NAME_INDEX_TTL = 3600
NAME_INDEX_RETRY = 60

_name_index = {"at": 0.0, "map": {}, "ttl": 0.0}


def name_index():
    #~33k keys for 31k cards, a couple of megabytes. IN MEMORY rather than in
    #sql, which is what keeps a 100 card list to zero round trips for matching
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
    #returns (matched oracle ids, names we could not find, copies of the matched).
    #blind to WHICH board a card is in: the lens reads the whole pile.
    #
    #matching is EXACT on the normalised name, NEVER fuzzy. find_card guesses
    #because a human is watching one result and can retype; a wrong guess here
    #sits silently in a hundred rows pretending to be someone's deck
    idx = name_index()
    found, missing = [], []
    seen = set()
    copies = 0
    text = text[:DECK_MAX_CHARS]
    #the file exports become lines before anything else looks at them, so there
    #is exactly ONE line parser and it is the tested one
    text = csv_to_lines(text) or dek_to_lines(text) or text
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        #mtgo's per-line sideboard marker and deckstats' trailing category
        line = DECK_HASH_TAIL.sub("", DECK_SIDEBOARD.sub("", line)).strip()
        if not line:
            continue
        #the line as typed FIRST, then with a leading count off. taking it off
        #blind turned "1996 World Champion" into a lookup for "World Champion".
        #
        #dormant, and written down so it is not read as dead weight: no card in
        #the pool starts with a digit, so this changes no result today. it costs
        #one dict lookup and covers a real shape, an uncounted line naming such a
        #card, for whenever one is added
        whole = DECK_TRAILERS.sub(" ", line).strip()
        #HERE rather than on the raw line, so a heading carrying its own count
        #("Commander (1)") is still a heading
        if DECK_HEADERS.match(whole):
            continue
        m = DECK_COUNT.match(line)
        counted = DECK_TRAILERS.sub(" ", line[m.end():]).strip() if m else ""
        tries = [t for t in (whole, counted) if t]
        if not tries:
            continue
        oid = None
        #WHICH of the two won, because only the counted one had a count taken
        #off it. reading m.group(1) regardless would charge a line naming a card
        #that starts with a digit 1996 copies of itself
        via = None
        for t in tries:
            oid = idx.get(deck_norm(t))
            if oid is not None:
                via = t
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
                        via = t
                        break
        if oid is None:
            if len(missing) < 40:
                #the count is off by now, so this reads back as the card name
                #the line was asking for
                missing.append(tries[-1])
            continue
        #the copies are tallied even though the ids drop them, and both lines of
        #that are load bearing. nine Islands say nothing about a deck's IDEAS
        #that one Island does not, so the lens reads a set. but the page still
        #has to answer "did all of it arrive", and "64 cards read in" is what a
        #whole hundred card deck looked like while this was not counted
        if m and via is not whole:
            try:
                copies += max(1, int(m.group(1)))
            except ValueError:
                copies += 1
        else:
            copies += 1
        if oid in seen:
            continue
        seen.add(oid)
        found.append(oid)
        if len(found) >= DECK_MAX_CARDS:
            break
    return found, missing, copies


#how many precons sit either side of the deck in each standing. enough to see
#what it landed between, short enough that five of these on one page is still
#a page. the whole board is one click away on /precons
DECK_WINDOW = 3


def deck_metrics(conn, oracle_ids, currency):
    #computed EXACTLY as PRECON_SQL computes them for a precon: a standing is a
    #comparison, and two numbers arrived at differently are not comparable. every
    #predicate below transcribes the matching CTE, and if one moves both must.
    #SALT_BASIC_SQL already carries its percent signs DOUBLED, every query using
    #it being parameterised, so it goes in untouched
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


def standing_band(stand):
    #"saltier than 26 of the 167" reads as 26th to about half the people who see
    #it, which is the opposite of what it says. a percentage of the board fixes
    #that, and it is read FROM THE NEARER END: "top 84%" is a true and useless
    #way to say 141st of 167.
    #
    #the two readings of a panel each sort from their own end, so a deck that is
    #bottom 16% of the saltiest is top 16% of the mildest. the same fact twice,
    #and it agrees with itself either way round
    place, of = stand["place"], stand["of"]
    if place * 2 <= of:
        stand["band_end"] = "top"
        share = place / of
    else:
        stand["band_end"] = "bottom"
        share = (of - place + 1) / of
    #never 0%: first of 167 is 0.6% and "the top 0%" is not a place
    stand["band_pct"] = max(1, int(round(share * 100)))
    return stand


def deck_standing(board, key, best, figure, slug=None):
    #"better" is the metric's OWN direction, never bigger-is-better: on play rate
    #a smaller median is more played, and getting that backwards tells someone
    #their pile of staples is the most obscure deck in the format.
    #
    #a precon passes its SLUG and is already a row, so it is located rather than
    #inserted. a pasted deck is dropped in at the position its figure earns,
    #making the population one bigger. both come back in the same shape
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
            #source rides along for the ctrl-click, these being precon links
            #like the board's
            window.append({"place": i + 1, "name": r["name"], "slug": r["slug"],
                           "source": r.get("source"),
                           "figure": float(r[key]), "you": i == at})
        return standing_band({"place": at + 1, "beaten": len(rows) - at - 1,
                              "of": len(rows), "window": window})

    better = 0
    for r in rows:
        v = float(r[key])
        if (v < figure) if best == "asc" else (v > figure):
            better += 1
        else:
            break
    #places come off the slice INDICES, never a lookup by value: two decks can
    #hold the identical figure, and a lookup hands back the first for both
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
    return standing_band({"place": better + 1, "beaten": len(rows) - better,
                          "of": len(rows) + 1, "window": window})


def deck_hub(error=None, pasted="", url="", missing=None):
    #one function, so an error state cannot drift into a different page
    board = precon_board()
    return render_template("deck/hub.html", deck_count=len(board),
                           example=board[0] if board else None,
                           error=error, pasted=pasted, url=url, missing=missing)


def deck_identity():
    #rides the FORM like the list itself, there being no session to keep it in.
    #EVERY form on every page of the lens has to carry it, or the name is lost
    #going back to change something: the importer knew the commander, and the
    #reading then called the same deck "72 cards"
    commander = " ".join(request.form.get("commander", "").split())[:200]
    name = " ".join(request.form.get("name", "").split())[:200]
    return (name or commander), commander


def deck_did():
    #WHICH SAVED DECK this is, in the visitor's own browser, passed through and
    #handed straight back. the server never reads it and could not use it: the
    #shelf is localStorage and nothing about it reaches us.
    #
    #keying the shelf on the decklist instead means a key that MOVES whenever a
    #swap changes the deck, so every page carries the list twice and every lookup
    #guesses which it holds.
    #
    #trimmed and stripped to alphanumerics: it is echoed into html, so it must
    #not become a decklist smuggled through a field never meant to carry one
    return "".join(c for c in request.form.get("did", "")[:64]
                   if c.isalnum())


def deck_leaders(conn, oracle_ids):
    #front face legendary creatures, the same test the search's "commanders only"
    #filter uses. the picker falls back to the whole list when a pile has none
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
    #the one query behind both /deck/view and a precon page.
    #
    #the labels come off the SAME helpers the results and swap grids use, which
    #keeps a price here reading identically to the same card's price on a search.
    #
    #DISTINCT cards, never copies: parse_decklist folds a list down, so thirty
    #seven Forests arrive as one Forest with no count to print
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


#the deck pages are POST results with no url of their own, which is the privacy
#decision. answering a bare GET with a 405 was never part of it, just what
#werkzeug does when no rule matches: a back button or a shared link arrives as a
#GET, so it gets the front door
@app.route("/deck/open", methods=["GET"])
@app.route("/deck/read", methods=["GET"])
@app.route("/deck/swap", methods=["GET"])
@app.route("/deck/view", methods=["GET"])
def deck_post_only():
    return redirect("/deck")


@app.route("/deck/open", methods=["POST"])
def deck_open():
    #where both inputs land, converging HERE so everything downstream sees a
    #pasted list either way. the import path's whole job is url to text
    text = request.form.get("list", "")
    url = request.form.get("url", "").strip()
    #a name coming back round: the recent-decks list and the back links all
    #repost through here, and without this the second visit forgets the name
    name, commander = deck_identity()
    if url:
        site = import_site(url)
        if not site:
            return deck_hub(error="That doesn't look like an Archidekt or Moxfield deck "
                                  "link. They look like archidekt.com/decks/1234567 and "
                                  "moxfield.com/decks/aBcDeFgH.", url=url)
        if not import_allowed(import_token()):
            #one message for both lids: different facts, same instruction
            return deck_hub(error="Too many deck imports just now, so we're giving "
                                  "them a rest. Try again in a minute, or paste the "
                                  "list below and carry on.", url=url)
        try:
            text, found, deck_name = site["fetch"](site["id"])
        except Exception:
            #one message for every failure mode: down, private and api-changed
            #are the same event to someone holding a link that did not work
            return deck_hub(error="Couldn't fetch that deck from " + site["name"] + ". It "
                                  "may be private, or they may be having a moment. "
                                  "Pasting the list below always works.", url=url)
        #the one thing a pasted list cannot say. it only PRESELECTS the picker,
        #so a wrong guess is one click to fix rather than a title nobody can change
        commander = commander or (found[0] if found else "")
        name = name or commander or deck_name
    if not text.strip():
        return deck_hub(error="Paste a decklist, or give an Archidekt or Moxfield link.")

    ids, missing, copies = parse_decklist(text)
    if not ids:
        return deck_hub(error="None of those lines matched a card.",
                        pasted=text[:DECK_MAX_CHARS], url=url, missing=missing)
    #what did not match is a ONE TIME question, asked when a deck arrives. a deck
    #coming back round has already been through it, and asking again is a nag
    #about lines they decided to live with.
    #nothing was stored either way: a miss only becomes a feedback row if the user
    #resolves it (see /deck/found)
    if request.form.get("seen"):
        missing = []
    with pool.connection() as conn:
        leaders = deck_leaders(conn, ids)
        #one legend has already answered the question, so it is filled in
        if not commander and len(leaders) == 1:
            commander = leaders[0]
        picker = leaders or deck_names(conn, ids)
    name = name or commander
    #the modes offered rather than assumed: it costs a click and buys proof the
    #list arrived whole, an import that read 40 of your 100 cards being the
    #failure nobody notices until the numbers look wrong
    return render_template("deck/modes.html", pasted=text[:DECK_MAX_CHARS],
                           did=deck_did(),
                           #COPIES, not distinct cards: this number's whole job
                           #is answering "did all of it arrive"
                           matched=copies, missing=missing,
                           deck_name=name, commander=commander,
                           leaders=leaders, picker=picker)


@app.route("/deck/view", methods=["POST"])
def deck_view():
    #the mode that answers "did this arrive whole". renders the same partial
    #/precons/<slug> does, so a pasted deck and a boxed one are one piece of code.
    #
    #what CHANGED is not computed here and CANNOT be: a swap session never reaches
    #the server, so the page carries the deck's id and the script fills those
    #blocks from the browser's own shelf
    text = request.form.get("list", "")
    ids, missing, copies = parse_decklist(text)
    if not ids:
        return deck_hub(error=("None of those lines matched a card." if text.strip()
                               else "Paste a decklist first."),
                        pasted=text[:DECK_MAX_CHARS], missing=missing)
    #`missing` goes no further than that error, and neither does `seen`: this page
    #does NOT draw the unmatched lines, view.html including no partial that could.
    #currency is the same, deciding what deck_cards formats and never reaching the
    #template
    cur = read_currency()
    name, commander = deck_identity()
    with pool.connection() as conn:
        cards = deck_cards(conn, ids, cur)
    #no matched count. the fold under it already says "View every card image 71
    #cards", and a second count is the one number on the page a revert cannot
    #correct, since the count is the server's and the revert is the browser's
    return render_template("deck/view.html", cards=cards,
                           section=DECK_SECTION,
                           deck_name=name,
                           commander=commander, pasted=text[:DECK_MAX_CHARS],
                           did=deck_did())


def read_deck_era():
    #request.values, not request.args: /deck/read is a POST result with no url of
    #its own, so the cut rides a submit button's own name and value
    want = request.values.get("era", "all")
    return next((e for e in PRECON_ERAS if e[0] == want), PRECON_ERAS[0])


@app.route("/deck/read", methods=["POST"])
def deck_read():
    #the pasted list, read and thrown away. nothing is stored and there is no
    #url to come back to, which is the product decision from the start: a lens
    #over someone else's list, not a deck builder with accounts and saves
    text = request.form.get("list", "")
    ids, missing, copies = parse_decklist(text)
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
    #the same cut /precons offers, and for the same reason: originality
    #correlates with release year at r=+0.46, so a 2013 deck ranked against 2024
    #precons is partly being told what year it is. every figure on the page
    #follows it, `total` included
    era = read_deck_era()
    _, _, era_lo, era_hi = era
    if era_lo is not None:
        board = [r for r in board
                 if r["release_date"] and era_lo <= r["release_date"].year <= era_hi]
    ranked = len(scored) >= DECK_MIN_FOR_RANK

    panels = []
    if ranked:
        #the salt tally borrows a connection OF ITS OWN, so it is asked for
        #before one is held rather than from inside the block. the pool holds
        #four, and a handler sitting on one while it queues for a second is how
        #four of them together wait forever: the same reasoning that reads the
        #report limiter's token before /feedback borrows anything
        salt = deck_salt(ids)
        with pool.connection() as conn:
            figures = deck_metrics(conn, ids, cur)
            figures["original"] = originality_of(scored)
            figures["salt"] = salt
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
                           #copies, same as the page before it. `counted` below
                           #is the distinct nonland slice the reading is made of
                           counted=len(scored), matched=copies, missing=missing,
                           total=len(board), ranked=ranked, min_cards=DECK_MIN_FOR_RANK,
                           cur=cur, deck_name=name, commander=commander, swaps=swaps,
                           section=DECK_SECTION,
                           #passed straight through: the Change it form below
                           #posts to /deck/swap and the id has to survive the hop
                           did=deck_did(),
                           #the currency control here is a form rather than
                           #links: this page has no url of its own to flip
                           cur_post=True, cur_labels=CURRENCY_LABELS,
                           #the era cut is /deck/read's alone. a precon page
                           #cannot take one: cutting the board can remove the
                           #very deck the page is about, and it has no placing
                           #left to draw
                           eras=PRECON_ERAS, era=era[0],
                           #handed straight back so the swap tool can be reached
                           #from a reading without pasting twice. it rides the
                           #page rather than a session for the same reason as
                           #everything else here: there is nothing to store
                           pasted=text[:DECK_MAX_CHARS])


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
        #the card still goes into their list: logging it is our business, and a
        #full disk here must not cost them the reading
        pass
    return {"ok": True, "name": card["name"]}


#----- importing a decklist from a url -----

#NEITHER site publishes a supported public api: archidekt calls its own open
#beta and documents nothing, moxfield asks third parties to write in and to
#identify themselves in the User-Agent. both can stop working without warning,
#so everything below is written for that day
ARCHIDEKT_URL = re.compile(r"^https?://(?:www\.)?archidekt\.com/(?:decks|api/decks)/(\d{1,12})", re.I)
#moxfield ids are a short opaque string. the CHARACTER CLASS is the allowlist
#that keeps this from becoming a path: no slashes, no dots, no percent signs
MOXFIELD_URL = re.compile(r"^https?://(?:www\.)?moxfield\.com/decks/([A-Za-z0-9_-]{1,40})", re.I)

#a slow third party must not become a slow page, and a big response must not
#become our memory problem. a 100 card deck's json runs about 400kb
DECK_IMPORT_TIMEOUT = 10
DECK_IMPORT_MAX_BYTES = 8 * 1024 * 1024


def import_site(url):
    #THE WHOLE SECURITY DESIGN: the user's url is NEVER fetched. an id is pulled
    #out of it and OUR url is built from that id, so there is no redirect to
    #follow, no host to revalidate and no way to point this at localhost or a
    #cloud metadata endpoint. a domain allowlist in front of a fetch of user
    #input is the version of this that keeps being a vulnerability
    url = (url or "").strip()
    for pattern, name, fetch in ((ARCHIDEKT_URL, "Archidekt", archidekt_deck),
                                 (MOXFIELD_URL, "Moxfield", moxfield_deck)):
        m = pattern.match(url)
        if m:
            return {"id": m.group(1), "name": name, "fetch": fetch}
    return None


#the only outbound request a visitor can command, so the only thing needing a lid.
#
#TWO lids, and the SECOND is the one that matters: archidekt sees ONE address for
#every import this site makes, railway's, so a hundred people importing once each
#looks exactly like one machine hammering them. without the aggregate cap a busy
#afternoon gets our address blocked for everybody.
#
#in memory, so per process and reset on deploy: the job is stopping a runaway,
#not enforcing a quota
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
        #a dict keyed by moxfield's own card id, so the values are what matter.
        #no per-board slice: the cap goes on the finished list below, the same
        #way the archidekt path does it. capping the entries first spends the
        #allowance on rows the loop is about to skip, which is a real card lost
        #off the end for every nameless entry moxfield sends
        for entry in cards.values():
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
    #EVERY entry is read and the cap goes on the finished list, the way the
    #moxfield path caps its own. archidekt keeps the maybeboard in this same
    #list, so capping the entries first spent the deck's 250 lines on cards
    #that were about to be skipped: a 100 card deck with a 200 card shortlist
    #lost real mainboard cards off the end and said nothing about it
    for entry in (data.get("cards") or []):
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
    return "\n".join(lines[:DECK_MAX_CARDS]), commanders, (data.get("name") or "").strip()


#----- the swap tool: the lens with a hand on it -----

#where every row into the tool starts unless it was told otherwise. cheaper,
#because a budget alternative is the ask that holds up whatever the page before
#it was about. all eight are on the control, see partials/deckways.html
SWAP_DEFAULT = ("price", "asc")


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
    #the UNION rather than the commander's identity, which is stricter and more
    #correct, because parse_decklist is blind to which board a card is in. the
    #union is the safe direction to be wrong in: it is only ever as wide as cards
    #the deck already plays. one illegal card in a paste widens it
    row = conn.execute("""
        SELECT string_agg(DISTINCT letter, '') AS letters
        FROM cards c, regexp_split_to_table(c.color_identity, '') AS letter
        WHERE c.oracle_id = ANY(%s::uuid[])
    """, ([str(o) for o in oracle_ids],)).fetchone()
    return (row["letters"] or "") if row else ""

#the SAME four fields the search sort offers, read the same way: the direction
#names the CONCEPT you want more of, never the column underneath. "best" is
#absent, there being no such thing as moving a deck toward better matching.
#
#"better" is which way the COLUMN moves, which is NOT the same question as the
#label. play rate is where they come apart: "less played" is ascending play rate
#but DESCENDING edhrec_rank, rank 1 being the most played card in the format.
#backwards, the tool suggests Sol Ring to someone asking for something obscure
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

#price is None because it depends on the currency on screen, and resolving it
#anywhere but price_col is a second place for the three to disagree
SWAP_COLUMNS = {"price": None, "played": "edhrec_rank",
                "released": "released_at", "salt": "salt"}


def swap_column(field, currency):
    return price_col(currency) if field == "price" else "c." + SWAP_COLUMNS[field]


#the match a suggestion has to clear before the page will offer it, IN BLENDED
#DISPLAY UNITS, the same number /search badges.
#
#80 would be a different SCALE rather than a stricter setting: that is the
#calibrated boundary for rules text alone. scored on both axes like everything
#else, the comparable boundary is /search's TIER_CUT of 70, because an average
#of two axes rarely reaches 80.
#
#75 rather than 70 because this page PROPOSES a card for a slot rather than
#handing back a list to browse. the only number on the site set above its
#calibrated boundary, and a real tightening: measured over 224 queue cards across
#14 precons on both the salt and price axes,
#
#  rule            skipped   median offer
#  rules >= 80        10%          14
#  blend >= 70         5%          13      (/search's boundary)
#  blend >= 75        18%           8      (this)
#  blend >= 80        32%           5
#
#so a fifth of queue cards are passed over. 70 is the setting if that reads as
#too harsh in use, and the table is what the choice costs.
#
#NO looser pass and no strict-mode toggle: an empty list IS the answer, and
#offering something worse is the tool lowering its standards rather than the user
#choosing to. a skipped card is named under "nothing close enough"
SWAP_GATE = 75

#its own constant rather than BLEND: the same value, but a separate decision
SWAP_BLEND = 0.5

#a BATCH rather than a lid. the page holds SWAP_DEEP cards in queue order and
#reveals them a batch at a time, which costs one column of json and no extra
#database work: a card's candidates are fetched only when it is reached
SWAP_QUEUE = 12

#the real end of the queue. the whole deck is not worth scanning, only the tail
#being worth acting on, and 48 keeps the json small
SWAP_DEEP = 48

#the deeper list is FREE: the query already scans 200 rows per line and cuts at
#the very end, so holding 48 costs one bigger json and no extra database work.
#twelve is the batch every other list on this site reveals at a time
SWAP_OFFER = 12
SWAP_OFFER_DEEP = 48

#similarity is on RULES TEXT, so a two mana rock and a six mana rock score
#identically on the ability that makes them rocks. on /search the user judges;
#here the page proposes a card for a specific slot, and a curve is a real
#constraint the text cannot see.
#
#NOT one flat number: two either way reaches 89% of the format at three mana and
#10.7% at eight, because the format thins fast past five (7,497 nonland
#commander-legal cards cost three, 292 cost eight). that is how Ancient Silver
#Dragon's "less salty" list came back holding one card while /search showed
#fourteen.
#
#the two fives below are the same number by COINCIDENCE, not by rule, hence two
#constants
SWAP_MV_BAND = 2
SWAP_MV_BAND_HIGH = 3
#where the wider band starts
SWAP_MV_HIGH = 5
#the lowest mana value a card past that band can reach down to
SWAP_MV_FLOOR = 5


def swap_mv_range(cmc):
    #min() and NOT max(): the floor only ever OPENS the range, so a three drop
    #still reaches down to one rather than being dragged up to five
    band = SWAP_MV_BAND if cmc <= SWAP_MV_HIGH else SWAP_MV_BAND_HIGH
    return min(cmc - band, SWAP_MV_FLOOR), cmc + band

#how close to the card's OWN rarest line another has to be to be worth anchoring
#on too. 0.9 keeps genuine second abilities and drops riders: one real ability
#plus a keyword everybody has gets searched on the ability
SWAP_ANCHOR_FRAC = 0.9

#a floor on the matched pair with BOTH sides weighted by how many cards carry the
#line. a backstop rather than the main defence: anchoring decides which of OUR
#lines is worth searching, this catches a candidate answering a rare line of ours
#with one half the format shares.
#
#LOW on purpose. at 0.75 it becomes a second gate and removes every mana rock in
#the game from "find me a less played Sol Ring", whose correct answers are all
#mana rocks sharing one very common line.
#
#always an EXCLUSION, never the number on screen: the badge stays the display
#score, so the list still reads in descending order of what the user can see
SWAP_PAIR_CUT = 0.2


def swap_queue(cards, field, direction):
    #worst first, the exact inverse of "better", off the SAME flag, so the queue
    #and the suggestions can never disagree about which way is up on an axis.
    #
    #a card with no value on the axis DROPS OUT rather than sorting as zero: an
    #unpriced card is unknown, not free, and would head the "cheaper" queue forever
    axis = SWAP_AXES[(field, direction)]
    key = "price" if field == "price" else SWAP_COLUMNS[field]
    rows = [c for c in cards if c.get(key) is not None]
    #belt and braces, deck_swappable having already dropped them for having no
    #rules lines: any other source puts nine Islands at the top of a salt queue
    #on the strength of the protest votes they carry
    rows = [c for c in rows if not is_basic_land(c.get("type_line") or "")]
    rows.sort(key=lambda c: c[key], reverse=(axis["better"] == "lower"))
    return rows[:SWAP_DEEP]


def swap_card_json(c, currency, anchor=None):
    #the card leaving and every card that could replace it go through HERE, so
    #the comparison between them means something: both numbers came out of one
    #function.
    #
    #given an anchor, every figure also carries its verdict against that card,
    #in the same vocabulary /search uses: cheaper, milder, more played
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
        #the fourth arrow, same as the results grid. no colour on it there and
        #none here: older is not better than newer
        out["age_vs"] = age_verdict(c["released_at"], anchor["released_at"])
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


def anchor_panel(conn, card, currency, picked=(), dropped=(), forced=(), mode="search"):
    #built once for both pages that draw the partial. /search renders it into the
    #page; /deck/swap/cards renders it to a string, the card changing as the queue
    #is walked. the display figures are set the SAME way /search sets them, so the
    #two cannot print a price differently
    card = dict(card)
    card["sideways"] = sideways(card.get("layout"), card.get("type_line"))
    card["flip"] = card.get("layout") == "flip"
    card["price"] = price_label(card, currency)
    card["rank"] = rank_label(card["edhrec_rank"])
    card["salt_text"] = salt_label(card["salt"])
    card["age"] = age_label(card["released_at"])
    card_lines, picked = build_lines(card, picked)
    chips = anchor_chips(conn, card["oracle_id"], dropped, picked, forced) if LINE_TAGS else []
    return {"card": card, "card_lines": card_lines, "picked_count": len(picked),
            "tag_chips": chips, "line_tags_on": LINE_TAGS, "mode": mode,
            "dropped_count": sum(1 for c in chips if c["state"] == "off"),
            "aside_count": sum(1 for c in chips if c["state"] == "aside")}


def swap_candidates(conn, card, deck_ids, colors, field, direction, currency="usd",
                    picked=(), dropped=(), forced=()):
    #one nearest neighbour walk per line of the outgoing card, as /search does,
    #with the deck's constraints folded into the WHERE so the LIMIT bites AFTER
    #them: a narrow deck digs deeper rather than thinning an already-cut list
    axis = SWAP_AXES[(field, direction)]
    col = swap_column(field, currency)
    qlines = conn.execute("""
        SELECT l.line_text, l.""" + EMBED_COL + """ AS embedding, coalesce(s.count, 1) AS count
        FROM lines l LEFT JOIN line_stats s ON s.line_text = l.line_text
        WHERE l.oracle_id = %s AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL
    """, (card["oracle_id"],)).fetchall()
    #NOTHING TO OFFER STILL ANSWERS IN THREE PARTS: the caller unpacks
    #(cards, offband, mv), so a bare [] is a ValueError and a 500 on a page that
    #had a perfectly ordinary thing to say
    if not qlines:
        return [], 0, (None, None)

    #anchor on what makes this card THIS card, its RAREST lines, not whichever
    #matches something best. "one matching ability is enough" is right for
    #/search, where the user browses and judges, and wrong for a slot: Stasis
    #matched Sunken City perfectly on its upkeep tax while the untap lock, the
    #reason anyone plays or hates it, went unexamined.
    #
    #RELATIVE to the card's own best line, never an absolute bar: Sol Ring is one
    #common line and nothing else, so an absolute cut returns nothing at all.
    #
    #a PICKED line wins outright and skips the anchoring. the fraction exists to
    #guess which line makes this card this card, and somebody who clicked one has
    #answered that themselves
    chosen = [ql for ql in qlines if ql["line_text"] in picked] if picked else []
    if chosen:
        qlines = chosen
    else:
        top_w = max(line_weight(ql["count"]) for ql in qlines)
        qlines = [ql for ql in qlines if line_weight(ql["count"]) >= SWAP_ANCHOR_FRAC * top_w]

    where = ""
    params = []
    #commander is singleton, so without this the best answer for your
    #Counterspell is reliably the Arcane Denial four rows below it
    where += " AND c.oracle_id <> ALL(%s::uuid[])"
    params.append([str(o) for o in deck_ids])
    #read the deckbuilding way: every letter of the card's identity has to be one
    #the deck can already produce, and colourless always fits
    if colors is not None:
        where += " AND c.color_identity ~ %s"
        params.append("^[" + colors + "]*$")
    where += " AND c.legal_commander"
    #a land slot stays a land slot: the text similarity cannot see the difference,
    #and offering a creature for a land is the most obvious way to read as broken
    where += " AND (c.type_line ILIKE %s) = %s"
    params.append("%Land%")
    params.append(bool("Land" in (card["type_line"] or "")))
    #the mana value band is NOT in this where clause. it is applied AFTER scoring,
    #so the page can say how many real matches it held back for costing the wrong
    #amount: filtered here they are indistinguishable from cards that never
    #matched, and a tool answering "one card" without saying it turned fourteen
    #away cannot be argued with. everything else stays in the sql, where the LIMIT
    #bites after it
    mv_lo, mv_hi = (swap_mv_range(card["cmc"])
                    if card.get("cmc") is not None else (None, None))
    #the axis as an EXCLUSION, never a sort applied later: similarity finds the
    #same EFFECT, and the effect is what people voted salt on, so the neighbours
    #of a salty card are salty too and sorting them puts the least bad offender at
    #the top of a list of offenders.
    #a NULL fails the comparison and drops out, which is right: a card nobody has
    #priced or voted on cannot be shown to be an improvement
    here = card.get("price" if field == "price" else SWAP_COLUMNS[field])
    if here is None:
        return [], 0, (None, None)
    where += " AND " + col + (" < %s" if axis["better"] == "lower" else " > %s")
    params.append(here)

    #EVERY pair per card, so a suggestion can say "+2 more matching lines". the
    #best one still decides the ranking and the badge
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
            #weighted BOTH ways for the ranking and the cut, raw for the number
            #on screen. one common line on either side is enough to make a
            #perfect match meaningless, so both sides have to earn it
            score = (m["sim"] * w * line_weight(m["their_count"]),
                     m["sim"], ql["line_text"], m["line_text"])
            pairs_by_card.setdefault(m["oracle_id"], []).append(score)
            #the row is the same card every time, so the first one wins and the
            #rest are the same values again
            meta.setdefault(m["oracle_id"], m)

    #sorted so pairs[0] is the best one, exactly as find_similar does it
    for pairs in pairs_by_card.values():
        pairs.sort(reverse=True)

    #the concepts half, which is what makes a suggestion scored the way
    #everything else on the site is scored rather than on rules text alone.
    #
    #re-ranks the candidates the LINES found and never adds any of its own. not a
    #shortcut but the Stasis rule holding: a slot replacement has to share a real
    #line with the card leaving, where a search result only has to be about the
    #same thing. a concept-only card could not clear the gate anyway (no line
    #means mech 0, so a 50/50 blend caps it at 50 against a bar of 75)
    concept_raw = {}
    shared = {}
    ids = list(pairs_by_card)
    atags, anorm = [], 0.0
    if ids:
        atags, aweights, anorm = anchor_vector(conn, card["oracle_id"], dropped, picked, forced)
        if atags and anorm:
            for r in conn.execute("""
                WITH anchor AS (
                    SELECT * FROM unnest(%s::text[], %s::real[]) AS a(tag, weight)
                )
                SELECT ct.oracle_id,
                       sum(a.weight * ct.weight) / (%s * nc.norm) AS raw
                FROM card_tags ct
                JOIN anchor a ON a.tag = ct.tag
                JOIN card_tag_norms nc ON nc.oracle_id = ct.oracle_id
                WHERE ct.oracle_id = ANY(%s::uuid[])
                GROUP BY ct.oracle_id, nc.norm
            """, (atags, aweights, anorm, ids)).fetchall():
                concept_raw[r["oracle_id"]] = r["raw"]
            #same query and ordering the results page uses
            for r in conn.execute("""
                SELECT ct.oracle_id, ct.tag FROM card_tags ct
                JOIN unnest(%s::text[], %s::real[]) AS a(tag, weight) ON a.tag = ct.tag
                WHERE ct.oracle_id = ANY(%s::uuid[])
                ORDER BY a.weight * ct.weight DESC
            """, (atags, aweights, ids)).fetchall():
                shared.setdefault(r["oracle_id"], []).append(r["tag"])

    #NO ANCHOR VECTOR MEANS THE CONCEPT AXIS SITS OUT, matching find_similar's
    #ranking condition. this is the THIRD place that has had to learn it.
    #
    #without it the tool answered nothing, silently: every candidate scored
    #concept 0, so the badge was half its rules-text percent, and half of a
    #perfect 100 is 50 against a gate of 75. measured on Faerie Mastermind, 17
    #suggestions with the best at 91%, and none at all once "Flash" was picked
    blending = bool(atags) and bool(anorm)

    out = []
    #the ONE exclusion worth reporting: the others all mean "not the same card"
    offband = 0
    for oid, pairs in pairs_by_card.items():
        weighted, raw, ours, theirs = pairs[0]
        mech_pct = mech_display(raw)
        #the badge IS the number the gate and the ranking use, which is the
        #promise the whole site runs on
        if blending:
            concept_pct = concept_display(concept_raw.get(oid, 0.0))
            pct = int(round((1 - SWAP_BLEND) * mech_pct + SWAP_BLEND * concept_pct))
        else:
            concept_pct = 0
            pct = mech_pct
        if pct < SWAP_GATE or weighted < SWAP_PAIR_CUT:
            continue
        #counted only AFTER the gate, so the number the page prints is cards
        #that would have been offered, not everything the vector walk touched
        cmc = meta[oid]["cmc"]
        if mv_lo is not None and cmc is not None and not (mv_lo <= cmc <= mv_hi):
            offband += 1
            continue
        #a pair reusing a line already shown is skipped, so the count means
        #genuinely different abilities matched
        more = []
        used_ours, used_theirs = [ours], [theirs]
        for p in pairs[1:]:
            if p[2] in used_ours or p[3] in used_theirs:
                continue
            used_ours.append(p[2])
            used_theirs.append(p[3])
            more.append('"' + p[3] + '" (' + str(mech_display(p[1])) + '%) matches "' + p[2] + '"')
        #every figure carried against the card LEAVING, the anchor here in the way
        #the searched card is the anchor on /search
        row = swap_card_json(meta[oid], currency, anchor=card)
        #the tooltip only claims to break a blend apart when there was one
        row.update({"match": pct, "their_line": theirs, "our_line": ours,
                    "blended": blending, "mech_pct": mech_pct, "concept_pct": concept_pct,
                    "concept_tags": ", ".join(shared.get(oid, [])[:3]),
                    "more_count": len(more), "more_text": "\n".join(more)})
        out.append(row)
    #the axis is NOT a tiebreak here, being already a gate: everything in this
    #list is a genuine improvement, so the only question left is which is closest
    out.sort(key=lambda c: -c["match"])
    #the held-back count rides back WITH the list, because it cannot be recovered
    #from it later: those cards are gone by then
    return out[:SWAP_OFFER_DEEP], offband, (mv_lo, mv_hi)


def read_axis():
    #falls back to the default rather than erroring: an unknown field is a stale
    #link, not an attack.
    #
    #a "goal" of "price:asc" says it in ONE field, which is what the modes picker
    #sends: "cheaper" is a field AND a direction, and two dropdowns would allow
    #"price" and "newer". the pair is still accepted, every link sending it
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
    ids, missing, copies = parse_decklist(text)
    if not ids:
        #through deck_hub like the other two, rather than rendering hub.html
        #here. building the front door inline instead means a second board
        #lookup and a second set of arguments that can quietly stop matching the
        #function whose whole job is that an error state never drifts into
        #looking like a different page
        return deck_hub(error=("None of those lines matched a card." if text.strip()
                               else "Paste a decklist first."),
                        pasted=text[:DECK_MAX_CHARS], missing=missing)
    cur = read_currency()
    with pool.connection() as conn:
        cards = deck_swappable(conn, ids, cur)
        colors = deck_colors(conn, ids)
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
                           #neither count nor the unmatched lines are drawn here:
                           #this page walks cards, and both were settled on the
                           #page before it
                           cur=cur,
                           deck_name=name, commander=commander, batch=SWAP_QUEUE,
                           offer=SWAP_OFFER,
                           pasted=text[:DECK_MAX_CHARS],
                           #which saved deck this is, so every swap made here
                           #writes itself onto the deck it belongs to rather
                           #than onto whichever entry holds a matching list
                           did=deck_did())


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
    #the two pickers' answers, in the same shapes /search reads off its url.
    #lines arrive as INDEXES, exactly like ?lines=0,2 does, so the browser never
    #has to send a rules line back to us and build_lines stays the one place
    #that turns an index into the text the tables are keyed on
    picked_idx = set()
    for x in (body.get("lines") or [])[:40]:
        if str(x).strip().lstrip("-").isdigit():
            picked_idx.add(int(str(x).strip()))

    def tags(key):
        v = body.get(key)
        return [str(x)[:120] for x in v][:60] if isinstance(v, list) else []
    dropped, forced = tags("notags"), tags("yestags")

    cur = read_currency()
    with pool.connection() as conn:
        #aliased c because price_col hands back a c-qualified column name, so
        #every query reading a price has to call the table the same thing.
        #the full CARD_FIELDS rather than the numbers a verdict needs, the panel
        #above the suggestions being the same one /search draws
        row = conn.execute("SELECT " + ", ".join("c." + f for f in CARD_FIELDS.split(", ")) +
                           ", c.cmc, " + price_col(cur) +
                           " AS price FROM cards c WHERE c.oracle_id = %s",
                           (oid,)).fetchone()
        if row is None:
            abort(404)
        card = dict(row)
        panel = anchor_panel(conn, card, cur, picked_idx, dropped, forced, mode="swap")
        #the TEXTS the picker resolved to, which is what the line table is keyed
        #on. read back out of anchor_panel rather than done twice
        picked = [l["text"] for l in panel["card_lines"] if l["selected"]]
        picked = [clean_line(t, card["name"]) for t in picked]
        cards, offband, mv = swap_candidates(conn, card, deck_ids, colors, field, direction,
                                             currency=cur, picked=picked, dropped=dropped, forced=forced)
    #an empty list is a REAL answer, not a miss, so it comes back as one.
    #
    #the panel rides back as RENDERED HTML, never as data the browser rebuilds,
    #which keeps partials/anchorcard.html the only description of this card
    #anywhere. offband and mv let the page name the cards held back for their cost
    #rather than printing a number nobody can check
    return {"cards": cards, "gate": SWAP_GATE, "axis": field, "dir": direction,
            "offband": offband,
            "mv_lo": None if mv[0] is None else int(mv[0]),
            "mv_hi": None if mv[1] is None else int(mv[1]),
            "panel": render_template("partials/anchorcard.html", **panel)}


def card_json(c, currency):
    #layout and image_back are what let the page offer rotate and turn-over
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
    #a RANDOM draw from everything that qualifies, never the top of a ranking.
    #the seen list arrives as a json BODY because after enough dealing it
    #outgrows what a url can carry
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
    #no uniqueness bar: the dealer works from whatever is left rather than from
    #a number anyone has to learn. cards with no searchable lines stay excluded,
    #untagged cards count as 0 on the concept side
    w = BLEND
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
        #the trail arrows show the same blended number a fresh deal would
        w = BLEND
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
    filters = read_filters()
    results, has_more, next_band = find_similar(card["oracle_id"], picked, filters, TIER_CUT, read_sort(), offset,
                                                band=band, currency=filters["cur"],
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
    #salt, which this was SILENT about while filter_sql had bounded it: a
    #missing-card report whose card a salt bound hid came back "nothing hides it,
    #the model just scores it low" and was filed against the model. the review
    #queue is the training set, so a filter the diagnosis cannot see becomes a
    #labelled example that is wrong.
    #unvoted is not mild: a card nobody voted on fails both comparisons, so any
    #bound hides it, the same call price and filter_sql make
    salt = None if card["salt"] is None else float(card["salt"])
    if (filters["smin"] is not None or filters["smax"] is not None) and salt is None:
        reasons.append("nobody has voted on how salty it is, and any salt filter hides unvoted cards")
    elif filters["smin"] is not None and salt < filters["smin"]:
        reasons.append("its salt (" + salt_label(salt) + ") is under your minimum")
    elif filters["smax"] is not None and salt > filters["smax"]:
        reasons.append("its salt (" + salt_label(salt) + ") is over your maximum")
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
    #the page's whole query string rides along like /more's does, so the report is
    #judged against the same anchor, lines, filters and cutoff the user saw.
    #
    #'missing' is a future exam_pairs.md entry, 'misplaced' a future bakeoff_lines.md
    #negative. missing reports are DIAGNOSED before anything is stored: when a
    #filter is what hides the card, the user learns that on the spot and the
    #review queue never hears about it
    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "")
    if kind not in ("missing", "misplaced", "tag"):
        return {"ok": False, "stored": False, "msg": "That report didn't make sense to the server, sorry."}

    card = find_card(request.args.get("q", ""))
    if card is None:
        return {"ok": False, "stored": False, "msg": "Lost track of which card you searched, try reloading the page."}

    reason = str(body.get("reason", "")).strip()[:500]

    filters = read_filters()
    _, picked = build_lines(card, read_picked())
    dropped = read_dropped()
    forced = read_forced()

    #stored only as the day's one-way token, same as the visit counter.
    #
    #read BEFORE the connection is borrowed: the first report of a day reaches
    #todays_salt() through here, which borrows one of its own, and the pool holds
    #FOUR. four reports landing on a day boundary each sit on one and wait for a
    #fifth
    ip = visitor_token(client_ip())

    with pool.connection() as conn:
        #there is no login, so this is all the abuse control there is. an hour,
        #so the token rotating at midnight only ever RESETS the lid
        recent = conn.execute("SELECT count(*) AS n FROM feedback WHERE ip = %s AND ip <> '' AND created_at > now() - interval '1 hour'",
                              (ip,)).fetchone()["n"]
        if recent >= 20:
            return {"ok": False, "stored": False, "msg": "That's a lot of reports for one hour. Thank you, but please come back later."}

        #which model's numbers this report is about, straight from the ingest's bookkeeping
        row = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
        model = row["value"] if row else ""
        snap = dict(filters)
        snap["min"] = TIER_CUT
        snap["sort"] = read_sort()
        #a concept percent scored against a narrowed vector is not the one the
        #full card gives, so a report is unreadable later without knowing which
        #tags made it. BOTH sides: the ones put back shape it as much
        if dropped:
            snap["notags"] = sorted(dropped)
        if forced:
            snap["yestags"] = sorted(forced)
        #scale marker: reports from before 2026-07-15 stored raw-cosine
        #percents, everything after stores calibrated display percents
        snap["cal"] = 1
        #WHICH PAGE it was filed from: "bad match" on /search is about the
        #ranking, the same words on the swap tool are about a card the site
        #PROPOSED, which is a stronger negative. an unknown value is dropped, so
        #the field can never hold whatever was in the url
        src = request.args.get("from", "")
        if src in ("swap",):
            snap["from"] = src

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
            #the number quoted back is the one the PAGE BADGES, not the mech
            #half: a 100% mech match badges 50% here, and "it's already there at
            #100%" reads as the site denying its own page. the database keeps the
            #mech percent and the snapshot the concept half, so the review can
            #still take the blend apart
            shown_pct = expected_pct
            cpct = concept_between(conn, card["oracle_id"], expected["oracle_id"], dropped, picked, forced)
            #none means the anchor had no vector, so the page ranked on rules
            #text alone and the quoted number has to do the same
            if cpct is not None:
                snap["concept_pct"] = cpct
                shown_pct = int(round((1 - BLEND) * expected_pct + BLEND * cpct))
            full = conn.execute("""SELECT color_identity, price_usd, price_eur, cmc, type_line, game_changer, legal_commander, oracle_text, salt
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
            if shown_pct >= TIER_CUT:
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
        #the same split the missing branch makes: the database keeps the mech
        #percent and the snapshot the concept half, the review needing the two
        #axes apart to route a report.
        #the sentence quotes the number the page BADGED. quoting the mech half
        #answers "shows at 92% right now" about a card the page badged 78%
        shown_pct = got_pct
        cpct = concept_between(conn, card["oracle_id"], got["oracle_id"], dropped, picked, forced)
        #a None cpct is the anchor having no vector, which is the ranking's own
        #signal to score on rules text alone. a None got_pct is a card with no
        #searchable lines, which cannot happen for a card that was ON the page,
        #but blending it would 500 rather than say something odd
        if cpct is not None:
            snap["concept_pct"] = cpct
            if got_pct is not None:
                shown_pct = int(round((1 - BLEND) * got_pct + BLEND * cpct))
        conn.execute("""INSERT INTO feedback (kind, anchor_id, anchor_name, got_id, got_name,
                                              got_pct, reason, picked_lines, filters, embed_model, ip)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (kind, card["oracle_id"], card["name"], got["oracle_id"], got["name"],
                      got_pct, reason, "\n".join(picked), json.dumps(snap), model, ip))
        return {"ok": True, "stored": True,
                "msg": "Logged. " + got["name"] + " shows at " + str(shown_pct) +
                       "% right now, and reports like this become the test cases the matcher is graded against."}


#---- the review side of the feedback loop ----

def admin_allowed():
    #no ADMIN_KEY in the environment means no admin pages anywhere, and a
    #wrong key 404s instead of 403 so the page doesn't admit it exists
    return ADMIN_KEY != "" and request.args.get("key", "") == ADMIN_KEY


def report_markdown(r, line_texts, n):
    #one accepted report in the shape exam_pairs.md uses, ready to paste. missing
    #becomes a should-match entry, misplaced a should-NOT one; promotion into
    #bakeoff_lines.md happens by hand. the anchor quotes only the PICKED lines when
    #the report came from a line-picked search
    def q(lines):
        if not lines:
            return "`(card no longer in the database)`"
        return " + ".join("`" + t + "`" for t in lines)

    if r["picked_lines"]:
        anchor_lines = r["picked_lines"].split("\n")
    else:
        anchor_lines = line_texts.get(r["anchor_id"], [])
    day = r["created_at"].strftime("%Y-%m-%d")

    #the stored pcts are always MECHANICAL, and the page badged a blend, so the
    #concept half is what makes the two numbers add up. a report judged on it is
    #often an exam_concepts.md entry rather than an exam_pairs.md one.
    #
    #absent on the oldest rows, and on any card whose anchor had no vector: the
    #ranking dropped to rules text there, so the mech percent IS what was badged
    mode = ""
    try:
        snap = json.loads(r["filters"] or "{}")
    except ValueError:
        snap = {}
    if "concept_pct" in snap:
        mode = "; concept score " + str(snap["concept_pct"]) + "% (user saw the blend) - consider exam_concepts.md"

    #a tag report is not an exam_pairs.md entry at all. it belongs in the LABELS dict
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
        usage = [{"day": today.isoformat(), "uniques": live}]
        for u in conn.execute("SELECT day, uniques FROM visit_daily ORDER BY day DESC LIMIT 60"):
            usage.append({"day": u["day"].isoformat(), "uniques": u["uniques"]})

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
        #WHERE it was reported from, on its own line rather than left buried in
        #the filters json. a bad match on /search is a complaint about the
        #ranking; the same words from the swap tool are about a card the site
        #actively proposed for somebody's deck, which is the stronger claim and
        #the more useful negative, so a reviewer should not have to go looking
        source = ""
        try:
            snap = json.loads(r["filters"] or "{}")
            if r["kind"] == "tag":
                tag_was = snap.get("tag_was", "")
            source = snap.get("from", "")
        except ValueError:
            pass
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
            "tag": r["tag"], "tag_was": tag_was, "source": source,
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


#one query, tiered like find_card: the substring tiers read alphabetically, the
#fuzzy tier closest-first (its alphabetical CASE key is NULL, which sorts after
#every real name). the HOTTEST route on the site, firing on every pause in typing
#SHOW and ROWS differ because the odd card name occurs twice in the pool and the
#duplicates collapse HERE, every ordering key being derived from the name.
#asking for exactly the eight shown meant every duplicate cost a row off the end,
#so this quietly handed back seven suggestions, or six. the spare four are free:
#the LIMIT is where the index walk stops, and it is the same walk either way
SUGGEST_SHOW = 8
SUGGEST_ROWS = 12


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
            LIMIT %s
        """, (p, s, p, s, q, s, q, SUGGEST_ROWS)):
            if row["name"] not in names:
                names.append(row["name"])
                if len(names) == SUGGEST_SHOW:
                    break
    return {"names": names}


#---- error pages ----
#these catch abort() and unmatched paths. a view returning its own (page, 404)
#does NOT come through here, which is how /search keeps its own miss page


@app.errorhandler(404)
def page_missing(e):
    return render_template("error.html", heading="That page isn't here",
                           message="The link may be wrong, or the page may have moved."), 404


@app.errorhandler(500)
def page_broke(e):
    #safe while the database is the thing that broke: base.html queries nothing
    return render_template("error.html", heading="Something went wrong",
                           message="That one is our fault. Try it again in a moment."), 500


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
