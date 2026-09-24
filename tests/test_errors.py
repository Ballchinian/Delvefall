#the error pages. flask's default 404 is a dead end with no way back into the
#site, and a 500 handler that raises while rendering is the same fault at a
#worse moment, so both are rendered here rather than assumed.
#
#no database needed: conftest's stub answers every query with nothing, which is
#exactly what a miss looks like

import html

import app
from conftest import needs_db


def text_of(response):
    #unescaped, because the headings ride in as variables and jinja turns the
    #apostrophe into &#39;. asserting on the entity would tie these to the copy
    return html.unescape(response.get_data(as_text=True))


class TestTheErrorPages:

    def test_an_unmatched_path_gets_the_sites_own_404(self):
        r = app.app.test_client().get("/nosuchpage")
        assert r.status_code == 404
        assert "That page isn't here" in text_of(r)

    def test_the_404_offers_a_way_back(self):
        #the whole reason it exists rather than flask's default
        body = app.app.test_client().get("/nosuchpage").get_data(as_text=True)
        for href in ('href="/unique"', 'href="/deck"', 'href="/precons"', 'href="/guide"'):
            assert href in body

    def test_error_pages_are_noindex(self):
        body = app.app.test_client().get("/nosuchpage").get_data(as_text=True)
        assert 'name="robots" content="noindex"' in body

    def test_the_500_page_renders_at_all(self):
        #called directly: raising for real needs PROPAGATE_EXCEPTIONS off and a
        #route that fails. what is being asserted is that the template renders
        with app.app.test_request_context("/"):
            body, code = app.page_broke(Exception("boom"))
        assert code == 500
        assert "Something went wrong" in body


class TestASearchThatMatchesNothing:

    def test_it_is_a_404_not_a_200(self):
        #a 200 makes every typo an indexable url
        assert app.app.test_client().get("/search?q=zzqqxx").status_code == 404

    def test_it_keeps_its_own_page_rather_than_the_generic_one(self):
        #the miss can name the query and suggest a spelling, which the
        #errorhandler's page cannot
        body = app.app.test_client().get("/search?q=zzqqxx").get_data(as_text=True)
        assert "zzqqxx" in body
        assert "That page isn't here" not in body

    def test_it_declares_noindex_and_no_canonical(self):
        #the base canonical is /search, which redirects, and a canonical must
        #never point at a redirect
        body = app.app.test_client().get("/search?q=zzqqxx").get_data(as_text=True)
        assert 'name="robots" content="noindex"' in body
        assert 'rel="canonical"' not in body


class TestAPostedBodyCannotTurnIntoA500:
    #each of these raised before reaching anything else the route does, so a
    #malformed request was a 500 however healthy the site was

    @needs_db
    def test_a_json_body_that_is_not_an_object(self):
        #get_json hands back the list, and `or {}` rescues only a falsy one. real
        #rows, because past the body /unique/cards subscripts what it reads back
        client = app.app.test_client()
        for path in ("/deck/found", "/deck/swap/cards", "/unique/cards", "/feedback"):
            assert client.post(path, json=[1, 2, 3]).status_code != 500, path

    def test_a_unicode_digit_in_the_picked_lines(self):
        #"²".isdigit() is True and int("²") raises
        with app.app.test_request_context("/search?q=Sol+Ring&lines=%C2%B2,1"):
            assert app.read_picked() == {1}
        client = app.app.test_client()
        assert client.post("/deck/swap/cards", json={"lines": ["²", "1"]}).status_code != 500
        assert client.post("/deck/swap/cards", json={"lines": {"0": 1}}).status_code != 500


class TestTheSuggestBoxIsBounded:

    def test_a_pasted_page_asks_for_a_name_no_longer_than_one(self, monkeypatch):
        #every keystroke sends it, and each pattern it builds goes into ILIKE and
        #a trigram comparison against every name
        asked = []

        class Pool:
            def connection(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                asked.extend(p for p in params if isinstance(p, str))
                return []

        monkeypatch.setattr(app, "pool", Pool())
        app.app.test_client().get("/suggest?q=" + "a" * 20000)
        assert asked and max(len(p) for p in asked) <= app.SUGGEST_MAX + 2
