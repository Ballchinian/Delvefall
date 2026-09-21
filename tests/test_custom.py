#/custom shows the printed cards that already do something like a card somebody
#invented. the page is built in pieces, and these are the pieces that can be
#checked without the model: the shared results grid, the reading of the form,
#and the wording of the sentence.

import app


def render_results(results, **kwargs):
    #the jinja env directly rather than a request: the partial names no url and
    #no request, which is what lets two different pages include it
    return app.app.jinja_env.get_template("partials/results.html").render(
        results=results, focus="", has_more=False, next_band=None, **kwargs)


#one result carrying only what the grid reads. the verdict fields are absent on
#purpose: /custom has no anchor card to compare a price or a rank against, and
#the grid has to cope with that rather than raise
ONE = [{"oracle_id": "0000", "name": "Shock", "image": "/i.jpg", "image_back": "",
        "scryfall_uri": "https://scryfall.com/x", "percent": 91, "sideways": False,
        "flip": False, "their_line": "this card deals 2 damage to any target.",
        "our_line": "this card deals 3 damage to any target."}]


class TestTheResultsGridIsSharedByTwoPages:

    def test_search_gets_the_report_flag(self):
        #the default, because search.html includes the partial without saying so
        assert 'class="report-flag"' in render_results(ONE)

    def test_custom_does_not(self):
        #the flag reports a result as a bad match FOR THE SEARCHED CARD, and a
        #card somebody typed is not in the database to be reported against
        out = render_results(ONE, report=False)
        assert "report-flag" not in out
        assert "Shock" in out and "91%" in out

    def test_a_missing_anchor_card_does_not_break_the_grid(self):
        #price_verdict and its three siblings return "" for a missing anchor, so
        #the tooltips naming card.name simply go quiet
        out = render_results(ONE, report=False)
        assert "None" not in out
