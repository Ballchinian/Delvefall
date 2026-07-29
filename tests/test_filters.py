#the filter box compiler: scryfall style syntax turned into one sql condition.
#
#the contract that matters is FAIL-SOFT. this parses whatever somebody is
#halfway through typing, so a token it cannot read has to degrade to a smaller
#filter and never to an exception, because an exception here is a 500 on the
#search page. that is not hypothetical: a filter box ending in a bare "-",
#which is every half typed negation, walked off the end of the token list and
#took the whole search down.
#
#the tests read the generated sql as a string on purpose. it is placeholdered
#and the params come back beside it, so asserting on both is what shows values
#never reach the sql by concatenation.
#
#gbp is deliberately absent from every case here: the gbp column is built from
#the day's exchange rates, which are fetched over the network on first use, and
#a unit test must not depend on that

import pytest

from app import compile_fq


class TestFailSoft:

    def test_nothing_at_all(self):
        assert compile_fq("") == (None, [])
        assert compile_fq(None) == (None, [])
        assert compile_fq("   ") == (None, [])

    def test_a_bare_negation_is_a_skipped_token_not_a_crash(self):
        #the exact input that used to 500 the search page
        assert compile_fq("-") == (None, [])

    def test_a_trailing_negation_keeps_the_rest_of_the_filter(self):
        sql, params = compile_fq("o:draw -")
        assert sql == "(c.oracle_text ILIKE %s)"
        assert params == ["%draw%"]

    def test_half_typed_negations_never_raise(self):
        for fq in ("-", "--", "o:draw -", "- -", "-(", "-)", "- or", "and -"):
            compile_fq(fq)

    def test_unbalanced_parens_degrade(self):
        sql, params = compile_fq("((o:draw")
        assert "c.oracle_text ILIKE %s" in sql
        assert params == ["%draw%"]
        sql, params = compile_fq("o:a)) o:b")
        assert params == ["%a%", "%b%"]
        assert compile_fq(")") == (None, [])

    def test_bare_words_are_ignored(self):
        assert compile_fq("randomword") == (None, [])
        sql, params = compile_fq("randomword o:draw")
        assert params == ["%draw%"]

    def test_a_key_we_do_not_speak_is_skipped(self):
        #skipped, never matched to an empty set, so a typo narrows nothing
        assert compile_fq("zzz:nope") == (None, [])
        assert compile_fq("is:reserved") == (None, [])
        sql, params = compile_fq("is:reserved o:draw")
        assert params == ["%draw%"]


class TestTerms:

    def test_oracle_text(self):
        assert compile_fq("o:draw") == ("(c.oracle_text ILIKE %s)", ["%draw%"])
        assert compile_fq("oracle:draw") == ("(c.oracle_text ILIKE %s)", ["%draw%"])

    def test_a_quoted_phrase_stays_one_term(self):
        sql, params = compile_fq('o:"draw a card"')
        assert params == ["%draw a card%"]

    def test_type_line(self):
        assert compile_fq("t:creature") == ("(c.type_line ILIKE %s)", ["%creature%"])

    def test_colour_identity_fits_inside(self):
        sql, params = compile_fq("id:wug")
        assert params == ["^[WUG]*$"]

    def test_colourless_identity_is_its_own_shape(self):
        assert compile_fq("id:c") == ("(c.color_identity = '')", [])

    def test_junk_colour_letters_are_dropped(self):
        #the value lands inside a regex, so only real colour letters get in
        sql, params = compile_fq("id:wxyzu")
        assert params == ["^[WU]*$"]

    def test_layouts(self):
        assert compile_fq("is:dfc") == ("(c.layout IN ('transform', 'modal_dfc', 'meld'))", [])
        assert compile_fq("is:split") == ("(c.layout = %s)", ["split"])

    def test_legality_reads_both_ways(self):
        assert compile_fq("f:commander") == ("(c.legal_commander = true)", [])
        assert compile_fq("banned:commander") == ("(c.legal_commander = false)", [])

    def test_a_format_we_do_not_track_is_skipped(self):
        assert compile_fq("f:modern") == (None, [])


