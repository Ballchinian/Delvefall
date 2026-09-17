# Are these the right tags for this text?

The chips `exam_autotags.py` infers for cards it never saw, for a person to judge.
Read at runtime by that script's `--marks`.

## Chips

**Wrong:** lists only the chips that are wrong about what the card does. `(none)`
means every chip is right, `?` means not judged yet and the card is not scored. A chip
that is true but tagger never typed it counts as RIGHT: this file is what precision
against the community tags cannot see.

1.
    **Card:** Anya, Merciless Angel
    **Line:** `Flying`
    **Line:** `this card gets +3/+3 for each opponent whose life total is less than half their starting life total.`
    **Line:** `As long as an opponent's life total is less than half their starting life total, this card has indestructible.`
    **Chips:** evasion, gains-indestructible, life-total-matters-self
    **Wrong:** ?

2.
    **Card:** Backdraft
    **Line:** `Choose a player who cast one or more sorcery spells this turn. this card deals damage to that player equal to half the damage dealt by one of those sorcery spells this turn, rounded down.`
    **Chips:** burn-player, division, storm-count-matters, synergy-sorcery
    **Wrong:** ?

3.
    **Card:** Boom Box
    **Line:** `{6}, {T}, Sacrifice this artifact: Destroy up to one target artifact, up to one target creature, and up to one target land.`
    **Chips:** activated-ability, egg, multi-removal, multiple-targets, removal-artifact, removal-creature, removal-destroy, removal-land, spot-removal
    **Wrong:** ?

4.
    **Card:** Callaphe, Beloved of the Sea
    **Line:** `this card's power is equal to your devotion to blue.`
    **Line:** `Creatures and enchantments you control have "Spells your opponents cast that target this permanent cost {1} more to cast."`
    **Chips:** cda-power, scales-with-power, synergy-blue
    **Wrong:** ?

5.
    **Card:** Cauldron's Gift
    **Line:** `If at least three black mana was spent to cast this spell, mill four cards.`
    **Line:** `You may choose a creature card in your graveyard. If you do, return it to the battlefield with an additional +1/+1 counter on it.`
    **Chips:** color-spent-matters, gives-pp-counters, mill-self, reanimate-creature
    **Wrong:** ?

6.
    **Card:** Celestial Reunion
    **Line:** `As an additional cost to cast this spell, you may choose a creature type and behold two creatures of that type.`
    **Line:** `Search your library for a creature card with mana value X or less, reveal it, put it into your hand, then shuffle. If this spell's additional cost was paid and the revealed card is the chosen type, put that card onto the battlefield instead of putting it into your hand.`
    **Chips:** additional-cost, hate-typal-choose, tutor-creature, tutor-mv, tutor-to-battlefield, tutor-to-hand
    **Wrong:** ?

7.
    **Card:** Crimson Manticore
    **Line:** `Flying`
    **Line:** `{R}, {T}: This creature deals 1 damage to target attacking or blocking creature.`
    **Chips:** activated-ability, burn-creature, evasion, hate-attacker, hate-blocker, pinger, repeatable-crime, repeatable-removal, spot-removal
    **Wrong:** ?

8.
    **Card:** Cult Guildmage
    **Line:** `{3}{B}, {T}: Target player discards a card. Activate only as a sorcery.`
    **Line:** `{R}, {T}: This creature deals 1 damage to target opponent or planeswalker.`
    **Chips:** activated-ability, burn-planeswalker, burn-player, discard, pinger, repeatable-crime, repeatable-removal
    **Wrong:** ?

9.
    **Card:** Defiled Crypt // Cadaver Lab
    **Line:** `Whenever one or more cards leave your graveyard, create a 2/2 black Horror enchantment creature token. This ability triggers only once each turn.`
    **Line:** `When you unlock this door, return target creature card from your graveyard to your hand.`
    **Chips:** leaves-graveyard-trigger, regrowth-creature, repeatable-creature-tokens
    **Wrong:** ?

10.
    **Card:** Don't Move
    **Line:** `Destroy all tapped creatures. Until your next turn, whenever a creature becomes tapped, destroy it.`
    **Chips:** delayed-trigger, hate-tapped, removal-creature, removal-destroy
    **Wrong:** ?

11.
    **Card:** Echo Tracer
    **Line:** `Morph {2}{U} You may cast this card face down as a 2/2 creature for {3}. Turn it face up any time for its morph cost.`
    **Line:** `When this creature is turned face up, return target creature to its owner's hand.`
    **Chips:** alternative-cost, removal-bounce, removal-creature, spot-removal, turn-face-up-trigger-self
    **Wrong:** ?

