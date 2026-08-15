#the structured data. a broken block here is SILENT: the page renders fine,
#google drops the json and nothing anywhere says so, so these PARSE it rather
#than looking for substrings.
#
#the macro is rendered out of the app's own environment, so what is under test is
#the template that ships. no database: nothing in partials/jsonld.html asks

import json
import re

import app

BLOCK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

HOME = "https://delvefall.com/"


def render(call, **ctx):
    tpl = app.app.jinja_env.from_string('{% import "partials/jsonld.html" as j %}' + call)
    with app.app.test_request_context("/"):
        return json.loads(BLOCK.search(tpl.render(**ctx)).group(1))


class TestTheBreadcrumbs:

    def test_a_two_step_trail_parses_and_keeps_its_order(self):
        got = render('{{ j.crumbs([("Delvefall", home), ("Sol Ring", None)]) }}', home=HOME)
        assert got["@type"] == "BreadcrumbList"
        assert [i["name"] for i in got["itemListElement"]] == ["Delvefall", "Sol Ring"]
        assert [i["position"] for i in got["itemListElement"]] == [1, 2]

    def test_the_last_crumb_names_itself_and_gives_no_url(self):
        #it IS the page. the canonical already says where that is, and two
        #answers to one question is how the two come to disagree
        got = render('{{ j.crumbs([("Delvefall", home), ("Sol Ring", None)]) }}', home=HOME)
        assert "item" not in got["itemListElement"][-1]
        assert got["itemListElement"][0]["item"] == HOME

    def test_a_three_step_trail_keeps_the_middle_link(self):
        #the precon detail pages, the only three deep ones on the site
        got = render('{{ j.crumbs([("Delvefall", home), ("Commander precons", home ~ "precons"),'
                     ' ("Mind Seize", None)]) }}', home=HOME)
        assert [i["position"] for i in got["itemListElement"]] == [1, 2, 3]
        assert got["itemListElement"][1]["item"].endswith("/precons")
        assert "item" not in got["itemListElement"][-1]

    def test_a_card_name_cannot_break_out_of_the_json(self):
        #card names are the one input here nobody on this side chooses, and
        #they carry apostrophes, commas and quotation marks
        for name in ("Ghoulcaller's Bell", 'Ach! Hans, Run!', 'Rakdos, Lord of Riots // Nothing',
                     'A "quoted" name', "back\\slash"):
            got = render('{{ j.crumbs([("Delvefall", home), (name, None)]) }}',
                         home=HOME, name=name)
            assert got["itemListElement"][-1]["name"] == name


class TestTheRankedList:

    def test_the_count_matches_the_entries(self):
        #numberOfItems disagreeing with the list is the error google reports
        got = render('{{ j.ranked("Three cards", ["a", "b", "c"]) }}')
        assert got["@type"] == "ItemList"
        assert got["numberOfItems"] == 3 == len(got["itemListElement"])

    def test_the_positions_run_from_one(self):
        got = render('{{ j.ranked("Three cards", ["a", "b", "c"]) }}')
        assert [i["position"] for i in got["itemListElement"]] == [1, 2, 3]
        assert [i["url"] for i in got["itemListElement"]] == ["a", "b", "c"]

    def test_a_single_entry_carries_no_trailing_comma(self):
        #the comma is emitted per item, so a list of one is where it breaks
        got = render('{{ j.ranked("One card", ["only"]) }}')
        assert got["numberOfItems"] == 1

    def test_it_claims_no_direction(self):
        #itemListOrder names which way the VALUES run, and /precons reads its
        #metrics from either end. the positions carry the order by themselves
        got = render('{{ j.ranked("Three cards", ["a", "b", "c"]) }}')
        assert "itemListOrder" not in got
