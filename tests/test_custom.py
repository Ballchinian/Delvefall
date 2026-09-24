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
                          rules_standing, typed_lines)


def cleaned(text, name=""):
    #what the model is sent: read_custom pairs every typed line with its cleaning
    return [c for _, c in read_custom(text, name) if c]


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
            req.waited = timeout
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

    def test_a_slow_answer_is_waited_on_once_rather_than_sent_again(self, served):
        #the service works one request at a time and keeps a timed out one in
        #its queue. on 2026-09-22 each 30s retry queued another 20 line request
        #behind the last, and /admin never got an answer again
        calls = served([TimeoutError("timed out")], budget=5.0)
        with pytest.raises(embedder.EmbedderDown):
            embedder.embed(["Flying"])
        assert len(calls) == 1
        assert 4.0 < calls[0].waited <= 5.0

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
        assert cleaned("Flying\nTrample") == ["Flying", "Trample"]

    def test_blank_lines_are_not_lines(self):
        assert cleaned("Flying\n\n   \nTrample") == ["Flying", "Trample"]

    def test_windows_newlines_are_newlines(self):
        #a textarea posted from windows sends \r\n. clean_line's strip() would
        #cover the text either way, so what this really guards is the length
        #check, which counts the raw line: a full length line arriving as \r\n
        #measures one over and gets turned away for being too long
        assert cleaned("Flying\r\nTrample") == ["Flying", "Trample"]
        assert cleaned("x" * MAX_CHARS + "\r\nFlying") == ["x" * MAX_CHARS, "Flying"]

    def test_the_name_becomes_this_card(self):
        #6,558 stored lines say "this card", and none say the card's own name,
        #so without this a card that refers to itself matches nothing
        assert cleaned("Shivan Dragon deals 2 damage.", "Shivan Dragon") == \
            ["this card deals 2 damage."]

    def test_no_name_leaves_the_text_alone(self):
        assert cleaned("Shivan Dragon deals 2 damage.") == ["Shivan Dragon deals 2 damage."]

    def test_a_line_under_three_characters_is_dropped(self):
        #the ingest's floor, applied by the ingest's own splitter. it is UNDER
        #three, so "{T}" at exactly three stays: a stored line that short is
        #rare but real, and the floor is there for stray punctuation
        assert cleaned("Flying\nII\nTrample") == ["Flying", "Trample"]
        assert cleaned("{T}") == ["{T}"]

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
        assert len(cleaned(ok)) == MAX_LINES
        with pytest.raises(Rejected, match=str(MAX_LINES)):
            read_custom("\n".join(["Flying"] * (MAX_LINES + 1)))

    def test_too_long_a_line_names_the_limit(self):
        assert cleaned("x" * MAX_CHARS) == ["x" * MAX_CHARS]
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

    def test_a_line_too_long_is_refused_before_anything_is_cleaned(self, monkeypatch):
        #clean_line's \(.*?\) is quadratic on unclosed brackets: 20,000 of them took
        #2s holding the GIL, and two such posts froze both workers. the rejection
        #page drew the card through the cleaning too, so the route is what is asked
        import views.custom

        def refuse(card):
            raise AssertionError("cleaned a line the limits turn away")

        monkeypatch.setattr(views.custom, "split_lines", refuse)
        with app.app.test_request_context("/custom", method="POST",
                                          data={"text": "(" * 20000, "name": "Test"}):
            page = views.custom.custom_post()
        assert "20000 characters" in page

    def test_a_stray_space_in_either_half_of_the_name_still_matches(self):
        #clean_line swaps the name by plain substring, so "Fire " would miss
        #"Fire deals" and a card naming itself would match nothing
        assert cleaned("Fire deals 2 damage to any target.", "Fire  // Ice") == \
            ["this card deals 2 damage to any target."]

    def test_a_blank_half_of_the_name_replaces_nothing(self):
        #"A //   // B" splits into a half that is one space, and replacing " "
        #rewrites every space on the card
        assert cleaned("Flying and first strike.", "A //   // B") == ["Flying and first strike."]

    def test_a_name_starting_with_a_comma_is_refused(self):
        #clean_line also replaces the part before a name's first comma, and when
        #that part is "" it puts "this card" between every character. a posted
        #name of "," turned every card into a 500
        for name in (",", "A // ,B"):
            with pytest.raises(Rejected):
                read_custom("Flying", name)

    def test_the_cleaned_line_has_to_fit_the_service_too(self):
        #"this card" is nine characters, so a one letter name can clean a line
        #LONGER, and embed/app.py refuses past 600 with a 400 the page does not
        #catch. 66 nines are 594 and fit, 67 are 603
        assert cleaned("x" * 66, "x") == ["this card" * 66]
        with pytest.raises(Rejected, match=str(MAX_CHARS)):
            read_custom("x" * 67, "x")

    def test_only_a_newline_ends_a_line(self):
        #split_lines splits on "\n" alone. counting U+2028 or \x0b as breaks too let
        #the limits pass a card whose lines past 20 then dropped out of sight
        from mirror import split_lines
        text = "Flying\u2028Trample\x0bMenace\nHaste"
        assert len(read_custom(text)) == len(split_lines({"oracle_text": text, "name": ""})) == 2
        assert len(typed_lines(text)) == 2