12.
    **Card:** Eye of the Storm
    **Line:** `Whenever a player casts an instant or sorcery card, exile it. Then that player copies each instant or sorcery card exiled with this enchantment. For each copy, the player may cast the copy without paying its mana cost.`
    **Chips:** cast-trigger, copy-instant, copy-sorcery, demilich-effect, free-cast-another, hate-instant, hate-sorcery, synergy-instant, synergy-sorcery, theft-cast
    **Wrong:** ?

13.
    **Card:** Fast Forward
    **Line:** `This spell costs {1} less to cast for each opponent you attacked this turn.`
    **Line:** `Goad all creatures your opponents control.`
    **Chips:** discount-self, force-attacker, pseudo-fog
    **Wrong:** ?

14.
    **Card:** Floodgate
    **Line:** `Defender`
    **Line:** `When this creature has flying, sacrifice it.`
    **Line:** `When this creature leaves the battlefield, it deals damage to each nonblue creature without flying equal to half the number of Islands you control, rounded down.`
    **Chips:** burn-creature, drawback, leaves-trigger-self, sweeper, triggered-ability
    **Wrong:** ?

15.
    **Card:** Foggy Swamp Hunters
    **Line:** `As long as you've drawn two or more cards this turn, this creature has lifelink and menace.`
    **Chips:** gains-lifelink, gains-menace, repeatable-lifegain, second-draw-matters
    **Wrong:** ?

16.
    **Card:** Frontline Heroism
    **Line:** `When this enchantment enters, create a 1/1 red Soldier creature token with haste.`
    **Line:** `Whenever you cast a spell that targets only a single creature you control, create a 1/1 red Soldier creature token with haste, then copy that spell. The copy targets that token.`
    **Chips:** cast-trigger-you, enters-in-company, heroic, repeatable-creature-tokens, triggered-ability
    **Wrong:** ?

17.
    **Card:** Glassworks // Shattered Yard
    **Line:** `When you unlock this door, this Room deals 4 damage to target creature an opponent controls.`
    **Line:** `At the beginning of your end step, this Room deals 1 damage to each opponent.`
    **Chips:** burn-creature, burn-player, group-slug, pinger, spot-removal
    **Wrong:** ?

18.
    **Card:** Goblin Test Pilot
    **Line:** `Flying`
    **Line:** `{T}: This creature deals 2 damage to any target chosen at random.`
    **Chips:** activated-ability, burn-any, evasion, pinger, repeatable-crime, repeatable-removal, spot-removal
    **Wrong:** ?

19.
    **Card:** Gonti's Aether Heart
    **Line:** `Whenever this card or another artifact you control enters, you get {E}{E} .`
    **Line:** `Pay eight {E}, Exile this card: Take an extra turn after this one.`
    **Chips:** artifactfall, counter-fuel-energy, energy-generator, extra-turn, triggered-ability
    **Wrong:** ?

20.
    **Card:** Heirloom Auntie
    **Line:** `This creature enters with two -1/-1 counters on it.`
    **Line:** `Whenever another creature you control dies, surveil 1, then remove a -1/-1 counter from this creature.`
    **Chips:** gains-mm-counters, removes-mm-counters-self, surveil
    **Wrong:** ?

21.
    **Card:** Hell to Pay
    **Line:** `this card deals X damage to target creature. Create a number of tapped Treasure tokens equal to the amount of excess damage dealt to that creature this way.`
    **Chips:** burn-creature, ramp, spot-removal
    **Wrong:** ?

22.
    **Card:** Hexgold Halberd
    **Line:** `For Mirrodin!`
    **Line:** `During your turn, equipped creature has first strike and trample.`
    **Line:** `Equip {2}{R}`
    **Chips:** activated-ability, gives-first-strike, gives-trample
    **Wrong:** ?

23.
    **Card:** Horobi's Whisper
    **Line:** `If you control a Swamp, destroy target nonblack creature.`
    **Line:** `Splice onto Arcane—Exile four cards from your graveyard. As you cast an Arcane spell, you may reveal this card from your hand and pay its splice cost. If you do, add this card's effects to that spell.`
    **Chips:** removal-creature, removal-destroy, spot-removal, synergy-arcane
    **Wrong:** ?

24.
    **Card:** Intrepid Adversary
    **Line:** `Lifelink`
    **Line:** `When this creature enters, you may pay {1}{W} any number of times. When you pay this cost one or more times, put that many valor counters on this creature.`
    **Line:** `Creatures you control get +1/+1 for each valor counter on this creature.`
    **Chips:** anthem, power-boost-to-all, reflexive-trigger, repeatable-lifegain, toughness-boost-to-all
    **Wrong:** ?

