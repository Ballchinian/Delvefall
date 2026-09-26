#the maps turning a raw cosine into the percent on the badge, and the idf weight
#behind the mechanical score.
#
#the site's promise is that the number means something fixed ("80 means a good
#match") while the scorer underneath is free to change, and these maps are where
#that is kept. the gate is written in DISPLAYED units for the same reason, so the
#two directions have to stay each other's inverse at the anchors or a filter set
#at 80 stops meaning 80.
#
#these read the SEEDS: conftest's stub returns no meta rows, so load_calibration
#falls back to the documented values rather than what the live database holds

import json
import math

import pytest

from conftest import needs_db
from common import concept
import mirror
#conftest's stub stands in for the pool, so this import costs no database
import app


ANCHORS = concept.CALIBRATION


class TestSeedsAgree:
    #tools/check_sync.py compares these by ast on every push. this asserts the
    #same thing at runtime, which is the form that catches a value being
    #assembled rather than written out

    def test_concept_seed_matches_its_source_of_truth(self):
        assert mirror.CALIBRATION == concept.CALIBRATION

    def test_the_stub_database_left_the_seed_in_place(self):
        #if this fails the suite is reading a live calibration and every
        #number below is measuring the wrong thing
        assert mirror.CALIBRATION == [(0.0, 0), (0.13, 35), (0.26, 55),
                                      (0.45, 70), (0.59, 82), (0.68, 90), (1.0, 100)]

    def test_the_mech_seed_survived_the_stub_too(self):
        #the mech anchors below parametrize off this very map, so a replaced
        #calibration would still pass them. this is the only thing asserting
        #the map itself is the documented seed
        assert mirror.MECH_CALIBRATION == [(0.0, 0), (0.30, 30), (0.42, 45),
                                           (0.62, 65), (0.76, 80), (0.90, 92), (1.0, 100)]


class TestConceptDisplay:

    @pytest.mark.parametrize("raw,pct", ANCHORS)
    def test_every_anchor_lands_on_its_own_percent(self, raw, pct):
        assert concept.to_display(raw) == pct
        assert mirror.concept_display(raw) == pct

    def test_the_judged_pairs_read_the_way_they_were_judged(self):
        #the pairs the map was fitted through, named in common/concept.py
        assert concept.to_display(0.59) == 82   #Shadrix/Gluntch, a real match
        assert concept.to_display(0.68) == 90   #Boots/Greaves, near substitutes
        assert concept.to_display(0.45) == 70   #close but generic
        assert concept.to_display(0.26) == 55   #same family, different everything
        assert concept.to_display(0.13) == 35   #shared-tag noise

    def test_monotone_so_orderings_survive_the_translation(self):
        last = -1
        for i in range(0, 101):
            got = concept.to_display(i / 100.0)
            assert got >= last
            last = got

    def test_out_of_range_is_clamped_not_extrapolated(self):
        assert concept.to_display(-0.5) == 0
        assert concept.to_display(1.5) == 100
        assert concept.to_display(0.0) == 0
        assert concept.to_display(1.0) == 100


class TestTheGateIsTheInverse:
    #the map walked backwards, so a gate written in displayed units becomes a
    #raw cutoff inside sql. if these two ever disagree, "show me 80+" quietly
    #starts filtering at something else

    @pytest.mark.parametrize("raw,pct", ANCHORS)
    def test_each_anchor_round_trips(self, raw, pct):
        assert concept.from_display(pct) == pytest.approx(raw)
        assert mirror.concept_raw_gate(pct) == pytest.approx(raw)

    def test_the_cutoff_the_search_actually_uses(self):
        #find_similar gates the concept injection at this value
        assert mirror.concept_raw_gate(70) == pytest.approx(0.45)

    def test_a_gate_never_admits_what_it_should_exclude(self):
        #the real contract: anything at or above the raw gate displays at or
        #above the percent that asked for it
        for pct in range(0, 101):
            raw = concept.from_display(pct)
            assert concept.to_display(raw) >= pct - 1

    def test_out_of_range_is_clamped(self):
        assert concept.from_display(-10) == 0.0
        assert concept.from_display(200) == 1.0


class TestMechDisplay:

    @pytest.mark.parametrize("raw,pct", mirror.MECH_CALIBRATION)
    def test_every_anchor_lands_on_its_own_percent(self, raw, pct):
        assert mirror.mech_display(raw) == pct

    def test_monotone_and_clamped(self):
        last = -1
        for i in range(0, 101):
            got = mirror.mech_display(i / 100.0)
            assert got >= last
            last = got
        assert mirror.mech_display(-1) == 0
        assert mirror.mech_display(2) == 100