class TestAnAnswerWithNoListKeepsTheControls:
    #the filter bar, the sort and the picks were drawn on a full answer alone, so
    #the retry a cold wake asks for started from the default filters. EMBED_URL
    #unset is the matcher down, answered before any database read

    DATA = {"text": "Flying\nWhenever this card attacks, draw a card.", "lines": ["1"],
            "cur": "eur", "sort": "price", "dir": "desc", "colors": ["R"], "cmode": "exact"}

    def post(self, monkeypatch, **extra):
        from views.custom import custom_post
        monkeypatch.setattr(embedder, "EMBED_URL", "")
        with app.app.test_request_context("/custom", method="POST", data=dict(self.DATA, **extra)):
            got = custom_post()
        return got[0] if isinstance(got, tuple) else got

    def assert_controls(self, page):
        assert '<option value="eur" selected>' in page
        assert 'value="R" checked' in page
        assert '<option value="price" selected>' in page
        assert '<option value="desc" selected>' in page

    def test_a_matcher_that_did_not_wake_keeps_them_and_the_picks(self, monkeypatch):
        page = self.post(monkeypatch)
        assert "wake up in time" in page
        self.assert_controls(page)
        assert '<input type="hidden" name="lines" value="1">' in page
        assert 'class="oracle-line picked"' in page
        #nothing was read from line_stats, so no line can be said to be unprinted
        assert "no printed card says this" not in page

    def test_a_rejected_card_keeps_them(self, monkeypatch):
        page = self.post(monkeypatch, text="x" * (MAX_CHARS + 1))
        assert str(MAX_CHARS) in page
        self.assert_controls(page)


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


@pytest.fixture
def typed(monkeypatch, seeded):
    #scores typed text without the model: custom_score imports embedder inside
    #itself, so this is the same module object it reaches for.
    #
    #at module level rather than in a class, both the sentence and the chips
    #being answers to the same call
    def score(vectors, **kwargs):
        monkeypatch.setattr(embedder, "embed",
                            lambda texts: [np.asarray(v, dtype=np.float32) for v in vectors])
        from views.custom import custom_score
        with app.app.test_request_context("/custom"):
            filters = app.read_filters()
        names = ["line %d" % i for i in range(len(vectors))]
        return custom_score(names, kwargs.pop("filters", filters), "match", **kwargs)

    return score


#the model the seed's vectors stand for, by name and by the sha256 of its weights.
#the chips are refused unless tag_probe's stamps still match the vectors'
PROBE_MODEL = "test/model-a"
WEIGHTS = "d06f255a" + "0" * 56
RETRAIN = "e17a3c90" + "0" * 56


