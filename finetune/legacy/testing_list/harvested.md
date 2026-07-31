# Harvested false positives, for review

A v1 worksheet, kept as evidence. No script has ever read it: the verdicts below
went into the training negatives and `exam_pairs.md` by hand.

Mined 2026-07-19 by replaying the site's ranking over 1,190 cards sampled across the whole
pool and keeping every pair it scored 88+. Uses the shape-counted idf, so the Overload and
Equip collisions f3328f8 already fixes are not in here.

Mark each one. **BAD** = the model is wrong, use it as a training negative. **OK** = the match
is fine and my detector was wrong. **EXAM** = worth holding out in exam_pairs.md instead of training.

---

## A - flip detected (the whole textual difference is a meaning flip)

91 pairs. These need no judgement call about *whether* they differ,
only about whether the difference matters enough to teach.

1.  **100%**  `gain/lose`
    **Weed Strangle:** `Destroy target creature. Clash with an opponent. If you win, you gain life equal to that creature's toughness.`
    **Devour in Shadow:** `Destroy target creature. It can't be regenerated. You lose life equal to that creature's toughness.`
    verdict: OK

2.  **100%**  `opponent/you`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    **Artificer's Epiphany:** `Draw two cards. If you control no artifacts, discard a card.`
    verdict: OK

3.  **99%**  `you/opponent`
    **Tragic Lesson:** `Draw two cards. Then discard a card unless you return a land you control to its owner's hand.`
    **Grab the Prize:** `Draw two cards. If the discarded card wasn't a land card, this card deals 2 damage to each opponent.`
    verdict: OK

4.  **99%**  `you/opponent`
    **Tragic Lesson:** `Draw two cards. Then discard a card unless you return a land you control to its owner's hand.`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    verdict:  OK

5.  **99%**  `your/their`
    **Discombobulate:** `Counter target spell. Look at the top four cards of your library, then put them back in any order.`
    **Fold into Aether:** `Counter target spell. If that spell is countered this way, its controller may put a creature card from their hand onto the battlefield.`
    verdict: OK

6.  **99%**  `opponent/you`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    **Chart a Course:** `Draw two cards. Then discard a card unless you attacked this turn.`
    verdict: OK

7.  **99%**  `opponent/you`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    **Rush of Inspiration // Crackling Falls:** `Draw two cards. Then discard a card at random unless you pay {E}{E} .`
    verdict: OK

8.  **99%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Commune with the Gods:** `Reveal the top five cards of your library. You may put a creature or enchantment card from among them into your hand. Put the rest into your graveyard.`
    verdict: EXAM

9.  **99%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Benefaction of Rhonas:** `Reveal the top five cards of your library. You may put a creature card and/or an enchantment card from among them into your hand. Put the rest into your graveyard.`
    verdict: Ignore

10.  **99%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Grisly Salvage:** `Reveal the top five cards of your library. You may put a creature or land card from among them into your hand. Put the rest into your graveyard.`
    verdict: Ignore

11.  **99%**  `each/target`
    **Kyscu Drake:** `{G}: This creature gets +0/+1 until end of turn. Activate only once each turn.`
    **Questing Phelddagrif:** `{G}: This creature gets +1/+1 until end of turn. Target opponent creates a 1/1 green Hippo creature token.`
    verdict: OK

12.  **98%**  `spend/add`
    **Elfhame Druid:** `{T}: Add {G}{G}. Spend this mana only to cast kicked spells.`
    **Undermountain Adventurer:** `{T}: Add {G}{G}. If you've completed a dungeon, add six {G} instead.`
    verdict: OK

13.  **98%**  `discard/draw`
    **Tragic Lesson:** `Draw two cards. Then discard a card unless you return a land you control to its owner's hand.`
    **Spirit Water Revival:** `Draw two cards. If this spell's additional cost was paid, instead shuffle your graveyard into your library, draw seven cards, and you have no maximum hand size for the rest of the game.`
    verdict: OK

14.  **98%**  `discard/draw`
    **Tragic Lesson:** `Draw two cards. Then discard a card unless you return a land you control to its owner's hand.`
    **Secrets of the Golden City:** `Draw two cards. If you have the city's blessing, draw three cards instead.`
    verdict: OK

15.  **98%**  `creature/player`
    **Fertile Imagination:** `Choose a card type. Target opponent reveals their hand. Create two 1/1 green Saproling creature tokens for each card of the chosen type revealed this way.`
    **Blood Oath:** `Choose a card type. Target opponent reveals their hand. this card deals 3 damage to that player for each card of the chosen type revealed this way.`
    verdict: OK (reveal hand is mechanic)

16.  **98%**  `opponent/you`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    **Eureka Moment:** `Draw two cards. You may put a land card from your hand onto the battlefield.`
    verdict: OK

17.  **98%**  `opponent/you`
    **Phyrexian Espionage:** `Draw two cards. If this spell was kicked, each opponent discards a card.`
    **Secrets of the Golden City:** `Draw two cards. If you have the city's blessing, draw three cards instead.`
    verdict: OK

18.  **98%**  `player/creature`
    **Counterbore:** `Counter target spell. Search its controller's graveyard, hand, and library for all cards with the same name as that spell and exile them. Then that player shuffles.`
    **Access Denied:** `Counter target spell. Create X 1/1 colorless Thopter artifact creature tokens with flying, where X is that spell's mana value.`
    verdict: OK

