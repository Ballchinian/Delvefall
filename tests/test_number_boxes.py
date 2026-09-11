#the filter WIDGETS, which are the half of the filtering tests/test_filters.py
#does not reach: that file compiles the filter box, this one reads the checkboxes
#and the number boxes beside it. both layers stack and both narrow the same query.
#
#two contracts hold this layer up and neither had a test.
#
#FAIL SOFT, same as the box: every one of these values arrives in a url, so every
#one of them arrives doctored sooner or later. the promise read_number makes is
#stronger than "do not crash", it is that anything ignored gets SAID, because a
#filter that silently did nothing and a filter that silently matched nothing look
#identical from the page and both read as the site being broken.
#
#THE WHITELIST GUARDS THE PATTERN. every user value in filter_sql is a bound
#parameter, injection included, so that is not what the two lists in read_filters
#are for. what those values reach is the inside of a PATTERN: the colours a regex
#character class, where "]" or "^" rewrites the pattern instead of being matched
#by it, and the types an ILIKE pattern, where "%" matches every row. keeping
#those characters out is the whole job, and it is one edit from not happening.
#
#the sql is read as a STRING on purpose, the same way test_filters.py reads it:
#the conditions come back beside their params, so asserting on both is what shows
#which values are parameters and which are pattern text

import math
import re

#conftest's stub stands in for the pool, so this import costs no database
import app


def filters_for(query):
    #read_filters reads the live request, so the url under test has to be the
    #request. gbp is deliberately never used here: that column is built from the
    #day's exchange rates over the network, and a unit test must not depend on it
    with app.app.test_request_context("/?" + query):
        return app.read_filters()


def sql_for(query):
    f = filters_for(query)
    return app.filter_sql(f), f


class TestTheNumberBoxesSayWhatTheyIgnored:
    #read_number's promise in full: junk is NAMED on the page rather than
    #dropped, so a filter that did not work says what was ignored

    def test_an_empty_box_is_not_a_filter(self):
        f = filters_for("pmin=&pmax=")
        assert f["pmin"] is None and f["pmax"] is None
        assert f["errors"] == []

    def test_a_word_in_the_price_box_is_named(self):
        f = filters_for("pmin=cheap")
        assert f["pmin"] is None
        assert len(f["errors"]) == 1
        #the message has to quote the value back, or it names a box rather than
        #a mistake and the reader still cannot see what to change
        assert "cheap" in f["errors"][0]

    def test_a_real_number_is_a_filter_and_not_an_error(self):
        f = filters_for("pmin=2.50&mvmax=4&smin=0.5")
        assert (f["pmin"], f["mvmax"], f["smin"]) == (2.50, 4.0, 0.5)
        assert f["errors"] == []

    def test_an_inverted_range_explains_itself(self):
        #the bounds still apply exactly as typed. the page just says why nothing
        #can fit between them, because an empty result with no explanation reads
        #as the site breaking rather than as the numbers disagreeing
        for pair, word in (("pmin=10&pmax=1", "price"),
                           ("mvmin=6&mvmax=2", "mana value"),
                           ("smin=3&smax=1", "salt")):
            f = filters_for(pair)
            assert len(f["errors"]) == 1, pair
            assert word in f["errors"][0]

    def test_a_range_that_is_merely_narrow_is_not_an_error(self):
        assert filters_for("pmin=5&pmax=5")["errors"] == []

    def test_not_a_number_is_not_a_number(self):
        #"nan" is a word in a price box. it is not a price, nobody typed it
        #meaning one, and every card in the database fails a comparison against
        #it, so the page it produces is empty.
        #
        #the promise says an ignored value gets named and a range that cannot
        #match gets explained. this value is neither: it passes float(), so it is
        #never named, and NaN compares false against everything including the
        #inverted-range check, so that explanation never fires either. the result
        #is the exact page both of those messages exist to prevent
        f = filters_for("pmin=nan&pmax=5")
        assert f["errors"] != [], "a price box holding \"nan\" said nothing about it"

    def test_infinity_is_not_a_price_either(self):
        #same door, same silence. float() takes "inf", "infinity" and "-inf"
        f = filters_for("pmax=inf")
        assert f["errors"] != [], "a price box holding \"inf\" said nothing about it"

    def test_a_number_the_search_cannot_use_never_reaches_the_query(self):
        #the other acceptable answer to the two above: name it OR drop it. what
        #must not happen is that it travels on into the candidate query as a
        #parameter, where it silently empties the page.
        #
        #inf is asked the same question as nan because it fails differently and
        #"p == p" would have waved it through: "price <= Infinity" reads as no
        #bound at all and is not one, it drops every card with no listed price
        for query in ("pmin=nan", "pmax=inf", "pmin=1e400"):
            (where, params), _ = sql_for(query)
            assert all(math.isfinite(p) for p in params if isinstance(p, float)), query