@needs_db
class TestTheChipsUnderTheForm:
    #the seed's one hot vectors again. a probe row here is an axis scaled by 40
    #with a bias of -20, so a line ON that axis scores sigmoid(20), about 1, and
    #a line anywhere else scores sigmoid(-20), about 0. without the bias every
    #unrelated tag would sit at sigmoid(0) = 0.5 and the top-up would show them

    @pytest.fixture
    def probe(self, seeded):
        #the table is emptied on the way in as well as out: a database somebody
        #has run tools/load_tag_probe.py against would otherwise answer these
        #with 1,933 real tags
        import db
        import seed
        from psycopg.types.json import Jsonb

        def clean(conn):
            conn.execute("DELETE FROM tag_probe")
            conn.execute("DELETE FROM meta WHERE key IN ('embed_model', 'tag_probe_model', "
                         "'embed_sha256', 'tag_probe_sha256')")

        with db.pool.connection() as conn:
            clean(conn)

        def load(rows, stamp=PROBE_MODEL, vectors_by=PROBE_MODEL, trained=None, weights=None):
            #the stamps are the loader's, and None for either side is a real state:
            #a probe loaded before a stamp existed, or a database with no ingest.
            #no shas at all is a database no ingest has recorded weights for
            with db.pool.connection() as conn:
                for tag, axis, banned, types in rows:
                    w = np.asarray(seed.vec(axis), dtype=np.float32) * 40
                    conn.execute("INSERT INTO tag_probe (tag, w, b, banned, types) "
                                 "VALUES (%s, %s, %s, %s, %s)", (tag, w, -20.0, banned, Jsonb(types)))
                for key, value in (("embed_model", vectors_by), ("tag_probe_model", stamp),
                                   ("embed_sha256", weights), ("tag_probe_sha256", trained)):
                    if value is not None:
                        conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                                     (key, value))

        yield load
        with db.pool.connection() as conn:
            clean(conn)

    def test_an_empty_probe_shows_no_chips_at_all(self, typed, probe):
        #the state of every database until tools/load_tag_probe.py has run. the
        #neighbours alone would still name draw-on-attack, and showing it would
        #be a worse rule rather than a missing one
        import seed
        probe([])
        assert typed([seed.vec(1)])["chips"] == []

    def test_a_probe_with_no_model_stamp_shows_nothing(self, typed, probe):
        #a database loaded before the stamp existed. the match cannot be proved, and
        #the failure being guarded has no symptom, so it is refused rather than shown
        import seed
        probe([("draw-on-attack", 1, False, {})], stamp=None)
        assert typed([seed.vec(1)])["chips"] == []

    def test_a_probe_stamped_with_another_model_shows_nothing(self, typed, probe):
        #what a model swap leaves behind: 768 weights fitted to the old vector space
        #scoring the new vectors, every number still in [0,1] and none of them meaning
        #anything
        import seed
        probe([("draw-on-attack", 1, False, {})], stamp="test/model-b")
        assert typed([seed.vec(1)])["chips"] == []

    def test_a_stamp_with_no_vectors_to_match_shows_nothing(self, typed, probe):
        #no embed_model in meta is a database the ingest has never run against
        import seed
        probe([("draw-on-attack", 1, False, {})], vectors_by=None)
        assert typed([seed.vec(1)])["chips"] == []

    def test_the_reason_names_both_models(self, probe):
        #tools/show_chips.py prints this instead of 0 chips a card, so it has to say
        #which way round the mismatch is
        import db
        from views.custom import probe_stale
        probe([("draw-on-attack", 1, False, {})], stamp="test/model-b")
        with db.pool.connection() as conn:
            why = probe_stale(conn)
        assert "test/model-b" in why
        assert PROBE_MODEL in why

    def test_matching_weights_show_chips(self, typed, probe):
        import seed
        probe([("draw-on-attack", 1, False, {})], trained=WEIGHTS, weights=WEIGHTS)
        assert [c["tag"] for c in typed([seed.vec(1)])["chips"]] == ["draw-on-attack"]

    def test_a_retrain_under_the_same_name_shows_nothing(self, typed, probe):
        #the names match and the weights do not: a new release of the same repo
        #reseeds the vectors and leaves the probe fitted to the old ones
        import seed
        probe([("draw-on-attack", 1, False, {})], trained=WEIGHTS, weights=RETRAIN)
        assert typed([seed.vec(1)])["chips"] == []

    def test_a_probe_with_no_weights_stamp_shows_nothing_once_the_vectors_have_one(self, typed, probe):
        #the names match here too, and would pass on their own
        import seed
        probe([("draw-on-attack", 1, False, {})], weights=WEIGHTS)
        assert typed([seed.vec(1)])["chips"] == []

    def test_the_reason_names_both_weights(self, probe):
        import db
        from views.custom import probe_stale
        probe([("draw-on-attack", 1, False, {})], trained=WEIGHTS, weights=RETRAIN)
        with db.pool.connection() as conn:
            why = probe_stale(conn)
        assert WEIGHTS[:12] in why and RETRAIN[:12] in why

    def test_a_tag_both_halves_name_is_the_first_chip(self, typed, probe):
        #axis 1 is "Whenever this card attacks, draw a card.", stored on three
        #cards and tagged draw-on-attack on all three
        import seed
        probe([("draw-on-attack", 1, False, {}), ("sac-outlet", 3, False, {})])
        chips = typed([seed.vec(1)])["chips"]
        assert [c["tag"] for c in chips][0] == "draw-on-attack"

    def test_a_chip_carries_what_the_tag_means(self, typed, probe):
        import seed
        probe([("draw-on-attack", 1, False, {})])
        chips = typed([seed.vec(1)])["chips"]
        assert chips[0]["description"] == "draws when it attacks"

    def test_a_banned_tag_is_never_a_chip(self, typed, probe):
        #make_tagreview.md's card and junk verdicts arrive as this column
        import seed
        probe([("draw-on-attack", 1, True, {})])
        assert [c["tag"] for c in typed([seed.vec(1)])["chips"]] == []

    def test_a_typed_type_line_drops_a_tag_that_never_lands_on_it(self, typed, probe):
        import seed
        probe([("draw-on-attack", 1, False, {"Instant": 0.999, "Creature": 0.0001})])
        wide = typed([seed.vec(1)])
        narrow = typed([seed.vec(1)], type_line="Creature — Test")
        assert "draw-on-attack" in [c["tag"] for c in wide["chips"]]
        assert "draw-on-attack" not in [c["tag"] for c in narrow["chips"]]

    def test_a_type_line_nothing_can_be_read_out_of_narrows_nothing(self, typed, probe):
        #only the first card type word is read, and "Delvefall" is not one
        import seed
        probe([("draw-on-attack", 1, False, {"Instant": 0.999, "Creature": 0.0001})])
        got = typed([seed.vec(1)], type_line="Delvefall")
        assert "draw-on-attack" in [c["tag"] for c in got["chips"]]

    def test_every_typed_line_gets_a_say(self, typed, probe):
        #a card is the best of its lines, so an ability on the second line is as
        #chippable as one on the first
        import seed
        probe([("draw-on-attack", 1, False, {}), ("sac-outlet", 3, False, {})])
        chips = [c["tag"] for c in typed([seed.vec(1), seed.vec(3)])["chips"]]
        assert "draw-on-attack" in chips
        assert "sac-outlet" in chips

    def test_the_next_page_of_results_does_not_pay_for_them(self, typed, probe):
        #/custom/more redraws the grid and no chips, so it asks for none
        import seed
        probe([("draw-on-attack", 1, False, {})])
        assert typed([seed.vec(1)], want_chips=False)["chips"] == []

    def test_the_sentence_and_the_chips_ignore_which_line_is_picked(self, typed, probe):
        #rank_on is a control on the LIST. the sentence is a calibrated number about
        #the whole card, and the chips' 98% marked precision was measured on whole
        #cards, so neither may move when a line is picked. both did, once
        import seed
        probe([("draw-on-attack", 1, False, {}), ("sac-outlet", 3, False, {})])
        whole = typed([seed.vec(1), seed.vec(3)])
        one = typed([seed.vec(1), seed.vec(3)], rank_on={0})
        assert one["uniqueness"] == whole["uniqueness"]
        assert [c["tag"] for c in one["chips"]] == [c["tag"] for c in whole["chips"]]
        #and the chips really are saying something, or this passes on two empties
        assert len(whole["chips"]) >= 2

    def test_the_sentence_is_unchanged_by_the_chips(self, typed, probe):
        #the neighbour query went from one row to ten to feed them, and the
        #originality is still the nearest of those rows
        import seed
        probe([("draw-on-attack", 1, False, {})])
        assert typed([seed.vec(1)])["uniqueness"] == pytest.approx(0.0, abs=1e-6)
        assert typed([seed.vec(5)])["uniqueness"] == pytest.approx(1.0, abs=1e-6)


