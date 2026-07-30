#one test per bug actually shipped and fixed, against real rows.
#
#the ones the pure-function suite cannot reach: every one lives in code that
#talks to postgres, which is why they all went unnoticed long enough to be found
#by reading rather than by failing. each names the wrong behaviour it guards, so
#a change reintroducing one gets told which bug it just brought back.
#
#needs TEST_DATABASE_URL, and without it the whole module skips

import pytest

import app
import seed
from conftest import needs_db

pytestmark = needs_db


@pytest.fixture(autouse=True)
def _always_seeded(seeded):
    #every test in this module reads the fixture world, including the ones that
    #reach it through the pool rather than through a connection of their own
    return seeded


@pytest.fixture
def conn(seeded):
    import db
    with db.pool.connection() as c:
        yield c


def plain_filters(cur="usd"):
    #what read_filters would hand back with nothing switched on, built by hand
    #because these tests have no request to read it off
    return {"errors": [], "colors": "", "cmode": "atmost", "pmin": None, "pmax": None,
            "mvmin": None, "mvmax": None, "smin": None, "smax": None, "types": [],
            "cmdr": False, "gc": False, "illegal": True, "cur": cur,
            "fq_sql": None, "fq_params": []}


class TestConceptOnlyCardsSortOnSalt:
    #BUG: the concept injection selected price, rank and date but not salt, so a
    #card the lines never found sank into the "nobody voted" pile on the salt
    #sorts while its own card frame printed a real salt score

    def test_a_concept_only_find_sorts_among_the_salted(self):
        #min_pct 0 puts every candidate in the strong tier, so this is measuring
        #the sort and nothing else
        results, _, _ = app.find_similar(seed.ANCHOR, [], plain_filters(), 0, "salty", how_many=20)
        names = [r["name"] for r in results]
        ghost = next(r for r in results if r["name"] == "Fixture Ghost")

        assert ghost["concept_only"], "the fixture stopped exercising the concept path"
        #it carries a real salt figure on its own frame
        assert ghost["salt"] == "2.00"
        #2.00 sits under the twin's 2.50 and above the stranger's 0.50
        assert names.index("Fixture Ghost") < names.index("Fixture Stranger")
        assert names.index("Fixture Twin") < names.index("Fixture Ghost")
        #and the pile it used to land in was the very end
        assert names[-1] != "Fixture Ghost"

    def test_the_mild_direction_agrees(self):
        results, _, _ = app.find_similar(seed.ANCHOR, [], plain_filters(), 0, "mild", how_many=20)
        names = [r["name"] for r in results]
        assert names.index("Fixture Ghost") > names.index("Fixture Stranger")
        #the half that bites: at 2.00 the ghost is milder than the twin's 2.50,
        #so it has to come FIRST. sunk into the unvoted pile it comes last, and
        #last is after the twin either way
        assert names.index("Fixture Ghost") < names.index("Fixture Twin")

    def test_an_unvoted_card_still_sinks(self, conn):
        #the behaviour the fix must NOT have broken: no salt is not mild
        conn.execute("UPDATE cards SET salt = NULL WHERE oracle_id = %s", (seed.COUSIN,))
        conn.commit()
        try:
            for sort in ("salty", "mild"):
                results, _, _ = app.find_similar(seed.ANCHOR, [], plain_filters(), 0, sort, how_many=20)
                assert results[-1]["name"] == "Fixture Cousin", sort
        finally:
            conn.execute("UPDATE cards SET salt = 0.10 WHERE oracle_id = %s", (seed.COUSIN,))
            conn.commit()


class TestDeckPanelsReadBothEnds:
    #BUG: the query asked for LIMIT limit * 2 and the dedupe below it tested
    #len(rows) > limit * 2, which can never be true. the "mildest" end was read
    #out of the MIDDLE of the ordering

    def test_the_bottom_end_is_the_real_bottom(self, conn):
        ids = [seed.deck_id(i) for i in range(seed.DECK_FILLER)]
        rows = app.metric_cards(conn, ids, "salt", "usd")
        assert len(rows) == app.DECK_EVIDENCE_MAX * 2

        true_mildest = conn.execute("""
            SELECT name FROM cards WHERE oracle_id = ANY(%s::uuid[]) AND salt IS NOT NULL
            ORDER BY salt ASC, name DESC LIMIT 1
        """, (ids,)).fetchone()["name"]
        assert rows[-1]["name"] == true_mildest

    def test_the_top_end_is_still_the_top(self, conn):
        ids = [seed.deck_id(i) for i in range(seed.DECK_FILLER)]
        rows = app.metric_cards(conn, ids, "salt", "usd")
        saltiest = conn.execute("""
            SELECT name FROM cards WHERE oracle_id = ANY(%s::uuid[]) AND salt IS NOT NULL
            ORDER BY salt DESC, name LIMIT 1
        """, (ids,)).fetchone()["name"]
        assert rows[0]["name"] == saltiest

    def test_a_small_deck_keeps_everything(self, conn):
        #the cheap case: the two slices overlap and nothing is dropped
        ids = [seed.deck_id(i) for i in range(10)]
        rows = app.metric_cards(conn, ids, "salt", "usd")
        assert len(rows) == 10


