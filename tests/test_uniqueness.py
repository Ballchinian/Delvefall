#the uniqueness number /unique ranks and deals by.
#
#the blend is one sum spelled twice: as sql for every query that ranks the table,
#and as python for scoring a card that is not in the table. the first two classes
#hold those spellings to one definition

import ast
import os

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
