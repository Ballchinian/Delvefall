#the uniqueness number /unique ranks and deals by.
#
#the blend is one sum spelled twice: as sql for every query that ranks the table,
#and as python for scoring a card that is not in the table. the first two classes
#hold those spellings to one definition

import ast
import os
import re

import pytest

import app
from conftest import ROOT, needs_db


def owners_of(needle):
    #the top level name each string constant mentioning needle sits under
    with open(os.path.join(ROOT, "web", "app.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    owners = []
    for top in tree.body:
        for node in ast.walk(top):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and needle in node.value:
                if isinstance(top, ast.Assign):
                    owners.append(top.targets[0].id)
                else:
                    owners.append(getattr(top, "name", type(top).__name__))
    return owners


class TestTheBlendIsWrittenOnce:

    def test_no_query_spells_the_formula_out_for_itself(self):
        #the concept column is only ever read through the blend, so any other
        #string naming it is a second copy of the formula
        assert owners_of("concept_uniqueness") == ["UNIQUE_BLEND_SQL"]


class TestAnUntaggedCardSitsOutTheConceptAxis:
    #schema.sql stores concept_uniqueness NULL for a card with no tags: unknown,
    #not unique. read as zero it halved the card's score: Ogre Enforcer ranked
    #17,164th where its rules text alone puts it 4,822nd

    def test_its_score_is_its_rules_text_alone(self):
        #Ogre Enforcer: rules text 0.271, no tags
        assert app.unique_blend(0.271, None) == pytest.approx(0.271)

    def test_a_concept_score_of_zero_is_not_a_missing_one(self):
        #a card whose exact tags another card shares has a real zero on that
        #axis, and it pulls the blend down
        assert app.unique_blend(0.271, 0.0) < 0.271


@needs_db
class TestPythonAndSqlAgree:

    #real cards: The Watcher in the Water, Deathcult Rogue, Soul Warden's float4
    #noise, and Ogre Enforcer, which carries no tags
    CARDS = [(0.3076, 0.7235), (0.1668, 0.8303), (-1.1920929e-07, 1.1920929e-07), (0.271, None)]

    def test_a_card_scores_the_same_either_way(self):
        import db
        with db.pool.connection() as conn:
            for u, cu in self.CARDS:
                row = conn.execute("SELECT " + app.UNIQUE_BLEND_SQL + " AS b FROM (SELECT %s::real AS uniqueness, "
                                   "%s::real AS concept_uniqueness) c", (u, cu)).fetchone()
                assert row["b"] == pytest.approx(app.unique_blend(u, cu), abs=1e-6), (u, cu)


def strength(words):
    #orders the phrases the way a reader does: the superlative, then a named
    #rank, then a percentile, then the tie at the bottom
    if "the most unique" in words:
        return (3, 0)
    named = re.search(r"#(\d+)", words)
    if named:
        return (2, -int(named.group(1)))
    pct = re.search(r"([\d.]+)%", words)
    if pct:
        return (1, float(pct.group(1)))
    return (0, 0)


class TestTheStandingInWords:
    #31,295 is the live count of commander-legal cards with a score

    def test_the_top_card_gets_the_superlative(self):
        assert "the most unique" in app.unique_words(1, 31294, 31295)

    def test_the_second_card_does_not(self):
        words = app.unique_words(2, 31293, 31295)
        assert "the most unique" not in words
        assert "#2" in words

    def test_named_ranks_stop_at_ten(self):
        assert "#10" in app.unique_words(10, 31285, 31295)
        assert "%" in app.unique_words(11, 31284, 31295)

    def test_the_tie_at_the_bottom_gets_no_number(self):
        #4,392 legal cards tie there, and "more original than 0%" or a rank
        #shared by thousands says nothing
        words = app.unique_words(26904, 0, 31295)
        assert "%" not in words and "#" not in words

    def test_a_percentile_never_claims_more_than_the_count(self):
        #11th of 31,295 beats 99.965% of cards, which rounds to 100.0: a claim
        #only a card with nothing above it could make
        total = 31295
        for rank in range(11, total):
            below = total - rank
            printed = float(re.search(r"([\d.]+)%", app.unique_words(rank, below, total)).group(1))
            assert printed <= 100 * below / total, rank

    def test_a_better_standing_never_reads_worse(self):
        #1,000 cards, the bottom 140 tied the way the float noise ties them
        total, tied = 1000, 140
        standings = [(rank, total - rank) for rank in range(1, total - tied + 1)]
        standings += [(total - tied + 1, 0)] * tied
        read = [strength(app.unique_words(rank, below, total)) for rank, below in standings]
        assert all(a >= b for a, b in zip(read, read[1:]))


@needs_db
class TestTheStandingIsCountedFromTheTable:
    #a temp table named cards shadows the real one inside this transaction, so
    #the population is exactly these rows. real values, measured
    CARDS = [
        ("Oddric, Lunar Marquis", 0.3474, 0.7277, False),
        ("The Watcher in the Water", 0.3076, 0.7235, True),
        ("Ogre Enforcer", 0.271, None, True),
        ("Disorient", 1.9073486e-05, -1.1920929e-07, True),
        ("Groundbreaker", 0.0, 0.0, True),
        ("Soul Warden", -1.1920929e-07, 1.1920929e-07, True),
        ("Kaijin of the Vanishing Touch", 1.1920929e-07, -1.1920929e-07, True),
        ("the widest noise measured", 5.9604645e-07, 0.0, True),
    ]
    NOISE = ["Groundbreaker", "Soul Warden", "Kaijin of the Vanishing Touch", "the widest noise measured"]

    @pytest.fixture
    def conn(self):
        import db
        with db.pool.connection() as c:
            c.execute("CREATE TEMP TABLE cards (name text, uniqueness real, concept_uniqueness real, "
                      "legal_commander boolean) ON COMMIT DROP")
            for row in self.CARDS:
                c.execute("INSERT INTO cards VALUES (%s, %s, %s, %s)", row)
            yield c
            c.rollback()

    def standing(self, conn, name, illegal=False):
        #the blend as the dealer reads it back, a float8 off the wire
        row = conn.execute("SELECT " + app.UNIQUE_BLEND_SQL + " AS b, legal_commander FROM cards c WHERE name = %s",
                           (name,)).fetchone()
        return app.unique_standing(conn, row["b"], illegal, row["legal_commander"])

    def test_the_top_legal_card_is_first_among_legal_cards(self, conn):
        assert self.standing(conn, "The Watcher in the Water") == (1, 6, 7)

    def test_including_illegal_cards_counts_the_one_above_it(self, conn):
        assert self.standing(conn, "The Watcher in the Water", illegal=True) == (2, 6, 8)

    def test_an_illegal_card_is_counted_among_everything(self, conn):
        #left in a trail after the illegal box is unticked. counted against legal
        #cards alone it read "the most unique card in Magic" beside Watcher
        assert self.standing(conn, "Oddric, Lunar Marquis") == (1, 7, 8)

    def test_a_card_is_never_counted_against_itself(self, conn):
        #Watcher above, Disorient and the four noise cards below
        assert self.standing(conn, "Ogre Enforcer") == (2, 5, 7)

    def test_float_noise_around_zero_is_one_tie(self, conn):
        for name in self.NOISE:
            assert self.standing(conn, name) == (4, 0, 7), name

    def test_the_first_real_near_copy_clears_the_tie(self, conn):
        assert self.standing(conn, "Disorient") == (3, 4, 7)
