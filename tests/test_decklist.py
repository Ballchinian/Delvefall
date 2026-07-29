#reading somebody else's decklist, which arrives in whatever shape the site
#they copied it from felt like emitting. every case below is a shape one of
#those exporters really produces, named where app.py names it.
#
#matching is EXACT on the normalised name and never fuzzy, because a wrong
#guess here would sit silently in a hundred rows pretending to be someone's
#deck. that is the property most of these tests are really defending.
#
#name_index is replaced with a small fixed map rather than reached for: the
#real one is a database read, and what is being tested is the parsing around
#it, not the lookup

import pytest

import app
from app import DECK_MAX_CARDS, csv_to_lines, dek_to_lines, deck_norm, parse_decklist


CARDS = [
    "Lightning Bolt",
    "Sol Ring",
    "Swords to Plowshares",
    #an accent and a curly apostrophe, the two things a person retyping a list
    #will not reproduce
    "Gríma Wormtongue",
    "Ajani's Pridemate",
    #a name that really ends in digits, so the collector-number trim must not
    #be applied blind
    "Pip-Boy 3000",
    #and one that starts with them
    "1996 World Champion",
    #two faced, written by exporters as the front face alone
    "Delver of Secrets // Insectile Aberration",
    "Jace, the Mind Sculptor",
]


def build_index(names):
    #the same two passes the real name_index makes, so the fake behaves like
    #the real one: faces go in first and full names win any collision
    idx = {}
    for n in names:
        if "//" in n:
            for part in n.split("//"):
                idx.setdefault(deck_norm(part), n)
    for n in names:
        idx[deck_norm(n)] = n
    return idx


@pytest.fixture(autouse=True)
def fake_index(monkeypatch):
    monkeypatch.setattr(app, "name_index", lambda: build_index(CARDS))


def found(text):
    return parse_decklist(text)[0]


def missing(text):
    return parse_decklist(text)[1]


class TestDeckNorm:

    def test_case_stops_mattering(self):
        assert deck_norm("LIGHTNING bolt") == deck_norm("Lightning Bolt")

    def test_accents_stop_mattering(self):
        #what lets a list typed without accents find Gríma Wormtongue
        assert deck_norm("Gríma Wormtongue") == deck_norm("Grima Wormtongue")

    def test_both_kinds_of_apostrophe_agree(self):
        assert deck_norm("Ajani’s Pridemate") == deck_norm("Ajani's Pridemate")
        assert deck_norm("Ajani‘s Pridemate") == deck_norm("Ajani's Pridemate")

    def test_whitespace_is_collapsed(self):
        assert deck_norm("  Sol   Ring  ") == "sol ring"


class TestCounts:

    def test_a_leading_count(self):
        assert found("1 Lightning Bolt") == ["Lightning Bolt"]

    def test_the_x_form(self):
        assert found("4x Lightning Bolt") == ["Lightning Bolt"]
        assert found("4 x Lightning Bolt") == ["Lightning Bolt"]

    def test_no_count_at_all(self):
        assert found("Lightning Bolt") == ["Lightning Bolt"]

    def test_counts_are_dropped_and_repeats_collapse(self):
        #nine Islands say nothing about a deck's ideas that one Island does not
        assert found("9 Lightning Bolt\n1 Lightning Bolt") == ["Lightning Bolt"]


class TestExporterWrappingPaper:

    def test_set_code_and_collector_number(self):
        assert found("1 Sol Ring (LTC) 123") == ["Sol Ring"]

    def test_foil_marker(self):
        assert found("1 Sol Ring *F*") == ["Sol Ring"]

    def test_square_bracket_category(self):
        assert found("1 Sol Ring [Ramp]") == ["Sol Ring"]

    def test_deckstats_hangs_its_category_off_the_end(self):
        assert found("1 Sol Ring #!Ramp") == ["Sol Ring"]

    def test_mtgo_marks_its_sideboard_per_line(self):
        #a .txt straight out of the client carries "SB: 3 ..."
        assert found("SB: 3 Swords to Plowshares") == ["Swords to Plowshares"]

    def test_comments_are_skipped(self):
        assert found("// a comment\n# another\n1 Sol Ring") == ["Sol Ring"]

    def test_blank_lines_are_skipped(self):
        assert found("\n\n1 Sol Ring\n\n") == ["Sol Ring"]


class TestHeadings:

    def test_plain_headings(self):
        for heading in ("Deck", "Sideboard", "Commander", "Creatures", "Lands",
                        "Sorceries", "Artifacts", "Maybeboard", "Ramp"):
            assert found(heading) == [], heading

    def test_a_heading_carrying_its_own_count_is_still_a_heading(self):
        #the heading test runs after the trailers come off for exactly this
        assert found("Commander (1)") == []
        assert found("Creatures (24)") == []

    def test_a_heading_does_not_eat_the_cards_under_it(self):
        assert found("Commander (1)\n1 Sol Ring") == ["Sol Ring"]


