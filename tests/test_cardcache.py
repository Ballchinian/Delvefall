#the rendered card page cache. what it holds is cheap to get right and expensive
#to get wrong: serving one url's page at another url is not a slow page, it is a
#page about the wrong card, and nothing downstream would notice.
#
#the read side needs no database. a hit answers before find_card runs, so under
#conftest's stub (which finds no card and would 404) a served page IS the cache
#being read, and a 404 is it correctly declining

import time

import pytest

import app
import seed
from conftest import needs_db


@pytest.fixture(autouse=True)
def _empty_cache():
    #both ways round: a leftover entry would serve the next test's request, and
    #a test's own entry would outlive it
    app._card_pages.clear()
    yield
    app._card_pages.clear()


def store(name, cur="usd", html="<cached page>", age=0):
    app._card_pages[(name, cur)] = {"at": time.time() - age, "html": html}


def get(url):
    return app.app.test_client().get(url)


class TestWhatTheCacheAnswers:

    def test_the_bare_url_is_served_from_it(self):
        store("Sol Ring")
        r = get("/search?q=Sol+Ring")
        assert r.status_code == 200
        assert "<cached page>" in r.get_data(as_text=True)

    def test_a_filtered_url_is_not_served_the_unfiltered_page(self):
        #the whole rule. a colour filter is a different page and shares nothing
        #with the bare one but the card's name
        store("Sol Ring")
        assert get("/search?q=Sol+Ring&colors=R").status_code == 404

    def test_a_picked_line_is_not_served_the_whole_card(self):
        store("Sol Ring")
        assert get("/search?q=Sol+Ring&lines=0").status_code == 404

    def test_a_sort_is_not_served_the_default_order(self):
        store("Sol Ring")
        assert get("/search?q=Sol+Ring&sort=price").status_code == 404

    def test_another_currency_is_not_served_the_dollar_page(self):
        #every price on the page is rendered by the server, so the currency is
        #part of what makes two pages the same page
        store("Sol Ring", "usd")
        assert get("/search?q=Sol+Ring&cur=gbp").status_code == 404

    def test_the_currency_cookie_picks_the_entry_the_url_does_not(self):
        store("Sol Ring", "gbp", html="<pounds>")
        client = app.app.test_client()
        client.set_cookie("cur", "gbp")
        assert "<pounds>" in client.get("/search?q=Sol+Ring").get_data(as_text=True)

    def test_a_stale_entry_is_not_served(self):
        store("Sol Ring", age=app.CARD_PAGE_TTL + 1)
        assert get("/search?q=Sol+Ring").status_code == 404

    def test_an_entry_just_inside_the_hour_still_is(self):
        store("Sol Ring", age=app.CARD_PAGE_TTL - 5)
        assert get("/search?q=Sol+Ring").status_code == 200


class TestTheHeadersACardPageCarries:

    def test_it_says_how_long_it_is_good_for(self):
        store("Sol Ring")
        assert get("/search?q=Sol+Ring").headers["Cache-Control"] == \
            "public, max-age=" + str(app.CARD_PAGE_TTL)

    def test_it_varies_on_the_cookie(self):
        #public without this lets a shared cache hand a pound page to a dollar
        #reader, the currency being a cookie
        store("Sol Ring")
        assert "Cookie" in get("/search?q=Sol+Ring").headers["Vary"]

    def test_it_carries_an_etag_so_a_recrawl_can_be_told_nothing_moved(self):
        store("Sol Ring")
        assert get("/search?q=Sol+Ring").headers.get("ETag")

    def test_the_etag_answers_a_conditional_request_with_a_304(self):
        #the crawl budget this is all for: 80kb of html against no body at all
        store("Sol Ring")
        tag = get("/search?q=Sol+Ring").headers["ETag"]
        r = app.app.test_client().get("/search?q=Sol+Ring", headers={"If-None-Match": tag})
        assert r.status_code == 304
        assert not r.get_data()

    def test_a_card_that_matches_nothing_is_not_cacheable(self):
        #a 404 with an hour of max-age would stick a typo to a real card's
        #future. the miss never reaches the header block at all
        r = get("/search?q=zzqqxx")
        assert r.status_code == 404
        assert "Cache-Control" not in r.headers


class TestWhatGetsStored:

    pytestmark = needs_db

    @pytest.fixture(autouse=True)
    def _always_seeded(self, seeded):
        return seeded

    def test_the_canonical_spelling_is_stored_and_read_back(self):
        assert get("/search?q=Fixture+Anchor").status_code == 200
        assert ("Fixture Anchor", "usd") in app._card_pages

    def test_a_different_spelling_of_the_same_card_is_not(self):
        #the search box prints the query back, so storing this would show
        #"fixture anchor" to whoever asked for the card by its name
        assert get("/search?q=fixture+anchor").status_code == 200
        assert app._card_pages == {}

    def test_a_filtered_page_is_not_stored(self):
        assert get("/search?q=Fixture+Anchor&colors=U").status_code == 200
        assert app._card_pages == {}

    def test_the_cache_cannot_grow_past_its_cap(self):
        #a crawler walking 31k sitemap urls inside the hour is the case this
        #guards, and the page is ~80kb
        for i in range(app.CARD_PAGE_MAX + 20):
            store("filler " + str(i))
        get("/search?q=Fixture+Anchor")
        assert len(app._card_pages) <= app.CARD_PAGE_MAX