19.  **98%**  `player/creature`
    **Counterbore:** `Counter target spell. Search its controller's graveyard, hand, and library for all cards with the same name as that spell and exile them. Then that player shuffles.`
    **Mystic Genesis:** `Counter target spell. Create an X/X green Ooze creature token, where X is that spell's mana value.`
    verdict: OK

20.  **97%**  `their/your`
    **Scheming Symmetry:** `Choose two target players. Each of them searches their library for a card, then shuffles and puts that card on top.`
    **The Brothers' War:** `Choose two target players. Until your next turn, each creature they control attacks the other chosen player each combat if able.`
    verdict: BAD (choose two target players isnt the mechanic)

21.  **97%**  `spend/add`
    **Qarsi Deceiver:** `{T}: Add {C}. Spend this mana only to cast a face-down creature spell, pay a mana cost to turn a manifested creature face up, or pay a morph cost.`
    **Urza's Tower:** `{T}: Add {C}. If you control an Urza's Mine and an Urza's Power-Plant, add {C}{C}{C} instead.`
    verdict: OK

22.  **97%**  `spend/add`
    **Qarsi Deceiver:** `{T}: Add {C}. Spend this mana only to cast a face-down creature spell, pay a mana cost to turn a manifested creature face up, or pay a morph cost.`
    **Tower Worker:** `{T}: Add {C}. If you control creatures named Mine Worker and Power Plant Worker, add {C}{C}{C} instead.`
    verdict: OK

23.  **96%**  `opponent/you`
    **Broken Ambitions:** `Counter target spell unless its controller pays {X}. Clash with an opponent. If you win, that spell's controller mills four cards.`
    **Silumgar's Scorn:** `Counter target spell unless its controller pays {1}. If you revealed a Dragon card or controlled a Dragon as you cast this spell, counter that spell instead.`
    verdict: OK

24.  **96%**  `bottom/top`
    **Raven Familiar:** `When this creature enters, look at the top three cards of your library. Put one of them into your hand and the rest on the bottom of your library in any order.`
    **Gurmag Nightwatch:** `When this creature enters, look at the top three cards of your library. You may put one of those cards back on top of your library. Put the rest into your graveyard.`
    verdict: Bad (while the text matches, the actual meat is different)

25.  **96%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Gather the Pack:** `Reveal the top five cards of your library. You may put a creature card from among them into your hand. Put the rest into your graveyard.`
    verdict: Bad, the mechaic is at the end of both and they are different, the before are prerequisites

26.  **96%**  `your/their`
    **Infectious Bloodlust:** `When enchanted creature dies, you may search your library for a card named this card, reveal it, put it into your hand, then shuffle.`
    **Pattern of Rebirth:** `When enchanted creature dies, that creature's controller may search their library for a creature card, put that card onto the battlefield, then shuffle.`
    verdict: BAD, this is bad because of 'named this card' vs 'creature card'

27.  **95%**  `bottom/top`
    **Sea Gate Oracle:** `When this creature enters, look at the top two cards of your library. Put one of them into your hand and the other on the bottom of your library.`
    **Gurmag Nightwatch:** `When this creature enters, look at the top three cards of your library. You may put one of those cards back on top of your library. Put the rest into your graveyard.`
    verdict: ok, part of the mechanic is the same, it shouldnt be as high?

28.  **95%**  `creature/player`
    **Izzet Chemister:** `{1}{R}, {T}, Sacrifice this creature: Cast any number of cards exiled with this creature without paying their mana costs.`
    **Magus of the Wheel:** `{1}{R}, {T}, Sacrifice this creature: Each player discards their hand, then draws seven cards.`
    verdict: Bad, very different final effects.

29.  **95%**  `opponent/you`
    **Swindler's Scheme:** `Whenever an opponent casts a spell from their hand, you may reveal the top card of your library. If it shares a card type with that spell, counter that spell and that opponent may cast the revealed card without paying its mana cost.`
    **Counterbalance:** `Whenever an opponent casts a spell, you may reveal the top card of your library. If you do, counter that spell if it has the same mana value as the revealed card.`
    verdict: Two very different effects, very similar wording so EXAM

30.  **94%**  `your/their`
    **Sauron's Ransom:** `Choose an opponent. They look at the top four cards of your library and separate them into a face-down pile and a face-up pile. Put one pile into your hand and the other into your graveyard. The Ring tempts you.`
    **Myrkul's Edict:** `Choose an opponent. That player sacrifices a creature of their choice.`
    verdict: Bad, effects are dofferemt

31.  **94%**  `you/opponent`
    **Pledge of Unity:** `Put a +1/+1 counter on each creature you control. You gain 1 life for each creature you control.`
    **Tempt with Glory:** `Put a +1/+1 counter on each creature you control. Each opponent may put a +1/+1 counter on each creature they control. For each opponent who does, put a +1/+1 counter on each creature you control.`
    verdict: Ok

32.  **94%**  `each/target`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Flamerush Rider:** `Whenever this creature attacks, create a token that's a copy of another target attacking creature and that's tapped and attacking. Exile the token at end of combat.`
    verdict: Ok

33.  **94%**  `exile/sacrifice,you/opponent`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Mardu Siegebreaker:** `Whenever this creature attacks, for each opponent, create a tapped token that's a copy of the exiled card attacking that opponent. At the beginning of your next end step, sacrifice those tokens.`
    verdict: 