@needs_db
class TestScoringTypedTextAgainstTheTable:
    #the seed's vectors are one hot on distinct axes, so a cosine between two
    #stored lines is 0 or 1 and a query vector's similarity to each is something
    #this can choose exactly. axis 1 is "Whenever this card attacks, draw a
    #card.", on three of the four fixture cards; axis 2 is "Destroy target
    #land."; nothing is stored on axis 5

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


class TestTypedLinesPairWithWhatTheModelReads:
    #the tick boxes post indexes into the TYPED lines, and the scoring uses the
    #cleaned line each one produced. if those two lists ever stop lining up, every
    #index shifts and switching one line off silently drops a different ability

    LINES = ["Flying", "Whenever this creature attacks, draw a card.", "{T}: Add {G}.",
             "ab", "Menace"]

    def test_the_splitter_is_per_line_so_the_pairing_holds(self):
        #the whole assumption in one assertion: split_lines carries nothing between
        #lines, so asking it one line at a time gives the same list as asking once.
        #a splitter that ever merged or reordered would fail here first
        from mirror import split_lines
        text = "\n".join(self.LINES)
        whole = split_lines({"oracle_text": text, "name": "Test"})
        one_at_a_time = []
        for line in self.LINES:
            one_at_a_time += split_lines({"oracle_text": line, "name": "Test"})
        assert whole == one_at_a_time

    def test_a_line_the_splitter_drops_pairs_with_nothing(self):
        #under three characters once cleaned, so there is nothing to rank on and
        #nothing to switch off either
        pairs = read_custom("ab\nWhenever this creature attacks, draw a card.", "Test")
        assert [cleaned is None for _, cleaned in pairs] == [True, False]
        assert pairs[0][0] == "ab"

    def test_the_rows_stay_in_the_order_typed(self):
        pairs = read_custom("Flying\nMenace\nTrample", "Test")
        assert [raw for raw, _ in pairs] == ["Flying", "Menace", "Trample"]

    def test_blank_lines_are_not_rows_at_all(self):
        #a blank row would take an index and shift every box below it
        pairs = read_custom("Flying\n\n   \nMenace", "Test")
        assert [raw for raw, _ in pairs] == ["Flying", "Menace"]