25.
    **Card:** Lantern Scout
    **Line:** `Whenever this creature or another Ally you control enters, creatures you control gain lifelink until end of turn.`
    **Chips:** creaturefall, gives-lifelink, repeatable-lifegain, triggered-ability, typal-ally
    **Wrong:** ?

26.
    **Card:** Mizzix's Mastery
    **Line:** `Exile target card that's an instant or sorcery from your graveyard. For each card exiled this way, copy it, and you may cast the copy without paying its mana cost. Exile this card.`
    **Line:** `Overload {5}{R}{R}{R} You may cast this spell for its overload cost. If you do, change "target" in its text to "each."`
    **Chips:** alternative-cost, copy-instant, demilich-effect, free-cast-another, graveyard-fuel-instant, graveyard-fuel-sorcery, more-expensive-than-mv, synergy-instant, synergy-sorcery, theft-cast
    **Wrong:** ?

27.
    **Card:** Mu Yanling
    **Line:** `+2: Target creature can't be blocked this turn.`
    **Line:** `−3: Draw two cards.`
    **Line:** `−10: Tap all creatures your opponents control. You take an extra turn after this one.`
    **Chips:** activated-ability, draw-engine, extra-turn, gives-unblockable, repeatable-crime, repeatable-pure-draw, tapper-creature
    **Wrong:** ?

28.
    **Card:** Neurok Prodigy
    **Line:** `Flying`
    **Line:** `Discard an artifact card: Return this creature to its owner's hand.`
    **Chips:** activated-ability, bounce-self, discard-outlet, evasion, free-discard-outlet
    **Wrong:** ?

29.
    **Card:** Neverending Torment
    **Line:** `Search target player's library for X cards, where X is the number of cards in your hand, and exile them. Then that player shuffles.`
    **Line:** `Epic`
    **Chips:** burst-draw, copy-self, extract
    **Wrong:** ?

30.
    **Card:** Owen Grady, Raptor Trainer
    **Line:** `Partner with Blue, Loyal Raptor`
    **Line:** `{T}: Put your choice of a reach, menace, trample, or haste counter on target Dinosaur. Activate only as a sorcery.`
    **Chips:** hate-blue, synergy-blue, trample-counter, tutors-by-name
    **Wrong:** ?

31.
    **Card:** Pain Distributor
    **Line:** `Menace`
    **Line:** `Whenever a player casts their first spell each turn, they create a Treasure token.`
    **Line:** `Whenever an artifact an opponent controls is put into a graveyard from the battlefield, this creature deals 1 damage to that player.`
    **Chips:** burn-player, cast-trigger, death-trigger, death-trigger-opponent, evasion, hate-artifact, pinger, ramp, repeatable-treasures, symmetrical
    **Wrong:** ?

32.
    **Card:** Patron of the Vein
    **Line:** `Flying`
    **Line:** `When this creature enters, destroy target creature an opponent controls.`
    **Line:** `Whenever a creature an opponent controls dies, exile it and put a +1/+1 counter on each Vampire you control.`
    **Chips:** death-trigger, evasion, gives-pp-counters, removal-creature, removal-destroy, repeatable-pp-counters, spot-removal, typal-vampire
    **Wrong:** ?

33.
    **Card:** Quagmire Lamprey
    **Line:** `Whenever this creature becomes blocked by a creature, put a -1/-1 counter on that creature.`
    **Chips:** block-trigger, gives-mm-counters, hate-blocker, removal-toughness, repeatable-removal, spot-removal
    **Wrong:** ?

34.
    **Card:** Random Encounter
    **Line:** `Shuffle your library, then mill four cards. Put each creature card milled this way onto the battlefield. They gain haste. At the beginning of the next end step, return those creatures to their owner's hand.`
    **Line:** `Flashback {6}{R}{R} You may cast this card from your graveyard for its flashback cost. Then exile it.`
    **Chips:** alternative-cost, castable-from-graveyard, delayed-trigger, exile-self, gives-haste, more-expensive-than-mv
    **Wrong:** ?

35.
    **Card:** Repel the Vile
    **Line:** `Choose one —`
    **Line:** `• Exile target creature with power 4 or greater.`
    **Line:** `• Exile target enchantment.`
    **Chips:** hate-high-pt, modal, removal-creature, removal-enchantment, removal-exile, spot-removal
    **Wrong:** ?

