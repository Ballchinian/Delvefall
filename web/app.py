#the actual website. the old version loaded a 90mb embedding matrix into
#memory at startup, this one just asks postgres. the embeddings live in the
#database and pgvector does the similarity math right where the data is, so
#this process stays tiny and never touches torch

import io
import re
import os
import csv
import math
import time
import uuid
import json
import random
import hashlib
import secrets
import datetime
import unicodedata
import urllib.request
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, redirect, abort, make_response, url_for, Response
from flask_compress import Compress
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from db import pool
from prefix_words import PREFIX_WORDS

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
CARD_FIELDS = "oracle_id, name, mana_cost, type_line, oracle_text, image, scryfall_uri, price_usd, price_eur, layout, image_back, edhrec_rank, salt"

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

#copied from common/cards.py because railway only deploys the web folder.
#these three have to stay identical to what the ingest used, otherwise the
#line picker cant match the lines shown on the page back to their rows in the
#database. see common/cards.py for why the keyword list looks like this
REMINDER_KEYWORDS = {
    "overload", "cascade", "storm", "cycling", "flashback", "morph", "disguise",
    "madness", "convoke", "delve", "buyback", "entwine", "replicate", "embalm",
    "eternalize", "unearth", "disturb", "blitz", "bargain", "craft", "mutate",
    "foretell", "bestow", "improvise", "emerge", "evoke", "dash", "spectacle",
    "surge", "escalate", "splice", "rebound", "conspire", "retrace", "miracle",
    "ninjutsu", "prowl", "transmute", "scavenge", "encore", "outlast",
}

_BARE_KEYWORD = re.compile(r"[A-Za-z][A-Za-z'’ -]*(?:\s*\{[^}]*\})*")


def reminder_is_the_rule(stripped):
    text = stripped.strip().rstrip(".")
    if not text:
        return False
    for part in text.split(","):
        part = part.strip()
        if part and not _BARE_KEYWORD.fullmatch(part):
            return False
    first = re.split(r"[^A-Za-z'’-]", text, maxsplit=1)[0].lower()
    return first in REMINDER_KEYWORDS


def clean_line(line, card_name):
    stripped = re.sub(r"\(.*?\)", "", line)
    if reminder_is_the_rule(stripped):
        line = line.replace("(", "").replace(")", "")
    else:
        line = stripped
    #flavour prefixes go, exactly like the ingest side: die-roll rows, saga
    #chapters, and scryfall's catalog of ability/flavor words before a dash
    line = re.sub(r"^\d+(?:—\d+)?\s*\|\s*", "", line)
    line = re.sub(r"^[IVX]+(?:, [IVX]+)*\s+—\s+", "", line)
    m = re.match(r"^([^—•|]{1,40}?)\s+—\s+(?=\S)", line)
    if m and m.group(1) in PREFIX_WORDS:
        line = line[m.end():]
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


#lines like "Flying" appear on thousands of cards, and if we don't do anything
#about it every flying creature "matches" every other flying creature at 100%
#and the results are useless. so common lines get weighted down when ranking.
#basically a homemade version of idf from search engines.
#
#the old curve started punishing at count 2, which buried exactly the best
#results: a line shared by 2 cards means someone printed a functional reprint
#of it, and that reprint is the match people came for. so nothing gets
#punished until a line is on more than 5 cards, then it falls off gently
def line_weight(count):
    if count <= 5:
        return 1.0
    return 1.0 / (1.0 + math.log10(count / 5.0))


#which column the searches read their vectors out of. the point is that trying
#a new embedding model stops being a one way door: the new vectors go into
#embedding_v2 (see common/schema.sql), this flips the site over to them, and
#unsetting it flips straight back with the old numbers still sitting there.
#
#the value lands INSIDE sql strings, so it is checked against a fixed list
#rather than trusted. anything else and we would be one typo in a railway
#variable away from an injection point on every search.
#
#defined UP HERE, above the calibration, because load_calibration reads it to
#decide which map belongs to the column being served
EMBED_COLUMNS = ("embedding", "embedding_v2")


def embed_column():
    col = os.environ.get("EMBED_COLUMN", "").strip() or "embedding"
    if col not in EMBED_COLUMNS:
        raise ValueError("EMBED_COLUMN must be one of " + ", ".join(EMBED_COLUMNS))
    return col


EMBED_COL = embed_column()


#axis 2: how conceptually close two cards are, scored from the community
#tags the ingest bakes into card_tags/tags. the raw cosine lives in a
#compressed band, this map turns it into the percent the site shows, and
#the gate is written in displayed units on purpose.
#
#this and MECH_CALIBRATION below are SEEDS: the ingest writes the real maps
#into meta next to the model name they're anchored to, and load_calibration
#(further down, once both are defined) makes the database's word win. these
#only hold until the first ingest run against a database, and a model swap
#carries its new map along with its new vectors automatically
CALIBRATION = [(0.0, 0), (0.13, 35), (0.26, 55), (0.45, 70), (0.59, 82), (0.68, 90), (1.0, 100)]


def concept_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100


def concept_raw_gate(pct):
    #the map walked backwards, so the displayed gate becomes a raw sql cutoff
    pct = max(0, min(100, pct))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if pct <= y1:
            return x0 + (x1 - x0) * (pct - y0) / (y1 - y0)
    return 1.0


