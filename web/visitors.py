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
#what "the same person today" means.
#
#the row also carries what KIND of request the token made: a page, the site's
#font, an action, a crawler's file, and whether it claimed a browser without a
#browser's headers. a User-Agent is the only thing saying "bot", and the crawlers
#carrying real volume on a stock browser string never say it, so the flags are
#what separate a visitor who rendered and typed from one who only ever asked for
#html. they are evidence and never a verdict: every one of them only ever proves
#a visitor DID something, and a year-long cache means a returning person fetches
#no font and no file, so what is missing proves nothing at all

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


#the five counts, in the order a visitor is placed: declared bots, then anything
#that did what automation does, then the evidence of a person, strongest first.
#each FILTER repeats the ones above it, which is what keeps one visitor out of
#two columns and makes the columns add up to the day.
#
#read by the rollup below and by /admin's row for today, so the newest row is
#counted exactly like the frozen ones
SPLIT_COUNTS = """count(*) FILTER (WHERE NOT bot) AS uniques,
                  count(*) FILTER (WHERE bot) AS bots,
                  count(*) FILTER (WHERE NOT bot AND (crawl OR lies)) AS suspect_n,
                  count(*) FILTER (WHERE NOT bot AND NOT (crawl OR lies) AND act) AS acted_n,
                  count(*) FILTER (WHERE NOT bot AND NOT (crawl OR lies) AND NOT act
                                   AND font) AS rendered_n"""


def todays_salt():
    #generated once and shared by every worker through the db. the first request
    #of a new day does the housekeeping: each finished day collapses to one row
    #of counts in visit_daily and its tokens and salt are DELETED, which is what
    #makes yesterday unrecoverable. only the counts survive the day
    day = _utc_day()
    if _visit["day"] == day and _visit["salt"]:
        return _visit["salt"]
    with pool.connection() as conn:
        conn.execute("INSERT INTO visit_salt (day, salt) VALUES (%s, %s) ON CONFLICT (day) DO NOTHING",
                     (day, secrets.token_hex(16)))
        salt = conn.execute("SELECT salt FROM visit_salt WHERE day = %s", (day,)).fetchone()["salt"]
        #AND html, so a visitor who fetched the sitemap or the share image and
        #never loaded a page is not one of the day's people
        conn.execute("""INSERT INTO visit_daily (day, uniques, bots, suspect_n, acted_n, rendered_n)
                        SELECT day, """ + SPLIT_COUNTS + """
                        FROM visit_seen WHERE day < %s AND html GROUP BY day
                        ON CONFLICT (day) DO UPDATE SET uniques = EXCLUDED.uniques,
                                                        bots = EXCLUDED.bots,
                                                        suspect_n = EXCLUDED.suspect_n,
                                                        acted_n = EXCLUDED.acted_n,
                                                        rendered_n = EXCLUDED.rendered_n""", (day,))
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


#these are flask ENDPOINT names, and a route moved into a blueprint is renamed to
#"blueprint.name". a name matching nothing raises nothing, it just stops counting
#that page while the numbers keep arriving, only smaller, which is why
#tests/test_visitors.py checks every name below against app.url_map
PAGE_ENDPOINTS = {"home", "search", "unique", "precons", "precon", "deck", "guide",
                  "privacy", "support",
                  #a blueprint route is named <blueprint>.<function>, so the bare
                  #name matches no rule and would count nobody, silently
                  "custom.custom"}


#every one of these needs a keystroke, a click or a submit to fire. the json ones
#set a flag and never a count: /suggest alone fires on every keystroke and would
#swamp a number.
#
#deck_swap_cards is NOT here. swap.js calls show() as the page loads, so it posts
#with nobody touching anything, and a headless browser would earn an action for
#sitting on the page.
#
#the four deck names are the POST half of those routes. their GET half is
#deck_post_only, so a plain visit cannot reach them
ACT_ENDPOINTS = {"suggest", "more", "unique_cards", "deck_found", "feedback",
                 "deck_open", "deck_view", "deck_read", "deck_swap",
                 #the POST that scores a typed card and the one behind its Load
                 #more. custom.custom_wake is in NEITHER: it fires on the first
                 #focus of the textarea, before anybody has done anything
                 "custom.custom_post", "custom.custom_more"}


#what a crawler reads first and a browser never asks for
CRAWL_ENDPOINTS = {"meta.robots", "meta.sitemap", "meta.sitemap_part", "meta.llms"}


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


