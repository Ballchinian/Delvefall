#the counter files every request under one kind, and the rollup sorts a day's
#tokens into one column each. both fail SILENTLY: count_visit swallows every
#exception and an endpoint name matching no route raises nothing, so a mistake
#here is not an error, it is a plausible number that is wrong.
#
#most of this needs no database. conftest's stub answers every query with
#nothing, which is all signal_for and usage_row ever wanted.

import datetime

import pytest

import app
import db
import visitors
from visitors import (ACT_ENDPOINTS, CRAWL_ENDPOINTS, PAGE_ENDPOINTS, signal_for,
                      ua_lies, usage_row)
from conftest import needs_db

DAY = datetime.date(2026, 9, 14)

#a finished day the rollup will take (it reads day < today) and no real day this
#database will ever hold
SEEDED = datetime.date(2019, 5, 4)
SEEDED_B = datetime.date(2019, 5, 5)

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/141.0.0.0 Safari/537.36")
BROWSER_HEADERS = {"User-Agent": CHROME, "Sec-Fetch-Dest": "document",
                   "Accept-Language": "en-GB,en;q=0.9"}


def kind_of(path, method="GET", **headers):
    with app.app.test_request_context(path, method=method, headers=headers):
        return signal_for()


def counts(uniques, bots=0, suspect=0, acted=0, rendered=0):
    return {"uniques": uniques, "bots": bots, "suspect_n": suspect,
            "acted_n": acted, "rendered_n": rendered}


class TestTheCountedNamesAreReal:

    def test_every_name_the_counter_watches_is_a_route(self):
        #the one failure nothing reports: a route renamed, or moved into a
        #blueprint and so renamed to "blueprint.name", goes on serving while its
        #visits stop being counted
        known = {rule.endpoint for rule in app.app.url_map.iter_rules()}
        for name in PAGE_ENDPOINTS | ACT_ENDPOINTS | CRAWL_ENDPOINTS:
            assert name in known, name + " is counted and is not a route"


class TestWhatARequestCountsAs:

    def test_a_page_is_the_gate(self):
        assert kind_of("/search?q=Sol+Ring") == "html"

    def test_a_head_is_nobody(self):
        #a link checker sends HEAD and a browser reading the site does not
        assert kind_of("/search", method="HEAD") is None

    def test_the_font_is_the_render(self):
        #a woff2 is fetched once layout needs the face, which is deeper into a
        #browser than parsing the html or running its javascript
        assert kind_of("/static/fonts/Fraunces.woff2?v=1a2b3c4d") == "font"

    def test_the_stylesheet_says_nothing(self):
        #its url carries a content hash, so every deploy makes returning
        #browsers fetch it again while the font url inside it does not change.
        #a flag both a person and a crawler set sorts nobody
        assert kind_of("/static/style-ink.css?v=1a2b3c4d") is None

    def test_a_suggestion_is_an_action(self):
        #base.js asks for it after two characters are typed
        assert kind_of("/suggest?q=so") == "act"

    def test_a_pasted_decklist_is_an_action(self):
        assert kind_of("/deck/open", method="POST") == "act"

    def test_the_swap_tools_own_fetch_is_not_an_action(self):
        #swap.js calls show() as the module loads, so this posts with nobody
        #touching anything. counting it would let a headless browser earn an
        #action for sitting on the page
        assert kind_of("/deck/swap/cards", method="POST") is None

    def test_robots_txt_is_what_a_crawler_reads(self):
        assert kind_of("/robots.txt") == "crawl"

    def test_a_url_that_does_not_exist_is_nobody(self):
        #what scanners spend their day on
        assert kind_of("/wp-login.php") is None


class TestTheHeaderCheck:

    def lies(self, **headers):
        with app.app.test_request_context("/", headers=headers):
            return ua_lies()

    def test_a_browser_sending_what_browsers_send_is_believed(self):
        #chrome, firefox, edge and safari from 16.4 all send both of these on a
        #navigation, and page javascript can set neither
        assert self.lies(**BROWSER_HEADERS) is False

    def test_a_chrome_string_without_sec_fetch_dest_is_a_lie(self):
        #what a script copying a user agent and nothing else looks like
        assert self.lies(**{"User-Agent": CHROME, "Accept-Language": "en-GB"}) is True

    def test_a_chrome_string_without_accept_language_is_a_lie(self):
        assert self.lies(**{"User-Agent": CHROME, "Sec-Fetch-Dest": "document"}) is True

    def test_a_client_that_claims_nothing_is_not_lying(self):
        #curl never said it was a browser, and BOT_AGENTS has it anyway. the
        #check is only ever about a client claiming to be something it is not
        assert self.lies(**{"User-Agent": "curl/8.4.0"}) is False


