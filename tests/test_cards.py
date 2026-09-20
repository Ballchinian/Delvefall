#the line cleaner, the most load bearing pure function in the repo: the ingest
#embeds what it returns and the line picker looks lines up by it, so a change
#nobody notices is a search that quietly stops matching its own pages.
#check_sync.py guards the web/ copy against drifting from this one, but cannot
#say whether either is still RIGHT.
#
#the em dashes in the data are real: scryfall prints them, and reading them is
#the cleaner's job

from common.cards import (REMINDER_KEYWORDS, can_command, clean_line, get_text,
                          keep_card, reminder_is_the_rule, split_lines)


class TestCanCommand:
    #who can lead a deck, which stopped being "legendary creature" in 2025. every
    #shape below is a real card, and the whole rule was checked against scryfall's
    #own is:commander over all 4226 legendary cards: it agrees bar Grist, below.
    #
    #the ingest is the only side that can answer this, the printed power not being
    #a column on the cards table

    def legend(self, types, **kw):
        return dict({"type_line": types, "oracle_text": ""}, **kw)

    def test_a_legendary_creature_still_leads(self):
        assert can_command(self.legend("Legendary Creature — Elf Warrior", power="1"))

    def test_a_plain_legend_with_no_body_cannot(self):
        #Legendary Artifact, no printed power, says nothing: The Eternity Elevator
        assert not can_command(self.legend("Legendary Artifact — Spacecraft"))

    def test_a_spacecraft_with_a_printed_power_can(self):
        #the user visible bug: 7 of the 8 legendary spacecraft are commanders,
        #and only the printed power tells them from the one that is not
        assert can_command(self.legend("Legendary Artifact — Spacecraft",
                                       power="4", toughness="5"))

    def test_a_legendary_vehicle_can(self):
        assert can_command(self.legend("Legendary Artifact — Vehicle",
                                       power="4", toughness="4"))

    def test_a_planeswalker_that_says_so_can(self):
        assert can_command(self.legend(
            "Legendary Planeswalker — Freyalise",
            oracle_text="Freyalise, Llanowar's Fury can be your commander."))

    def test_a_planeswalker_that_does_not_say_so_cannot(self):
        assert not can_command(self.legend("Legendary Planeswalker — Jace"))

    def test_a_background_can(self):
        #only ever half of a pair, and still a commander
        assert can_command(self.legend("Legendary Enchantment — Background"))

    def test_a_nonlegendary_card_never_can(self):
        assert not can_command(self.legend("Creature — Elf Warrior", power="1"))
        assert not can_command(self.legend("Artifact — Vehicle", power="4"))

    def test_the_front_face_decides(self):
        #Akki Lavarunner // Tok-Tok, Volcano Born. the back being legendary is
        #nothing to do with who can lead a deck, and a rule reading the whole
        #type line makes 44 cards commanders that are not
        card = {"type_line": "Creature — Goblin Warrior // Legendary Creature — Goblin Spirit",
                "card_faces": [{"type_line": "Creature — Goblin Warrior", "power": "1",
                                "oracle_text": "Haste"},
                               {"type_line": "Legendary Creature — Goblin Spirit",
                                "power": "2", "oracle_text": "Protection from red"}]}
        assert not can_command(card)

    def test_a_legendary_front_face_still_leads(self):
        card = {"type_line": "Legendary Creature — Human // Legendary Planeswalker",
                "card_faces": [{"type_line": "Legendary Creature — Human", "power": "2",
                                "oracle_text": ""},
                               {"type_line": "Legendary Planeswalker", "oracle_text": ""}]}
        assert can_command(card)

    def test_grist_is_the_known_miss(self):
        #a creature in every zone except the battlefield, said in words no
        #predicate should try to read. one card in the whole pool, and the deck
        #picker is a shortcut rather than a gate, so it is typed by hand instead
        assert not can_command(self.legend(
            "Legendary Planeswalker — Grist",
            oracle_text="As long as Grist, the Hunger Tide isn't on the "
                        "battlefield, it's a 1/1 Insect creature."))


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
        #letters and spaces alone cannot be told from a keyword list, so prose led
        #by a listed keyword answers true. it costs nothing where it is reached,
        #since all clean_line does with a true is keep the text inside parens and
        #a line with no parens comes out the same either way. the second half
        #asserts that, and is the test that should fail if it stops holding
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

    def test_no_name_leaves_the_line_alone(self):
        #"".split(" // ") is [""], and replacing the empty string inserts at
        #every position. no stored card reaches this, but /custom's name field
        #is optional and a visitor leaving it blank must not turn "Flying" into
        #"this cardFthis cardlthis card..."
        assert clean_line("Flying", "") == "Flying"
        assert clean_line("Shivan Dragon deals 2 damage.", "") == \
            "Shivan Dragon deals 2 damage."