class TestFeedbackQuotesThePageNumber:
    #BUG: concept_between scored against the anchor's FULL tag set even when the
    #page had narrowed it, so a report answered with a percent the page never
    #printed. its sibling: a picked keyword line leaves no vector at all, where
    #the ranking drops to rules text and the reply has to as well

    def test_a_picked_line_narrows_the_vector(self, conn):
        #the anchor owns two concepts on two lines and the twin owns both, so
        #narrowing to one line has to move the number. the assertion the bug
        #failed: handing over the dropped tags alone scored the FULL card either way
        line = "Whenever this card attacks, draw a card."
        wide = app.concept_between(conn, seed.ANCHOR, seed.TWIN)
        narrow = app.concept_between(conn, seed.ANCHOR, seed.TWIN, (), [line], ())
        assert wide is not None and narrow is not None
        assert narrow != wide
        #and narrowing to one of two shared concepts can only lose overlap
        assert narrow < wide

    def test_a_forced_tag_comes_back(self, conn):
        #the mirror of the above: a tag the line picker set aside, put back by
        #hand, has to reach the vector the report is scored against
        line = "Whenever this card attacks, draw a card."
        narrow = app.concept_between(conn, seed.ANCHOR, seed.TWIN, (), [line], ())
        forced = app.concept_between(conn, seed.ANCHOR, seed.TWIN, (), [line], ["sac-outlet"])
        assert forced > narrow

    def test_a_picked_keyword_line_drops_the_axis(self, conn):
        #"Flying" owns no tags, and the attribution HAS run on this card, so an
        #empty answer means the axis sits out rather than falling back
        assert app.concept_between(conn, seed.ANCHOR, seed.TWIN, (), ["Flying"], ()) is None

    def test_none_and_zero_are_different_answers(self, conn):
        #the stranger shares no tags with the anchor, which is a real 0 and must
        #not read as "the axis sat out"
        assert app.concept_between(conn, seed.ANCHOR, seed.STRANGER) == 0

    def test_dropping_every_tag_drops_the_axis(self, conn):
        dropped = [t["tag"] for t in conn.execute(
            "SELECT tag FROM card_tags WHERE oracle_id = %s", (seed.ANCHOR,)).fetchall()]
        assert app.concept_between(conn, seed.ANCHOR, seed.TWIN, dropped) is None


class TestSwapToolAlwaysAnswers:
    #BUG: swap_candidates blended unconditionally, so with no anchor vector every
    #candidate scored half its rules-text percent against a gate of 75 and the
    #tool returned nothing at all, silently

    def anchor(self, conn):
        row = conn.execute("SELECT " + ", ".join("c." + f for f in app.CARD_FIELDS.split(", ")) +
                           ", c.cmc, c.price_usd AS price FROM cards c WHERE c.oracle_id = %s",
                           (seed.ANCHOR,)).fetchone()
        return dict(row)

    def test_it_suggests_with_the_tags_on(self, conn):
        cards, _, _ = app.swap_candidates(conn, self.anchor(conn), [seed.ANCHOR], None,
                                          "salt", "asc", currency="usd")
        assert [c["name"] for c in cards] == ["Fixture Cousin"]
        assert cards[0]["blended"] is True

    def test_it_still_suggests_with_every_tag_dropped(self, conn):
        dropped = [t["tag"] for t in conn.execute(
            "SELECT tag FROM card_tags WHERE oracle_id = %s", (seed.ANCHOR,)).fetchall()]
        cards, _, _ = app.swap_candidates(conn, self.anchor(conn), [seed.ANCHOR], None,
                                          "salt", "asc", currency="usd", dropped=dropped)
        #it used to be zero, which the page showed as "no suggestions"
        assert [c["name"] for c in cards] == ["Fixture Cousin"]

    def test_and_says_it_did_not_blend(self, conn):
        dropped = [t["tag"] for t in conn.execute(
            "SELECT tag FROM card_tags WHERE oracle_id = %s", (seed.ANCHOR,)).fetchall()]
        cards, _, _ = app.swap_candidates(conn, self.anchor(conn), [seed.ANCHOR], None,
                                          "salt", "asc", currency="usd", dropped=dropped)
        #the tooltip must not claim a blend that never happened
        assert cards[0]["blended"] is False
        assert cards[0]["match"] == cards[0]["mech_pct"]