34.  **94%**  `exile/sacrifice`
    **Moorland Rescuer:** `When this creature dies, return any number of other creature cards with total power X or less from your graveyard to the battlefield, where X is this creature's power. Exile this card.`
    **Rekindling Phoenix:** `When this creature dies, create a 0/1 red Elemental creature token with "At the beginning of your upkeep, sacrifice this token and return target card named this card from your graveyard to the battlefield. It gains haste until end of turn."`
    verdict: 

35.  **94%**  `you/opponent`
    **Sultai Flayer:** `Whenever a creature you control with toughness 4 or greater dies, you gain 4 life.`
    **Sangromancer:** `Whenever a creature an opponent controls dies, you may gain 3 life.`
    verdict: BAD 

36.  **94%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Glacial Revelation:** `Reveal the top six cards of your library. You may put any number of snow permanent cards from among them into your hand. Put the rest into your graveyard.`
    verdict: 

37.  **94%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Bounty of Skemfar:** `Reveal the top six cards of your library. You may put up to one land card from among them onto the battlefield tapped and up to one Elf card from among them into your hand. Put the rest on the bottom of your library in a random order.`
    verdict: 

38.  **93%**  `player/creature`
    **Guiltfeeder:** `Whenever this creature attacks and isn't blocked, defending player loses 1 life for each card in their graveyard.`
    **Delta Bloodflies:** `Whenever this creature attacks, if you control a creature with a counter on it, each opponent loses 1 life.`
    verdict: 

39.  **93%**  `exile/sacrifice`
    **Moorland Rescuer:** `When this creature dies, return any number of other creature cards with total power X or less from your graveyard to the battlefield, where X is this creature's power. Exile this card.`
    **Deathpact Angel:** `When this creature dies, create a 1/1 white and black Cleric creature token. It has "{3}{W}{B}{B}, {T}, Sacrifice this token: Return a card named this card from your graveyard to the battlefield."`
    verdict: 

40.  **93%**  `you/opponent`
    **Sultai Flayer:** `Whenever a creature you control with toughness 4 or greater dies, you gain 4 life.`
    **The Meathook Massacre:** `Whenever a creature an opponent controls dies, you gain 1 life.`
    verdict: 

41.  **93%**  `may/can't`
    **Swift Reckoning:** `If there are two or more instant and/or sorcery cards in your graveyard, you may cast this spell as though it had flash.`
    **Exquisite Firecraft:** `If there are two or more instant and/or sorcery cards in your graveyard, this spell can't be countered.`
    verdict: 

42.  **93%**  `their/your`
    **Struggle for Sanity:** `Target opponent reveals their hand. That player exiles a card from it, then you exile a card from it. Repeat this process until all cards in that hand have been exiled. That player returns the cards they exiled this way to their hand and puts the rest into their graveyard.`
    **Specter's Shriek:** `Target opponent reveals their hand. You may choose a nonland card from it. If you do, that player exiles that card. If a nonblack card is exiled this way, exile a card from your hand.`
    verdict: 

43.  **92%**  `opponent/you`
    **Teferi, Time Raveler:** `Each opponent can cast spells only any time they could cast a sorcery.`
    **Inventive Iteration // Living Breakthrough:** `Whenever you cast a spell, your opponents can't cast spells with the same mana value as that spell until your next turn.`
    verdict: 

44.  **92%**  `exile/sacrifice`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Redoubled Stormsinger:** `Whenever this creature attacks, for each creature token you control that entered this turn, create a tapped and attacking token that's a copy of that token. At the beginning of the next end step, sacrifice those tokens.`
    verdict: 

45.  **92%**  `opponent/you`
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Wakanda Forever!:** `Reveal the top six cards of your library. You may put a permanent card from among them onto the battlefield with an indestructible counter on it. You may put a permanent card from among them into your hand. Put the rest into your graveyard.`
    verdict: 

46.  **92%**  `their/your`
    **Struggle for Sanity:** `Target opponent reveals their hand. That player exiles a card from it, then you exile a card from it. Repeat this process until all cards in that hand have been exiled. That player returns the cards they exiled this way to their hand and puts the rest into their graveyard.`
    **Ego Drain:** `Target opponent reveals their hand. You choose a nonland card from it. That player discards that card. If you don't control a Faerie, exile a card from your hand.`
    verdict: 

47.  **92%**  `exile/sacrifice,player/creature,their/your`
    **Struggle for Sanity:** `Target opponent reveals their hand. That player exiles a card from it, then you exile a card from it. Repeat this process until all cards in that hand have been exiled. That player returns the cards they exiled this way to their hand and puts the rest into their graveyard.`
    **Treacherous Urge:** `Target opponent reveals their hand. You may put a creature card from it onto the battlefield under your control. That creature gains haste. Sacrifice it at the beginning of the next end step.`
    verdict: 

48.  **92%**  `player/creature`
    **Haunted Cadaver:** `Whenever this creature deals combat damage to a player, you may sacrifice it. If you do, that player discards three cards.`
    **Aspiring Champion:** `When this creature deals combat damage to a player, sacrifice it. If you do, reveal cards from the top of your library until you reveal a creature card. Put that card onto the battlefield, then shuffle the rest into your library. If that creature is a Demon, it deals damage equal to its power to each opponent.`
    verdict: 

49.  **92%**  `opponent/you`
    **Mossdog:** `Whenever this creature becomes the target of a spell or ability an opponent controls, put a +1/+1 counter on this creature.`
    **Heartfire Hero:** `Whenever this creature becomes the target of a spell or ability you control for the first time each turn, put a +1/+1 counter on it.`
    verdict: 