#the mechanical axis wears a calibration map too, same shape as the concept
#one. raw cosine is arbitrary per model, so the displayed percent is pinned
#to judged pairs instead. the map is anchored to the tuned embeddinggemma
#the ingest embeds with, and the full story of the anchors lives next to
#EMBED_MODEL in ingest/update.py, which is the source of truth that lands
#in meta. this copy is the seed for databases the ingest hasn't touched yet
MECH_CALIBRATION = [(0.0, 0), (0.30, 30), (0.42, 45), (0.62, 65), (0.76, 80), (0.90, 92), (1.0, 100)]


def load_calibration():
    #the maps the ingest wrote into meta replace the seeds above, so the
    #percents the site shows always belong to the model that made the
    #vectors. a database the ingest has never run against has no meta rows
    #(maybe no meta table), then the seeds hold.
    #
    #a trial column needs its OWN map, or every percent on the page is a lie:
    #cosines sit in a different band per model, and the meta row belongs to
    #whichever model filled lines.embedding. so when EMBED_COLUMN points
    #somewhere else, prefer a key suffixed with it, and fall back to the
    #shared one where a trial has not been calibrated yet. measured
    #2026-07-22: without this a near verbatim match read 62% under the trial
    #model where the refit puts it at 77%
    global CALIBRATION, MECH_CALIBRATION
    suffix = "" if EMBED_COL == "embedding" else "_" + EMBED_COL
    try:
        with pool.connection() as conn:
            for key in ("concept_calibration", "mech_calibration"):
                row = None
                if suffix:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s",
                                       (key + suffix,)).fetchone()
                if row is None:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
                if row:
                    pts = [(float(x), float(y)) for x, y in json.loads(row["value"])]
                    if key == "concept_calibration":
                        CALIBRATION = pts
                    else:
                        MECH_CALIBRATION = pts
    except Exception:
        pass


load_calibration()


