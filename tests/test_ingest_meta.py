#what ingest/update.py writes into meta at the two ends of a run. the site
#rereads the calibration maps every five minutes, so a map published before its
#vectors is live against the wrong ones for the whole reseed. and a model is its
#weights, not its name: a retrain released under the same repo keeps the name.
#
#these functions commit, so each test gets a schema of its own holding only a
#meta table, dropped afterwards whatever happened

import json

import pytest

from conftest import TEST_DB, needs_db

OLD_MAP = [[0.0, 0], [1.0, 100]]
RELEASE = "d06f255a" + "0" * 56
RETRAIN = "e17a3c90" + "0" * 56


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


def embedded_by(conn, model, sha256=None, **more):
    rows = dict({"embed_model": model, "embed_sha256": sha256}, **more)
    for key in ("mech_calibration", "concept_calibration"):
        rows[key] = json.dumps(OLD_MAP)
    for key, value in rows.items():
        if value is not None:
            conn.execute("INSERT INTO meta VALUES (%s, %s)", (key, value))
    conn.commit()


@needs_db
class TestAModelSwapPublishesItsMapsWithItsVectors:

    def test_the_old_maps_stay_live_until_the_run_is_recorded(self, conn):
        #the recall check can still refuse the swap after the reseed, and then the
        #old vectors stay live, so the new maps must not be out yet
        from ingest import update
        embedded_by(conn, "test/old-model", "f" * 64)
        assert update.swapping_models(conn, RELEASE)
        assert json.loads(meta(conn)["mech_calibration"]) == OLD_MAP
        assert json.loads(meta(conn)["concept_calibration"]) == OLD_MAP

        update.record_run(conn, "2026-09-24T09:00:00", True, RELEASE)
        conn.commit()
        got = meta(conn)
        assert got["embed_model"] == update.EMBED_MODEL
        assert got["embed_sha256"] == RELEASE
        assert json.loads(got["mech_calibration"]) == [list(p) for p in update.MECH_CALIBRATION]
        assert json.loads(got["concept_calibration"]) == [list(p) for p in update.CONCEPT_CALIBRATION]

    def test_the_same_model_refits_its_maps_at_the_start(self, conn):
        #a nothing-changed run returns at the gate, before record_run, and a map
        #refitted for the model already in the table still has to reach the site
        from ingest import update
        embedded_by(conn, update.EMBED_MODEL, RELEASE)
        assert not update.swapping_models(conn, RELEASE)
        assert json.loads(meta(conn)["mech_calibration"]) == [list(p) for p in update.MECH_CALIBRATION]

    def test_a_database_never_embedded_counts_as_a_swap(self, conn):
        from ingest import update
        assert update.swapping_models(conn, RELEASE)
        assert "mech_calibration" not in meta(conn)


@needs_db
class TestAModelIsItsWeights:

    def test_a_retrain_under_the_same_name_is_a_swap(self, conn):
        #the name was all that was compared, so a new release of the same repo
        #embedded each day's new cards with it, beside every old vector
        from ingest import update
        embedded_by(conn, update.EMBED_MODEL, RELEASE)
        assert update.swapping_models(conn, RETRAIN)
        assert json.loads(meta(conn)["mech_calibration"]) == OLD_MAP

    def test_a_database_with_no_weights_recorded_takes_the_release(self, conn):
        #production before the sha was recorded: the name and nothing else. the
        #alternative is an 86 minute reseed onto the weights it already has, and
        #the probe loaded under that name keeps its chips
        from ingest import update
        embedded_by(conn, update.EMBED_MODEL, tag_probe_model=update.EMBED_MODEL)
        assert not update.swapping_models(conn, RELEASE)
        got = meta(conn)
        assert got["embed_sha256"] == RELEASE
        assert got["tag_probe_sha256"] == RELEASE

    def test_a_probe_stamped_with_another_name_is_not_vouched_for(self, conn):
        from ingest import update
        embedded_by(conn, update.EMBED_MODEL, tag_probe_model="test/old-model")
        update.swapping_models(conn, RELEASE)
        assert "tag_probe_sha256" not in meta(conn)

    def test_another_name_with_no_weights_is_still_a_swap(self, conn):
        from ingest import update
        embedded_by(conn, "test/old-model")
        assert update.swapping_models(conn, RELEASE)
        assert "embed_sha256" not in meta(conn)


@needs_db
class TestTheWeightsARunEmbedsWithAreTheRelease:
    #needs_db for the driver, not the rows: ingest/update.py imports psycopg,
    #which the pure suite must not

    @pytest.fixture
    def release(self, tmp_path, monkeypatch):
        from ingest import update

        def write(repo=None, stamp=None):
            path = tmp_path / "model_release.json"
            path.write_text(json.dumps({"hf_repo": repo or update.EMBED_MODEL, "sha256": RELEASE,
                                        "hf_revision": "4b9e7825f7153a0e6eed2a4cdc6b38c9aa0008ae"}))
            monkeypatch.setattr(update, "RELEASE", str(path))
            folder = tmp_path / "model"
            folder.mkdir(exist_ok=True)
            if stamp is not None:
                (folder / ".sha256").write_text(stamp + "\n")
            monkeypatch.setenv("EMBED_MODEL_DIR", str(folder))
            return update.model_release()

        monkeypatch.delenv("EMBED_MODEL_DIR", raising=False)
        return write

    def test_a_folder_holding_the_release_is_taken(self, release):
        assert release(stamp=RELEASE)["sha256"] == RELEASE

    def test_a_folder_holding_other_weights_is_refused(self, release):
        #the run would record the release's sha over vectors from the folder
        with pytest.raises(SystemExit, match=RETRAIN[:12]):
            release(stamp=RETRAIN)

    def test_a_folder_with_no_stamp_is_refused(self, release):
        #fetch_model.py writes the stamp last, so a folder without one is a
        #half extracted release or somebody else's weights
        with pytest.raises(SystemExit, match="no .sha256"):
            release()

    def test_a_release_of_another_repo_is_refused(self, release):
        with pytest.raises(SystemExit, match="test/other-model"):
            release(repo="test/other-model", stamp=RELEASE)