50.  **91%**  `opponent/you`
    **Hooded Blightfang:** `Whenever a creature you control with deathtouch attacks, each opponent loses 1 life and you gain 1 life.`
    **Revenge of Ravens:** `Whenever a creature attacks you or a planeswalker you control, that creature's controller loses 1 life and you gain 1 life.`
    verdict: 

51.  **91%**  `their/your`
    **Guiltfeeder:** `Whenever this creature attacks and isn't blocked, defending player loses 1 life for each card in their graveyard.`
    **Calculating Lich:** `Whenever a creature attacks one of your opponents, that player loses 1 life.`
    verdict: 

52.  **91%**  `creature/player`
    **Finest Hour:** `Whenever a creature you control attacks alone, if it's the first combat phase of the turn, untap that creature. After this phase, there is an additional combat phase.`
    **Scourge of the Throne:** `Whenever this creature attacks for the first time each turn, if it's attacking the player with the most life or tied for most life, untap all attacking creatures. After this phase, there is an additional combat phase.`
    verdict: 

53.  **91%**  `their/your`
    **New Frontiers:** `Each player may search their library for up to X basic land cards and put them onto the battlefield tapped. Then each player who searched their library this way shuffles.`
    **Far Wanderings:** `If there are seven or more cards in your graveyard, instead search your library for up to three basic land cards, put them onto the battlefield tapped, then shuffle.`
    verdict: 

54.  **91%**  `their/your`
    **Rising Waters:** `Lands don't untap during their controllers' untap steps.`
    **Forsaken City:** `This land doesn't untap during your untap step.`
    verdict: 

55.  **91%**  `you/opponent`
    **Lambholt Pacifist // Lambholt Butcher:** `This creature can't attack unless you control a creature with power 4 or greater.`
    **Bloodcrazed Goblin:** `This creature can't attack unless an opponent has been dealt damage this turn.`
    verdict: 

56.  **91%**  `creature/player`
    **Lambholt Pacifist // Lambholt Butcher:** `This creature can't attack unless you control a creature with power 4 or greater.`
    **Goblin Goon:** `This creature can't attack unless you control more creatures than defending player.`
    verdict: 

57.  **91%**  `player/creature`
    **Struggle for Sanity:** `Target opponent reveals their hand. That player exiles a card from it, then you exile a card from it. Repeat this process until all cards in that hand have been exiled. That player returns the cards they exiled this way to their hand and puts the rest into their graveyard.`
    **Traumatic Revelation:** `Target opponent reveals their hand. You may choose a creature or battle card from it. If you do, that player discards that card. If you don't, incubate 3.`
    verdict: 

58.  **91%**  `opponent/you,target/each`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Strength of the Coalition:** `Target creature you control gets +2/+2 until end of turn. If this spell was kicked, put a +1/+1 counter on each creature you control.`
    verdict: 

59.  **91%**  `opponent/you,target/each`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Phalanx Tactics:** `Target creature you control gets +2/+1 until end of turn. Each other creature you control gets +1/+1 until end of turn.`
    verdict: 

60.  **91%**  `you/opponent`
    **Foul Imp:** `When this creature enters, you lose 2 life.`
    **Dusk Mangler:** `When this creature enters, each opponent sacrifices a creature of their choice, discards a card, and loses 4 life.`
    verdict: 

61.  **90%**  `can't/may,opponent/you`
    **Aclazotz, Deepest Betrayal // Temple of the Dead:** `Whenever this card attacks, each opponent discards a card. For each opponent who can't, you draw a card.`
    **Veronica, Dissident Scribe:** `Whenever this card attacks, you may discard a card. If you do, draw a card.`
    verdict: 

62.  **90%**  `creature/player`
    **Finest Hour:** `Whenever a creature you control attacks alone, if it's the first combat phase of the turn, untap that creature. After this phase, there is an additional combat phase.`
    **Jangling Automaton:** `Whenever this creature attacks, untap all creatures defending player controls.`
    verdict: 

63.  **90%**  `opponent/you`
    **Haunted Library:** `Whenever a creature an opponent controls dies, you may pay {1}. If you do, create a 1/1 white Spirit creature token with flying.`
    **Ajani's Last Stand:** `Whenever a creature or planeswalker you control dies, you may sacrifice this enchantment. If you do, create a 4/4 white Avatar creature token with flying.`
    verdict: 

64.  **90%**  `can't/may`
    **Serra Avenger:** `You can't cast this card during your first, second, or third turns of the game.`
    **Haakon, Stromgald Scourge:** `You may cast this card from your graveyard, but not from anywhere else.`
    verdict: 

65.  **90%**  `exile/sacrifice`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Phantom Steed:** `Whenever this creature attacks, create a tapped and attacking token that's a copy of the exiled card, except it's an Illusion in addition to its other types. Sacrifice that token at end of combat.`
    verdict: 

66.  **90%**  `each/target`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Tilonalli's Skinshifter:** `Whenever this creature attacks, it becomes a copy of another target nonlegendary attacking creature until end of turn.`
    verdict: 

67.  **90%**  `player/creature`
    **Haunted Cadaver:** `Whenever this creature deals combat damage to a player, you may sacrifice it. If you do, that player discards three cards.`
    **Servant of the Stinger:** `Whenever this creature deals combat damage to a player, if you've committed a crime this turn, you may sacrifice this creature. If you do, search your library for a card, put it into your hand, then shuffle.`
    verdict: 