class TestSplitLines:
    #split_lines picks the name clean_line strips, and on a two faced card that
    #name is both halves joined by " // ", which neither face ever prints. the
    #splitting happens inside clean_line rather than here, which is what keeps
    #the web app's build_lines saying the same thing off a row that stores only
    #the joined name

    def faced(self, name, *faces):
        return {"name": name,
                "card_faces": [{"name": n, "oracle_text": t} for n, t in faces]}

    def test_a_single_faced_card_loses_its_name(self):
        card = {"name": "Lightning Bolt",
                "oracle_text": "Lightning Bolt deals 3 damage to any target."}
        assert split_lines(card) == [("this card deals 3 damage to any target.", 0)]

    def test_an_adventure_half_loses_its_own_name(self):
        card = self.faced("Bonecrusher Giant // Stomp",
                          ("Bonecrusher Giant", "Trample"),
                          ("Stomp", "Stomp deals 2 damage to any target."))
        assert split_lines(card) == [("Trample", 0),
                                     ("this card deals 2 damage to any target.", 1)]

    def test_a_split_card_cleans_each_half_against_its_own_name(self):
        #Turn // Burn, both halves at once. the joined name appears in neither,
        #so without the split Burn keeps its own and stops matching the three
        #damage burn spells printing the sentence it copies. the fuse line rides
        #on both faces.
        #
        #"Until end of turn" survives the Turn half only because the replace is
        #case sensitive, which is the thin part of stripping both halves off
        #every line rather than each half off its own
        card = self.faced(
            "Turn // Burn",
            ("Turn", "Until end of turn, target creature loses all abilities and becomes "
                     "a red Weird with base power and toughness 0/1.\n"
                     "Fuse (You may cast one or both halves of this card from your hand.)"),
            ("Burn", "Burn deals 2 damage to any target.\n"
                     "Fuse (You may cast one or both halves of this card from your hand.)"))
        assert split_lines(card) == [
            ("Until end of turn, target creature loses all abilities and becomes "
             "a red Weird with base power and toughness 0/1.", 0),
            ("Fuse", 0),
            ("this card deals 2 damage to any target.", 1),
            ("Fuse", 1)]

    def test_a_name_holding_slashes_is_not_two_faces(self):
        #SP//dr, Piloted by Peni is the one card carrying the slashes in its own
        #name, and it has a single face. clean_line splits on " // " WITH the
        #spaces for exactly this card: split on bare slashes it reads as two
        #faces and cuts the name in half, leaving "this card//this card enters"
        card = {"name": "SP//dr, Piloted by Peni",
                "oracle_text": "Vigilance\n"
                               "When SP//dr enters, put a +1/+1 counter on target creature."}
        assert split_lines(card) == [
            ("Vigilance", 0),
            ("When this card enters, put a +1/+1 counter on target creature.", 0)]

    def test_a_line_that_cleans_down_to_nothing_is_dropped(self):
        #a reminder only line leaves an empty string, and the three character
        #floor is what keeps it out of the lines table
        card = {"name": "Bird",
                "oracle_text": "Flying\n(You may cast this any time you could cast an "
                               "instant.)\nDraw a card."}
        assert split_lines(card) == [("Flying", 0), ("Draw a card.", 0)]


class TestThePickerAsksForWhatTheIngestStored:
    #both sides key on the cleaned text: the ingest writes it to lines.line_text
    #and build_lines recomputes it to find the row behind a clicked line. a name
    #one side strips and the other keeps is a line nobody can select.
    #
    #check_sync.py compares the two clean_line copies, but split_lines lives only
    #in common/ and build_lines only in web/, so this is what holds the pair of
    #them together

    def card(self):
        return {"name": "Turn // Burn",
                "card_faces": [
                    {"name": "Turn",
                     "oracle_text": "Until end of turn, target creature loses all abilities "
                                    "and becomes a red Weird with base power and toughness 0/1."},
                    {"name": "Burn", "oracle_text": "Burn deals 2 damage to any target."}]}

    def both_sides(self, card):
        #imported here and not at the top of the file: app is the whole flask
        #app, and at module scope one bad import inside it takes every clean_line
        #test above down with it as a collection error rather than one failure.
        #conftest's stub stands in for the pool, so this costs no database
        import app

        #the ingest reads the faces. the web app reads cards.oracle_text, which
        #is get_text's join of those same faces, so it never sees a face name
        stored = [text for text, face in split_lines(card)]
        page = {"name": card["name"], "oracle_text": get_text(card)}
        _, asked = app.build_lines(page, set(range(len(page["oracle_text"].split("\n")))))
        return stored, asked

    def test_a_split_card_cleans_the_same_on_both_sides(self):
        stored, asked = self.both_sides(self.card())
        assert asked == stored


class TestKeepCard:
    #the other gatekeeper: what reaches the cards table at all. only the digital
    #branch is pinned here, because it is the one that reads like a redundant
    #condition and is not. the layout, joke set and missing id branches say what
    #they do on the line

    def printing(self, **kw):
        return dict({"oracle_id": "abc", "oracle_text": "Draw a card.",
                     "set_type": "expansion", "layout": "normal"}, **kw)

    def test_a_digital_printing_of_a_paper_card_is_kept(self):
        #scryfall represents Ancestral Recall with a vintage masters printing,
        #an mtgo set, so the card arrives flagged digital. the vintage check is
        #the only thing separating it from an arena card, and dropping every
        #digital printing takes the power nine off the site
        assert keep_card(self.printing(digital=True, set_type="masters",
                                       legalities={"vintage": "restricted"}))

    def test_an_arena_only_card_drops(self):
        #Davriel, Soul Broker. never printed on paper, so nothing in vintage
        assert not keep_card(self.printing(digital=True, set_type="draft_innovation",
                                           legalities={"vintage": "not_legal"}))

    def test_a_digital_card_with_no_legalities_at_all_drops(self):
        #the default is not_legal rather than a KeyError, so a bulk row missing
        #the field fails closed
        assert not keep_card(self.printing(digital=True, legalities={}))

    def test_a_null_legalities_block_fails_closed_too(self):
        #the shape the default above cannot answer: the key PRESENT holding
        #null, which .get hands back as None rather than as the {}. the ingest
        #loop in update.py has nothing around it, so one AttributeError here is
        #the whole nightly run and the site keeps yesterday's prices
        assert not keep_card(self.printing(digital=True, legalities=None))

    def test_a_card_with_no_rules_text_has_nothing_to_compare(self):
        #vanilla creatures and basic lands. the whole site is line similarity,
        #so a card with no lines is a page that can never match anything
        assert not keep_card(self.printing(oracle_text=""))
        assert not keep_card(self.printing(oracle_text="   "))