class TestTheDayRow:

    def test_the_four_columns_divide_the_day(self):
        #every visitor that loaded a page sits in exactly one of them, so they
        #add up to uniques and unproven is whatever is left
        row = usage_row(DAY, counts(30, bots=12, suspect=6, acted=3, rendered=5), True, True)
        assert row["acted"] + row["rendered"] + row["unproven"] + row["suspect"] == 30
        assert row["unproven"] == 16

    def test_a_suspect_is_kept_out_of_both_ends_of_the_range(self):
        #the rule the whole split exists for: a missed bot costs more than a
        #missed person, so evidence of automation is not people at either end
        row = usage_row(DAY, counts(30, suspect=6, acted=3, rendered=5), True, True)
        assert row["floor"] == 3
        assert row["ceiling"] == 24

    def test_a_day_of_nothing_but_unproven_visitors_promises_no_people(self):
        #the shape this change was written to show. 33 visitors, not one of them
        #having done anything a person does, is a floor of zero
        row = usage_row(DAY, counts(33), True, True)
        assert row["floor"] == 0
        assert row["ceiling"] == 33

    def test_a_day_from_before_the_flags_offers_a_ceiling_and_no_floor(self):
        #13 september 2026 read as 34 people. all that number ever meant was
        #"not a declared bot", which is the most people it could have been
        row = usage_row(DAY, counts(34, bots=29), True, False)
        assert row["ceiling"] == 34
        assert row["bots"] == 29
        assert "floor" not in row


@needs_db
class TestTheRollup:

    @pytest.fixture(autouse=True)
    def clean(self):
        visitors._visit = {"day": None, "salt": None}
        visitors._visit_memo = {"day": None, "kinds": {}}
        yield
        with db.pool.connection() as conn:
            for day in (SEEDED, SEEDED_B, visitors._utc_day()):
                conn.execute("DELETE FROM visit_seen WHERE day = %s", (day,))
                conn.execute("DELETE FROM visit_daily WHERE day = %s", (day,))
                conn.execute("DELETE FROM visit_salt WHERE day = %s", (day,))
            conn.commit()

    def seen(self, conn, day, token, **flags):
        row = dict(bot=False, html=True, font=False, act=False, crawl=False, lies=False)
        row.update(flags)
        conn.execute("""INSERT INTO visit_seen (day, token, bot, html, font, act, crawl, lies)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                     (day, token, row["bot"], row["html"], row["font"], row["act"],
                      row["crawl"], row["lies"]))

    def rolled(self, day):
        visitors.todays_salt()
        with db.pool.connection() as conn:
            return conn.execute("SELECT * FROM visit_daily WHERE day = %s", (day,)).fetchone()

    def test_a_visitor_lands_in_one_column_and_the_strongest_doubt_wins(self):
        with db.pool.connection() as conn:
            self.seen(conn, SEEDED, "person", font=True, act=True)
            self.seen(conn, SEEDED, "reader", font=True)
            self.seen(conn, SEEDED, "quiet")
            self.seen(conn, SEEDED, "sitemap-reader", crawl=True)
            #acted AND lied. a script can call /suggest, a real browser cannot
            #forget the headers, so this is suspect and not a person
            self.seen(conn, SEEDED, "liar", font=True, act=True, lies=True)
            self.seen(conn, SEEDED, "declared", bot=True, font=True, act=True)
            conn.commit()
        row = self.rolled(SEEDED)
        assert row["uniques"] == 5
        assert row["bots"] == 1
        assert row["suspect_n"] == 2
        assert row["acted_n"] == 1
        assert row["rendered_n"] == 1

    def test_a_visitor_that_never_loaded_a_page_is_not_one_of_the_days_people(self):
        #whatsapp fetching the share image to draw a link preview, and a crawler
        #reading robots.txt from an address it never browses from
        with db.pool.connection() as conn:
            self.seen(conn, SEEDED_B, "reader", font=True, act=True)
            self.seen(conn, SEEDED_B, "share-image", html=False, font=True)
            self.seen(conn, SEEDED_B, "robots-only", html=False, crawl=True)
            conn.commit()
        row = self.rolled(SEEDED_B)
        assert row["uniques"] == 1
        assert row["suspect_n"] == 0

    def test_a_visitors_kinds_gather_into_one_row(self):
        #the page and the font arrive as separate requests minutes apart, and a
        #flag already set never goes out again
        headers = dict(BROWSER_HEADERS, **{"X-Forwarded-For": "203.0.113.9"})
        for path in ("/search?q=Sol+Ring", "/static/fonts/Fraunces.woff2", "/suggest?q=so"):
            with app.app.test_request_context(path, headers=headers):
                visitors.count_visit()
        token = visitors.visitor_token("203.0.113.9")
        with db.pool.connection() as conn:
            row = conn.execute("SELECT * FROM visit_seen WHERE day = %s AND token = %s",
                               (visitors._utc_day(), token)).fetchone()
        assert (row["html"], row["font"], row["act"]) == (True, True, True)
        assert row["lies"] is False
