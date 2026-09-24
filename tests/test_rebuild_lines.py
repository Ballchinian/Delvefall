#ingest/rebuild_lines.py swaps a copy of lines in under the live name, so what
#has to survive is everything schema.sql hangs on the table: the column type, the
#indexes and keys, line_tags' cascade and the id sequence.
#
#each test builds lines and line_tags from schema.sql's own statements in a
#schema of its own, turns the vectors back to the 4 byte type production held
#before the rebuild, and rolls all of it back after

import os
import re

import numpy as np
import pytest

from conftest import ROOT, TEST_DB, needs_db


def statements_about_lines():
    with open(os.path.join(ROOT, "common", "schema.sql"), encoding="utf-8") as f:
        sql = "\n".join(line for line in f.read().splitlines() if not line.lstrip().startswith("--"))
    #a $$ body carries its own semicolons, so the split steps over one whole
    #rather than cutting inside it
    statements = re.findall(r"(?:\$\$.*?\$\$|[^;])+", sql, re.S)
    wanted = re.compile(r"(CREATE TABLE IF NOT EXISTS (lines|line_tags|line_stats) |ALTER TABLE lines |"
                        r"CREATE INDEX IF NOT EXISTS \w+ ON (lines|line_tags) |DO \$\$)")
    return [s.strip() for s in statements if wanted.match(s.strip())]


def shape(conn):
    indexes = sorted(r[0] for r in conn.execute(
        "SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indrelid = 'lines'::regclass"))
    keys = sorted(conn.execute("""
        SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid = 'lines'::regclass OR confrelid = 'lines'::regclass""").fetchall())
    return indexes, keys


def embedding_type(conn):
    return conn.execute("""SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                           WHERE attrelid = 'lines'::regclass AND attname = 'embedding'""").fetchone()[0]