68.  **89%**  `can't/may,draw/discard,opponent/you`
    **Aclazotz, Deepest Betrayal // Temple of the Dead:** `Whenever this card attacks, each opponent discards a card. For each opponent who can't, you draw a card.`
    **Azula, Ruthless Firebender:** `Whenever this card attacks, you may discard a card. Then you get an experience counter for each player who discarded a card this turn.`
    verdict: 

69.  **89%**  `opponent/you`
    **War's Toll:** `If a creature an opponent controls attacks, all creatures that opponent controls attack if able.`
    **Viashino Bey:** `If this creature attacks, all creatures you control attack if able.`
    verdict: 

70.  **89%**  `creature/player`
    **Haunted Library:** `Whenever a creature an opponent controls dies, you may pay {1}. If you do, create a 1/1 white Spirit creature token with flying.`
    **Millicent, Restless Revenant:** `Whenever this card or another nontoken Spirit you control dies or deals combat damage to a player, create a 1/1 white Spirit creature token with flying.`
    verdict: 

71.  **89%**  `can't/may`
    **Serra Avenger:** `You can't cast this card during your first, second, or third turns of the game.`
    **Me, the Immortal:** `You may cast this card from your graveyard by discarding two cards in addition to paying its other costs.`
    verdict: 

72.  **89%**  `can't/may`
    **Serra Avenger:** `You can't cast this card during your first, second, or third turns of the game.`
    **Alien Symbiosis:** `You may cast this card from your graveyard by discarding a card in addition to paying its other costs.`
    verdict: 

73.  **89%**  `target/each`
    **Breaking of the Fellowship:** `Target creature an opponent controls deals damage equal to its power to another target creature that player controls. The Ring tempts you.`
    **Alpha Brawl:** `Target creature an opponent controls deals damage equal to its power to each other creature that player controls, then each of those creatures deals damage equal to its power to that creature.`
    verdict: 

74.  **89%**  `each/target`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Sunfrill Imitator:** `Whenever this creature attacks, you may have it become a copy of another target Dinosaur you control, except its name is this card and it has this ability.`
    verdict: 

75.  **89%**  `creature/player`
    **Mirror-Style Master:** `Whenever this creature attacks, for each attacking modified creature you control, create a tapped and attacking token that's a copy of that creature. Exile those tokens at end of combat.`
    **Nacatl War-Pride:** `Whenever this creature attacks, create X tokens that are copies of it and that are tapped and attacking, where X is the number of creatures defending player controls. Exile the tokens at the beginning of the next end step.`
    verdict: 

76.  **89%**  `your/their`
    **Vengevine:** `Whenever you cast a spell, if it's the second creature spell you cast this turn, you may return this card from your graveyard to the battlefield.`
    **Bloodbond March:** `Whenever a player casts a creature spell, each player returns all cards with the same name as that spell from their graveyard to the battlefield.`
    verdict: 

77.  **89%**  `may/can't`
    **Lu Xun, Scholar General:** `Whenever this card deals damage to an opponent, you may draw a card.`
    **Leovold, Emissary of Trest:** `Each opponent can't draw more than one card each turn.`
    verdict: 

78.  **89%**  `their/your`
    **Rising Waters:** `Lands don't untap during their controllers' untap steps.`
    **Mungha Wurm:** `You can't untap more than one land during your untap step.`
    verdict: 

79.  **89%**  `each/target`
    **Winter Sky:** `Flip a coin. If you win the flip, this card deals 1 damage to each creature and each player. If you lose the flip, each player draws a card.`
    **Odds // Ends:** `Flip a coin. If it comes up heads, counter target instant or sorcery spell. If it comes up tails, copy that spell and you may choose new targets for the copy.`
    verdict: 

80.  **89%**  `you/opponent`
    **Gladehart Cavalry:** `Whenever a creature you control with a +1/+1 counter on it dies, you gain 2 life.`
    **The Meathook Massacre:** `Whenever a creature an opponent controls dies, you gain 1 life.`
    verdict: 

81.  **89%**  `your/their`
    **Sins of the Past:** `Until end of turn, you may cast target instant or sorcery card from your graveyard without paying its mana cost. If that spell would be put into your graveyard, exile it instead. Exile this card.`
    **Arcane Heist:** `You may cast target instant or sorcery card from an opponent's graveyard without paying its mana cost. If that spell would be put into their graveyard, exile it instead.`
    verdict: 

82.  **88%**  `creature/player`
    **Hooded Blightfang:** `Whenever a creature you control with deathtouch attacks, each opponent loses 1 life and you gain 1 life.`
    **Fumulus, the Infestation:** `Whenever an Insect, Leech, Slug, or Worm you control attacks, defending player loses 1 life and you gain 1 life.`
    verdict: 

83.  **88%**  `creatures/players,player/creature`
    **Raphael, Tag Team Tough:** `Whenever this card deals combat damage to a player for the first time each turn, untap all attacking creatures. After this combat phase, there is an additional combat phase.`
    **Smoke:** `Players can't untap more than one creature during their untap steps.`
    verdict: 

84.  **88%**  `can't/may`
    **Serra Avenger:** `You can't cast this card during your first, second, or third turns of the game.`
    **Hogaak, Arisen Necropolis:** `You may cast this card from your graveyard.`
    verdict: 

