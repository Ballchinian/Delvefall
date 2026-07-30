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

import math

import pytest

from common import concept
import mirror


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
