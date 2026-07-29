#what makes the rest of this folder possible: web/app.py opens a connection at
#import time (the CREATE TABLE block that keeps a railway-only deploy in step
#with common/schema.sql), and web/db.py reads DATABASE_URL out of the
#environment the moment it is imported. neither is wrong, but between them they
#mean "import app" is a database call.
#
#so a stub module called db goes into sys.modules BEFORE anything imports the
#real one. by default it answers every query with nothing, which is exactly what
#the two import-time callers can cope with: the DDL block does not read anything
#back, and load_calibration in mirror.py already falls back to its seed maps
#when the lookup comes up empty. that fallback is a bonus rather than a
#workaround, since it means the calibration under test is the documented seed
#rather than whatever the live database happens to hold today.
#
#SET TEST_DATABASE_URL AND THE STUB BECOMES REAL. the same seam that stands in
#for a database can just as easily be one, so the tests that need rows (the
#ranking, the deck panels, the swap tool) get a real postgres while every pure
#function test carries on knowing nothing about it. the check workflow points
#that variable at a pgvector service container; a laptop with nothing set runs
#the pure tests alone and skips the rest. NEVER point it at the live database:
#the seed below writes rows.

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#web/ has to come first: its modules import each other by bare name (db,
#mirror, prefix_words) because railway deploys that folder on its own
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, ROOT)

TEST_DB = os.environ.get("TEST_DATABASE_URL", "").strip()

import pytest


class _Result:
    #enough of a cursor for the import-time callers and no more
    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _Connection:
    def execute(self, *args, **kwargs):
        return _Result()

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _NullPool:
    def connection(self):
        return _Connection()


#the two lines of schema.sql that need a contrib module rather than a plain
#server. the workflow's pgvector image carries pg_trgm like any postgres build
#does, but a pip-installed throwaway server (pgserver, the way to run these on a
#laptop with no docker) ships vector and nothing else. dropping them there costs
#the trigram index behind find_card's fuzzy name tier and nothing else, so the
#tests below still measure what they claim to
TRGM_LINES = ("CREATE EXTENSION IF NOT EXISTS pg_trgm;",
              "CREATE INDEX IF NOT EXISTS cards_name_trgm ON cards USING gin (name gin_trgm_ops);")


def _load_schema(url):
    #the schema has to land BEFORE the pool opens, because the pool's configure
    #hook calls register_vector, which needs the vector extension to exist.
    #schema.sql is idempotent by design (the ingest reruns it daily), so this is
    #free on every run after the first
    import psycopg
    with psycopg.connect(url) as conn:
        with open(os.path.join(ROOT, "common", "schema.sql"), encoding="utf-8") as f:
            sql = f.read()
        have_trgm = conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'").fetchone()
        if not have_trgm:
            for line in TRGM_LINES:
                if line not in sql:
                    raise RuntimeError("schema.sql moved " + line[:40] +
                                       ", update TRGM_LINES in tests/conftest.py")
                sql = sql.replace(line, "")
        conn.execute(sql)
        conn.commit()


def _real_pool(url):
    #mirrors web/db.py, smaller: find_similar borrows up to three connections
    #for its side-by-side line scans, so the ceiling has to clear that
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from pgvector.psycopg import register_vector

    def setup(conn):
        register_vector(conn)
        conn.commit()

    return ConnectionPool(url, min_size=1, max_size=4, kwargs={"row_factory": dict_row},
                          configure=setup, open=True)


if "db" not in sys.modules:
    stub = types.ModuleType("db")
    if TEST_DB:
        _load_schema(TEST_DB)
        stub.pool = _real_pool(TEST_DB)
    else:
        stub.pool = _NullPool()
    sys.modules["db"] = stub


needs_db = pytest.mark.skipif(not TEST_DB, reason="needs TEST_DATABASE_URL (a throwaway postgres)")


@pytest.fixture(scope="session")
def seeded():
    #a small deterministic world: enough cards, lines, tags and vectors for the
    #ranking and the deck pages to do their real work, few enough to read.
    #built once per session and torn down after, so a run leaves nothing behind
    if not TEST_DB:
        pytest.skip("needs TEST_DATABASE_URL")
    from seed import build, teardown
    import db
    with db.pool.connection() as conn:
        build(conn)
        conn.commit()
    yield
    with db.pool.connection() as conn:
        teardown(conn)
        conn.commit()
