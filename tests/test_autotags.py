#the chip rule, away from any database: scores in, chips out.
#
#the numbers here come from what web/autotags.py says it does, not from what it
#currently returns. what they cannot check is whether the port still agrees
#with finetune/exam_autotags.py, which takes real cards scored both ways

import pytest

from autotags import (CHIP_BAR, CHIP_FLOOR, TYPE_FLOOR, blend, card_type, chips,
                      probe_scores, share_scores)


class TestWhatTheNeighboursSay:

    def test_a_tag_every_neighbour_carries_is_certain(self):
        #"the weighted share of the neighbours carrying it", so all of them is 1
        assert share_scores([[(0.9, {"flying"}), (0.8, {"flying"})]]) == {"flying": 1.0}

    def test_two_equal_neighbours_split_it(self):
        got = share_scores([[(0.9, {"flying"}), (0.9, {"trample"})]])
        assert got == {"flying": 0.5, "trample": 0.5}

    def test_a_near_copy_outvotes_a_loose_match(self):
        #the whole point of the 16th power: 0.99 against 0.90 is not a close run
        got = share_scores([[(0.99, {"copy"}), (0.90, {"loose"})]])
        assert got["copy"] > 0.8
        assert got["loose"] < 0.2

    def test_a_neighbour_pointing_the_other_way_cannot_vote(self):
        #max(sim, 0) ** 16, so a negative cosine weighs nothing at all
        got = share_scores([[(0.9, {"flying"}), (-0.5, {"nonsense"})]])
        assert got["flying"] == 1.0
        assert "nonsense" not in got

    def test_a_card_takes_each_tag_at_its_best_line(self):
        #one ability nobody else has must not drag down the tag another line
        #names outright
        got = share_scores([[(0.9, {"flying"}), (0.9, {"other"})],
                            [(0.9, {"flying"})]])
        assert got["flying"] == 1.0

    def test_a_line_with_no_neighbours_says_nothing(self):
        assert share_scores([[]]) == {}


class TestWhatTheProbeSays:

    def test_a_card_takes_each_tag_at_its_best_line(self):
        assert probe_scores([{"flying": 0.4}, {"flying": 0.9}]) == {"flying": 0.9}

    def test_only_the_top_scores_of_a_line_count(self):
        #the exam reads the top PROBE_KEEP per line out of a file, so live has to
        #cut at the same place or the two stop agreeing
        line = {"tag%03d" % i: 0.9 - 0.001 * i for i in range(65)}
        got = probe_scores([line])
        assert len(got) == 60
        assert "tag000" in got
        assert "tag060" not in got


class TestBlendingTheTwo:

    def test_the_probe_takes_most_of_the_score(self):
        #0.7/0.3 is what the exam was tuned to and what 98% precision at 5
        #chips was measured on, so the numbers are spelled out rather than
        #read back off the module
        assert blend({"flying": 1.0}, {}) == {"flying": pytest.approx(0.7)}

    def test_a_tag_the_probe_never_learned_cannot_reach_the_bar(self):
        #the 58 rare tags: neighbours alone top out below CHIP_BAR, so they only
        #ever arrive through the floor
        alone = blend({}, {"rare": 1.0})["rare"]
        assert alone == pytest.approx(0.3)
        assert alone < CHIP_BAR
        assert alone > CHIP_FLOOR

    def test_both_halves_agreeing_is_a_perfect_score(self):
        assert blend({"flying": 1.0}, {"flying": 1.0}) == {"flying": 1.0}


class TestWhichScoresBecomeChips:

    def test_everything_at_the_bar_and_above_is_kept(self):
        got = chips({"a": CHIP_BAR, "b": 0.9, "c": CHIP_BAR - 0.01})
        assert set(got) == {"a", "b"}

    def test_the_best_come_first(self):
        assert list(chips({"a": 0.5, "b": 0.9, "c": 0.7})) == ["b", "c", "a"]

    def test_no_more_than_ten(self):
        got = chips({"tag%02d" % i: 0.9 - 0.001 * i for i in range(20)})
        assert len(got) == 10

    def test_a_card_with_one_good_tag_is_topped_up(self):
        #a keyword line whose neighbours agree on little still shows two chips
        got = chips({"a": 0.9, "b": 0.2, "c": 0.05})
        assert set(got) == {"a", "b"}

    def test_the_top_up_never_reaches_below_the_floor(self):
        got = chips({"a": 0.9, "b": CHIP_FLOOR - 0.01})
        assert set(got) == {"a"}

    def test_a_card_nothing_is_known_about_shows_nothing(self):
        assert chips({"a": 0.01, "b": 0.02}) == {}

    def test_the_top_up_stops_at_two(self):
        got = chips({"a": 0.2, "b": 0.19, "c": 0.18})
        assert len(got) == 2


class TestTagsThatAreNeverChips:

    def test_a_banned_tag_is_dropped_however_certain(self):
        got = chips({"doom-blade": 1.0, "flying": 0.9}, banned={"doom-blade"})
        assert set(got) == {"flying"}

    def test_it_does_not_take_a_slot_on_the_way_out(self):
        #dropped before the ranking, so the tenth real tag still gets shown
        scores = {"tag%02d" % i: 0.9 - 0.001 * i for i in range(11)}
        got = chips(scores, banned={"tag00"})
        assert len(got) == 10
        assert "tag10" in got


class TestTheTypeLine:

    def test_a_tag_that_hardly_ever_lands_on_this_type_is_dropped(self):
        shares = {"burn": {"Instant": 0.9, "Creature": TYPE_FLOOR / 2}}
        assert set(chips({"burn": 0.9}, type_shares=shares, kind="Creature")) == set()
        assert set(chips({"burn": 0.9}, type_shares=shares, kind="Instant")) == {"burn"}

    def test_nothing_is_dropped_without_a_type_line(self):
        shares = {"burn": {"Instant": 0.9, "Creature": TYPE_FLOOR / 2}}
        assert set(chips({"burn": 0.9}, type_shares=shares, kind=None)) == {"burn"}

    def test_a_tag_nobody_has_counted_survives(self):
        #a tag too new to have a row is not a tag measured as wrong here
        assert set(chips({"new": 0.9}, type_shares={}, kind="Creature")) == {"new"}

    def test_a_tag_exactly_at_the_floor_stays(self):
        shares = {"edge": {"Creature": TYPE_FLOOR}}
        assert set(chips({"edge": 0.9}, type_shares=shares, kind="Creature")) == {"edge"}


class TestReadingATypeLine:

    @pytest.mark.parametrize("line,kind", [
        ("Creature — Human Wizard", "Creature"),
        ("Artifact Creature — Golem", "Creature"),
        ("Legendary Artifact — Vehicle", "Artifact"),
        ("Land Creature — Forest Dryad", "Land"),
        ("Instant", "Instant"),
        ("Legendary Enchantment Creature — God", "Creature"),
    ])
    def test_the_type_that_decides_wins(self, line, kind):
        assert card_type(line) == kind

    def test_only_the_front_face_is_read(self):
        assert card_type("Instant // Creature — Spirit") == "Instant"

    def test_something_unrecognised_is_other(self):
        assert card_type("Kindred Hippo") == "other"
        assert card_type("") == "other"
        assert card_type(None) == "other"