class TestLineWeight:
    #how much a matched line counts for, by how many cards carry it. a line
    #half the format shares must not answer a rare one at full value

    def test_a_rare_line_counts_full(self):
        for count in (0, 1, 3, 5):
            assert mirror.line_weight(count) == 1.0

    def test_the_curve_starts_at_the_boundary(self):
        #5 is the last count worth 1.0 and the curve is continuous there
        assert mirror.line_weight(5) == 1.0
        assert mirror.line_weight(6) < 1.0
        assert mirror.line_weight(6) == pytest.approx(1.0 / (1.0 + math.log10(6 / 5.0)))

    def test_a_decade_of_cards_halves_the_weight(self):
        #50 cards is ten times the free allowance, so log10 lands on 1
        assert mirror.line_weight(50) == pytest.approx(0.5)

    def test_strictly_decreasing_past_the_boundary(self):
        last = 1.0
        for count in range(6, 5000, 37):
            got = mirror.line_weight(count)
            assert got < last
            last = got
        assert last > 0


class TestAnchorSparsevec:
    #the anchor half of the concept axis, as pgvector wants to read it. the
    #candidate half is baked by ingest/tags.py and the two are compared to the
    #bit, so a literal that rounds or reorders scores a different pair than the
    #one the page is showing

    def rows(self, *pairs):
        return [{"dim": d, "weight": w} for d, w in pairs]

    def test_pairs_come_out_in_ascending_dim_order(self):
        got = app.anchor_sparsevec(self.rows((90, 1.5), (2, 2.0), (40, 0.5)))
        assert got.startswith("{2:2.0,40:0.5,90:1.5}/")

    def test_it_declares_the_width_the_column_does(self):
        #pgvector refuses to compare two sparsevecs of different widths, so this
        #is the number that decides whether a search runs or 500s
        got = app.anchor_sparsevec(self.rows((1, 1.0)))
        assert got.endswith("/" + str(app.TAG_VEC_WIDTH))

    def test_weights_survive_the_round_trip_exactly(self):
        #repr, not str: a float4 weight printed short comes back as a different
        #float4, and then the anchor and the stored vector disagree
        w = 1.1936421394348145
        got = app.anchor_sparsevec(self.rows((7, w)))
        assert float(got.split(":")[1].split("}")[0]) == w

    def test_an_empty_anchor_is_still_a_legal_literal(self):
        #find_similar guards this case rather than querying with it (cosine
        #against a zero vector is NaN), but it must not raise on the way out
        assert app.anchor_sparsevec([]) == "{}/" + str(app.TAG_VEC_WIDTH)


class _Clock:
    #monotonic only, so mirror's timer can be wound forward without sleeping
    def __init__(self, now):
        self.now = now

    def monotonic(self):
        return self.now


class TestTheMapsAreReadAgainOnATimer:
    #a model swap writes new maps into meta beside the new vectors, and nothing
    #redeploys web: railway ships it on /web/** only. a worker that reads once then
    #serves the new model's vectors through the OLD model's map, silently and site
    #wide, where a near verbatim match reads 62% and the refit puts it at 77%

    def armed(self, monkeypatch, now, calibrated=True):
        clock = _Clock(now)
        reads = []
        monkeypatch.setattr(mirror, "time", clock)
        monkeypatch.setattr(mirror, "CALIBRATED", calibrated)
        monkeypatch.setattr(mirror, "_LOADED_AT", now)
        monkeypatch.setattr(mirror, "load_calibration", lambda wait=None: reads.append(clock.now))
        return clock, reads

    def test_nothing_is_read_before_the_interval_is_up(self, monkeypatch):
        clock, reads = self.armed(monkeypatch, 1000.0)
        for _ in range(100):
            mirror.refresh_calibration()
        clock.now = 1000.0 + mirror.RELOAD_EVERY - 0.5
        mirror.refresh_calibration()
        assert reads == []

    def test_the_first_request_past_it_reads_again(self, monkeypatch):
        clock, reads = self.armed(monkeypatch, 1000.0)
        clock.now = 1000.0 + mirror.RELOAD_EVERY
        mirror.refresh_calibration()
        assert reads == [clock.now]

    def test_a_worker_that_never_got_an_answer_retries_every_request(self, monkeypatch):
        #the boot blip retry predates the timer and has to outlive it: a database
        #unreachable at boot costs one request's worth of seeds, not a worker's
        clock, reads = self.armed(monkeypatch, 1000.0, calibrated=False)
        for _ in range(3):
            mirror.refresh_calibration()
        assert len(reads) == 3


