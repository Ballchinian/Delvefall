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
#
#this is its own module because visitor_token is not only the counter's: the
#report rate limit and the decklist import limit both identify a visitor
#through it, and all three have to agree on what "the same person today" means

import hashlib
import secrets
import datetime

from flask import request

from db import pool

_visit = {"day": None, "salt": None}


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
#and /more, the unique dealer and the report post are not visits.
#
#CAREFUL: these are flask ENDPOINT names, and a route moved into a blueprint
#is renamed to "blueprint.name". moving /search into a blueprint without
#writing "search.search" here does not raise anything, it just silently stops
#counting that page. the numbers would keep arriving, only smaller.
#
#"support" is here now, and its absence was that warning coming true rather
#than a decision: the tip jar is a page a person reads, it is linked from the
#footer and it is in the sitemap, so a visitor who arrives on it and nowhere
#else was not being counted at all. every other human page was
PAGE_ENDPOINTS = {"home", "search", "unique", "precons", "precon", "deck", "guide",
                  "privacy", "support"}


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


def register(app):
    #the hook is wired here rather than with a decorator at import time, so
    #importing this module for visitor_token alone (the report limiter does)
    #cannot accidentally start counting visits on somebody else's app
    app.before_request(count_visit)
