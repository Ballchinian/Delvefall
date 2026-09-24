#common/schema.sql runs at the top of every ingest step, as ONE transaction, on
#a database the site is reading. a statement in it that queues for ACCESS
#EXCLUSIVE behind a search holds every lock the file took before it, and every
#search behind that: the first ALTER on cards waited for a read of lines, and
#card pages waited for it.
#
#on a database that already has everything, a run has to take no lock a reader
#holds. asked of a real postgres, since only postgres can say what it locks

import os

import pytest

from conftest import ROOT, TEST_DB, TRGM_LINES, needs_db

#every table schema.sql adds a column to, read by the blocker below
READ = ("cards", "lines", "card_tags", "tags", "decks", "feedback")


def schema_sql(conn):
    with open(os.path.join(ROOT, "common", "schema.sql"), encoding="utf-8") as f:
        sql = f.read()
    #the same cut conftest makes for a server without the contrib module
    if not conn.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'").fetchone():
        for line in TRGM_LINES:
            sql = sql.replace(line, "")
    return sql


@needs_db
class TestARunOverAFinishedSchemaWaitsForNoReader:

    def test_it_finishes_while_every_table_it_touches_is_being_read(self):
        import psycopg

        reader = psycopg.connect(TEST_DB)
        ingest = psycopg.connect(TEST_DB)
        try:
            for table in READ:
                reader.execute("SELECT 1 FROM " + table + " LIMIT 1")
            ingest.execute("SET lock_timeout = '2s'")
            try:
                ingest.execute(schema_sql(ingest))
            except psycopg.errors.LockNotAvailable as e:
                pytest.fail("schema.sql queued behind a reader: " + str(e).splitlines()[0])
            ingest.rollback()
        finally:
            reader.close()
            ingest.close()