class TestNamesThatLookLikeCounts:

    def test_a_name_starting_with_digits_survives_uncounted(self):
        #taking a leading number off blind turned "1996 World Champion" into a
        #lookup for "World Champion"
        assert found("1996 World Champion") == ["1996 World Champion"]

    def test_and_survives_with_a_count_in_front(self):
        assert found("1 1996 World Champion") == ["1996 World Champion"]

    def test_a_name_ending_in_digits_is_not_truncated(self):
        #the collector-number trim is only tried after the whole name fails
        assert found("1 Pip-Boy 3000") == ["Pip-Boy 3000"]

    def test_a_stranded_collector_number_still_comes_off(self):
        assert found("1 Sol Ring 456") == ["Sol Ring"]


class TestFaces:

    def test_the_front_face_alone_finds_the_card(self):
        assert found("1 Delver of Secrets") == ["Delver of Secrets // Insectile Aberration"]

    def test_so_does_the_whole_name(self):
        assert found("1 Delver of Secrets // Insectile Aberration") == \
            ["Delver of Secrets // Insectile Aberration"]


class TestMisses:

    def test_an_unknown_name_is_reported_not_guessed(self):
        assert found("1 Not A Real Card") == []
        assert missing("1 Not A Real Card") == ["Not A Real Card"]

    def test_a_near_miss_is_still_a_miss(self):
        #never fuzzy: a wrong guess would sit silently in someone's deck
        assert found("1 Lightning Bolts") == []

    def test_the_miss_list_is_capped(self):
        text = "\n".join("1 Nonexistent Card %d" % i for i in range(100))
        assert len(missing(text)) == 40

    def test_misses_do_not_stop_the_matches(self):
        assert found("1 Not A Real Card\n1 Sol Ring") == ["Sol Ring"]


class TestCaps:

    def test_the_card_cap_holds(self, monkeypatch):
        names = ["Filler %d" % i for i in range(DECK_MAX_CARDS + 50)]
        monkeypatch.setattr(app, "name_index", lambda: build_index(names))
        text = "\n".join("1 " + n for n in names)
        assert len(parse_decklist(text)[0]) == DECK_MAX_CARDS


class TestCsvExport:
    #archidekt and moxfield both offer a csv beside the text export

    def test_a_quoted_name_containing_a_comma_survives(self):
        #half the commander names in the game contain a comma
        text = 'Quantity,Name,Set\n1,"Jace, the Mind Sculptor",WWK\n'
        assert csv_to_lines(text) == "1 Jace, the Mind Sculptor"
        assert found(text) == ["Jace, the Mind Sculptor"]

    def test_moxfield_calls_the_count_column_count(self):
        text = 'Count,Name\n3,Sol Ring\n'
        assert csv_to_lines(text) == "3 Sol Ring"

    def test_a_csv_with_no_count_column_is_still_a_list(self):
        text = 'Name,Set\nSol Ring,LTC\n'
        assert csv_to_lines(text) == "1 Sol Ring"

    def test_an_ordinary_decklist_is_not_a_csv(self):
        #without the header test every paste starting with a legendary
        #creature would be run through a csv parse to learn nothing
        assert csv_to_lines("1 Jace, the Mind Sculptor\n1 Sol Ring") is None

    def test_a_header_with_no_name_column_is_not_a_csv(self):
        assert csv_to_lines("Quantity,Set\n1,LTC\n") is None

    def test_rows_short_of_the_name_column_are_skipped(self):
        text = 'Quantity,Name\n1\n1,Sol Ring\n'
        assert csv_to_lines(text) == "1 Sol Ring"


class TestMtgoDekExport:
    #mtgo's own save file, which is xml

    def test_cards_come_out_with_their_quantities(self):
        text = ('<Deck><Cards CatID="1" Quantity="3" Name="Sol Ring" />'
                '<Cards CatID="2" Quantity="1" Name="Lightning Bolt" /></Deck>')
        assert dek_to_lines(text) == "3 Sol Ring\n1 Lightning Bolt"

    def test_a_missing_quantity_reads_as_one(self):
        assert dek_to_lines('<Cards Name="Sol Ring" />') == "1 Sol Ring"

    def test_anything_that_is_not_a_dek_falls_through(self):
        assert dek_to_lines("1 Sol Ring") is None
        assert dek_to_lines("<Deck></Deck>") is None

    def test_the_parser_reads_it_end_to_end(self):
        text = '<Deck><Cards Quantity="1" Name="Sol Ring" /></Deck>'
        assert found(text) == ["Sol Ring"]
