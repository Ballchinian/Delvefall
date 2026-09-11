#the comparison readouts: the four arrows under a result card, and the band under
#a deck panel. both answer "how does this compare" and both are read by eye
#rather than checked, so a wrong one is simply believed.
#
#none of this has a database behind it and none of it had a test. the numbers are
#all decided by constants sitting a few lines above each function, which is
#exactly the shape that survives a refactor looking correct: the boundary moves,
#every page still renders, and the only thing that changed is which cards wear
#which arrow.
#
#every expected value below comes from the sentence the constant was written for,
#named in the comment on each test. where the code and that sentence disagree the
#test says so out loud rather than pinning what the code does today

import datetime

#conftest's stub stands in for the pool, so this import costs no database
import app


class TestPriceVerdict:
    #the money arrow. the RULE is that colour costs two things at once: a
    #doubling AND a real gap in cash. either alone is not "much"

    def test_the_pair_the_rule_was_written_for(self):
        #the comment above PRICE_MUCH_GAP names this pair: 25p against 10p is
        #2.5x and nobody would call it much more expensive. the ratio clears on
        #its own, so this is the test that fails if the gap is ever dropped
        assert app.price_verdict(0.25, 0.10) == "pricier"

    def test_a_real_gap_without_a_doubling_is_not_much_either(self):
        #the mirror of the case above, and the half a ratio-only rule would miss:
        #a fiver is real money and 15 against 10 is nowhere near double
        assert app.price_verdict(15.0, 10.0) == "pricier"
        assert app.price_verdict(10.0, 15.0) == "cheaper"

    def test_both_conditions_together_earn_the_colour(self):
        assert app.price_verdict(20.0, 10.0) == "much-pricier"
        assert app.price_verdict(10.0, 20.0) == "much-cheaper"

    def test_the_corner_where_the_two_conditions_meet(self):
        #2.00 against 1.00 is the cheapest pair that satisfies both at once: the
        #gap is exactly the pound and the ratio is exactly the doubling. a penny
        #under and the gap fails while the ratio still holds, which is the whole
        #point of the pair of them
        assert app.price_verdict(2.00, 1.00) == "much-pricier"
        assert app.price_verdict(1.99, 1.00) == "pricier"

    def test_the_same_two_cards_agree_whichever_one_was_searched(self):
        #a result's arrow is read against the anchor, so the two pages showing
        #this pair have to tell the same story backwards. nothing else asserts
        #that the "much" test is symmetric, and it is easy to lose: written
        #against the anchor alone (price >= anchor * 2, no second branch) it
        #reads much one way round and plain the other
        #every value is a boundary rather than a sample, which is what lets six
        #of them say more than the eight arbitrary ones they replaced: 0.00 is
        #the unpriced promo two tests below, 0.10 and 0.25 clear the ratio
        #without the gap, 1.00 and 2.00 clear both exactly, 10.00 sits a scale
        #away from the rest. 0.00 is the one that was missing and the one the
        #rule was actually broken on
        mirror = {"pricier": "cheaper", "much-pricier": "much-cheaper",
                  "cheaper": "pricier", "much-cheaper": "much-pricier", "": ""}
        prices = (0.0, 0.10, 0.25, 1.00, 2.00, 10.00)
        for a in prices:
            for b in prices:
                assert app.price_verdict(a, b) == mirror[app.price_verdict(b, a)], (a, b)

    def test_an_identical_price_says_nothing(self):
        assert app.price_verdict(5.0, 5.0) == ""

    def test_an_unpriced_card_on_either_side_says_nothing(self):
        #absent is not zero, the same rule price_label follows
        assert app.price_verdict(None, 5.0) == ""
        assert app.price_verdict(5.0, None) == ""

    def test_a_free_price_says_nothing_from_either_end(self):
        #a stored 0.00 is an unpriced promo rather than a card that costs
        #nothing, and every ratio against it is meaningless. this is the one
        #place a verdict treats zero as absent, and it is deliberate: salt does
        #the opposite two classes down.
        #
        #both ways round, because the same two cards are shown on two pages and
        #each is the other's anchor there. guarding one side alone is what had
        #the promo reading "much cheaper" on a page where the fiver read nothing
        assert app.price_verdict(5.0, 0.0) == ""
        assert app.price_verdict(0.0, 5.0) == ""