85.  **88%**  `creature/player`
    **Chancellor of the Forge:** `You may reveal this card from your opening hand. If you do, at the beginning of the first upkeep, create a 1/1 red Phyrexian Goblin creature token with haste.`
    **Chancellor of the Annex:** `You may reveal this card from your opening hand. If you do, when each opponent casts their first spell of the game, counter that spell unless that player pays {1}.`
    verdict: 

86.  **88%**  `each/target`
    **Cavalry Pegasus:** `Whenever this creature attacks, each attacking Human gains flying until end of turn.`
    **Kitesail Skirmisher:** `Whenever this creature attacks, another target creature attacking the same player or planeswalker gains flying until end of turn.`
    verdict: 

87.  **88%**  `creature/player`
    **Lockjaw Snapper:** `When this creature dies, put a -1/-1 counter on each creature with a -1/-1 counter on it.`
    **Oft-Nabbed Goat:** `When this creature dies, if it had one or more -1/-1 counters on it, its owner draws that many cards and each other player loses that much life.`
    verdict: 

88.  **88%**  `opponent/you`
    **Tempt with Glory:** `Put a +1/+1 counter on each creature you control. Each opponent may put a +1/+1 counter on each creature they control. For each opponent who does, put a +1/+1 counter on each creature you control.`
    **Gideon's Battle Cry:** `Put a +1/+1 counter on each creature you control. You may search your library and/or graveyard for a card named Gideon, the Oathsworn, reveal it, and put it into your hand. If you search your library this way, shuffle.`
    verdict: 

89.  **88%**  `their/your`
    **Rising Waters:** `Lands don't untap during their controllers' untap steps.`
    **Bottomless Vault:** `You may choose not to untap this land during your untap step.`
    verdict: 

90.  **88%**  `creature/player`
    **Zektar Shrine Expedition:** `Remove three quest counters from this enchantment and sacrifice it: Create a 7/1 red Elemental creature token with trample and haste. Exile it at the beginning of the next end step.`
    **Quest for Pure Flame:** `Remove four quest counters from this enchantment and sacrifice it: If any source you control would deal damage to a permanent or player this turn, it deals double that damage to that permanent or player instead.`
    verdict: 

91.  **88%**  `player/creature`
    **Namor, Atlantean King:** `Whenever this card attacks a player who has more life than you, other creatures you control attacking that player get +2/+0 until end of turn.`
    **Wingnut, Bat on the Belfry:** `Whenever this card attacks, each other attacking creature gets +1/+0 until end of turn.`
    verdict: 

---

## B - qualifier blindness (identical opening, the trailing clause ignored)

A 45 pair sample of 537 found. The shape: both lines open identically and differ only in a
trailing restriction, and the model scores the pair on the opening alone. Riders are supposed
to be forgivable, so this is the section where a wrong call teaches the model something false.

1.  **100%**
    **Dissipate:** `Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard.`
    **Lapse of Certainty:** `Counter target spell. If that spell is countered this way, put it on top of its owner's library instead of into that player's graveyard.`
    verdict: 

2.  **100%**
    **Dissipate:** `Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard.`
    **Fold into Aether:** `Counter target spell. If that spell is countered this way, its controller may put a creature card from their hand onto the battlefield.`
    verdict: 

3.  **100%**
    **Rout:** `Destroy all creatures. They can't be regenerated.`
    **Decree of Pain:** `Destroy all creatures. They can't be regenerated. Draw a card for each creature destroyed this way.`
    verdict: 

4.  **100%**
    **Kami's Flare:** `this card deals 3 damage to target creature or planeswalker. this card also deals 2 damage to that permanent's controller if you control a modified creature.`
    **Take Out the Trash:** `this card deals 3 damage to target creature or planeswalker. If you control a Raccoon, you may discard a card. If you do, draw a card.`
    verdict: 

5.  **100%**
    **Hexgold Slash:** `this card deals 2 damage to target creature. If that creature has toxic, this card deals 4 damage to that creature instead.`
    **Blooming Blast:** `this card deals 2 damage to target creature. If the gift was promised, this card also deals 3 damage to that creature's controller.`
    verdict: 

6.  **100%**
    **Discombobulate:** `Counter target spell. Look at the top four cards of your library, then put them back in any order.`
    **Counterlash:** `Counter target spell. You may cast a spell that shares a card type with it from your hand without paying its mana cost.`
    verdict: 

7.  **100%**
    **Hexgold Slash:** `this card deals 2 damage to target creature. If that creature has toxic, this card deals 4 damage to that creature instead.`
    **Firebending Lesson:** `this card deals 2 damage to target creature. If this spell was kicked, it deals 5 damage to that creature instead.`
    verdict: 

8.  **100%**
    **Invasive Maneuvers:** `this card deals 3 damage to target creature. It deals 5 damage instead if you control a Spacecraft.`
    **Starfall:** `this card deals 3 damage to target creature. If that creature is an enchantment, this card deals 3 damage to that creature's controller.`
    verdict: 

9.  **99%**
    **Talisman of Hierarchy:** `{T}: Add {W} or {B}. This artifact deals 1 damage to you.`
    **Ballroom:** `{T}: Add {W} or {B}.`
    verdict: 

10.  **99%**
    **Invasive Maneuvers:** `this card deals 3 damage to target creature. It deals 5 damage instead if you control a Spacecraft.`
    **Draconic Roar:** `this card deals 3 damage to target creature. If you revealed a Dragon card or controlled a Dragon as you cast this spell, this card deals 3 damage to that creature's controller.`
    verdict: 

