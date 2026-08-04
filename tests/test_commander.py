#who leads a deck when the answer is two cards. every text below is a real
#card's, including the ones that print the keyword with no reminder text, which
#is what a rule reading the reminder alone gets wrong.
#
#the pairing is used to NAME a pasted deck, so a wrong pair is a deck called
#after a card in its 99. it returns nothing rather than guess.

from app import commander_pair, partner_kind


def card(name, text="", types="Legendary Creature — Human"):
    return {"name": name, "oracle_text": text, "type_line": types}


PARTNER = "Partner (You can have two commanders if both have partner.)"
FF = "Partner—Friends forever (You can have two commanders if both have this ability.)"
DOC = "Doctor's companion (You can have two commanders if the other is the Doctor.)"
BG = "Choose a Background (You can have a Background as a second commander.)"


class TestPartnerKind:

    def test_plain_partner(self):
        assert partner_kind(card("Tymna", PARTNER)) == "partner"

    def test_a_bare_keyword_with_no_reminder_counts(self):
        #Jeska, Thrice Reborn and Tevesh Szat print exactly this, and matching
        #the reminder text alone missed them
        assert partner_kind(card("Jeska", "Partner")) == "partner"
        assert partner_kind(card("Volo", "Choose a Background")) == "choose a background"

    def test_friends_forever_is_not_partner(self):
        #it pairs only with itself, and its line contains the word Partner
        assert partner_kind(card("Cecily", FF)) == "friends forever"

    def test_partner_with_carries_the_name(self):
        got = partner_kind(card("Gorm", "Partner with Virtus the Veiled (When this "
                                        "creature enters, target player may...)"))
        assert got == "with:virtus the veiled"

    def test_partner_with_and_no_reminder(self):
        assert partner_kind(card("Rowan", "Partner with Will Kenrith")) == "with:will kenrith"

    def test_an_ordinary_legend_has_none(self):
        assert partner_kind(card("Krenko", "{T}: Create two 1/1 Goblins.")) == ""

    def test_a_word_in_the_middle_of_a_sentence_is_not_the_keyword(self):
        assert partner_kind(card("Someone", "Your partner gains 2 life.")) == ""

    def test_the_reminder_alone_catches_a_shape_nobody_has_printed(self):
        #the half that auto-matches the next mechanic of this family
        assert partner_kind(card("Future", "Crewmate (You can have two commanders "
                                           "if both have crewmate.)")) == "second commander"


class TestCommanderPair:

    def test_one_legend_is_the_commander(self):
        assert commander_pair([card("Krenko")]) == ["Krenko"]

    def test_two_partners_pair(self):
        got = commander_pair([card("Thrasios", PARTNER), card("Tymna", PARTNER)])
        assert got == ["Thrasios", "Tymna"]

    def test_partner_never_pairs_with_friends_forever(self):
        assert commander_pair([card("Tymna", PARTNER), card("Cecily", FF)]) == []

    def test_two_friends_forever_pair(self):
        assert commander_pair([card("Cecily", FF), card("Othelm", FF)]) == ["Cecily", "Othelm"]

    def test_partner_with_pairs_with_the_card_it_names(self):
        got = commander_pair([card("Gorm the Great", "Partner with Virtus the Veiled"),
                              card("Virtus the Veiled", "Partner with Gorm the Great")])
        assert got == ["Gorm the Great", "Virtus the Veiled"]

    def test_partner_with_ignores_a_mate_that_is_not_in_the_deck(self):
        assert commander_pair([card("Gorm the Great", "Partner with Virtus the Veiled"),
                               card("Krenko")]) == []

    def test_a_background_pairs_with_its_holder(self):
        got = commander_pair([card("Wilson", BG),
                              card("Guild Artisan", "Commander creatures you own have...",
                                   "Legendary Enchantment — Background")])
        assert got == ["Guild Artisan", "Wilson"]

    def test_a_third_candidate_stops_any_pair(self):
        #the failure the precons found: 15 of the 166 hold a partner pair down in
        #the 99, so a deck with a third card that could lead it is ambiguous and
        #gets no name rather than the wrong one
        assert commander_pair([
            card("Wilson", BG),
            card("Guild Artisan", "", "Legendary Enchantment — Background"),
            card("Far Traveler", "", "Legendary Enchantment — Background")]) == []
        assert commander_pair([card("Felothar"), card("Ikra Shidiqi", PARTNER),
                               card("Sidar Kondo", PARTNER)]) == []

    def test_a_doctors_companion_pairs_with_the_doctor(self):
        got = commander_pair([card("Rose Noble", DOC),
                              card("The Tenth Doctor", "", "Legendary Creature — Time Lord Doctor")])
        assert got == ["Rose Noble", "The Tenth Doctor"]

    def test_a_partner_plus_a_random_legend_is_no_pair(self):
        #the false positive worth refusing: a Tymna deck holding one other legend
        #in the 99 must not be named after both
        assert commander_pair([card("Tymna", PARTNER), card("Thalia")]) == []

    def test_three_partners_is_no_pair(self):
        assert commander_pair([card("A", PARTNER), card("B", PARTNER),
                               card("C", PARTNER)]) == []

    def test_a_pile_of_legends_answers_nothing(self):
        assert commander_pair([card("A"), card("B"), card("C")]) == []

    def test_nothing_in_the_deck_can_lead_it(self):
        assert commander_pair([]) == []