class TestASecondReadReplacesTheFirst:

    def served(self, monkeypatch, maps):
        #enough of the pool for load_calibration, which looks each key up by name
        class Rows:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return None if self.value is None else {"value": json.dumps(self.value)}

        class Conn:
            def execute(self, sql, args):
                return Rows(maps.get(args[0]))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Pool:
            def connection(self, timeout=None):
                return Conn()

        monkeypatch.setattr(mirror, "pool", Pool())

    def test_new_maps_in_meta_overwrite_the_ones_in_memory(self, monkeypatch):
        monkeypatch.setattr(mirror, "CALIBRATION", list(mirror.CALIBRATION))
        monkeypatch.setattr(mirror, "MECH_CALIBRATION", list(mirror.MECH_CALIBRATION))
        monkeypatch.setattr(mirror, "CALIBRATED", False)
        monkeypatch.setattr(mirror, "_LOADED_AT", 0.0)
        #both keys at once, because which map each one lands in is an if/else
        self.served(monkeypatch, {"concept_calibration": [[0.0, 0], [0.5, 90], [1.0, 100]],
                                  "mech_calibration": [[0.0, 0], [0.5, 20], [1.0, 100]]})
        was = mirror.concept_display(0.5)
        mirror.load_calibration()
        assert mirror.concept_display(0.5) == 90
        assert mirror.mech_display(0.5) == 20
        #74 under the seed map, so the reread is what moved it and not the arithmetic
        assert was == 74

    def test_a_read_that_dies_between_the_maps_changes_neither(self, monkeypatch):
        #the concept map arrives, the mech read throws: the new concept map beside
        #the old mech map is one model's percents on one axis and another's on the
        #other, for the 300s until the next reload
        monkeypatch.setattr(mirror, "CALIBRATION", [(0.0, 0.0), (1.0, 100.0)])
        monkeypatch.setattr(mirror, "MECH_CALIBRATION", [(0.0, 0.0), (1.0, 100.0)])
        monkeypatch.setattr(mirror, "CALIBRATED", True)

        class Rows:
            def fetchone(self):
                return {"value": json.dumps([[0.0, 0], [0.5, 90], [1.0, 100]])}

        class Conn:
            def execute(self, sql, args):
                if args[0].startswith("mech"):
                    raise RuntimeError("the connection dropped")
                return Rows()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Pool:
            def connection(self, timeout=None):
                return Conn()

        monkeypatch.setattr(mirror, "pool", Pool())
        mirror.load_calibration()
        assert mirror.CALIBRATION == [(0.0, 0.0), (1.0, 100.0)]
        assert mirror.MECH_CALIBRATION == [(0.0, 0.0), (1.0, 100.0)]

    def test_a_read_that_throws_keeps_the_last_good_maps(self, monkeypatch):
        #reverting to the seeds would move every percent on the site, so a blip has
        #to change nothing. the timer moves anyway, because it is stamped before the
        #query: a database that is down is asked once an interval, not once a request
        clock = _Clock(5000.0)
        monkeypatch.setattr(mirror, "time", clock)
        monkeypatch.setattr(mirror, "_LOADED_AT", 0.0)
        monkeypatch.setattr(mirror, "CALIBRATED", True)
        monkeypatch.setattr(mirror, "CALIBRATION", [(0.0, 0.0), (1.0, 100.0)])

        class Dead:
            def connection(self, timeout=None):
                raise RuntimeError("the database is down")

        monkeypatch.setattr(mirror, "pool", Dead())
        mirror.load_calibration()
        assert mirror.CALIBRATION == [(0.0, 0.0), (1.0, 100.0)]
        assert mirror.CALIBRATED is True
        assert mirror._LOADED_AT == 5000.0


@needs_db
class TestItReadsTheMetaRowsThatAreActuallyThere:
    #the tests above prove the timer against a stub. this one proves the query:
    #nothing else in the suite reads a meta row that exists, since a test database
    #the ingest never ran against has none

    def test_a_map_written_to_meta_is_the_one_the_site_serves(self, monkeypatch):
        import db
        monkeypatch.setattr(mirror, "CALIBRATION", list(mirror.CALIBRATION))
        monkeypatch.setattr(mirror, "CALIBRATED", False)
        monkeypatch.setattr(mirror, "_LOADED_AT", 0.0)
        written = [[0.0, 0], [0.4, 88], [1.0, 100]]
        with db.pool.connection() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                         ("concept_calibration", json.dumps(written)))
            conn.commit()
        try:
            mirror.load_calibration()
            assert mirror.CALIBRATION == [(0.0, 0.0), (0.4, 88.0), (1.0, 100.0)]
            assert mirror.concept_display(0.4) == 88
            assert mirror.CALIBRATED is True
        finally:
            with db.pool.connection() as conn:
                conn.execute("DELETE FROM meta WHERE key = %s", ("concept_calibration",))
                conn.commit()
