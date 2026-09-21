#/custom shows the printed cards that already do something like a card somebody
#invented. the page is built in pieces, and these are the pieces that can be
#checked without the model: the shared results grid, the reading of the form,
#and the wording of the sentence.

import io
import json
import urllib.error

import numpy as np
import pytest

import app
import embedder
from conftest import needs_db
from views.custom import (MAX_CHARS, MAX_LINES, Rejected, custom_words, read_custom,
                          rules_standing)


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


class _Answer:
    #enough of urlopen's return for the client, which reads and json-parses it
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, payload=None):
    return urllib.error.HTTPError("http://x/embed", code, "", {},
                                  io.BytesIO(json.dumps(payload or {}).encode()))


@pytest.fixture
def served(monkeypatch):
    #a stand-in for the embed service. the calls it received are recorded, so a
    #test can say how many times the client tried rather than only what it
    #returned
    calls = []

    def serve(answers, budget=0.5):
        answers = list(answers)
        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")
        #no real waiting: the retry loop is under test, not the clock. the
        #BUDGET goes down WITH it, or a test whose service never answers spins
        #for the full 90 seconds instead of failing. it is an argument because
        #this runs AFTER whatever the test set, and would otherwise overrule it
        monkeypatch.setattr(embedder, "RETRY_EVERY", 0.0)
        monkeypatch.setattr(embedder, "BUDGET", budget)

        def fake(req, timeout=None):
            calls.append(req)
            a = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(a, Exception):
                raise a
            return a

        monkeypatch.setattr(embedder.urllib.request, "urlopen", fake)
        return calls

    return serve


class TestTheClientForTheModelService:

    def test_no_service_configured_fails_at_once(self, monkeypatch):
        #a laptop that never started one, and every test that does not want it.
        #it must not spend the budget discovering there is nothing to call
        monkeypatch.setattr(embedder, "EMBED_URL", "")
        with pytest.raises(embedder.EmbedderDown):
            embedder.embed(["Flying"])

    def test_vectors_come_back_as_float32(self, served):
        #pgvector's adapter sends an ndarray as a vector and postgres casts
        #vector to halfvec, so this is what goes straight into the sql
        served([_Answer({"vectors": [[0.5] * 768], "sha256": "abc123"})])
        got = embedder.embed(["Flying"])
        assert len(got) == 1 and got[0].dtype == np.float32 and got[0].shape == (768,)
        assert embedder._last_sha256 == "abc123"

    def test_a_waking_service_is_retried_and_then_answers(self, served):
        #the first request into a sleeping container can be refused while it
        #comes up, which is the whole reason this retries rather than fails
        calls = served([http_error(503), http_error(502),
                        _Answer({"vectors": [[0.1] * 768], "sha256": "s"})])
        assert len(embedder.embed(["Flying"])) == 1
        assert len(calls) == 3

    def test_a_service_that_never_wakes_gives_up_inside_the_budget(self, served):
        calls = served([http_error(503)], budget=0.0)
        with pytest.raises(embedder.EmbedderDown):
            embedder.embed(["Flying"])
        #tried once, then found no budget to sleep into. a budget of zero that
        #still slept would hold a request thread for nothing
        assert len(calls) == 1

    def test_a_refusal_is_not_worded_as_a_wake(self, served):
        #read_custom applies the same two limits before calling, so a 400 means
        #the page and the service have drifted apart. that is a bug, and
        #retrying it would spend the budget hiding one
        calls = served([http_error(400, {"error": "at most 20 texts, got 21"})])
        with pytest.raises(embedder.EmbedderRefused, match="at most 20 texts"):
            embedder.embed(["Flying"] * 21)
        assert len(calls) == 1

    def test_the_wrong_number_of_vectors_is_refused(self, served):
        served([_Answer({"vectors": [[0.1] * 768], "sha256": "s"})])
        with pytest.raises(embedder.EmbedderRefused):
            embedder.embed(["Flying", "Trample"])

    def test_only_so_many_requests_wait_at_once(self, served, monkeypatch):
        #2 workers of 4 threads serve the whole site. a cold start must not be
        #able to park them all waiting on the model while /search queues behind
        served([_Answer({"vectors": [[0.1] * 768], "sha256": "s"})])
        monkeypatch.setattr(embedder, "_waiting", embedder.MAX_WAITING)
        with pytest.raises(embedder.EmbedderDown, match="already waiting"):
            embedder.embed(["Flying"])

    def test_the_counter_comes_back_down_after_a_failure(self, served):
        #or the third failed wake of the process locks /custom out for good
        served([http_error(503)], budget=0.0)
        for _ in range(embedder.MAX_WAITING + 1):
            with pytest.raises(embedder.EmbedderDown):
                embedder.embed(["Flying"])
        assert embedder._waiting == 0

    def test_the_wake_ping_never_raises(self, served):
        #fired at the first keystroke and never waited on, so a service that is
        #not there yet must not turn into an error on the page
        served([http_error(502)])
        assert embedder.wake() is False


