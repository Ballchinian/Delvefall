#the property that lets the check workflow run this suite at all: conftest's stub
#means these tests need neither a database nor the drivers that talk to one, so
#the deploy gate installs three small packages instead of postgres.
#
#easy to lose by accident, one test reaching for a real connection or one import
#pulled in for convenience, and the workflow starts failing on a machine nobody
#can reproduce. so it is asserted out loud

import sys

import pytest

import app
import mirror
from conftest import TEST_DB

#the DEFAULT shape only. with TEST_DATABASE_URL set the same seam is deliberately
#a real pool and a real driver, so asserting their absence would assert the
#opposite of what was asked for
no_db_only = pytest.mark.skipif(bool(TEST_DB),
                                reason="TEST_DATABASE_URL makes the seam real on purpose")


@no_db_only
def test_the_database_driver_was_never_imported():
    #if this fails on a plain run, something imported the real web/db.py and the
    #pure suite now needs psycopg, pgvector and a reachable postgres
    assert "psycopg" not in sys.modules
    assert "pgvector" not in sys.modules


@no_db_only
def test_the_stub_is_what_the_app_is_holding():
    assert sys.modules["db"].__name__ == "db"
    assert type(app.pool).__name__ == "_NullPool"
    assert app.pool is mirror.pool


@no_db_only
def test_the_stub_answers_with_nothing_rather_than_raising():
    #the two import-time callers depend on this exact shape: the DDL block
    #needs a working context manager, load_calibration needs an empty fetchone
    with app.pool.connection() as conn:
        assert conn.execute("SELECT 1").fetchone() is None
        assert conn.execute("SELECT 1").fetchall() == []


def test_the_app_and_the_mirror_share_one_pool_either_way():
    #true in both shapes, and the thing that makes the switch a switch
    assert app.pool is mirror.pool