#the two headers every current browser sends and a script has to be told to send.
#page javascript can set neither, so what the page serves cannot forge them,
#only whoever wrote the client can. safari sends Sec-Fetch-Dest from 16.4, which
#leaves an iphone 7 and older reading as a lie
def ua_lies():
    return "Mozilla/" in request.headers.get("User-Agent", "") and not (
        request.headers.get("Sec-Fetch-Dest") and request.headers.get("Accept-Language"))


def signal_for():
    #the kind of request this is, or None for one that says nothing about who
    #sent it. css and js are None on purpose: their urls carry a content hash, so
    #a deploy makes every returning browser fetch them again while the font url
    #inside the css does not change and stays cached, and a flag both a person
    #and a crawler set sorts nobody.
    #
    #HEAD is nobody: a link checker sends it and a browser does not
    ep = request.endpoint
    if request.method == "HEAD":
        return None
    if request.method == "GET":
        if ep in PAGE_ENDPOINTS:
            return "html"
        if ep == "static":
            #a woff2 is asked for once layout needs the face, which is further
            #into a browser than parsing the html or running its javascript
            return "font" if request.path.endswith(".woff2") else None
        if ep in CRAWL_ENDPOINTS:
            return "crawl"
    if ep in ACT_ENDPOINTS:
        return "act"
    return None


#bot is not in the SET: it is whatever the first request of the day decided, and
#every request from one token carries the same User-Agent. the flags OR, so two
#workers writing the same one cannot undo each other and a flag never goes out
_UPSERT = """INSERT INTO visit_seen (day, token, bot, html, font, act, crawl, lies)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
             ON CONFLICT (day, token) DO UPDATE SET
                 html  = visit_seen.html  OR EXCLUDED.html,
                 font  = visit_seen.font  OR EXCLUDED.font,
                 act   = visit_seen.act   OR EXCLUDED.act,
                 crawl = visit_seen.crawl OR EXCLUDED.crawl,
                 lies  = visit_seen.lies  OR EXCLUDED.lies"""


#the kinds this worker already wrote today, per token. a first page load is a
#page, a font and eight cached-forever files, and without this every one of them
#borrows a pool connection before the handler starts, on a search that already
#borrows three. a token costs at most four writes a day instead.
#
#CORRECTNESS DOES NOT LIVE HERE: the primary key on (day, token) and the OR above
#are what make a repeat one row, and this only skips writes that would have
#changed nothing. past the cap the memo takes no new tokens and their writes go
#back to being paid for, while the ones it holds carry on collecting kinds
VISIT_MEMO_MAX = 50000

_visit_memo = {"day": None, "kinds": {}}


def count_visit():
    kind = signal_for()
    if kind is None:
        return
    #a blanket catch, because analytics must NEVER break a page: a missing column
    #on a fresh deploy or a db hiccup means an uncounted visit, never a 500
    try:
        token = visitor_token(client_ip())
        if not token:
            return
        day = _utc_day()
        if _visit_memo["day"] != day:
            _visit_memo["day"] = day
            _visit_memo["kinds"] = {}
        seen = _visit_memo["kinds"]
        if kind in seen.get(token, ()):
            return
        with pool.connection() as conn:
            #read on the page request alone, where the headers are the ones a
            #browser sends navigating rather than fetching
            conn.execute(_UPSERT, (day, token, is_bot(), kind == "html", kind == "font",
                                   kind == "act", kind == "crawl",
                                   kind == "html" and ua_lies()))
        #memoised only AFTER the write lands, so a failed one is retried on the
        #next request rather than remembered as done
        if token in seen or len(seen) < VISIT_MEMO_MAX:
            seen.setdefault(token, set()).add(kind)
    except Exception:
        pass


def usage_row(day, counts, split, measured):
    #one row of /admin's table. unproven is what is left over: a visitor who
    #loaded a page and did nothing pointing either way, which is a person with a
    #warm cache as readily as a scraper, so it is never part of the floor.
    #
    #people is a RANGE. the floor is the ones who typed or clicked, the ceiling is
    #everyone the day could not call a bot, and nothing here picks a number
    #between them
    row = {"day": day.isoformat(), "bots": counts["bots"], "split": split,
           "measured": measured}
    if not measured:
        row["ceiling"] = counts["uniques"]
        return row
    unproven = counts["uniques"] - counts["acted_n"] - counts["rendered_n"] - counts["suspect_n"]
    row.update(acted=counts["acted_n"], rendered=counts["rendered_n"],
               suspect=counts["suspect_n"], unproven=unproven, floor=counts["acted_n"],
               ceiling=counts["acted_n"] + counts["rendered_n"] + unproven)
    return row


def register(app):
    #wired here rather than by a decorator at import time, so importing this
    #module for visitor_token alone cannot start counting visits by accident
    app.before_request(count_visit)