11.  **99%**
    **Chromatic Star:** `{1}, {T}, Sacrifice this artifact: Add one mana of any color.`
    **Barbed Sextant:** `{1}, {T}, Sacrifice this artifact: Add one mana of any color. Draw a card at the beginning of the next turn's upkeep.`
    verdict: 

12.  **99%**
    **Heavy Infantry:** `When this creature enters, tap target creature an opponent controls.`
    **Protocol Knight:** `When this creature enters, tap target creature an opponent controls. Put a stun counter on that creature if you control another Knight.`
    verdict: 

13.  **99%**
    **Celestial Prism:** `{2}, {T}: Add one mana of any color.`
    **Pyramid of the Pantheon:** `{2}, {T}: Add one mana of any color. Put a brick counter on this artifact.`
    verdict: 

14.  **99%**
    **Wastewood Verge:** `{T}: Add {B}. Activate only if you control a Swamp or a Forest.`
    **Elves of Deep Shadow:** `{T}: Add {B}. This creature deals 1 damage to you.`
    verdict: 

15.  **99%**
    **Talisman of Hierarchy:** `{T}: Add {W} or {B}. This artifact deals 1 damage to you.`
    **Tainted Field:** `{T}: Add {W} or {B}. Activate only if you control a Swamp.`
    verdict: 

16.  **99%**
    **Radiant Epicure:** `When this creature enters, each opponent loses X life and you gain X life, where X is the number of colors of mana spent to cast this spell.`
    **Shimmercreep:** `When this creature enters, each opponent loses X life and you gain X life, where X is the number of colors among permanents you control.`
    verdict: 

17.  **99%**
    **Tragic Lesson:** `Draw two cards. Then discard a card unless you return a land you control to its owner's hand.`
    **Inspiring Refrain:** `Draw two cards. Exile this card with three time counters on it.`
    verdict: 

18.  **99%**
    **Kami's Flare:** `this card deals 3 damage to target creature or planeswalker. this card also deals 2 damage to that permanent's controller if you control a modified creature.`
    **Dragon's Fire:** `this card deals 3 damage to target creature or planeswalker. If you revealed a Dragon card or chose a Dragon as you cast this spell, this card deals damage equal to the power of that card or creature instead.`
    verdict: 

19.  **99%**
    **Paradox Surveyor:** `When this creature enters, look at the top five cards of your library. You may reveal a land card or a card with {X} in its mana cost from among them and put it into your hand. Put the rest on the bottom of your library in a random order.`
    **Frontier Seeker:** `When this creature enters, look at the top five cards of your library. You may reveal a Mount creature card or a Plains card from among them and put it into your hand. Put the rest on the bottom of your library in a random order.`
    verdict: 

20.  **98%**
    **Exclude:** `Counter target creature spell.`
    **Geist Snatch:** `Counter target creature spell. Create a 1/1 blue Spirit creature token with flying.`
    verdict: 

21.  **98%**
    **Ezzaroot Channeler:** `{T}: You gain 2 life.`
    **Potioner's Trove:** `{T}: You gain 2 life. Activate only if you've cast an instant or sorcery spell this turn.`
    verdict: 

22.  **98%**
    **Counterbore:** `Counter target spell. Search its controller's graveyard, hand, and library for all cards with the same name as that spell and exile them. Then that player shuffles.`
    **Discombobulate:** `Counter target spell. Look at the top four cards of your library, then put them back in any order.`
    verdict: 

23.  **98%**
    **Mandate of Abaddon:** `Choose target creature you control. Destroy all creatures with power less than that creature's power.`
    **Hunter's Insight:** `Choose target creature you control. Whenever that creature deals combat damage to a player or planeswalker this turn, draw that many cards.`
    verdict: 

24.  **97%**
    **Olivia's Midnight Ambush:** `Target creature gets -2/-2 until end of turn. If it's night, that creature gets -13/-13 until end of turn instead.`
    **Crippling Fatigue:** `Target creature gets -2/-2 until end of turn.`
    verdict: 

25.  **97%**
    **Invasive Maneuvers:** `this card deals 3 damage to target creature. It deals 5 damage instead if you control a Spacecraft.`
    **Firecannon Blast:** `this card deals 3 damage to target creature.`
    verdict: 

26.  **97%**
    **Pledge of Unity:** `Put a +1/+1 counter on each creature you control. You gain 1 life for each creature you control.`
    **Now for Wrath, Now for Ruin!:** `Put a +1/+1 counter on each creature you control. They gain vigilance until end of turn. The Ring tempts you.`
    verdict: 

27.  **97%**
    **Qarsi Deceiver:** `{T}: Add {C}. Spend this mana only to cast a face-down creature spell, pay a mana cost to turn a manifested creature face up, or pay a morph cost.`
    **Strixhaven Stadium:** `{T}: Add {C}. Put a point counter on this artifact.`
    verdict: 

28.  **97%**
    **Worldsoul's Rage:** `this card deals X damage to any target. Put up to X land cards from your hand and/or graveyard onto the battlefield tapped.`
    **Banefire:** `this card deals X damage to any target.`
    verdict: 

29.  **96%**
    **Tuinvale Treefolk // Oaken Boon:** `Put two +1/+1 counters on target creature.`
    **Angelfire Ignition:** `Put two +1/+1 counters on target creature. It gains vigilance, trample, lifelink, indestructible, and haste until end of turn.`
    verdict: 

30.  **96%**
    **Death Mutation:** `Destroy target nonblack creature. It can't be regenerated. Create X 1/1 green Saproling creature tokens, where X is that creature's mana value.`
    **Dark Withering:** `Destroy target nonblack creature.`
    verdict: 

31.  **96%**
    **Waking Nightmare:** `Target player discards two cards.`
    **Haunting Hymn:** `Target player discards two cards. If you cast this spell during your main phase, that player discards four cards instead.`
    verdict: 

32.  **95%**
    **Soltari Trooper:** `Whenever this creature attacks, it gets +1/+1 until end of turn.`
    **Slimy Piper:** `Whenever this creature attacks, it gets +1/+1 until end of turn. If you control four or more creatures, it gets +2/+2 and gains indestructible until end of turn instead.`
    verdict: 

33.  **94%**
    **Haunting Hymn:** `Target player discards two cards. If you cast this spell during your main phase, that player discards four cards instead.`
    **Go Blank:** `Target player discards two cards. Then exile that player's graveyard.`
    verdict: 

