#what ingest/update.py writes into meta at the two ends of a run. the site
#rereads the calibration maps every five minutes, so a map published before its
#vectors is live against the wrong ones for the whole reseed.
#
#these functions commit, so each test gets a schema of its own holding only a
#meta table, dropped afterwards whatever happened

import json

import pytest

from conftest import TEST_DB, needs_db

OLD_MAP = [[0.0, 0], [1.0, 100]]


@pytest.fixture
def conn():
    import psycopg

    c = psycopg.connect(TEST_DB)
    c.execute("CREATE SCHEMA meta_check")
    c.execute("SET search_path TO meta_check")
    c.execute("CREATE TABLE meta (key text PRIMARY KEY, value text)")
    c.commit()
    yield c
    c.rollback()
    c.execute("DROP SCHEMA IF EXISTS meta_check CASCADE")
    c.commit()
    c.close()


def meta(conn):
    return dict(conn.execute("SELECT key, value FROM meta").fetchall())


def embedded_by(conn, model):
    conn.execute("INSERT INTO meta VALUES ('embed_model', %s)", (model,))
    for key in ("mech_calibration", "concept_calibration"):
        conn.execute("INSERT INTO meta VALUES (%s, %s)", (key, json.dumps(OLD_MAP)))
    conn.commit()


@needs_db
class TestAModelSwapPublishesItsMapsWithItsVectors:

    def test_the_old_maps_stay_live_until_the_run_is_recorded(self, conn):
        #the recall check can still refuse the swap after the reseed, and then the
        #old vectors stay live, so the new maps must not be out yet
        from ingest import update
        embedded_by(conn, "test/old-model")
        assert update.swapping_models(conn)
        assert json.loads(meta(conn)["mech_calibration"]) == OLD_MAP
        assert json.loads(meta(conn)["concept_calibration"]) == OLD_MAP

        update.record_run(conn, "2026-09-24T09:00:00", True)
        conn.commit()
        got = meta(conn)
        assert got["embed_model"] == update.EMBED_MODEL
        assert json.loads(got["mech_calibration"]) == [list(p) for p in update.MECH_CALIBRATION]
        assert json.loads(got["concept_calibration"]) == [list(p) for p in update.CONCEPT_CALIBRATION]

    def test_the_same_model_refits_its_maps_at_the_start(self, conn):
        #a nothing-changed run returns at the gate, before record_run, and a map
        #refitted for the model already in the table still has to reach the site
        from ingest import update
        embedded_by(conn, update.EMBED_MODEL)
        assert not update.swapping_models(conn)
        assert json.loads(meta(conn)["mech_calibration"]) == [list(p) for p in update.MECH_CALIBRATION]

    def test_a_database_never_embedded_counts_as_a_swap(self, conn):
        from ingest import update
        assert update.swapping_models(conn)
        assert "mech_calibration" not in meta(conn)
