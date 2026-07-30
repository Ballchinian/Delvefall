#the line cleaner, which is the most load bearing pure function in the repo:
#the ingest embeds what it returns and the line picker looks lines up by it, so
#a change here that nobody notices is a search that quietly stops matching its
#own pages. tools/check_sync.py already guards the web/ copy against drifting
#from this one; what it cannot say is whether either of them is still right.
#
#every case below is one the comments in common/cards.py argue for, with the
#card or the measurement that made the argument named where there is one.
#the em dashes in the data are real: scryfall prints them, and the cleaner's
#job is reading them

from common.cards import REMINDER_KEYWORDS, clean_line, reminder_is_the_rule


class TestReminderIsTheRule:
    #true only when the parens held the whole rule AND the leading keyword is
    #one whose reminder text carries it

    def test_keyword_whose_reminder_is_the_rule(self):
        assert reminder_is_the_rule("Overload {6}{U}")
        assert reminder_is_the_rule("Cycling {2}")
        assert reminder_is_the_rule("Storm")

    def test_evergreen_keywords_are_deliberately_absent(self):
        #2442 cards print a bare "Flying" against 75 that spell the reminder
        #out, so keeping those 75 would orphan them from the other 2442
        assert not reminder_is_the_rule("Flying")
        assert not reminder_is_the_rule("Trample")
        assert not reminder_is_the_rule("Menace")

    def test_a_real_sentence_kept_its_meaning(self):
        #punctuation and numbers are what stop a sentence looking like a list
        #of bare keyword names, and every real rules sentence carries some
        assert not reminder_is_the_rule("Draw a card, then discard a card.")
        assert not reminder_is_the_rule("Cascade, then draw 2 cards.")
        assert not reminder_is_the_rule("Discard this card: Draw a card.")

    def test_keyword_led_prose_with_nothing_but_letters_reads_as_keywords(self):
        #the edge of the bare-keyword test, recorded rather than wished away:
        #letters and spaces alone cannot be told apart from a keyword list, so
        #prose led by a listed keyword answers true.
        #it costs nothing where it is actually reached. the only thing
        #clean_line does with a true is keep the text inside parens, and a line
        #with no parens comes out the same either way, which is what the second
        #half of this asserts. if that ever stops being true this test is the
        #one that should fail
        assert reminder_is_the_rule("Overload the target and draw a card")
        assert clean_line("Overload the target and draw a card.", "X") == \
            "Overload the target and draw a card."

    def test_the_leading_keyword_is_the_one_that_decides(self):
        #a list of bare keywords led by an evergreen one stays stripped
        assert not reminder_is_the_rule("Flying, double strike")

    def test_a_cost_spelled_out_after_a_dash_is_still_a_cost(self):
        #wizards write the cost either as mana symbols or as words after a dash,
        #and the words are the price rather than the effect. 56 lines read this
        #way, over 13 keywords: without this Street Wraith's cycling line stores
        #as "Cycling—Pay 2 life" and never mentions drawing a card
        assert reminder_is_the_rule("Cycling—Pay 2 life")
        assert reminder_is_the_rule("Morph—Discard a card")
        assert reminder_is_the_rule("Buyback—Sacrifice a land")
        assert reminder_is_the_rule("Flashback—{1}{U}, Exile X blue cards from your graveyard")
        assert reminder_is_the_rule("Splice onto Arcane—An opponent gains 5 life")

    def test_a_sentence_after_the_cost_still_counts_as_meaning(self):
        #Visions of Glory and Fugitive Codebreaker say what they do in the line
        #itself, so they keep nothing back and the reminder stays dropped
        assert not reminder_is_the_rule(
            "Flashback {8}{W}{W}. This spell costs {X} less to cast this way")
        assert not reminder_is_the_rule(
            "Disguise {5}{R}. This cost is reduced by {1} for each instant")

    def test_a_dash_cost_under_an_unlisted_keyword_is_still_false(self):
        #the dash is not what decides it, the keyword is
        assert not reminder_is_the_rule("Flying—Pay 2 life")
        assert not reminder_is_the_rule("Landfall—Draw a card")

    def test_empty_is_false_rather_than_an_error(self):
        assert not reminder_is_the_rule("")
        assert not reminder_is_the_rule("   ")

    def test_every_listed_keyword_answers_to_its_own_name(self):
        #the list is only useful if the matcher can actually reach each entry
        for kw in REMINDER_KEYWORDS:
            assert reminder_is_the_rule(kw.title()), kw


class TestCleanLineReminders:

    def test_reminder_that_is_the_rule_keeps_its_text(self):
        #Cyclonic Rift: stripping the parens stored it as a plain one-target
        #bounce and it matched Perilous Voyage at 91%
        out = clean_line("Overload {6}{U} (You may cast this spell for its overload cost. "
                         "If you do, change its targets.)", "Cyclonic Rift")
        assert out.startswith("Overload {6}{U} You may cast")
        assert "(" not in out and ")" not in out

    def test_ordinary_reminder_is_dropped(self):
        out = clean_line("Flying (This creature can't be blocked except by creatures "
                         "with flying or reach.)", "Bird")
        assert out == "Flying"

    def test_line_with_no_parens_is_untouched(self):
        assert clean_line("Draw a card.", "X") == "Draw a card."


class TestCleanLineTableRows:
    #scryfall prints four shapes. read only two and 49 of the 150 table rows in
    #the pool keep their prefix

    def test_em_dash_range_the_commonest_by_far(self):
        assert clean_line("1—9 | Draw a card.", "X") == "Draw a card."

    def test_threshold_row(self):
        assert clean_line("10+ | Draw a card.", "X") == "Draw a card."

    def test_bare_number_row(self):
        assert clean_line("20 | Draw a card.", "X") == "Draw a card."

    def test_plain_hyphen_range(self):
        assert clean_line("1-9 | Draw a card.", "X") == "Draw a card."

    def test_the_row_that_made_the_case(self):
        #"8+ | Flying, deathtouch" was embedded as its own text instead of
        #joining the two and a half thousand cards that just say flying
        assert clean_line("8+ | Flying, deathtouch", "X") == "Flying, deathtouch"


class TestCleanLinePrefixes:

    def test_saga_chapter_markers_go(self):
        assert clean_line("I, II — Draw a card.", "X") == "Draw a card."
        assert clean_line("III — Draw a card.", "X") == "Draw a card."

    def test_ability_words_go(self):
        assert clean_line("Landfall — Whenever a land enters, draw.", "X") == \
            "Whenever a land enters, draw."

    def test_a_dash_that_is_not_a_prefix_word_stays_whole(self):
        #the word list is scryfall's own catalog, so anything not in it keeps
        #its dash. a type line is the clearest example of text that must not
        #lose its left hand side
        assert clean_line("Basic Creature — Shapeshifter", "X") == "Basic Creature — Shapeshifter"


class TestCleanLineCardNames:

    def test_the_card_refers_to_itself_generically(self):
        assert clean_line("Shivan Dragon deals 2 damage.", "Shivan Dragon") == \
            "this card deals 2 damage."

    def test_a_legendary_first_name_counts_too(self):
        #legendary cards get shortened to their first name mid text
        out = clean_line("Jacob, the Great deals 2 damage. Jacob attacks.", "Jacob, the Great")
        assert out == "this card deals 2 damage. this card attacks."

    def test_result_is_stripped(self):
        assert clean_line("   Draw a card.   ", "X") == "Draw a card."
