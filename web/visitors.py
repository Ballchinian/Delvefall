#---- privacy-preserving visitor counting ----
#hash the ip with a salt that ROTATES DAILY and is then thrown away. within a day
#the same visitor collapses to one token; once that day's salt is deleted nobody,
#us included, can turn the stored tokens back into an ip. the raw ip never
#reaches disk.
#
#SERVER-SIDE on purpose: it touches nothing on the visitor's device, so it needs
#no cookie banner, where a localStorage "visited" flag is non-essential storage
#the eprivacy rules require consent for. the device-storage route is the more
#regulated one.
#
#its own module because visitor_token is not only the counter's: the report and
#import limits identify a visitor through it too, and all three have to agree on
#what "the same person today" means

import hashlib
import secrets
import datetime

from flask import request

from db import pool

_visit = {"day": None, "salt": None}


def client_ip():
    #railway's proxy APPENDS what it saw to X-Forwarded-For, so the LAST entry is
    #its word and everything left of it is client supplied: reading the first
    #lets anyone dodge the rate limit with a made-up header.
    #one proxy deep is a railway fact. a cdn in front adds an entry and this has
    #to move one step left
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.remote_addr or ""


def _utc_day():
    return datetime.datetime.now(datetime.timezone.utc).date()


def todays_salt():
    #generated once and shared by every worker through the db. the first request
    #of a new day does the housekeeping: each finished day collapses to one count
    #in visit_daily and its tokens and salt are DELETED, which is what makes
    #yesterday unrecoverable. only an integer survives the day
    day = _utc_day()
    if _visit["day"] == day and _visit["salt"]:
        return _visit["salt"]
    with pool.connection() as conn:
        conn.execute("INSERT INTO visit_salt (day, salt) VALUES (%s, %s) ON CONFLICT (day) DO NOTHING",
                     (day, secrets.token_hex(16)))
        salt = conn.execute("SELECT salt FROM visit_salt WHERE day = %s", (day,)).fetchone()["salt"]
        conn.execute("""INSERT INTO visit_daily (day, uniques, bots)
                        SELECT day, count(*) FILTER (WHERE NOT bot),
                                    count(*) FILTER (WHERE bot)
                        FROM visit_seen WHERE day < %s GROUP BY day
                        ON CONFLICT (day) DO UPDATE SET uniques = EXCLUDED.uniques,
                                                        bots = EXCLUDED.bots""", (day,))
        conn.execute("DELETE FROM visit_seen WHERE day < %s", (day,))
        conn.execute("DELETE FROM visit_salt WHERE day < %s", (day,))
    _visit["day"] = day
    _visit["salt"] = salt
    return salt


def visitor_token(ip):
    #an empty ip stays EMPTY rather than becoming a hash of the salt alone
    if not ip:
        return ""
    return hashlib.sha256((todays_salt() + "|" + ip).encode("utf-8")).hexdigest()


#the json endpoints are deliberately absent: /suggest alone fires on every
#keystroke and would swamp the number.
#
#these are flask ENDPOINT names, and a route moved into a blueprint is renamed to
#"blueprint.name". a name matching nothing raises nothing, it just stops counting
#that page while the numbers keep arriving, only smaller
PAGE_ENDPOINTS = {"home", "search", "unique", "precons", "precon", "deck", "guide",
                  "privacy", "support"}


#substrings of a lowercased User-Agent. the crawlers carrying real volume name
#themselves, since being recognised is how they stay unblocked, so a substring
#reaches the ones that move the number.
#
#a COUNT and not a gate: the header is client supplied, so headless chrome on a
#stock string passes as a person. the rate limit stays on the visitor token
BOT_AGENTS = ("bot", "crawler", "spider", "slurp", "scrapy", "curl", "wget",
              "python-requests", "httpx", "facebookexternalhit")


def is_bot():
    #an absent header is a script often enough to sit with them
    ua = request.headers.get("User-Agent", "").lower()
    return not ua or any(s in ua for s in BOT_AGENTS)


#the tokens this worker already wrote today, so a second page view costs nothing.
#without it every view borrows a pool connection before the handler starts, on a
#search that already borrows three.
#
#CORRECTNESS DOES NOT LIVE HERE: the primary key on (day, token) is what makes a
#repeat visit one row, and this only skips inserts that would have hit it.
#past the cap the memo stops growing and the inserts go back to being paid for
VISIT_MEMO_MAX = 50000

_visit_memo = {"day": None, "seen": set()}


def count_visit():
    #a blanket catch, because analytics must NEVER break a page: a missing table
    #on a fresh deploy or a db hiccup means an uncounted visit, never a 500
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
            #the flag rides the row rather than skipping it, so the day splits
            #into people and bots instead of losing the second number
            conn.execute("INSERT INTO visit_seen (day, token, bot) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                         (day, token, is_bot()))
        #memoised only AFTER the insert lands, so a failed one is retried on the
        #next page view rather than remembered as done
        if len(_visit_memo["seen"]) < VISIT_MEMO_MAX:
            _visit_memo["seen"].add(token)
    except Exception:
        pass


def register(app):
    #wired here rather than by a decorator at import time, so importing this
    #module for visitor_token alone cannot start counting visits by accident
    app.before_request(count_visit)