class TestRankVerdict:
    #play rate, where the number runs backwards: rank 1 is the most played card
    #in the format

    def test_a_smaller_rank_is_the_more_played_card(self):
        #the direction that is easy to flip, and flipping it tells someone their
        #staple is the obscure one
        assert app.rank_verdict(10, 1000) == "more-played"
        assert app.rank_verdict(1000, 10) == "less-played"

    def test_forty_places_apart_is_the_same_card(self):
        #the sentence RANK_BAND was written for: ranks are ordinal over the whole
        #format, so two cards forty places apart are equally played in any sense
        #that matters
        assert app.rank_verdict(1040, 1000) == ""

    def test_the_band_is_a_fifth_of_the_anchor(self):
        #199 places off a rank of 1000 is inside the band, 201 is outside it
        assert app.rank_verdict(1199, 1000) == ""
        assert app.rank_verdict(1201, 1000) == "less-played"

    def test_the_band_belongs_to_the_anchor_and_not_to_the_pair(self):
        #recorded rather than wished away. the band is a fraction of the CARD YOU
        #SEARCHED FOR, so the same two cards can wear an arrow on one page and
        #nothing on the other. that is the right reading (a fifth of rank 100 is
        #a different distance from a fifth of rank 20000) but it does mean the
        #relation is not symmetric, unlike the price one above
        assert app.rank_verdict(121, 100) == "less-played"
        assert app.rank_verdict(100, 121) == ""

    def test_an_unranked_card_on_either_side_says_nothing(self):
        #plenty of cards are unranked: nobody plays them, or they are too new
        assert app.rank_verdict(None, 500) == ""
        assert app.rank_verdict(500, None) == ""


class TestSaltVerdict:
    #annoyance, judged on the GAP alone. the constants' comment says why: salt is
    #an average of votes rather than an amount of something, so a ratio over it
    #means nothing

    def test_a_doubling_alone_never_earns_the_colour(self):
        #0.1 against 0.2 is the pair the "no ratio test" comment names. it is a
        #doubling, and a doubling is exactly what the price rule would colour, so
        #this is the test that fails if the two verdicts are ever unified
        assert not app.salt_verdict(0.2, 0.1).startswith("much")

    def test_a_gap_inside_the_band_says_nothing(self):
        assert app.salt_verdict(0.59, 0.50) == ""
        assert app.salt_verdict(0.41, 0.50) == ""

    def test_a_gap_past_the_band_earns_the_arrow(self):
        assert app.salt_verdict(0.61, 0.50) == "saltier"
        assert app.salt_verdict(0.39, 0.50) == "milder"

    def test_a_gap_wider_than_the_middle_half_of_the_game_earns_colour(self):
        #SALT_MUCH_GAP is 0.4 because the pool's whole interquartile range is
        #0.31, so this is a move wider than the middle half of every card there is
        assert app.salt_verdict(0.95, 0.50) == "much-saltier"
        assert app.salt_verdict(0.50, 0.95) == "much-milder"

    def test_a_salt_of_zero_is_a_reading_and_not_a_blank(self):
        #the invariant three other places in the codebase had to learn. an unvoted
        #card has NO salt and sits out; a card scored 0.00 was voted on and nobody
        #minded it, which is a real and useful thing to say. contrast
        #test_a_free_anchor_says_nothing above, where zero DOES mean absent
        #because an unpriced card is stored as a missing price rather than a free one
        assert app.salt_verdict(0.5, 0.0) == "much-saltier"
        assert app.salt_verdict(0.0, 0.5) == "much-milder"

    def test_an_unvoted_card_on_either_side_says_nothing(self):
        assert app.salt_verdict(None, 0.5) == ""
        assert app.salt_verdict(0.5, None) == ""


class TestAgeVerdict:
    #the only verdict of the four with two states instead of four, because older
    #is not better than newer and colour is reserved for an end that is

    def date(self, y, m, d):
        return datetime.date(y, m, d)

    def test_the_older_card_is_the_one_printed_first(self):
        #the subtraction runs anchor minus released, so a positive gap means this
        #card came first. getting it backwards labels every reprint as older than
        #the card it reprints
        anchor = self.date(2020, 1, 1)
        assert app.age_verdict(self.date(2015, 1, 1), anchor) == "older"
        assert app.age_verdict(self.date(2024, 1, 1), anchor) == "newer"

    def test_half_a_year_apart_is_contemporary(self):
        #the sentence AGE_BAND_DAYS was written for: four sets a year means a six
        #month gap says nothing about whether two cards are of an era
        anchor = self.date(2020, 7, 1)
        assert app.age_verdict(self.date(2020, 1, 1), anchor) == ""
        assert app.age_verdict(self.date(2020, 12, 1), anchor) == ""

    def test_the_boundary_sits_between_365_days_and_366(self):
        #the band is 365.25 days against an integer number of days, so a card
        #exactly one calendar year older is silent in an ordinary year and earns
        #the arrow across a leap one. that is a day of slack on a year long band
        #and it is the shape this records rather than a fault to fix
        anchor = self.date(2020, 1, 1)
        assert app.age_verdict(self.date(2019, 1, 1), anchor) == ""       #365 days
        assert app.age_verdict(self.date(2018, 12, 31), anchor) == "older"  #366 days

    def test_age_never_wears_colour(self):
        #the rule the guide states out loud: colour means one end is better, and
        #neither end of this one is. a "much-older" would be a promise the page
        #cannot keep, so this walks a decade either side rather than trusting the
        #two branches to stay two
        anchor = self.date(2020, 1, 1)
        for offset in range(-4000, 4000, 31):
            got = app.age_verdict(anchor + datetime.timedelta(days=offset), anchor)
            assert got in ("", "older", "newer"), (offset, got)

    def test_an_undated_card_on_either_side_says_nothing(self):
        assert app.age_verdict(None, self.date(2020, 1, 1)) == ""
        assert app.age_verdict(self.date(2020, 1, 1), None) == ""