class TestNumericFields:

    @pytest.mark.parametrize("op", [">=", "<=", "=", ">", "<"])
    def test_every_operator_survives(self, op):
        sql, params = compile_fq("mv" + op + "2")
        assert sql == "(c.cmc " + op + " %s)"
        assert params == [2.0]

    def test_mana_value_answers_to_both_names(self):
        assert compile_fq("mv=2") == compile_fq("cmc=2")

    def test_decimals(self):
        assert compile_fq("salt>=1.5") == ("(c.salt >= %s)", [1.5])

    def test_named_currencies_always_mean_themselves(self):
        #usd and eur name their own column whatever the toggle says
        assert compile_fq("usd<5", currency="eur") == ("(c.price_usd < %s)", [5.0])
        assert compile_fq("eur<5", currency="usd") == ("(c.price_eur < %s)", [5.0])

    def test_the_bare_word_price_follows_the_toggle(self):
        assert compile_fq("price<5", currency="usd") == ("(c.price_usd < %s)", [5.0])
        assert compile_fq("price<5", currency="eur") == ("(c.price_eur < %s)", [5.0])

    def test_the_number_is_a_parameter_never_text_in_the_sql(self):
        sql, params = compile_fq("usd>=1")
        assert "1" not in sql
        assert params == [1.0]


class TestOperators:

    def test_words_side_by_side_mean_and(self):
        sql, params = compile_fq("o:a o:b")
        assert sql == "(c.oracle_text ILIKE %s AND c.oracle_text ILIKE %s)"
        assert params == ["%a%", "%b%"]

    def test_and_can_be_written_out(self):
        assert compile_fq("o:a and o:b") == compile_fq("o:a o:b")

    def test_or(self):
        sql, params = compile_fq("o:a or o:b")
        assert sql == "((c.oracle_text ILIKE %s) OR (c.oracle_text ILIKE %s))"
        assert params == ["%a%", "%b%"]

    def test_and_binds_tighter_than_or(self):
        #"a and b" is one side of the or, which the brackets have to show
        sql, params = compile_fq("o:a and o:b or o:c")
        assert sql == ("((c.oracle_text ILIKE %s AND c.oracle_text ILIKE %s) "
                       "OR (c.oracle_text ILIKE %s))")
        assert params == ["%a%", "%b%", "%c%"]

    def test_negation(self):
        sql, params = compile_fq("-t:creature")
        assert sql == "(NOT (c.type_line ILIKE %s))"
        assert params == ["%creature%"]

    def test_negation_applies_to_a_group(self):
        sql, params = compile_fq("-(o:a or o:b)")
        assert sql.startswith("(NOT (")
        assert params == ["%a%", "%b%"]

    def test_the_users_grouping_is_kept(self):
        #the documented example from the syntax note
        sql, params = compile_fq("(o:draw or o:scry) -t:creature")
        assert sql == ("(((c.oracle_text ILIKE %s) OR (c.oracle_text ILIKE %s)) "
                       "AND NOT (c.type_line ILIKE %s))")
        assert params == ["%draw%", "%scry%", "%creature%"]

    def test_params_arrive_in_the_order_the_placeholders_do(self):
        #the whole safety story depends on this pairing holding
        sql, params = compile_fq("o:one t:two mv=3 o:four")
        assert sql.count("%s") == len(params)
        assert params == ["%one%", "%two%", 3.0, "%four%"]


class TestCaseInsensitivity:

    def test_keys_and_operators_read_in_any_case(self):
        assert compile_fq("O:draw") == compile_fq("o:draw")
        assert compile_fq("o:a OR o:b") == compile_fq("o:a or o:b")
        assert compile_fq("o:a AND o:b") == compile_fq("o:a and o:b")