36.
    **Card:** Sacred Boon
    **Line:** `Prevent the next 3 damage that would be dealt to target creature this turn. At the beginning of the next end step, put a +0/+1 counter on that creature for each 1 damage prevented this way.`
    **Chips:** combat-trick, damage-prevention, delayed-trigger, gives-pp-counters, vigor-effect
    **Wrong:** ?

37.
    **Card:** Sculptor of Winter
    **Line:** `{T}: Untap target snow land.`
    **Chips:** activated-ability, mana-dork, repeatable-crime, synergy-snow, untapper-land
    **Wrong:** ?

38.
    **Card:** Shadowed Caravel
    **Line:** `Whenever a creature you control explores, put a +1/+1 counter on this Vehicle.`
    **Line:** `Crew 2`
    **Chips:** crew, gains-pp-counters, repeatable-pp-counters, triggered-ability
    **Wrong:** ?

39.
    **Card:** Shifting Sky
    **Line:** `As this enchantment enters, choose a color.`
    **Line:** `All nonland permanents are the chosen color.`
    **Chips:** hate-color-choose, removal-nonland, symmetrical
    **Wrong:** ?

40.
    **Card:** Skull Catapult
    **Line:** `{1}, {T}, Sacrifice a creature: This artifact deals 2 damage to any target.`
    **Chips:** activated-ability, bombard, burn-any, pinger, repeatable-crime, repeatable-removal, repeatable-sacrifice-outlet, sacrifice-outlet-creature, spot-removal
    **Wrong:** ?

41.
    **Card:** Spikeshell Harrier
    **Line:** `When this creature enters, return target creature or Vehicle an opponent controls to its owner's hand. If that opponent's speed is greater than each other player's speed, reduce that opponent's speed by 1. This effect can't reduce their speed below 1.`
    **Chips:** man-o-war, spot-removal, triggered-ability
    **Wrong:** ?

42.
    **Card:** Stabilizer
    **Line:** `Players can't cycle cards.`
    **Chips:** prevent-cast, symmetrical, synergy-cycling
    **Wrong:** ?

43.
    **Card:** Strands of Night
    **Line:** `{B}{B}, Pay 2 life, Sacrifice a Swamp: Return target creature card from your graveyard to the battlefield.`
    **Chips:** activated-ability, life-payment, reanimate-creature, recycle, repeatable-sacrifice-outlet, sacrifice-outlet-creature, sacrifice-outlet-land, synergy-swamp
    **Wrong:** ?

44.
    **Card:** Strength of Lunacy
    **Line:** `Enchant creature`
    **Line:** `Enchanted creature gets +2/+1 and has protection from white.`
    **Line:** `Madness {B} If you discard this card, discard it into exile. When you do, cast it for its madness cost or put it into your graveyard.`
    **Chips:** alternative-cost, french-vanilla-aura, gives-protection, hate-discard, hate-white, madness
    **Wrong:** ?

45.
    **Card:** Tel-Jilad Defiance
    **Line:** `Target creature gains protection from artifacts until end of turn.`
    **Line:** `Draw a card.`
    **Chips:** cantrip, combat-trick, gives-protection, gives-unblockable, hate-artifact, protects-creature
    **Wrong:** ?

46.
    **Card:** The Blue Spirit
    **Line:** `You may cast the first creature spell you cast each turn as though it had flash.`
    **Line:** `Whenever a nontoken creature you control enters during combat, draw a card.`
    **Chips:** creaturefall, draw-engine, gives-flash, repeatable-pure-draw, triggered-ability
    **Wrong:** ?

47.
    **Card:** Underworld Hermit
    **Line:** `When this creature enters, create a number of 1/1 green Squirrel creature tokens equal to your devotion to black.`
    **Chips:** enters-in-company, synergy-black, triggered-ability
    **Wrong:** ?

48.
    **Card:** Virtue's Ruin
    **Line:** `Destroy all white creatures.`
    **Chips:** hate-white, removal-creature, removal-destroy, single-minded-color-hate, sweeper
    **Wrong:** ?

49.
    **Card:** Wolf Strike
    **Line:** `Target creature you control gets +2/+0 until end of turn if it's night. Then it deals damage equal to its power to target creature you don't control.`
    **Chips:** combat-trick, multiple-targets, one-sided-fight, spot-removal
    **Wrong:** ?

50.
    **Card:** Zerapa Minotaur
    **Line:** `First strike`
    **Line:** `{2}: This creature loses first strike until end of turn. Any player may activate this ability.`
    **Chips:** activated-ability, any-player-ability
    **Wrong:** ?