class TestReadingTheForm:

    def test_one_ability_a_line(self):
        assert read_custom("Flying\nTrample") == ["Flying", "Trample"]

    def test_blank_lines_are_not_lines(self):
        assert read_custom("Flying\n\n   \nTrample") == ["Flying", "Trample"]

    def test_windows_newlines_are_newlines(self):
        #a textarea posted from windows sends \r\n. clean_line's strip() would
        #cover the text either way, so what this really guards is the length
        #check, which counts the raw line: a full length line arriving as \r\n
        #measures one over and gets turned away for being too long
        assert read_custom("Flying\r\nTrample") == ["Flying", "Trample"]
        assert read_custom("x" * MAX_CHARS + "\r\nFlying") == ["x" * MAX_CHARS, "Flying"]

    def test_the_name_becomes_this_card(self):
        #6,558 stored lines say "this card", and none say the card's own name,
        #so without this a card that refers to itself matches nothing
        assert read_custom("Shivan Dragon deals 2 damage.", "Shivan Dragon") == \
            ["this card deals 2 damage."]

    def test_no_name_leaves_the_text_alone(self):
        assert read_custom("Shivan Dragon deals 2 damage.") == ["Shivan Dragon deals 2 damage."]

    def test_a_line_under_three_characters_is_dropped(self):
        #the ingest's floor, applied by the ingest's own splitter. it is UNDER
        #three, so "{T}" at exactly three stays: a stored line that short is
        #rare but real, and the floor is there for stray punctuation
        assert read_custom("Flying\nII\nTrample") == ["Flying", "Trample"]
        assert read_custom("{T}") == ["{T}"]

    def test_nothing_to_score_is_rejected(self):
        for text in ("", "   ", "\n\n"):
            with pytest.raises(Rejected):
                read_custom(text)

    def test_text_that_cleans_away_to_nothing_is_rejected(self):
        #reminder text alone: the parens come out and there is no rule left
        with pytest.raises(Rejected):
            read_custom("(This is just a reminder.)")

    def test_too_many_lines_names_the_limit(self):
        ok = "\n".join(["Flying"] * MAX_LINES)
        assert len(read_custom(ok)) == MAX_LINES
        with pytest.raises(Rejected, match=str(MAX_LINES)):
            read_custom("\n".join(["Flying"] * (MAX_LINES + 1)))

    def test_too_long_a_line_names_the_limit(self):
        assert read_custom("x" * MAX_CHARS) == ["x" * MAX_CHARS]
        with pytest.raises(Rejected, match=str(MAX_CHARS)):
            read_custom("x" * (MAX_CHARS + 1))

    def test_the_length_check_is_on_the_raw_line(self):
        #cleaning SHORTENS text, so checking afterwards would let a 5,000
        #character line of reminder text through to the model
        with pytest.raises(Rejected):
            read_custom("Flying " + "(reminder) " * 200)

    def test_an_overlong_name_is_rejected(self):
        with pytest.raises(Rejected):
            read_custom("Flying", "x" * 151)


class TestTheOriginalitySentence:

    def test_nothing_below_it_reads_zero(self):
        assert custom_words(0, 31295) == "Its rules text is more original than 0.0% of Magic cards"

    def test_everything_below_it_reads_a_hundred(self):
        assert custom_words(31295, 31295) == \
            "Its rules text is more original than 100.0% of Magic cards"

    def test_the_percent_is_floored_not_rounded(self):
        #101st of 31,295 beats 99.677%, which ROUNDS to 99.7 and would claim a
        #place the card has not earned. unique_words floors for the same reason
        assert "99.6%" in custom_words(31194, 31295)

    def test_it_never_claims_a_rank_among_magic_cards(self):
        #the three things /unique says about printed cards, none of which can be
        #said about a card that is not in Magic
        for below, total in ((0, 31295), (1, 31295), (31294, 31295), (31295, 31295), (0, 0)):
            said = custom_words(below, total)
            assert "already do everything it does" not in said
            assert "most unique card in Magic" not in said
            assert "#" not in said