@pytest.fixture
def conn():
    import psycopg
    from pgvector.psycopg import register_vector

    c = psycopg.connect(TEST_DB)
    register_vector(c)
    c.execute("CREATE SCHEMA rebuild_check")
    #session wide, not SET LOCAL: anything that commits mid test would end the
    #transaction and drop a local setting, and the rest of the test would build
    #its tables in public, on top of the fixtures every other test reads
    c.execute("SET search_path TO rebuild_check, public")
    c.execute("CREATE TABLE cards (oracle_id uuid PRIMARY KEY)")
    for statement in statements_about_lines():
        c.execute(statement)
    c.fresh = shape(c)
    c.fresh_type = embedding_type(c)

    c.execute("DROP INDEX lines_embedding_hnsw")
    c.execute("ALTER TABLE lines ALTER COLUMN embedding TYPE vector(768)")
    c.execute("CREATE INDEX lines_embedding_hnsw ON lines USING hnsw (embedding vector_cosine_ops) "
              "WITH (m = 32, ef_construction = 200) WHERE (NOT whole)")
    rng = np.random.default_rng(11)
    for k in range(6):
        oid = "00000000-0000-4000-8000-0000000bb%03d" % k
        c.execute("INSERT INTO cards VALUES (%s)", (oid,))
        for j in range(3):
            v = rng.standard_normal(768).astype(np.float32)
            line_id = c.execute("""INSERT INTO lines (oracle_id, line_text, embedding, nn_sim, whole)
                                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                                (oid, "line %d of card %d" % (j, k), v / np.linalg.norm(v), 0.1 * j, j == 2)).fetchone()[0]
            c.execute("INSERT INTO line_tags (line_id, tag, lift) VALUES (%s, 'fixture', 2.0)", (line_id,))
    yield c
    c.rollback()
    c.execute("DROP SCHEMA IF EXISTS rebuild_check CASCADE")
    c.commit()
    c.close()


def build(conn):
    from ingest import rebuild_lines
    rebuild_lines.fill(conn)
    rebuild_lines.constrain(conn)
    rebuild_lines.index(conn)


def rebuild(conn):
    from ingest import rebuild_lines
    build(conn)
    rebuild_lines.record(conn, rebuild_lines.check(conn))
    rebuild_lines.exchange(conn, "lines_new", "lines_old")
    rebuild_lines.validate(conn)


def rows(conn):
    return {r[0]: r[1:] for r in conn.execute(
        "SELECT id, oracle_id, line_text, nn_sim, face, whole, embedding FROM lines ORDER BY id")}


@needs_db
class TestTheRebuiltTableIsTheOneSchemaSqlBuilds:

    def test_every_row_arrives_at_the_schema_type_with_its_vector(self, conn):
        before = rows(conn)
        rebuild(conn)
        after = rows(conn)
        assert embedding_type(conn) == conn.fresh_type
        assert sorted(after) == sorted(before)
        for line_id, row in before.items():
            assert after[line_id][:-1] == row[:-1]
            #ieee half rounds each component, and over the live vectors the worst
            #cosine to the original measured 0.99999982
            assert float(np.dot(row[-1].to_numpy(), after[line_id][-1].to_numpy().astype(np.float32))) > 0.9999

    def test_it_carries_the_indexes_and_keys_schema_sql_hangs_on_lines(self, conn):
        rebuild(conn)
        assert shape(conn) == conn.fresh


@needs_db
class TestSchemaSqlAppliesEitherSideOfTheRebuild:

    def test_it_leaves_a_vector_column_and_its_index_alone(self, conn):
        #the fixture leaves lines in the shape production holds before the
        #rebuild, and schema.sql runs at the top of every ingest, so it has to
        #keep applying to that shape. a halfvec operator class written out in the
        #file throws DatatypeMismatch against this column whether or not the
        #index it names is already there, correct, and in use
        for statement in statements_about_lines():
            conn.execute(statement)
        assert embedding_type(conn) == "vector(768)"
        assert "vector_cosine_ops" in conn.execute(
            "SELECT pg_get_indexdef('lines_embedding_hnsw'::regclass)").fetchone()[0]

    def test_it_leaves_the_rebuilt_halfvec_column_alone(self, conn):
        rebuild(conn)
        for statement in statements_about_lines():
            conn.execute(statement)
        assert shape(conn) == conn.fresh


@needs_db
class TestTheOldTableCanGo:

    def test_new_lines_still_get_ids_once_it_is_dropped(self, conn):
        #bigserial's sequence belongs to the column that created it, and dropping
        #that table drops the sequence the live table's ids come from
        rebuild(conn)
        highest = conn.execute("SELECT max(id) FROM lines").fetchone()[0]
        conn.execute("DROP TABLE lines_old")
        new_id = conn.execute("""INSERT INTO lines (oracle_id, line_text, embedding)
                                 VALUES ('00000000-0000-4000-8000-0000000bb000', 'Flying', %s) RETURNING id""",
                              (np.ones(768, dtype=np.float32),)).fetchone()[0]
        assert new_id > highest


@needs_db
class TestTheSwapOnlyHappensOverWhatWasCopied:

    def test_a_write_after_the_copy_refuses_the_swap(self, conn):
        #the uniqueness pass rewriting nn_sim is the write most likely to land
        #between a copy and a swap
        from ingest import rebuild_lines
        build(conn)
        rebuild_lines.record(conn, rebuild_lines.check(conn))
        conn.execute("UPDATE lines SET nn_sim = 0.25 WHERE id = (SELECT min(id) FROM lines)")
        with pytest.raises(rebuild_lines.Refused):
            rebuild_lines.exchange(conn, "lines_new", "lines_old")
        assert embedding_type(conn) == "vector(768)"

    def test_a_rollback_puts_the_old_table_back_and_the_new_one_can_go(self, conn):
        from ingest import rebuild_lines
        rebuild(conn)
        highest = conn.execute("SELECT max(id) FROM lines").fetchone()[0]
        rebuild_lines.exchange(conn, "lines_old", "lines_new")
        rebuild_lines.validate(conn)
        conn.execute("DROP TABLE lines_new")
        assert embedding_type(conn) == "vector(768)"
        new_id = conn.execute("""INSERT INTO lines (oracle_id, line_text, embedding)
                                 VALUES ('00000000-0000-4000-8000-0000000bb000', 'Flying', %s) RETURNING id""",
                              (np.ones(768, dtype=np.float32),)).fetchone()[0]
        assert new_id > highest


@needs_db
class TestTheIngestAndTheToolTakeTurns:

    def test_the_tool_refuses_while_the_ingest_holds_the_lock(self, conn):
        #the clock cannot be the guard: update.yml asks for 9 utc and github has
        #started it anywhere from 12:43 to 15:46
        import psycopg

        from common import locks
        from ingest import rebuild_lines

        ingest = psycopg.connect(TEST_DB)
        try:
            locks.hold(ingest)
            with pytest.raises(rebuild_lines.Refused):
                rebuild_lines.fill(conn)
        finally:
            ingest.close()
        assert conn.execute("SELECT to_regclass('lines_new')").fetchone()[0] is None
        #and once it lets go, the same call goes through
        rebuild_lines.fill(conn)
        assert conn.execute("SELECT count(*) FROM lines_new").fetchone()[0] == 18

    @pytest.mark.parametrize("action,tables", [
        ("--drop-old", ["lines_old"]), ("--discard", ["lines_new"]), ("--swap", ["lines_new"]),
        ("--rollback", ["lines_old"]), ("--check", ["lines_new"]), (None, []),
    ])
    def test_every_action_refuses_while_the_ingest_holds_the_lock(self, conn, monkeypatch, capsys,
                                                                  action, tables):
        #each action is its own branch of main and the lock is taken inside the calls
        #that write, so a branch that never makes one writes unguarded. --drop-old
        #and --discard did. each gets only the tables it needs, so no other refusal
        #can stand in for this one
        import sys
        import urllib.parse

        import psycopg

        from common import locks
        from ingest import rebuild_lines

        def tables_now():
            return sorted(r[0] for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'rebuild_check'"))

        for t in tables:
            conn.execute("CREATE TABLE " + t + " (LIKE lines)")
        conn.commit()
        before = tables_now()
        monkeypatch.setenv("DATABASE_URL", TEST_DB + ("&" if "?" in TEST_DB else "?") + "options=" +
                           urllib.parse.quote("-c search_path=rebuild_check,public"))
        monkeypatch.setattr(sys, "argv", ["rebuild_lines"] + ([action] if action else []))
        ingest = psycopg.connect(TEST_DB)
        try:
            locks.hold(ingest)
            with pytest.raises(SystemExit):
                rebuild_lines.main()
        finally:
            ingest.close()
        assert "an ingest run holds the lock" in capsys.readouterr().out
        assert tables_now() == before

    def test_a_drop_waits_on_cards_no_longer_than_the_lock_timeout(self, conn, monkeypatch):
        #lines_new's foreign key into cards means its drop takes ACCESS EXCLUSIVE on
        #cards, and every card page queues behind a drop that is waiting
        import psycopg

        from ingest import rebuild_lines
        monkeypatch.setattr(rebuild_lines, "LOCK_TIMEOUT", "200ms")
        build(conn)
        conn.commit()
        #a drop with no lock timeout fails here instead of hanging the suite
        conn.execute("SET statement_timeout = '10s'")
        page = psycopg.connect(TEST_DB)
        try:
            page.execute("SET search_path TO rebuild_check, public")
            page.execute("SELECT count(*) FROM cards")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                rebuild_lines.drop(conn, "lines_new")
            conn.rollback()
        finally:
            page.close()
        assert conn.execute("SELECT to_regclass('lines_new')").fetchone()[0] is not None
        #and with the card page gone, the same drop goes through
        rebuild_lines.drop(conn, "lines_new")
        assert conn.execute("SELECT to_regclass('lines_new')").fetchone()[0] is None


class TestTheRecallVerdict:

    def test_a_walk_that_never_reaches_the_twins_is_blind(self):
        #the live m=32 graph on "Flying, trample": 88 cards print it, so the exact
        #top 20 are its twins at 1.0, and the index came back with 0.6968 at best
        from ingest.rebuild_lines import verdict
        found = [0.6968 - 0.002 * k for k in range(20)]
        assert verdict(found, [1.0] * 20) == (0, True)

    def test_a_line_that_finds_its_best_but_loses_middle_ranks_is_not_blind(self):
        #"Web-slinging {U}" on both m=64 lab builds: best match found, 12 of 20 in
        #place. the swap is refused on blind lines only, these are reported
        from ingest.rebuild_lines import verdict
        exact = [0.95 - 0.01 * k for k in range(21)]
        found = exact[:12] + exact[13:]
        assert verdict(found, exact[:20]) == (12, False)

    def test_a_walk_that_returns_nothing_is_blind(self):
        #guards rather than describes: no build has returned an empty walk
        from ingest.rebuild_lines import verdict
        assert verdict([], [0.9] * 20) == (0, True)


@needs_db
class TestTheSwapNeedsAPassingRecallCheck:

    def test_a_lines_new_never_checked_is_refused(self, conn):
        from ingest import rebuild_lines
        build(conn)
        with pytest.raises(rebuild_lines.Refused):
            rebuild_lines.exchange(conn, "lines_new", "lines_old")
        assert embedding_type(conn) == "vector(768)"

    def test_a_failed_check_is_refused(self, conn):
        from ingest import rebuild_lines
        build(conn)
        rebuild_lines.record(conn, {"passed": False, "texts": 1096, "blind": 13, "below_20": 95})
        with pytest.raises(rebuild_lines.Refused):
            rebuild_lines.exchange(conn, "lines_new", "lines_old")
        assert embedding_type(conn) == "vector(768)"

    def test_a_search_that_does_not_walk_the_graph_fails_the_check(self, conn):
        #the check this replaced let the planner choose, and it seq scanned one
        #table while walking the other: truth scored against itself reads perfect
        from ingest import rebuild_lines
        build(conn)
        conn.execute("DROP INDEX lines_new_embedding_hnsw")
        assert not rebuild_lines.check(conn)["passed"]

    def test_the_exact_search_reads_every_row_whatever_the_settings(self, conn):
        #the exact searches once shared the index search's text and leaned on
        #enable_* to stay off the graph. a prepared plan outlives those, and the
        #check passed a lab build with 55 texts blind
        from ingest import rebuild_lines
        build(conn)
        vec = conn.execute("SELECT embedding FROM lines_new WHERE NOT whole LIMIT 1").fetchone()[0]
        conn.execute("SET enable_seqscan = off; SET enable_sort = off")
        plan = " ".join(r[0] for r in conn.execute(
            "EXPLAIN " + rebuild_lines.EXACT, (vec, "00000000-0000-4000-8000-0000000bb000", vec)))
        assert "lines_new_embedding_hnsw" not in plan

    def test_a_rolled_back_table_is_checked_again_before_it_returns(self, conn):
        from ingest import rebuild_lines
        rebuild(conn)
        rebuild_lines.exchange(conn, "lines_old", "lines_new")
        rebuild_lines.validate(conn)
        with pytest.raises(rebuild_lines.Refused):
            rebuild_lines.exchange(conn, "lines_new", "lines_old")


def new_model_rows():
    #what a model swap's encode hands update.py: every card again under new
    #vectors, each printing Flying once, so line_stats has a count to get right
    rng = np.random.default_rng(12)
    unit = lambda v: v / np.linalg.norm(v)
    flying = unit(rng.standard_normal(768).astype(np.float32))
    rows = []
    for k in range(6):
        oid = "00000000-0000-4000-8000-0000000bb%03d" % k
        rows.append((oid, "Flying", flying, 0, False))
        rows.append((oid, "new line of card %d" % k, unit(rng.standard_normal(768).astype(np.float32)), 0, False))
        rows.append((oid, "Flying\nnew line of card %d" % k, unit(rng.standard_normal(768).astype(np.float32)), 0, True))
    return rows


def build_aside(conn):
    #update.py's model swap up to the swap: the COPY main runs, then build_aside
    from ingest import rebuild_lines, update
    rebuild_lines.create(conn)
    with conn.cursor() as cur:
        with cur.copy("COPY lines_new (oracle_id, line_text, embedding, face, whole) FROM STDIN") as copy:
            for r in new_model_rows():
                copy.write_row(r)
    return update.build_aside(conn)


def texts(conn):
    return sorted(conn.execute("SELECT oracle_id::text, line_text, whole FROM lines").fetchall())


@needs_db
class TestAModelSwapGoesThroughLinesNew:

    def test_the_site_reads_the_old_rows_until_the_swap_and_only_the_new_ones_after(self, conn):
        from ingest import rebuild_lines, update
        before = {k: v[:-1] for k, v in rows(conn).items()}
        assert build_aside(conn)
        assert {k: v[:-1] for k, v in rows(conn).items()} == before
        update.swap_in(conn)
        rebuild_lines.validate(conn)
        conn.execute("DROP TABLE lines_old")
        assert texts(conn) == sorted((r[0], r[1], r[4]) for r in new_model_rows())
        assert shape(conn) == conn.fresh
        #every tag pointed at an old line id
        assert conn.execute("SELECT count(*) FROM line_tags").fetchone()[0] == 0
        #six cards print Flying once each, and a whole card row is never counted
        stats = dict(conn.execute("SELECT line_text, count FROM line_stats").fetchall())
        assert stats["Flying"] == 6
        assert stats["new line of card 0"] == 1
        assert not [t for t in stats if "\n" in t]

    def test_a_search_holding_lines_past_the_timeout_costs_a_retry_not_the_run(self, conn, monkeypatch):
        #the other connection has to see the tables, so this one commits them.
        #the fixture drops the schema whatever happens
        import psycopg

        from ingest import update
        assert build_aside(conn)
        conn.commit()
        #stands for the run's writes before the swap: the card upsert, the encode
        conn.execute("INSERT INTO cards VALUES ('00000000-0000-4000-8000-0000000bb999')")
        search = psycopg.connect(TEST_DB)
        try:
            search.execute("SET search_path TO rebuild_check, public")
            search.execute("SELECT count(*) FROM lines")
            waits = []
            monkeypatch.setattr(update.time, "sleep", lambda s: (waits.append(s), search.rollback()))
            update.swap_in(conn)
        finally:
            search.close()
        assert len(waits) == 1
        assert conn.execute("SELECT count(*) FROM cards WHERE oracle_id = '00000000-0000-4000-8000-0000000bb999'"
                            ).fetchone()[0] == 1
        assert texts(conn) == sorted((r[0], r[1], r[4]) for r in new_model_rows())

    def test_skipping_the_fingerprint_does_not_skip_the_recall_check(self, conn):
        #a swap's lines_new differs from lines by design, so update.py turns the
        #fingerprint off. the verdict still has to hold it back
        from ingest import rebuild_lines, update
        assert build_aside(conn)
        rebuild_lines.record(conn, {"passed": False, "texts": 12, "blind": 1, "below_20": 1})
        before = texts(conn)
        with pytest.raises(rebuild_lines.Refused):
            update.swap_in(conn)
        assert texts(conn) == before