class TestTheFiguresUnderACard:
    #the three labels beside the arrows. only the absent case is pinned: the
    #formatting is visible on the line, but what a MISSING value prints is the
    #thing every one of them had to be taught separately

    def test_absent_prints_nothing_rather_than_zero(self):
        #an unranked, unpriced or unvoted card shows a blank. printing a 0 there
        #says "we measured this and it came to nothing", which is a different and
        #false claim
        assert app.rank_label(None) == ""
        assert app.salt_label(None) == ""
        assert app.age_label(None) == ""

    def test_a_scored_zero_still_prints_its_zero(self):
        #the other half, and the half that makes the blanks mean anything at all
        assert app.salt_label(0.0) == "0.00"

    def test_salt_keeps_two_decimals(self):
        #most of the pool lives between 0.07 and 0.38, where one decimal place
        #collapses half the range into "0.2"
        assert app.salt_label(0.2) == "0.20"
        assert app.salt_label(0.375) != app.salt_label(0.325)

    def test_age_counts_from_the_first_printing(self):
        #released_at is scryfall's EARLIEST printing, so a reprint does not make
        #an old card new. ten years is 3653 days at the 365.25 the whole site uses
        today = datetime.date.today()
        assert app.age_label(today) == "0.0 years"
        assert app.age_label(today - datetime.timedelta(days=3653)) == "10.0 years"


class TestStandingBand:
    #"26th of 167" reads as a rank, so the deck panels say "top 16%" instead. the
    #stated rule is that the share is read FROM THE NEARER END, because "top 84%"
    #is a true and useless way to say 141st of 167

    def band(self, place, of):
        return app.standing_band({"place": place, "of": of})

    def test_the_best_deck_on_the_board_reads_from_the_top(self):
        #first of 167 is 0.6%, which ROUNDS to 1 on its own: the max(1, ...) in
        #standing_band only starts doing anything on a board over 200, so this
        #asserts the reading rather than that guard. worth saying because the
        #guard's own comment cites this very number as its reason
        assert self.band(1, 167)["band_end"] == "top"
        assert self.band(1, 167)["band_pct"] == 1

    def test_the_bottom_of_the_board_reads_from_the_bottom(self):
        #last of 167 is the same 0.6% as first, said from the other end
        got = self.band(167, 167)
        assert got["band_end"] == "bottom"
        assert got["band_pct"] == 1

    def test_the_two_readings_of_a_panel_are_the_same_fact(self):
        #a deck that is bottom 16% of the saltiest is top 16% of the mildest. the
        #panel flips by walking the board from the other end, so the mirrored
        #place has to come back with the mirrored share or the switch changes the
        #answer rather than the wording
        for of in (3, 4, 17, 100, 167, 168):
            for place in range(1, of + 1):
                here = self.band(place, of)
                there = self.band(of - place + 1, of)
                assert here["band_pct"] == there["band_pct"], (place, of)

    def test_a_large_share_is_never_offered_as_a_top(self):
        #the fault the rule was written against: "top 84%" is a true and useless
        #way to say 141st of 167, so a share that big has to be said from the
        #other end instead.
        #
        #this asks the SHARE, not the branch that picked it. asking "place * 2
        #<= of" here would be standing_band's own condition handed back to it,
        #green for any arithmetic at all: invert the share and first of 167
        #reads "top 100%" with that assertion still passing. 50 rather than a
        #tighter number because the midpoint of an odd board lands a point the
        #wrong side of half, which the tie-break was never written to promise
        for of in (3, 17, 100, 167, 168):
            for place in range(1, of + 1):
                got = self.band(place, of)
                if got["band_end"] == "top":
                    assert got["band_pct"] <= 50, (place, of, got)
