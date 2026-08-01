#the error pages. flask's default 404 is a dead end with no way back into the
#site, and a 500 handler that raises while rendering is the same fault at a
#worse moment, so both are rendered here rather than assumed.
#
#no database needed: conftest's stub answers every query with nothing, which is
#exactly what a miss looks like

import html

import app


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