def mech_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(MECH_CALIBRATION, MECH_CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100


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
    #template rather than the handful that pass them explicitly
    return {"line_tags_on": LINE_TAGS, "kofi_url": KOFI_URL, "running_cost": RUNNING_COST}


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


CURRENCY_SIGNS = {"usd": "$", "eur": "€", "gbp": "£"}

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
    #empty when the card has no price there. dollars and euros print the
    #stored number as is, pounds are computed so they get pinned to pennies
    if currency == "gbp":
        p = price_in(c, currency)
        return "" if p is None else "£%.2f" % p
    p = c["price_usd"] if currency == "usd" else c["price_eur"]
    if p is None:
        return ""
    return CURRENCY_SIGNS[currency] + str(p)


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
    "released": {"label": "Release date", "default": "desc",
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
    #its form, /unique deals and trail-walks through fetch)
    cur = request.args.get("cur")
    if cur in CURRENCY_SIGNS:
        resp.set_cookie("cur", cur, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


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
                 anchor_salt=None):
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
        #the two little arrows: which side of the searched card this result
        #sits on for money and for how much the format plays it. a comparison
        #is the one thing these numbers honestly support on their own, and
        #both tooltips name the card being compared against
        price_vs = price_verdict(price_in(c, currency), anchor_price)
        rank_vs = rank_verdict(c["edhrec_rank"], anchor_rank)
        salt_vs = salt_verdict(c["salt"], anchor_salt)
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
    #source column for the same reason
    card["salt_text"] = salt_label(card["salt"])
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
                                                anchor_salt=card["salt"])
    resp = make_response(render_template("search.html", query=query, card=card, card_lines=card_lines,
                                         picked_count=len(picked), results=results, has_more=has_more,
                                         next_band=next_band, min_pct=min_pct, errors=filters["errors"],
                                         blend=blend, cur=filters["cur"], types=CARD_TYPES,
                                         tag_chips=chips, dropped_count=sum(1 for c in chips if c["state"] == "off"),
                                         aside_count=sum(1 for c in chips if c["state"] == "aside"),
                                         line_tags_on=LINE_TAGS,
                                         sort_fields=SORT_FIELDS, sort_field=sort_field,
                                         sort_dir=sort_dir))
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
#a third lands at 20.3 cards on the average precon, so the board it produces
#is the one that was there before, just distributed fairly
PRECON_TOP_FRAC = 1.0 / 3.0

#how deep the board can be read, for the curious. the default is first.
#raising it does NOT make the number more accurate, which is worth knowing
#before reaching for it: every step costs discrimination (spread 0.143 at a
#third, 0.103 using everything) because the cards being added are the ones
#every deck shares. the ranking itself barely moves, the ends not at all
PRECON_DEPTHS = [
    ("third", "Top third", 1.0 / 3.0),
    ("half", "Top half", 0.5),
    ("threequarters", "Top three quarters", 0.75),
    ("all", "Every card", 1.0),
]

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

#what the board can be ranked by. each entry is the key, the button label, the
#row key holding the number, the row key holding its top cards, the label for
#the list under each row, how many decimals the figure wants, and WHICH WAY IS
#BEST.
#
#that last one is new and it is not decoration: "most played" is the LOWEST
#median rank, because rank 1 is the most played card in the format. the board
#sorted descending on everything until now because every number it held
#happened to be better when bigger
PRECON_SORTS = [
    ("original", "Most original", "originality", "drivers", "Most original cards", 3, "desc"),
    ("salt", "Saltiest", "salt", "salt_drivers", "Saltiest cards", 1, "desc"),
    ("price", "Most expensive", "price", "price_drivers", "Priciest cards", 2, "desc"),
    ("played", "Most played", "play_median", "play_drivers", "Most played cards", 0, "asc"),
    ("age", "Oldest cards", "age_mean", "age_drivers", "Oldest cards", 1, "desc"),
]

#same shape as the seed cache: the board is identical for everyone and only
#moves when the ingest reruns, so it is worth an hour of not asking.
#
#the query costs ~600ms against railway from home, measured 2026-07-26. it was
#~130ms when it computed two numbers, and five aggregates over deck_cards is what
#the other 470 bought. that is far too much to pay per visit and nothing to pay
#once an hour, which is the whole reason this cache exists, but it does mean a
#cold board is a visibly slow page rather than an imperceptibly slow one.
#
#keyed by depth AND currency. only the four in PRECON_DEPTHS and the three in
#CURRENCY_SIGNS can ever get in, so twelve entries is the ceiling and the url
#cannot grow this without bound
_precon_cache = {}


def precon_board(frac=PRECON_TOP_FRAC, currency="usd"):
    #keyed by currency as well as depth now, because the price total is a real
    #sum in one currency rather than a number that can be converted afterwards:
    #pounds are derived per CARD from whichever of the two prices that card
    #has, so a pound total is not the dollar total times a rate
    key = (frac, currency)
    hit = _precon_cache.get(key)
    if hit and time.time() - hit["at"] < 3600:
        return hit["rows"]
    try:
        with pool.connection() as conn:
            #filled at query time, never baked into the constant: price_col
            #builds the pound expression out of the DAY'S rates, and a module
            #level string would freeze whatever they were at import
            sql = PRECON_SQL.replace("__PRICE__", price_col(currency))
            rows = [dict(r) for r in conn.execute(sql, (frac,)).fetchall()]
    except Exception:
        return hit["rows"] if hit else []
    _precon_cache[key] = {"at": time.time(), "rows": rows}
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
    #an unknown sort falls back to originality rather than 404ing, same as
    #every other url reader here
    swant = request.args.get("sort", "original")
    sort = next((s for s in PRECON_SORTS if s[0] == swant), PRECON_SORTS[0])
    skey, driver_key, best = sort[2], sort[3], sort[6]
    #how deep to read each deck. only the listed keys resolve, so the cache
    #cannot be grown from the url
    dwant = request.args.get("depth", "third")
    depth = next((d for d in PRECON_DEPTHS if d[0] == dwant), PRECON_DEPTHS[0])

    cur = read_currency()
    rows = []
    for r in precon_board(depth[2], cur):
        year = r["release_date"].year if r["release_date"] else 0
        if lo is not None and not (lo <= year <= hi):
            continue
        #a deck with no salt at all cannot be placed on a salt board, and
        #sorting None against floats would raise rather than degrade
        if r.get(skey) is None:
            continue
        rows.append(dict(r, year=year, figure=float(r[skey]),
                         cards=r.get(driver_key) or []))
    #ascending when a SMALLER number is the better one, which so far is only
    #play rate: rank 1 is the most played card in the format
    rows.sort(key=lambda r: (r["figure"] if best == "asc" else -r["figure"], r["name"]))

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
            if best == "asc":
                share = 1.0 - share
            #every bar keeps a visible stub, or the last row reads as a
            #missing value rather than as the least original deck
            r["fill"] = 8 + 92 * share if span else 100
    return render_template("precons.html", rows=rows, eras=PRECON_ERAS, era=era[0],
                           sorts=PRECON_SORTS, sort=sort[0], sort_label=sort[4],
                           decimals=sort[5], depths=PRECON_DEPTHS, depth=depth[0],
                           depth_label=depth[1], cur=cur,
                           #the figure's units. price needs the sign of
                           #whichever currency the toggle is showing, age needs
                           #a word or "12.4" means nothing, play rate needs the
                           #hash that says "rank" everywhere else on the site
                           prefix={"price": CURRENCY_SIGNS[cur], "played": "#"}.get(sort[0], ""),
                           suffix=(" years" if sort[0] == "age" else ""))


#the idf weight from line_weight() written in sql, so the deck queries below
#can rank inside postgres instead of hauling every pair back here. same curve:
#nothing is punished until a line is on more than 5 cards, then it falls off
#gently. it MUST stay in step with line_weight, which is why the python one is
#the doc comment and this is the transcription
LINE_WEIGHT_SQL = ("CASE WHEN coalesce(s.count, 1) <= 5 THEN 1.0"
                   " ELSE 1.0 / (1.0 + log(coalesce(s.count, 1) / 5.0)) END")

#every card in one deck, each against the closest thing in the SAME deck. it
#is cards.uniqueness with the universe swapped from all 31k cards to the other
#99 here, which is a different and more useful question on a decklist: not
#"has anyone printed this before" but "does anything else in MY deck do this".
#
#at ~100 cards this is ~250 lines, so the all-pairs the ingest has to do in
#numpy overnight is a 250x250 join here, 160-215ms measured against railway on
#the wordiest precons. that is the whole reason the lens can be a page and not
#a batch job.
#
#the weights are why the pairings are readable. unweighted, every top pair was
#two lands sharing "This land enters tapped." (438 cards) or two rocks sharing
#a mana ability (831): technically the nearest neighbour, useless as "these do
#the same job". weighting both sides by the line's rarity buries all of it
#it takes a LIST OF IDS rather than a deck slug so the pasted-list path and
#the precon pages run the exact same query. that is not tidiness: it means the
#166 precon pages are a standing test of the code the paste box depends on
DECK_PAIRS_SQL = """
WITH dl AS (
    SELECT l.id, l.oracle_id, l.line_text, l.""" + EMBED_COL + """ AS embedding,
           """ + LINE_WEIGHT_SQL + """ AS w
    FROM lines l
    LEFT JOIN line_stats s ON s.line_text = l.line_text
    WHERE l.oracle_id = ANY(%s::uuid[]) AND NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL
),
scored AS (
    SELECT DISTINCT ON (a.id) a.id, a.oracle_id, a.line_text, b.oracle_id AS partner,
           1 - (a.embedding <=> b.embedding) AS raw,
           (1 - (a.embedding <=> b.embedding)) * a.w * b.w AS weighted
    FROM dl a JOIN dl b ON b.oracle_id <> a.oracle_id
    ORDER BY a.id, (1 - (a.embedding <=> b.embedding)) * a.w * b.w DESC
),
per_card AS (
    SELECT DISTINCT ON (oracle_id) oracle_id, line_text, partner, raw, weighted
    FROM scored ORDER BY oracle_id, weighted DESC
)
SELECT c.name, c.type_line, c.uniqueness AS global_u, c.oracle_id,
       p.line_text, p.weighted, pc.name AS partner_name
FROM per_card p
JOIN cards c ON c.oracle_id = p.oracle_id
LEFT JOIN cards pc ON pc.oracle_id = p.partner
ORDER BY p.weighted DESC
"""

#how close two cards have to sit before the page says they do the same job.
#0.75 was picked by reading the pairings on a dozen decks: above it they are
#things like Nekusar/Spiteful Visions and Fog Bank/Guard Gomazoa, below it
#they start being two cards that merely share a rider. the site's own result
#gate is 70, and this is deliberately STRICTER, because there the user judges
#a list and here the page is making the claim itself
DECK_PAIR_CUT = 0.75

#how many cards the detail page lists per section. enough to read as evidence,
#short enough that nobody scrolls a 100 row table looking for the point
DECK_SECTION = 12

_deck_cache = {}


def lens_rows(oracle_ids):
    #the lens over any pile of cards. no caching here: the precon path caches
    #by slug below, and a pasted list is seen once and never again
    if not oracle_ids:
        return []
    try:
        with pool.connection() as conn:
            return [dict(r) for r in conn.execute(DECK_PAIRS_SQL, ([str(o) for o in oracle_ids],)).fetchall()]
    except Exception:
        return []


def deck_detail(slug):
    #cached per deck for an hour, same as the board. the numbers only move
    #when the ingest reruns or the model changes, and the query is far too
    #heavy to pay for on every visit
    hit = _deck_cache.get(slug)
    if hit and time.time() - hit["at"] < 3600:
        return hit["rows"]
    try:
        with pool.connection() as conn:
            ids = [r["oracle_id"] for r in
                   conn.execute("SELECT oracle_id FROM deck_cards WHERE deck_slug = %s", (slug,)).fetchall()]
    except Exception:
        return []
    rows = lens_rows(ids)
    _deck_cache[slug] = {"at": time.time(), "rows": rows}
    return rows


def lens_sections(cards):
    #the two readings both pages show, from one query's rows. lands are left
    #out for the same reason they are left out of the score: a mana base is
    #not what makes a deck a deck, and left in they fill both lists with duals
    #pairing with other duals
    spells = [c for c in cards if "Land" not in (c["type_line"] or "")]
    original = sorted(spells, key=lambda c: -(c["global_u"] or 0))[:DECK_SECTION]

    #the pair list names both sides, so without the dedup the same partnership
    #prints twice facing opposite ways (Nekusar/Spiteful, Spiteful/Nekusar)
    seen, pairs = set(), []
    for c in spells:
        if c["weighted"] < DECK_PAIR_CUT:
            break
        key = frozenset((c["name"], c["partner_name"]))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(c)
        if len(pairs) >= DECK_SECTION:
            break
    return spells, original, pairs


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
    vals = sorted((c["global_u"] for c in cards
                   if "Land" not in (c["type_line"] or "") and c["global_u"] is not None),
                  reverse=True)
    if not vals:
        return 0.0
    keep = max(1, round(len(vals) * frac))
    vals = vals[:keep]
    return sum(vals) / len(vals)


#how many of the deck's salt sources the page names. the total is the headline
#and this is what it is MADE of, which is the part anyone can act on
SALT_SECTION = 10


def salt_standing(total):
    #how many precons this deck is SALTIER than, plus the population size, so
    #the page can say it in words rather than printing a bare number. reads
    #the one board rather than keeping a second cache of the same decks
    totals = [r["salt"] for r in precon_board() if r["salt"] is not None]
    if not totals:
        return None
    return {"saltier_than": sum(1 for t in totals if t < total), "total": len(totals)}


def deck_salt(oracle_ids):
    #the salt tally: what this pile of cards is worth on edhrec's annoyance
    #poll. its own query rather than a read off the lens rows, because the
    #lens only sees cards with rules LINES and a basic land has none, so half
    #a mana base would silently go missing from a total that claims to count
    #everything.
    #
    #counted per DISTINCT card, not per copy. salt is how much a card annoys
    #the table and nine Islands are not nine times the annoyance of one, and
    #it is also the only way this can agree with the pasted path, which drops
    #counts on the way in
    if not oracle_ids:
        return 0.0, []
    try:
        with pool.connection() as conn:
            rows = conn.execute("""
                SELECT name, salt, type_line FROM cards
                WHERE oracle_id = ANY(%s::uuid[]) AND salt IS NOT NULL
                ORDER BY salt DESC
            """, ([str(o) for o in oracle_ids],)).fetchall()
    except Exception:
        return 0.0, []
    if SALT_SKIP_BASICS:
        rows = [r for r in rows if not is_basic_land(r["type_line"])]
    total = sum(r["salt"] or 0 for r in rows)
    return total, [dict(r) for r in rows[:SALT_SECTION]]


@app.route("/precons/<slug>")
def precon(slug):
    #one deck read through the lens. this is the view a PASTED list will get
    #too, which is the point of building it here first: the precons are 166
    #worked examples of what the paste box does, and the template is the same
    #either way
    board = precon_board()
    place = None
    deck_row = None
    for i, r in enumerate(board, 1):
        if r["slug"] == slug:
            place, deck_row = i, r
            break
    if deck_row is None:
        abort(404)

    spells, original, pairs = lens_sections(deck_detail(slug))
    #the salt tally reads the WHOLE deck, not the lens rows: it counts lands,
    #and a basic land has no rules lines to appear in the lens with
    with pool.connection() as conn:
        ids = [r["oracle_id"] for r in
               conn.execute("SELECT oracle_id FROM deck_cards WHERE deck_slug = %s", (slug,)).fetchall()]
    #the CARD LIST comes off that query, the TOTAL comes off the board row.
    #adding it up again here added in python the same numbers postgres had
    #already added as real, and sum(real) accumulates in float32 where python
    #is float64, so on a 62 card deck the two land about 7e-07 apart. that is
    #nothing anywhere except against the deck's OWN entry in the board, which
    #is what salt_standing walks, and there it decided whether the deck came
    #out saltier than itself
    _, salt_cards = deck_salt(ids)
    salt_total = deck_row["salt"] or 0.0
    year = deck_row["release_date"].year if deck_row["release_date"] else 0
    return render_template("precon.html", deck=deck_row, place=place, total=len(board),
                           year=year, original=original, pairs=pairs,
                           counted=len(spells),
                           salt_total=salt_total, salt_cards=salt_cards,
                           salt_rank=salt_standing(salt_total))


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
                          r"considering|tokens?|creatures?|lands?|instants?|sorceries|"
                          r"artifacts?|enchantments?|planeswalkers?|battles?)\b[:\s]*$", re.I)
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
    if "," not in head:
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
              AND NOT """ + basic + """) AS age_cards,
          (SELECT array_agg(x.name) FROM (SELECT c.name FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND """ + price_col(currency) + """ IS NOT NULL
            ORDER BY """ + price_col(currency) + """ DESC LIMIT 3) x) AS price_drivers,
          (SELECT array_agg(x.name) FROM (SELECT c.name FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.edhrec_rank IS NOT NULL
              AND c.type_line NOT LIKE '%%Land%%'
            ORDER BY c.edhrec_rank LIMIT 3) x) AS play_drivers,
          (SELECT array_agg(x.name) FROM (SELECT c.name FROM cards c
            WHERE c.oracle_id = ANY(%s::uuid[]) AND c.released_at IS NOT NULL
              AND NOT """ + basic + """
            ORDER BY c.released_at LIMIT 3) x) AS age_drivers
    """, (ids, ids, ids, ids, ids, ids, ids, ids)).fetchone()
    return dict(row) if row else {}


def deck_standing(board, key, best, figure):
    #where the deck lands on the board, and who it landed between.
    #
    #"better" is the axis's own direction rather than bigger-is-better, which
    #is the whole reason the board learned one: on play rate a SMALLER median
    #is more played, and a standing that got that backwards would tell someone
    #their pile of staples was the most obscure deck in the format
    if figure is None:
        return None
    rows = [r for r in board if r.get(key) is not None]
    rows.sort(key=lambda r: (float(r[key]) if best == "asc" else -float(r[key]), r["name"]))
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
    return {"place": better + 1, "beaten": len(rows) - better,
            "total": len(rows), "window": window}


def deck_hub(error=None, pasted="", url="", missing=None):
    #the front door, rendered the same way whether it is being visited or
    #being returned to with a complaint. one function so an error state can
    #never drift into looking like a different page
    board = precon_board()
    return render_template("deck.html", deck_count=len(board),
                           example=board[0] if board else None,
                           error=error, pasted=pasted, url=url, missing=missing)


#the three pages below are rendered from a POST and have no url of their own,
#which is the privacy decision and it stays: a pasted list is nobody's business
#and there is nothing to come back to. answering a bare GET with a 405 was
#never part of that decision though, it is just what werkzeug does when no
#rule matches. a back button, a bookmark or a link someone shared all arrive
#as a GET, so they get the front door with the paste box on it
@app.route("/deck/open", methods=["GET"])
@app.route("/deck/read", methods=["GET"])
@app.route("/deck/swap", methods=["GET"])
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
    commanders, deck_name = [], ""
    if url:
        deck_id = archidekt_id(url)
        if not deck_id:
            return deck_hub(error="That doesn't look like an Archidekt deck link. "
                                  "It should look like archidekt.com/decks/1234567.", url=url)
        if not import_allowed(import_token()):
            #one message for both lids on purpose. "you have imported a lot"
            #and "the site has imported a lot" are different facts but the same
            #instruction, and the paste box below answers either one
            return deck_hub(error="Too many deck imports just now, so we're giving "
                                  "Archidekt a rest. Try again in a minute, or paste the "
                                  "list below and carry on.", url=url)
        try:
            text, commanders, deck_name = archidekt_deck(deck_id)
        except Exception:
            #deliberately one message for every failure mode. archidekt being
            #down, the deck being private and their api changing shape are the
            #same event to someone holding a link that did not work, and the
            #paste box underneath is the answer to all three
            return deck_hub(error="Couldn't fetch that deck from Archidekt. It may be "
                                  "private, or Archidekt may be having a moment. "
                                  "Pasting the list below always works.", url=url)
    if not text.strip():
        return deck_hub(error="Paste a decklist, or give an Archidekt link.")

    ids, missing = parse_decklist(text)
    if not ids:
        return deck_hub(error="None of those lines matched a card.",
                        pasted=text[:DECK_MAX_CHARS], url=url, missing=missing)
    #the two modes, offered rather than assumed. it costs a click and buys the
    #confirmation that the list arrived intact, which is the thing an IMPORT
    #most needs: a link that silently read 40 of your 100 cards is the failure
    #nobody notices until the numbers look wrong
    return render_template("deck_modes.html", pasted=text[:DECK_MAX_CHARS],
                           matched=len(ids), missing=missing,
                           commanders=commanders, deck_name=deck_name,
                           swap_axes=SWAP_AXES, swap_default=SWAP_DEFAULT)


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
    cards = lens_rows(ids)
    spells, original, pairs = lens_sections(cards)

    #the number only means something against the precons, which is what the
    #whole calibration set was for. beaten counts how many it is MORE original
    #than, so the sentence reads the way a person would say it. a list too
    #short to compare fairly gets the sections and no ranking, rather than a
    #placing that quietly comes from averaging six cards against a hundred
    board = precon_board(currency=cur)
    ranked = len(spells) >= DECK_MIN_FOR_RANK
    score = originality_of(cards) if ranked else 0.0
    #the tally counts the whole pasted list, lands included, off the ids
    #rather than the lens rows for the same reason the precon page does
    salt_total, salt_cards = deck_salt(ids)

    #the five standings, built off the SAME PRECON_SORTS the board is built
    #from. one list drives both pages, so a sort can never exist on the
    #leaderboard and quietly not exist here, and the direction that decides
    #"most played is the smallest number" is stated once
    metrics = []
    if ranked:
        with pool.connection() as conn:
            figures = deck_metrics(conn, ids, cur)
        mine = {"original": score, "salt": salt_total, "price": figures.get("price"),
                "played": figures.get("play_median"), "age": figures.get("age_mean")}
        drivers = {"original": [c["name"] for c in original[:3]],
                   "salt": [c["name"] for c in salt_cards[:3]],
                   "price": figures.get("price_drivers") or [],
                   "played": figures.get("play_drivers") or [],
                   "age": figures.get("age_drivers") or []}
        for key, label, fkey, dkey, dlabel, dp, best in PRECON_SORTS:
            figure = mine.get(key)
            figure = None if figure is None else float(figure)
            stand = deck_standing(board, fkey, best, figure)
            if stand is None:
                continue
            metrics.append(dict(stand, key=key, label=label, figure=figure,
                                decimals=dp, drivers=drivers.get(key) or [],
                                driver_label=dlabel,
                                prefix={"price": CURRENCY_SIGNS[cur], "played": "#"}.get(key, ""),
                                suffix=(" years" if key == "age" else ""),
                                total_years=figures.get("age_total") if key == "age" else None,
                                age_cards=figures.get("age_cards") if key == "age" else None))

    return render_template("deck_read.html", original=original, pairs=pairs,
                           counted=len(spells), matched=len(ids), missing=missing,
                           score=score, total=len(board),
                           ranked=ranked, min_cards=DECK_MIN_FOR_RANK,
                           salt_total=salt_total, salt_cards=salt_cards,
                           metrics=metrics, cur=cur,
                           #handed straight back so the swap tool can be reached
                           #from a reading without pasting twice. it rides the
                           #page rather than a session for the same reason as
                           #everything else here: there is nothing to store
                           pasted=text[:DECK_MAX_CHARS], swap_axes=SWAP_AXES,
                           swap_default=SWAP_DEFAULT)


#----- importing a decklist from a url -----

#archidekt only, deliberately. moxfield has restricted third party api use and
#that needs checking before it goes on a label promising it works, so it is
#absent rather than half done.
#
#archidekt publishes NO official api documentation and calls it open beta, so
#this can change without warning. everything below is written for that: a
#failure says so in words and the paste box is right there underneath, because
#an importer that takes the page down with it when somebody else ships a
#change is worse than no importer
ARCHIDEKT_URL = re.compile(r"^https?://(?:www\.)?archidekt\.com/(?:decks|api/decks)/(\d{1,12})", re.I)

#a slow third party must not become a slow page, and a big response must not
#become our memory problem. a 100 card deck's json runs about 400kb
DECK_IMPORT_TIMEOUT = 10
DECK_IMPORT_MAX_BYTES = 8 * 1024 * 1024


def archidekt_id(url):
    #the deck id, as an integer, and nothing else.
    #
    #this is the whole security design and it is worth being explicit: the
    #user's url is NEVER fetched. an id is pulled out of it and OUR url is
    #built from that id, so there is no redirect to follow, no host to
    #revalidate and no way to point this at localhost or a cloud metadata
    #endpoint. a domain allowlist in front of a fetch of user input is the
    #version of this that keeps being a vulnerability
    m = ARCHIDEKT_URL.match((url or "").strip())
    return m.group(1) if m else None


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


def archidekt_deck(deck_id):
    #(decklist text, commander names, deck name), or raises.
    #
    #it hands back TEXT and lets parse_decklist do the matching, rather than
    #resolving names to cards here. that parser is tested at 100% across 166
    #decks and five export shapes, and a second matching path would be a
    #second thing to get wrong and a second thing to keep in step. the
    #importer's entire job is turning a url into the same thing a paste is
    req = urllib.request.Request(
        "https://archidekt.com/api/decks/%s/" % deck_id,
        headers={"User-Agent": "Delvefall/1.0 (+https://delvefall.com)",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=DECK_IMPORT_TIMEOUT) as r:
        raw = r.read(DECK_IMPORT_MAX_BYTES + 1)
    if len(raw) > DECK_IMPORT_MAX_BYTES:
        raise ValueError("deck too large")
    data = json.loads(raw.decode("utf-8"))

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

#how many cards the queue considers. the whole deck is not worth scanning:
#on any axis only the tail is worth acting on, and a hundred nearest neighbour
#walks to tell someone their Islands are fine is a lot of database for nothing
SWAP_QUEUE = 12

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
#deliberately far below DECK_PAIR_CUT's 0.75. at that value it was not a
#backstop but a second gate, and it removed every mana rock in the game from
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
    return rows[:SWAP_QUEUE]


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
        "released": str(c["released_at"])[:4] if c["released_at"] else "",
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
        return None if v is None else "play rank " + str(v)
    if field == "released":
        v = card.get("released_at")
        return None if v is None else str(v)[:4]
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
    #tool has a sensible thing to do with one
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
        return render_template("deck.html", deck_count=len(precon_board()),
                               example=(precon_board() or [None])[0],
                               error=("None of those lines matched a card." if text.strip()
                                      else "Paste a decklist first."),
                               missing=missing, pasted=text[:DECK_MAX_CHARS])
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
    return render_template("deck_swap.html", queue=queue, deck_ids=[str(i) for i in ids],
                           colors=colors, axis=field, direction=direction,
                           goal=SWAP_AXES[(field, direction)]["goal"],
                           matched=len(ids), missing=missing, cur=cur,
                           pasted=text[:DECK_MAX_CHARS])


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
                                                anchor_salt=card["salt"])
    return {"results": results, "has_more": has_more, "next_band": next_band}


#---- user feedback: "a card is missing" / "this card shouldn't be here" ----

def client_ip():
    #railway's proxy APPENDS the address it saw to X-Forwarded-For, so the
    #last entry is its word and everything left of it is client supplied.
    #reading the first entry would let anyone dodge the report rate limit by
    #sending a made-up header. one proxy deep is a railway fact: putting a
    #cdn in front of the site would add an entry and this needs to move one
    #step left
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.remote_addr or ""


#---- privacy-preserving visitor counting ----
#how many distinct people used the site each day, keeping NOTHING that can be
#traced back to one of them. the recipe is the privacy-first standard (the same
#one plausible and friends use): hash the ip with a salt that ROTATES DAILY and
#is then thrown away. within a day the same visitor collapses to one token; once
#that day's salt is deleted, nobody, us included, can turn the stored tokens
#back into an ip. the raw ip is never written to disk.
#
#done server-side ON PURPOSE. it touches nothing on the visitor's device, so it
#needs no cookie banner, where a localStorage "visited" flag would count as
#non-essential storage the eprivacy rules require consent for. counter-intuitive
#but true: the device-storage route is the more regulated one.

_visit = {"day": None, "salt": None}


def _utc_day():
    return datetime.datetime.now(datetime.timezone.utc).date()


def todays_salt():
    #today's rotating salt, generated once and shared by every worker through
    #the db. the first request of a new day also does the housekeeping: each
    #finished day collapses into a single count in visit_daily and its
    #per-visitor tokens and its salt are deleted. that deletion is what makes
    #yesterday unrecoverable, so only ever an integer survives the day
    day = _utc_day()
    if _visit["day"] == day and _visit["salt"]:
        return _visit["salt"]
    with pool.connection() as conn:
        conn.execute("INSERT INTO visit_salt (day, salt) VALUES (%s, %s) ON CONFLICT (day) DO NOTHING",
                     (day, secrets.token_hex(16)))
        salt = conn.execute("SELECT salt FROM visit_salt WHERE day = %s", (day,)).fetchone()["salt"]
        conn.execute("""INSERT INTO visit_daily (day, uniques)
                        SELECT day, count(*) FROM visit_seen WHERE day < %s GROUP BY day
                        ON CONFLICT (day) DO UPDATE SET uniques = EXCLUDED.uniques""", (day,))
        conn.execute("DELETE FROM visit_seen WHERE day < %s", (day,))
        conn.execute("DELETE FROM visit_salt WHERE day < %s", (day,))
    _visit["day"] = day
    _visit["salt"] = salt
    return salt


def visitor_token(ip):
    #one-way daily fingerprint of an ip, shared by the visit counter and the
    #feedback rate limit so the two never diverge. an empty ip (nothing to
    #hash) stays empty rather than becoming a hash of the salt alone
    if not ip:
        return ""
    return hashlib.sha256((todays_salt() + "|" + ip).encode("utf-8")).hexdigest()


#the routes that count as a page view. the json endpoints are deliberately
#absent: /suggest alone fires on every keystroke and would swamp the number,
#and /more, the unique dealer and the report post are not visits
PAGE_ENDPOINTS = {"home", "search", "unique", "precons", "precon", "deck", "guide", "privacy"}


#the tokens this worker has already written today, so a visitor's second and
#twentieth page view cost nothing. every page view used to borrow one of the
#pool's four connections before the handler had even started, on a search that
#already borrows three for its line scans.
#
#the count stays correct because correctness was never here: the primary key
#on (day, token) is what makes a repeat visit one row, and this only skips
#inserts that would have hit that key and done nothing.
#
#one entry per unique visitor per day per worker, dropped when the day rolls
#over. the cap is a floor under the worst case rather than a real limit, since
#past it the memo stops growing and the inserts go back to being paid for,
#which is what happened before any of this existed
VISIT_MEMO_MAX = 50000

_visit_memo = {"day": None, "seen": set()}


@app.before_request
def count_visit():
    #one insert-or-nothing per new visitor per day. wrapped in a blanket catch
    #because analytics must NEVER be able to break a page: a missing table
    #(fresh deploy before the ingest self-heals) or a db hiccup just means an
    #uncounted visit, never a 500
    if request.method != "GET" or request.endpoint not in PAGE_ENDPOINTS:
        return
    try:
        token = visitor_token(client_ip())
        if not token:
            return
        day = _utc_day()
        if _visit_memo["day"] != day:
            _visit_memo["day"] = day
            _visit_memo["seen"] = set()
        if token in _visit_memo["seen"]:
            return
        with pool.connection() as conn:
            conn.execute("INSERT INTO visit_seen (day, token) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (day, token))
        #memoised only after the insert lands, so a failed one is retried on
        #the next page view rather than being remembered as done
        if len(_visit_memo["seen"]) < VISIT_MEMO_MAX:
            _visit_memo["seen"].add(token)
    except Exception:
        pass


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
    #in finetune/attribution_eval.py, keyed by card name and LINE INDEX, so it
    #is emitted in that shape instead: the index the picked line actually has,
    #and which way the disagreement runs. the line index is what the eval reads,
    #and it is not stored on the report (the text is), so it is looked up here
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
            elif r["kind"] == "misplaced":
                triplet_md.append(report_markdown(r, line_texts, len(triplet_md) + 1))
            else:
                pair_md.append(report_markdown(r, line_texts, len(pair_md) + 1))

    return render_template("admin.html", key=ADMIN_KEY, pending=pending, accepted=accepted,
                           triplet_md="\n".join(triplet_md), pair_md="\n".join(pair_md),
                           tag_md="\n".join(tag_md), usage=usage)


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


#---- crawler plumbing: robots.txt and the sitemap ----

#every card's search page is a landing page, but crawlers can only find
#them by walking result pages link by link. the sitemap hands over the
#whole list of canonical card urls in one file. the names are cached for a
#day (they change on the ingest's schedule, not the request's), the xml is
#rebuilt per request because it embeds whichever host the request came in on
_sitemap_names = {"names": [], "made": 0.0}


@app.route("/sitemap.xml")
def sitemap():
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


@app.route("/robots.txt")
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
        "Sitemap: " + request.url_root + "sitemap.xml",
    ]) + "\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(debug=True)