34.  **94%**
    **Elfhame Druid:** `{T}: Add {G}{G}. Spend this mana only to cast kicked spells.`
    **The Great Henge:** `{T}: Add {G}{G}. You gain 2 life.`
    verdict: 

35.  **93%**
    **Magma Spray:** `this card deals 2 damage to target creature. If that creature would die this turn, exile it instead.`
    **Searing Blood:** `this card deals 2 damage to target creature. When that creature dies this turn, this card deals 3 damage to the creature's controller.`
    verdict: 

36.  **93%**
    **Cogwork Wrestler:** `When this creature enters, target creature an opponent controls gets -2/-0 until end of turn.`
    **Blitz Leech:** `When this creature enters, target creature an opponent controls gets -2/-2 until end of turn. Remove all counters from that creature.`
    verdict: 

37.  **92%**
    **Skyshroud War Beast:** `this card's power and toughness are each equal to the number of nonbasic lands the chosen player controls.`
    **Awakened Amalgam:** `this card's power and toughness are each equal to the number of differently named lands you control.`
    verdict: 

38.  **92%**
    **Plasm Capture:** `Counter target spell. At the beginning of your next first main phase, add X mana in any combination of colors, where X is that spell's mana value.`
    **Dismal Failure:** `Counter target spell. Its controller discards a card.`
    verdict: 

39.  **91%**
    **Malamet Battle Glyph:** `Choose target creature you control and target creature you don't control. If the creature you control entered this turn, put a +1/+1 counter on it. Then those creatures fight each other.`
    **Tail Swipe:** `Choose target creature you control and target creature you don't control. If you cast this spell during your main phase, the creature you control gets +1/+1 until end of turn. Then those creatures fight each other.`
    verdict: 

40.  **91%**
    **Doomed Necromancer:** `{B}, {T}, Sacrifice this creature: Return target creature card from your graveyard to the battlefield.`
    **Soulcoil Viper:** `{B}, {T}, Sacrifice this creature: Return target creature card from your graveyard to the battlefield with a finality counter on it. Activate only as a sorcery.`
    verdict: 

41.  **91%**
    **Animal Magnetism:** `Reveal the top five cards of your library. An opponent chooses a creature card from among them. Put that card onto the battlefield and the rest into your graveyard.`
    **Memories Returning:** `Reveal the top five cards of your library. Put one of them into your hand. Then choose an opponent. They put one on the bottom of your library. Then you put one into your hand. Then they put one on the bottom of your library. Put the other into your hand.`
    verdict: 

42.  **91%**
    **Psychic Pickpocket:** `When this creature enters, it connives. When it connives this way, return up to one target nonland permanent to its owner's hand.`
    **A.I.M. Scientists:** `When this creature enters, it connives.`
    verdict: 

43.  **90%**
    **Gust of Wind:** `Return target nonland permanent you don't control to its owner's hand.`
    **Johann's Stopgap:** `Return target nonland permanent to its owner's hand. Draw a card.`
    verdict: 

44.  **88%**
    **Feral Contest:** `Put a +1/+1 counter on target creature you control. Another target creature blocks it this turn if able.`
    **Teachings of the Kirin // Kirin-Touched Orochi:** `Put a +1/+1 counter on target creature you control.`
    verdict: 

45.  **88%**
    **Kiora, the Rising Tide:** `When this card enters, draw two cards, then discard two cards.`
    **Stockman, Mad Fly-entist:** `When this card enters, draw a card, then discard a card.`
    verdict: 

---

## C - my detector's own false alarms, for reference

Dropped from A automatically. "a creature an opponent controls" and "a creature you don't
control" are the same thing, and a token diff cannot see it. Listed so the filter can be
checked rather than trusted.

1.  **100%**  `opponent/you`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Savage Smash:** `Target creature you control gets +2/+2 until end of turn. It fights target creature you don't control.`

2.  **100%**  `opponent/you`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Bridgeworks Battle // Tanglespan Bridgeworks:** `Target creature you control gets +2/+2 until end of turn. It fights up to one target creature you don't control.`

3.  **98%**  `opponent/you`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Bite Down on Crime:** `Target creature you control gets +2/+0 until end of turn. It deals damage equal to its power to target creature you don't control.`

4.  **88%**  `opponent/you`
    **Wild Instincts:** `Target creature you control gets +2/+2 until end of turn. It fights target creature an opponent controls.`
    **Epic Confrontation:** `Target creature you control gets +1/+2 until end of turn. It fights target creature you don't control.`