class TestReadingWhichLinesToScore:

    def kept(self, data, how_many):
        from views.custom import read_kept
        with app.app.test_request_context("/custom", method="POST", data=data):
            return read_kept(how_many)

    def test_nothing_posted_means_every_line(self):
        #what /search's picker already means by an empty pick, and scoring nothing
        #is not a question anyone can answer
        assert self.kept({}, 3) == {0, 1, 2}

    def test_the_boxes_left_on_are_what_gets_scored(self):
        assert self.kept({"lines": ["0", "2"]}, 3) == {0, 2}

    def test_an_index_past_the_end_is_dropped(self):
        assert self.kept({"lines": ["1", "9"]}, 3) == {1}

    def test_a_unicode_digit_is_not_a_500(self):
        #"²".isdigit() is True where int() on it raises, so isdigit on its own
        #turns a posted body into an error page
        assert self.kept({"lines": ["²"]}, 2) == {0, 1}


@needs_db
class TestPickingALineRanksOnIt:
    #the point of the feature: a keyword hundreds of cards share otherwise drags
    #the list toward whatever else those cards have in common.
    #
    #the pick is a control on the LIST alone. the model still sees the whole card,
    #because the sentence is a calibrated number about the card and the chips' 98%
    #marked precision was measured on whole cards

    TWO = "Menace\nWhenever this creature attacks, draw a card."

    @pytest.fixture
    def asked(self, monkeypatch, seeded):
        #two recordings: what reached the model, and what the ranking was handed.
        #asserted by substring rather than against clean_line's exact output, or
        #this would be checking the cleaning against itself. case folded because
        #clean_line keeps the case it was given
        import seed
        embedded, ranked = [], []

        def fake(texts):
            embedded.append(list(texts))
            return [np.asarray(seed.vec(1), dtype=np.float32) for _ in texts]

        monkeypatch.setattr(embedder, "embed", fake)
        real = app.similar_from_lines

        def spy(qlines, *args, **kwargs):
            ranked.append([q["line_text"] for q in qlines])
            return real(qlines, *args, **kwargs)

        monkeypatch.setattr(app, "similar_from_lines", spy)

        def post(route="post", **extra):
            from views.custom import custom_more, custom_post
            data = dict({"text": self.TWO}, **extra)
            with app.app.test_request_context("/custom", method="POST", data=data):
                #the rendered page hangs off the function, for the tests that read
                #what the card looks like rather than what was scored
                post.page = (custom_post if route == "post" else custom_more)()
            return {"embedded": embedded[-1], "ranked": ranked[-1]}

        return post

    def test_the_whole_card_is_ranked_on_by_default(self, asked):
        got = asked()
        assert len(got["ranked"]) == 2
        assert any("menace" in t.lower() for t in got["ranked"])
        assert any("draw a card" in t for t in got["ranked"])

    def test_the_line_not_picked_is_left_out_of_the_ranking(self, asked):
        got = asked(lines=["1"])
        assert len(got["ranked"]) == 1
        assert "draw a card" in got["ranked"][0]
        assert "menace" not in got["ranked"][0].lower()

    def test_the_keyword_can_be_the_one_picked(self, asked):
        #nothing in the rule prefers the interesting line: it is whichever is picked
        got = asked(lines=["0"])
        assert len(got["ranked"]) == 1
        assert "menace" in got["ranked"][0].lower()

    def test_the_model_still_sees_every_line(self, asked):
        #the sentence and the chips are about the CARD, so narrowing the ranking
        #must not narrow what was embedded. this is the regression: it did
        got = asked(lines=["1"])
        assert len(got["embedded"]) == 2
        assert any("menace" in t.lower() for t in got["embedded"])

    def test_a_line_not_picked_still_says_how_common_it_is(self, asked):
        #the count is what the decision to rank without a line is made from. the
        #seed puts Flying on 3,000 cards for exactly this reason, and Flying is the
        #line NOT picked here
        asked(text="Flying\nWhenever this card attacks, draw a card.", lines=["1"])
        page = asked.page
        #the thousands separator too, since the number is what carries the point
        assert "3,000" in page
        assert "printed cards" in page

    def test_the_picked_line_is_the_one_marked_on_the_card(self, asked):
        #/search's own class, so its hover, picked and focus styles come with it
        asked(text="Flying\nWhenever this card attacks, draw a card.", lines=["1"])
        assert 'class="oracle-line picked"' in asked.page
        #carried forward, or a second click would lose the first
        assert '<input type="hidden" name="lines" value="1">' in asked.page

    def test_a_line_the_model_never_reads_is_not_a_control(self, asked):
        #"ab" is under the splitter's three characters. clickable, it posted a pick
        #of nothing and the page came back asking for a readable line with no list
        asked(text="ab\nWhenever this card attacks, draw a card.")
        assert '<div class="oracle-plain"' in asked.page
        assert 'data-idx="0"' not in asked.page
        assert 'data-idx="1"' in asked.page

    def test_nothing_picked_marks_nothing_and_says_how_to(self, asked):
        #the class and not the word: the filters panel has its own picked colors
        asked(text="Flying\nWhenever this card attacks, draw a card.")
        assert 'class="oracle-line picked"' not in asked.page
        assert 'class="oracle-line"' in asked.page
        assert "Click a line to rank on it alone" in asked.page

    def test_page_two_is_ranked_on_the_same_lines(self, asked):
        #custom.js posts the WHOLE form for /custom/more, the picks with it, so a
        #second page that ignored them would append a different ranking onto the
        #first
        got = asked(route="more", lines=["1"])
        assert len(got["ranked"]) == 1
        assert "draw a card" in got["ranked"][0]
        assert "menace" not in got["ranked"][0].lower()
