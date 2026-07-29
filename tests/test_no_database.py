#the property that lets the check workflow run this suite at all.
#
#the whole point of conftest's stub is that these tests need neither a database
#nor the drivers that talk to one, so the deploy gate can install three small
#packages and get behaviour checking rather than needing postgres on the runner.
#that is easy to lose by accident: one test that reaches for a real connection,
#or one import pulled in for convenience, and the workflow starts failing on a
#machine nobody can reproduce. these assert it out loud instead

import sys

import app
import mirror


def test_the_database_driver_was_never_imported():
    #if this fails, something imported the real web/db.py and the workflow now
    #needs psycopg, pgvector and a reachable postgres to go green
    assert "psycopg" not in sys.modules
    assert "pgvector" not in sys.modules


def test_the_stub_is_what_the_app_is_holding():
    assert sys.modules["db"].__name__ == "db"
    assert type(app.pool).__name__ == "_Pool"
    assert app.pool is mirror.pool


def test_the_stub_answers_with_nothing_rather_than_raising():
    #the two import-time callers depend on this exact shape: the DDL block
    #needs a working context manager, load_calibration needs an empty fetchone
    with app.pool.connection() as conn:
        assert conn.execute("SELECT 1").fetchone() is None
        assert conn.execute("SELECT 1").fetchall() == []