@needs_db
class TestTheSentenceIsCountedOnRulesTextAlone:
    #a temp table named cards shadows the real one inside this transaction, so
    #the population is exactly these rows. concept_uniqueness is present and
    #DELIBERATELY CONTRADICTS the rules score on two of them: /unique blends the
    #two and this must not, or a printed card typed into /custom would read its
    #own /unique percent and the wording would be a lie
    CARDS = [
        #name, uniqueness, concept_uniqueness, legal_commander
        ("novel",       0.40,          0.01, True),
        ("middling",    0.20,          0.99, True),
        ("ordinary",    0.05,          0.50, True),
        ("tied at zero", 0.0,          0.90, True),
        ("also tied",   -1.1920929e-07, 0.10, True),
        ("noise tied",   5.9604645e-07, 0.00, True),
        ("not legal",   0.30,          0.30, False),
    ]

    @pytest.fixture
    def conn(self):
        import db
        with db.pool.connection() as c:
            c.execute("CREATE TEMP TABLE cards (name text, uniqueness real, "
                      "concept_uniqueness real, legal_commander boolean) ON COMMIT DROP")
            for row in self.CARDS:
                c.execute("INSERT INTO cards VALUES (%s, %s, %s, %s)", row)
            yield c
            c.rollback()

    def test_the_pool_is_commander_legal_cards_with_a_score(self, conn):
        #six legal rows, the seventh left out however original it is
        assert rules_standing(conn, 1.0)[1] == 6

    def test_a_card_beating_everything_reads_the_whole_pool(self, conn):
        assert rules_standing(conn, 1.0) == (6, 6)

    def test_the_bottom_tie_counts_as_zero(self, conn):
        #three of the six sit under UNIQUE_NOISE and tie there, so a card that
        #also ties beats none of them rather than sorting on rounding error
        assert rules_standing(conn, 0.0) == (0, 6)
        assert rules_standing(conn, app.UNIQUE_NOISE / 2) == (0, 6)

    def test_a_middling_card_beats_the_tie_and_the_ordinary_one(self, conn):
        assert rules_standing(conn, 0.20) == (4, 6)

    def test_the_concept_score_is_not_read(self, conn):
        #"middling" has the pool's highest concept score and a middling rules
        #score. blending would put it near the top; this must not move it
        blended = rules_standing(conn, 0.20)
        conn.execute("UPDATE cards SET concept_uniqueness = 0.0")
        assert rules_standing(conn, 0.20) == blended


@needs_db
class TestScoringTypedTextAgainstTheTable:
    #the seed's vectors are one hot on distinct axes, so a cosine between two
    #stored lines is 0 or 1 and a query vector's similarity to each is something
    #this can choose exactly. axis 1 is "Whenever this card attacks, draw a
    #card.", on three of the four fixture cards; axis 2 is "Destroy target
    #land."; nothing is stored on axis 5

    @pytest.fixture
    def typed(self, monkeypatch, seeded):
        #the model never runs here. custom_score imports embedder inside itself,
        #so this is the same module object it reaches for
        def score(vectors, **kwargs):
            monkeypatch.setattr(embedder, "embed",
                                lambda texts: [np.asarray(v, dtype=np.float32) for v in vectors])
            from views.custom import custom_score
            with app.app.test_request_context("/custom"):
                filters = app.read_filters()
            names = ["line %d" % i for i in range(len(vectors))]
            return custom_score(names, kwargs.pop("filters", filters), "match", **kwargs)

        return score

    def axis(self, i):
        import seed
        return seed.vec(i)

    def between(self, i, j):
        #halfway between two axes, so the cosine to a line on either is 1/sqrt(2)
        import seed
        v = seed.vec(i)
        v[j] = 1.0
        return [x / (2 ** 0.5) for x in v]

    def test_a_line_already_in_the_table_is_not_original(self, typed):
        assert typed([self.axis(1)])["uniqueness"] == pytest.approx(0.0, abs=1e-6)

    def test_a_line_nothing_comes_near_is_wholly_original(self, typed):
        assert typed([self.axis(5)])["uniqueness"] == pytest.approx(1.0, abs=1e-6)

    def test_the_most_isolated_line_decides(self, typed):
        #recompute_uniqueness's rule, and the reason it is not an average: one
        #genuinely new ability makes a card original however ordinary the rest
        #of it is. averaging these two would read 0.5, taking the best 0.0
        got = typed([self.axis(1), self.axis(5)])["uniqueness"]
        assert got == pytest.approx(1.0, abs=1e-6)

    def test_a_partial_match_scores_between(self, typed):
        #1 - 1/sqrt(2), so neither the floor nor the ceiling can pass by accident
        got = typed([self.between(2, 5)])["uniqueness"]
        assert got == pytest.approx(1 - 2 ** -0.5, abs=1e-5)

    def test_with_nothing_to_exclude_the_results_still_come_back(self, typed):
        #oracle_id <> NULL is NULL, which drops EVERY row rather than one card's.
        #no route passes exclude_id, so this is the shape the page actually runs
        assert typed([self.axis(1)])["results"]

    def test_excluding_a_card_drops_only_that_card(self, typed):
        import seed
        everyone = {r["name"] for r in typed([self.axis(1)])["results"]}
        without = {r["name"] for r in typed([self.axis(1)], exclude_id=seed.ANCHOR)["results"]}
        assert "Fixture Anchor" in everyone
        assert without == everyone - {"Fixture Anchor"}

    def test_a_filter_moves_the_list_and_never_the_sentence(self, typed):
        #how original a card is cannot depend on which colours somebody is
        #browsing. the fixture cards are all blue, so filtering to red empties
        #the list while the score behind the sentence has to stay put
        with app.app.test_request_context("/custom?colors=R&cmode=exact"):
            red = app.read_filters()
        wide = typed([self.between(2, 5)])
        narrow = typed([self.between(2, 5)], filters=red)
        assert narrow["results"] == []
        assert narrow["uniqueness"] == wide["uniqueness"]
        assert narrow["words"] == wide["words"]
