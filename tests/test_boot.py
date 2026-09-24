#web's boot block is the only place the site takes a lock on a table, and on
#2026-09-22 that was enough to take it down: an ingest step hung with its
#transaction open, both gunicorn workers queued behind it at import time and
#every page 503d. so what is asserted here is that a locked table costs one
#statement and nothing else.
#
#a real postgres, because the whole behaviour is lock_timeout's: a stub cannot
#refuse a lock

import pytest

from conftest import TEST_DB, needs_db

LOCKED = "boot_probe_locked"
FREE = "boot_probe_free"


@pytest.fixture
def two_tables():
    #one table a blocker holds and one it does not, so a skipped statement and a
    #granted one can be told apart in the same run
    import psycopg

    conn = psycopg.connect(TEST_DB)
    for table in (LOCKED, FREE):
        conn.execute("DROP TABLE IF EXISTS " + table)
        conn.execute("CREATE TABLE " + table + " (a int)")
    conn.commit()
    try:
        yield conn
    finally:
        for table in (LOCKED, FREE):
            conn.execute("DROP TABLE IF EXISTS " + table)
        conn.commit()
        conn.close()


def has_column(conn, table, column):
    return conn.execute("""
        SELECT 1 FROM pg_attribute
        WHERE attrelid = to_regclass(%s) AND attname = %s AND NOT attisdropped
    """, (table, column)).fetchone() is not None


@needs_db
class TestABootStatementNeverWaitsForALockedTable:

    def test_the_locked_statement_is_skipped_and_the_next_one_still_lands(self, two_tables):
        import psycopg

        from app import boot_ddl

        blocker = psycopg.connect(TEST_DB)
        victim = psycopg.connect(TEST_DB)
        try:
            blocker.execute("LOCK TABLE " + LOCKED + " IN ACCESS EXCLUSIVE MODE")
            #without boot_ddl's lock timeout the ALTER below waits for a blocker
            #that is never let go, which would hang the suite rather than fail it
            victim.execute("SET statement_timeout = '15s'")
            boot_ddl(victim, "ALTER TABLE " + LOCKED + " ADD COLUMN IF NOT EXISTS b int")
            boot_ddl(victim, "ALTER TABLE " + FREE + " ADD COLUMN IF NOT EXISTS b int")
            victim.commit()

            assert not has_column(two_tables, LOCKED, "b")
            #the one that matters: an aborted statement leaves the connection in a
            #failed transaction, and the rest of the block goes down with it
            assert has_column(two_tables, FREE, "b")
        finally:
            blocker.close()
            victim.close()

    def test_the_next_boot_applies_what_this_one_skipped(self, two_tables):
        import psycopg

        from app import boot_ddl

        blocker = psycopg.connect(TEST_DB)
        victim = psycopg.connect(TEST_DB)
        try:
            blocker.execute("LOCK TABLE " + LOCKED + " IN ACCESS EXCLUSIVE MODE")
            boot_ddl(victim, "ALTER TABLE " + LOCKED + " ADD COLUMN IF NOT EXISTS b int")
            blocker.rollback()
            boot_ddl(victim, "ALTER TABLE " + LOCKED + " ADD COLUMN IF NOT EXISTS b int")
            victim.commit()
            assert has_column(two_tables, LOCKED, "b")
        finally:
            blocker.close()
            victim.close()


@needs_db
class TestTheTimeoutDiesWithTheTransaction:

    def test_the_connection_goes_back_into_the_pool_without_one(self, two_tables):
        #a plain SET would ride back in, and a search that inherited a one
        #second lock timeout is a 500 on a page that was only busy. SET LOCAL
        #lasts to the end of the TRANSACTION, not the statement: inside an open
        #one psycopg gives boot_ddl a savepoint, so the commit is what ends it,
        #and the pool commits when the boot block lets the connection go
        import psycopg

        from app import boot_ddl

        victim = psycopg.connect(TEST_DB)
        try:
            before = victim.execute("SHOW lock_timeout").fetchone()[0]
            boot_ddl(victim, "ALTER TABLE " + FREE + " ADD COLUMN IF NOT EXISTS b int")
            victim.commit()
            assert victim.execute("SHOW lock_timeout").fetchone()[0] == before
        finally:
            victim.close()


@needs_db
class TestAStatementThatFailsForAnyOtherReason:

    def test_it_is_not_swallowed(self):
        #the timeout is for a lock and nothing else. a boot statement with a typo
        #in it has to reach the logs as a crash, not a quiet skip
        import psycopg

        from app import boot_ddl

        victim = psycopg.connect(TEST_DB)
        try:
            with pytest.raises(psycopg.errors.UndefinedTable):
                boot_ddl(victim, "ALTER TABLE boot_probe_missing ADD COLUMN b int")
        finally:
            victim.close()


@needs_db
class TestAColumnAlreadyThereTakesNoLock:

    def test_it_is_asked_of_the_catalog_and_never_altered(self, two_tables, monkeypatch):
        #ADD COLUMN IF NOT EXISTS takes ACCESS EXCLUSIVE whether or not it adds
        #anything, so every boot queued behind any open read of the table
        import psycopg

        import app

        altered = []
        monkeypatch.setattr(app, "boot_ddl", lambda conn, sql: altered.append(sql))
        victim = psycopg.connect(TEST_DB)
        try:
            app.boot_column(victim, FREE, "a", "ALTER TABLE " + FREE + " ADD COLUMN IF NOT EXISTS a int")
            assert altered == []
            app.boot_column(victim, FREE, "b", "ALTER TABLE " + FREE + " ADD COLUMN IF NOT EXISTS b int")
            assert len(altered) == 1
        finally:
            victim.close()


class TestTheBootBlockOpensNoTransactionOfItsOwn:

    def test_every_statement_comes_before_the_first_read(self):
        #a read opens a transaction, and every boot_ddl after it is then a
        #savepoint inside it, holding its lock to the end of the block
        import ast
        import os

        from conftest import ROOT

        with open(os.path.join(ROOT, "web", "app.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        block = next(node for node in tree.body if isinstance(node, ast.With)
                     and ast.unparse(node.items[0].context_expr) == "pool.connection()")
        kinds = []
        for stmt in block.body:
            names = {ast.unparse(n.func) for n in ast.walk(stmt) if isinstance(n, ast.Call)}
            if names & {"boot_ddl", "boot_column"}:
                kinds.append("ddl")
            elif "_conn.execute" in names:
                kinds.append("read")
        assert "ddl" in kinds and "read" in kinds
        assert "ddl" not in kinds[kinds.index("read"):]
