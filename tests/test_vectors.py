#lines.embedding is a halfvec, so every vector the ingest reads back has each
#component rounded to ieee half precision. the numpy passes dot rows together
#and read the result as a cosine, which only holds for rows of length 1

import ast
import os
import re

import numpy as np

import app
from common.vectors import unit_rows
from conftest import ROOT, TEST_DB, needs_db


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


class TestAModelSwapRebuildsTheColumnSchemaSqlDeclares:

    def test_the_column_it_declares_is_the_one_a_swap_alters_to(self):
        #a model swap ALTERs lines.embedding to EMBED_TYPE underneath the hnsw
        #index schema.sql built, and pgvector refuses an operator class for another
        #type, so the swap would die after the full reembed. read rather than
        #imported: ingest/update.py imports psycopg, which the pure suite must not
        embed_type = next(ast.literal_eval(node.value) for node in ast.parse(read("ingest", "update.py")).body
                          if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EMBED_TYPE")
        sql = read("common", "schema.sql")
        table = re.search(r"CREATE TABLE IF NOT EXISTS lines \((.*?)\n\);", sql, re.S).group(1)
        declared = re.search(r"^\s*embedding\s+(\S+)\s+NOT NULL", table, re.M).group(1)
        assert embed_type == declared

    def test_the_index_takes_its_operator_class_from_the_column(self):
        #the pair above cannot be checked against a written out operator class
        #any more, because a name in the file throws against a database on the
        #other type: see the statement's own comment. what holds the two together
        #now is that the statement reads pg_attribute, which
        #tests/test_rebuild_lines.py runs against both shapes
        index = re.search(r"lines_embedding_hnsw ON lines USING hnsw \(embedding (\S+)\)", read("common", "schema.sql"))
        assert index.group(1) == "%s_cosine_ops"


class TestAHalfPrecisionRowIsUnitLengthAgain:

    def test_a_line_printed_on_two_cards_still_ties_at_zero(self):
        #uniqueness is 1 minus a line's best dot product against other cards, and
        #/unique ties every card under app.UNIQUE_NOISE as "other cards already do
        #everything it does". two cards printing the same text hold the same
        #vector, so that dot product is the row against itself. unrenormalised,
        #the rounding put the live vectors up to 1.2e-4 off, and 2,708 of the
        #4,392 tied cards fell out of the tie
        rng = np.random.default_rng(7)
        v = rng.standard_normal((500, 768)).astype(np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        rows = unit_rows(v.astype(np.float16))
        assert (1 - (rows * rows).sum(axis=1)).max() < app.UNIQUE_NOISE


@needs_db
class TestTheUniquenessPassReadsTheColumnAsStored:

    def test_two_cards_printing_the_same_line_tie_at_zero(self):
        #the unit test above proves unit_rows. this proves recompute_uniqueness
        #reads through it, off a column built the way schema.sql builds it. temp
        #tables shadow cards and lines for this one connection, so the fixture rows
        #other tests read are never scored
        import psycopg
        from pgvector.psycopg import register_vector
        from ingest import update

        rng = np.random.default_rng(3)
        shared, other = rng.standard_normal((2, 768)).astype(np.float32)
        shared /= np.linalg.norm(shared)
        other /= np.linalg.norm(other)
        #otherwise the test passes whether or not anything renormalises
        assert abs(1 - (shared.astype(np.float16).astype(np.float32) ** 2).sum()) > app.UNIQUE_NOISE

        twin_a = "00000000-0000-4000-8000-00000000aa01"
        twin_b = "00000000-0000-4000-8000-00000000aa02"
        loner = "00000000-0000-4000-8000-00000000aa03"
        with psycopg.connect(TEST_DB) as conn:
            register_vector(conn)
            conn.execute("CREATE TEMP TABLE cards (oracle_id uuid PRIMARY KEY, uniqueness real, unique_line text)")
            conn.execute("CREATE TEMP TABLE lines (LIKE public.lines INCLUDING DEFAULTS)")
            for oid, text, vec in ((twin_a, "Flying", shared), (twin_b, "Flying", shared), (loner, "Banding", other)):
                conn.execute("INSERT INTO cards (oracle_id) VALUES (%s)", (oid,))
                conn.execute("INSERT INTO lines (oracle_id, line_text, embedding) VALUES (%s, %s, %s)", (oid, text, vec))
            update.recompute_uniqueness(conn)
            scores = dict(conn.execute("SELECT oracle_id::text, uniqueness FROM cards").fetchall())
        assert scores[twin_a] < app.UNIQUE_NOISE
        assert scores[twin_b] < app.UNIQUE_NOISE