class TestTheWhitelistGuardsThePattern:
    #not about injection: the values below are bound parameters whether or not
    #the lists exist, which test_every_number_arrives_as_a_parameter is the
    #reading of. this is about what a character MEANS once it is inside the
    #pattern it lands in, and the lists are what hold those characters back

    def test_only_wubrg_reaches_the_character_class(self):
        #the picked letters are concatenated straight into a regex character
        #class, so a "]" or a "^" through this door rewrites the pattern rather
        #than being matched by it. every one of these is dropped before then
        f = filters_for("colors=W&colors=x&colors=]&colors=^&colors=WU&colors=%25")
        assert f["colors"] == "W"

    def test_the_class_is_built_from_nothing_else(self):
        (where, params), _ = sql_for("colors=W&colors=]&cmode=atmost")
        assert params[0] == "^[W]*$"

    def test_a_type_we_do_not_offer_never_reaches_the_pattern(self):
        #the type names go into ILIKE patterns the same way, where the character
        #that changes the meaning is "%": alone it matches every row, so a type
        #through this door would widen the search rather than narrow it
        f = filters_for("type=Creature&type=Goblin&type=%25&type=_")
        assert f["types"] == ["Creature"]

    def test_the_colour_mode_is_one_of_three_and_never_a_fourth(self):
        #cmode picks which conditions get built, so an unknown value must land on
        #a known branch rather than falling through to none of them
        assert filters_for("cmode=exact")["cmode"] == "exact"
        assert filters_for("cmode=include")["cmode"] == "include"
        assert filters_for("cmode=nonsense")["cmode"] == "atmost"
        assert filters_for("")["cmode"] == "atmost"

    def test_every_number_arrives_as_a_parameter(self):
        #the bounds are the values a user can put an arbitrary string in, and
        #none of them appear in the sql text. this is the whole answer to
        #injection here, the lists above being about pattern meaning instead
        (where, params), _ = sql_for("pmin=1&pmax=2&mvmin=3&mvmax=4&smin=5&smax=6")
        assert "%s" in where
        for n in ("1", "2", "3", "4", "5", "6"):
            assert n not in where.replace("%s", "")
        assert params == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


class TestWhatTheColourModesMean:
    #three readings of the same tick boxes, and the sql is the only place they
    #are written down. these apply the generated conditions to real colour
    #identities rather than asserting the strings, so what is under test is what
    #a card would DO against them.
    #
    #postgres "~" is an unanchored SEARCH and LIKE with two wildcards is "in",
    #which is what makes that possible here. re.search and not re.match: match
    #anchors at position 0 by itself, so it would answer for the "^" in the
    #pattern long after somebody dropped it, and dropping it is what turns "at
    #most W,U" into a filter that admits every colour

    def conditions(self, query):
        (where, params), _ = sql_for(query)
        #paired by CONSUMING one parameter per "%s" rather than by position:
        #filter_sql emits parameterless conditions too, and COMMANDER_SQL splits
        #into two fragments of its own on the " AND " inside it, so a positional
        #zip lines up only while the colour block happens to be built first
        pairs = []
        rest = list(params)
        for cond in where.split(" AND "):
            taken, rest = rest[:cond.count("%s")], rest[cond.count("%s"):]
            if "color_identity" in cond:
                pairs.append(("regex" if "~" in cond else "like", taken[0]))
        return pairs

    def fits(self, pairs, identity):
        for kind, param in pairs:
            if kind == "regex" and not re.search(param, identity):
                return False
            if kind == "like" and param.strip("%") not in identity:
                return False
        return True

    def test_at_most_is_the_deckbuilding_question(self):
        #"fits within": every letter of the card's identity has to be one of the
        #picked colours. that is what a deckbuilder is asking, and it is the only
        #behaviour this filter had before the mode existed
        pairs = self.conditions("colors=W&colors=U&cmode=atmost")
        assert self.fits(pairs, "W")
        assert self.fits(pairs, "U")
        assert self.fits(pairs, "WU")
        assert not self.fits(pairs, "WB")
        assert not self.fits(pairs, "B")

    def test_colourless_fits_inside_every_pick(self):
        #a colourless card's identity is the empty string, and it goes in any
        #deck there is. the pattern has to admit it, which is what the "*" is for
        pairs = self.conditions("colors=W&colors=U&cmode=atmost")
        assert self.fits(pairs, "")

    def test_including_wants_them_all_present_and_welcomes_extras(self):
        pairs = self.conditions("colors=W&colors=U&cmode=include")
        assert self.fits(pairs, "WU")
        assert self.fits(pairs, "WUB")
        assert not self.fits(pairs, "W")
        assert not self.fits(pairs, "")

    def test_exactly_is_the_two_of_them_at_once(self):
        pairs = self.conditions("colors=W&colors=U&cmode=exact")
        assert self.fits(pairs, "WU")
        assert not self.fits(pairs, "W")
        assert not self.fits(pairs, "WUB")
        assert not self.fits(pairs, "")

    def test_exactly_does_not_rest_on_the_stored_letter_order(self):
        #said as a regex plus one LIKE per letter rather than an equality against
        #"WU", so a row holding "UW" answers the same. an equality here would
        #depend on scryfall's ordering matching ours forever
        pairs = self.conditions("colors=W&colors=U&cmode=exact")
        assert self.fits(pairs, "UW")

    def test_no_colours_picked_is_no_colour_filter(self):
        #and not "exactly colourless", which is what an unticked row would mean
        #if the conditions were built anyway
        (where, params), _ = sql_for("cmode=exact")
        assert "color_identity" not in where


class TestTheConditionsTheSearchAlwaysCarries:

    def test_illegal_cards_are_hidden_unless_asked_for(self):
        #most visitors are commander players, so the default is the legal pool
        (where, _), _ = sql_for("")
        assert "c.legal_commander" in where
        (where, _), _ = sql_for("illegal=1")
        assert "legal_commander" not in where

    def test_the_snippet_always_starts_where_it_will_be_glued(self):
        #it is concatenated onto a query that already has a WHERE, so a snippet
        #not starting with AND is a syntax error at the far end of the app
        for query in ("", "colors=W", "pmin=1", "gc=1&cmdr=1&type=Creature"):
            (where, _), _ = sql_for(query)
            assert where.startswith(" AND "), query

    def test_a_filter_nobody_set_adds_no_conditions(self):
        #the default search must not pay for six unset boxes
        (where, params), _ = sql_for("")
        assert params == []
        assert where.count(" AND ") == 1
