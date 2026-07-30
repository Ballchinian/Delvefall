#the mana value window the swap tool looks inside for a replacement.
#
#worth pinning because it is easy to get backwards: the floor uses min() rather
#than max() so it only ever OPENS the range. written the other way a three drop
#stops reaching down to one and gets dragged up to five, and the tool quietly
#stops offering the cheaper card that was the point of asking

import pytest

from app import (SWAP_MV_BAND, SWAP_MV_BAND_HIGH, SWAP_MV_FLOOR, SWAP_MV_HIGH,
                 swap_mv_range)


class TestInsideTheNarrowBand:

    @pytest.mark.parametrize("cmc,expected", [(2, (0, 4)), (3, (1, 5)), (4, (2, 6)), (5, (3, 7))])
    def test_the_window_is_the_band_either_side(self, cmc, expected):
        assert swap_mv_range(cmc) == expected

    def test_a_three_drop_reaches_down_to_one(self):
        #the case the min() is written for
        low, high = swap_mv_range(3)
        assert low == 1
        assert low < SWAP_MV_FLOOR


class TestPastTheBand:

    def test_the_wider_band_starts_above_the_threshold(self):
        assert swap_mv_range(SWAP_MV_HIGH)[1] == SWAP_MV_HIGH + SWAP_MV_BAND
        assert swap_mv_range(SWAP_MV_HIGH + 1)[1] == SWAP_MV_HIGH + 1 + SWAP_MV_BAND_HIGH

    @pytest.mark.parametrize("cmc,expected", [(6, (3, 9)), (7, (4, 10)), (8, (5, 11)), (12, (5, 15))])
    def test_the_window_widens_but_the_floor_holds(self, cmc, expected):
        assert swap_mv_range(cmc) == expected

    def test_the_floor_is_a_ceiling_on_the_floor(self):
        #an expensive card always reaches down to SWAP_MV_FLOOR, never stranded
        #above it however costly
        for cmc in range(SWAP_MV_HIGH + 1, 20):
            low, high = swap_mv_range(cmc)
            assert low <= SWAP_MV_FLOOR
            assert high == cmc + SWAP_MV_BAND_HIGH


class TestShape:

    def test_the_range_is_never_backwards(self):
        for cmc in range(0, 25):
            low, high = swap_mv_range(cmc)
            assert low <= cmc <= high

    def test_cheap_cards_reach_below_zero(self):
        #harmless where it lands, nothing costing less than nothing, so the sql
        #matches from zero. recorded so the shape is not a surprise
        assert swap_mv_range(0) == (-2, 2)
        assert swap_mv_range(1) == (-1, 3)
