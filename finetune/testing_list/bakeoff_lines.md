# The line similarity exam

v1's exam, still run against v2 as a regression guard. Read at runtime by `bakeoff_lines.py`.

Every negative is a *hard* negative on purpose: it shares surface wording with the anchor but means something else. A candidate card carries every line the engine would see for it, joined with `+`, and its best matching line is the one that counts.

## Triplets

Passes when the anchor lands closer to the Match than to the NOT.

1.
    **Test:** loot vs rummage
    **Anchor:** Merfolk Looter - `{T}: Draw a card, then discard a card.`
    **Match:** Careful Study - `Draw two cards, then discard two cards.`
    **NOT:** Rummaging Goblin - `{T}, Discard a card: Draw a card.`
    *Same three verbs, opposite order. Looting (draw first) vs rummaging (discard first).*

2.
    **Test:** loot vs cost-discard
    **Anchor:** Frantic Search - `Draw two cards, then discard two cards. Untap up to three lands.`
    **Match:** Merfolk Looter - `{T}: Draw a card, then discard a card.`
    **NOT:** Cathartic Reunion - `As an additional cost to cast this spell, discard two cards.` + `Draw three cards.`
    *Discard-as-cost-before-drawing is rummaging in disguise.*

3.
    **Test:** tap vs untap
    **Anchor:** Pressure Point - `Tap target creature.`
    **Match:** Frost Breath - `Tap up to two target creatures. Those creatures don't untap during their controller's next untap step.`
    **NOT:** Refocus - `Untap target creature.` + `Draw a card.`
    *Anchor and negative differ by two letters. (Both cards also have a separate `Draw a card.` line - the site embeds lines separately, so the test is the tap/untap line.)*

4.
    **Test:** dies vs enters
    **Anchor:** Blood Artist - `Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.`
    **Match:** Zulaport Cutthroat - `Whenever this creature or another creature you control dies, each opponent loses 1 life and you gain 1 life.`
    **NOT:** Soul Warden - `Whenever another creature enters, you gain 1 life.`
    *Dies vs enters. Both are "creature event → 1 life" on the surface.*

5.
    **Test:** yours vs theirs
    **Anchor:** Soul Warden - `Whenever another creature enters, you gain 1 life.`
    **Match:** Ajani's Welcome - `Whenever a creature you control enters, you gain 1 life.`
    **NOT:** Blood Seeker - `Whenever a creature an opponent controls enters, you may have that player lose 1 life.`
    *Subject flip: whose creatures, and gain vs drain.*

6.
    **Test:** hand vs battlefield
    **Anchor:** Raise Dead - `Return target creature card from your graveyard to your hand.`
    **Match:** Gravedigger - `When this creature enters, you may return target creature card from your graveyard to your hand.`
    **NOT:** Zombify - `Return target creature card from your graveyard to the battlefield.`
    *One word (hand/battlefield) separates a common from a reanimation staple.*

7.
    **Test:** reanimate reworded
    **Anchor:** Zombify - `Return target creature card from your graveyard to the battlefield.`
    **Match:** Reanimate - `Put target creature card from a graveyard onto the battlefield under your control. You lose life equal to that card's mana value.`
    **NOT:** Raise Dead - `Return target creature card from your graveyard to your hand.`
    *The positive uses different verbs ("put... onto") - function over phrasing.*

8.
    **Test:** bounce vs blink
    **Anchor:** Unsummon - `Return target creature to its owner's hand.`
    **Match:** Vapor Snag - `Return target creature to its owner's hand. Its controller loses 1 life.`
    **NOT:** Cloudshift - `Exile target creature you control, then return that card to the battlefield under your control.`
    *"Return target creature" appears in both, but blink is a completely different mechanic.*

9.
    **Test:** ramp vs tutor
    **Anchor:** Rampant Growth - `Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    **Match:** Nature's Lore - `Search your library for a Forest card, put that card onto the battlefield, then shuffle.`
    **NOT:** Diabolic Tutor - `Search your library for a card, put that card into your hand, then shuffle.`
    *Identical shell, but one ramps while the other tutors.*

10.
    **Test:** spell vs ability counter
    **Anchor:** Cancel - `Counter target spell.`
    **Match:** Mana Leak - `Counter target spell unless its controller pays {3}.`
    **NOT:** Stifle - `Counter target activated or triggered ability. (Mana abilities can't be targeted.)`
    *"Counter target" shell; Stifle can't touch spells.*

11.
    **Test:** narrow counter
    **Anchor:** Dismiss - `Counter target spell.`
    **Match:** Exclude - `Counter target creature spell.` + `Draw a card.`
    **NOT:** Stifle - `Counter target activated or triggered ability. (Mana abilities can't be targeted.)`
    *Scope-narrowed counter is still a spell counter; abilities are different.*

12.
    **Test:** rhystic punisher
    **Anchor:** Rhystic Study - `Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.`
    **Match:** Mystic Remora - `Cumulative upkeep {1} (At the beginning of your upkeep, put an age counter on this permanent, then sacrifice it unless you pay its upkeep cost for each age counter on it.)` + `Whenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.`
    **NOT:** Forced Fruition - `Whenever an opponent casts a spell, that player draws seven cards.`
    *Different trigger and payoff despite sharing a tax mechanic.*

13.
    **Test:** numbers vs verbs
    **Anchor:** Divination - `Draw two cards.`
    **Match:** Concentrate - `Draw three cards.`
    **NOT:** Mind Rot - `Target player discards two cards.`
    *The shared verb matters more than the shared number.*

14.
    **Test:** one vs all
    **Anchor:** Murder - `Destroy target creature.`
    **Match:** Hero's Downfall - `Destroy target creature or planeswalker.`
    **NOT:** Day of Judgment - `Destroy all creatures.`
    *Spot removal versus board wipe.*

15.
    **Test:** counter polarity
    **Anchor:** Battlegrowth - `Put a +1/+1 counter on target creature.`
    **Match:** Increasing Savagery - `Put five +1/+1 counters on target creature. If this spell was cast from a graveyard, put ten +1/+1 counters on that creature instead.`
    **NOT:** Grim Affliction - `Put a -1/-1 counter on target creature, then proliferate. (Choose any number of permanents and/or players, then give each another counter of each kind already there.)`
    *A single sign flips the mechanic from buffing to weakening.*

16.
    **Test:** hug vs punish
    **Anchor:** Howling Mine - `At the beginning of each player's draw step, if this artifact is untapped, that player draws an additional card.`
    **Match:** Font of Mythos - `At the beginning of each player's draw step, that player draws two additional cards.`
    **NOT:** Underworld Dreams - `Whenever an opponent draws a card, this enchantment deals 1 damage to that player.`
    *Both mention opponents drawing; one rewards it, one punishes it.*

17.
    **Test:** mill vs draw
    **Anchor:** Glimpse the Unthinkable - `Target player mills ten cards.`
    **Match:** Tome Scour - `Target player mills five cards.`
    **NOT:** Concentrate - `Draw three cards.`
    *Putting cards into the graveyard isn't drawing cards.*

18.
    **Test:** sac payload (freebie)
    **Anchor:** Village Rites - `Draw two cards.`
    **Match:** Altar's Reap - `Draw two cards.`
    **NOT:** Bone Splinters - `Destroy target creature.`
    *The sacrifice cost is identical; only the payoff distinguishes them.*

19.
    **Test:** block vs attack
    **Anchor:** Bedlam - `Creatures can't block.`
    **Match:** Falter - `Creatures without flying can't block this turn.`
    **NOT:** Peacekeeper - `At the beginning of your upkeep, sacrifice this creature unless you pay {1}{W}.` + `Creatures can't attack.`
    *Attack/block one-word flip. The match adds a duration and a flying carve-out but keeps the mechanism.*

20.
    **Test:** hexproof vs shroud (domain)
    **Anchor:** Slippery Bogle - `Hexproof (This creature can't be the target of spells or abilities your opponents control.)`
    **Match:** Deadly Insect - `Shroud (This creature can't be the target of spells or abilities.)`
    **NOT:** Boggart Brute - `Menace (This creature can't be blocked except by two or more creatures.)`
    *Reminder text gets stripped by the cleaner, so these embed as single bare words. Tests if fine-tuning has worked.*

21.
    **Test:** doubling domains
    **Anchor:** Parallel Lives - `If an effect would create one or more tokens under your control, it creates twice that many of those tokens instead.`
    **Match:** Mondrak, Glory Dominus - `If one or more tokens would be created under your control, twice that many of those tokens are created instead.`
    **NOT:** Dictate of the Twin Gods - `Flash` + `If a source would deal damage to a permanent or player, it deals double that damage to that permanent or player instead.`
    *All three share the "if X would happen, twice/double instead" shell; the match is a rewording (function over phrasing), the negative doubles damage, not tokens.*

22.
    **Test:** extra vs end turn
    **Anchor:** Time Warp - `Target player takes an extra turn after this one.`
    **Match:** Temporal Manipulation - `Take an extra turn after this one.`
    **NOT:** Time Stop - `End the turn. (Exile all spells and abilities, including this spell. The player whose turn it is discards down to their maximum hand size. Damage heals and "this turn" and "until end of turn" effects end.)`
    *Opposite directions of time manipulation, also tests behavior on very short lines.*

23.
    **Test:** retrieve vs grave hate
    **Anchor:** Regrowth - `Return target card from your graveyard to your hand.`
    **Match:** Eternal Witness - `When this creature enters, you may return target card from your graveyard to your hand.`
    **NOT:** Coffin Purge - `Exile target card from a graveyard.` + `Flashback {B} (You may cast this card from your graveyard for its flashback cost. Then exile it.)`
    *Getting a card back vs deleting it; "target card ... graveyard" shared.*

24.
    **Test:** counter vs uncounterable
    **Anchor:** Counterspell - `Counter target spell.`
    **Match:** Negate - `Counter target noncreature spell.`
    **NOT:** Prowling Serpopard - `This spell can't be countered.` + `Creature spells you control can't be countered.`
    *Maximum word overlap ("counter", "spell"), opposite sides of the mechanic.*

25.
    **Test:** fog vs anti-fog
    **Anchor:** Fog - `Prevent all combat damage that would be dealt this turn.`
    **Match:** Ethereal Haze - `Prevent all damage that would be dealt by creatures this turn.`
    **NOT:** Skullcrack - `Players can't gain life this turn. Damage can't be prevented this turn. Skullcrack deals 3 damage to target player or planeswalker.`
    *"Damage prevented" appears on both sides. Also exercises the name substitution path.*

26.
    **Test:** enemy vs self discard
    **Anchor:** Mind Rot - `Target player discards two cards.`
    **Match:** Hymn to Tourach - `Target player discards two cards at random.`
    **NOT:** Careful Study - `Draw two cards, then discard two cards.`
    *"Discard two cards" appears in all three; forced discard and self-discard should not be conflated.*

27.
    **Test:** flavour prefix trap
    **Anchor:** Farideh's Fireball - `1—9 | Farideh's Fireball deals 2 damage to each player.`
    **Match:** Flame Rift - `Flame Rift deals 4 damage to each player.`
    **NOT:** Thunderwave - `Roll a d20.` + `1—9 | Thunderwave deals 3 damage to each creature.` + `10—19 | You may choose a creature. Thunderwave deals 3 damage to each creature not chosen this way.` + `20 | Thunderwave deals 6 damage to each creature your opponents control.`
    *The `1—9 |` die-roll prefix is flavour, it should not overpower the text after but some relevence should be kept.*

28.
    **Test:** mana colour is payload
    **Anchor:** Sol Ring - `{T}: Add {C}{C}.`
    **Match:** Mind Stone - `{T}: Add {C}.` + `{1}, {T}, Sacrifice this artifact: Draw a card.`
    **NOT:** Ulvenwald Captive // Ulvenwald Abomination - `{T}: Add {G}.` + `Defender` + `{5}{G}{G}: Transform this creature.`
    *Ruling: for a mana ability the mana produced is the payload - {G} vs {C} decides which decks the card works in.*

29.
    **Test:** protection plus haste
    **Anchor:** Swiftfoot Boots - `Equipped creature has hexproof and haste. (It can't be the target of spells or abilities your opponents control. It can attack and {T} no matter when it came under your control.)`
    **Match:** Lightning Greaves - `Equipped creature has haste and shroud. (It can't be the target of spells or abilities.)` + `Equip {0}`
    **NOT:** Ring of Valkas - `Equipped creature has haste. (It can attack and {T} no matter when it came under your control.)` + `At the beginning of your upkeep, put a +1/+1 counter on equipped creature if it's red.` + `Equip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)`
    *Hexproof ≈ shroud, so the match shares both halves of the anchor with the keyword order flipped; the negative shares the shell and one keyword but misses the protection half entirely.*

30.
    **Test:** all your spells vs this spell
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    **NOT:** Fierce Guardianship - `If you control a commander, you may cast this spell without paying its mana cost.` + `Counter target noncreature spell.`
    *Permission vs restriction: "you may cast without paying" grants freedom, "you can't spend mana" takes an option away and demands another payment path.*

31.
    **Test:** may vs can't
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    **NOT:** Hogaak, Arisen Necropolis - `You can't spend mana to cast this spell.` + `You may cast this card from your graveyard.` + `Convoke, delve (Each creature you tap while casting this spell pays for {1} or one mana of that creature's color. Each card you exile from your graveyard pays for {1}.)` + `Trample`
    *Permission vs restriction: "you may cast without paying" grants freedom, "you can't spend mana" takes an option away and demands another payment path.*

## Judged, not scored

Reasoned through and never promoted into the scored list, so the headline stays comparable with the runs recorded in the README. Promote one by moving it up into Triplets.

1.
    **Anchor:** Rhystic Study - `Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.`
    **Match:** Mystic Remora - `Whenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.`
    **NOT:** Forced Fruition - `Whenever an opponent casts a spell, that player draws seven cards.`
    *Same trigger and tax structure, opposite beneficiary.*

2.
    **Anchor:** Lightning Bolt - `Lightning Bolt deals 3 damage to any target.`
    **Match:** Acorn Catapult - `{1}, {T}: This artifact deals 1 damage to any target. That permanent's controller or that player creates a 1/1 green Squirrel creature token.`
    **NOT:** Murder - `Destroy target creature.`
    *Both positives deal damage despite different wording; direct damage is distinct from destroy effects.*

3.
    **Anchor:** Swords to Plowshares - `Exile target creature. Its controller gains life equal to its power.`
    **Match:** Path to Exile - `Exile target creature. Its controller may search their library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    **NOT:** Murder - `Destroy target creature.`
    *Same cheap exile removal with different drawback riders.*

4.
    **Anchor:** Raise the Alarm - `Create two 1/1 white Soldier creature tokens.`
    **Match:** Dragon Fodder - `Create two 1/1 red Goblin creature tokens.`
    **NOT:** Parallel Lives - `If an effect would create one or more tokens under your control, it creates twice that many of those tokens instead.`
    *Color and creature type change, but both create two small creature tokens. Should appear above generic token cases*

5.
    **Anchor:** Rhystic Study - `Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.`
    **Match:** Mystic Remora - `Whenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.`
    **NOT:** Smothering Tithe - `Whenever an opponent draws a card, that player may pay {2}. If the player doesn't, you create a Treasure token.`
    *Different trigger and payoff despite sharing a tax mechanic.*

6.
    **Anchor:** Phyrexian Vault - `{2}, {T}, Sacrifice a creature: Draw a card.`
    **Match:** Village Rites - `As an additional cost to cast this spell, sacrifice a creature.` + `Draw two cards.`
    **NOT:** Grim Haruspex - `Whenever another nontoken creature you control dies, draw a card.`
    *Sacrifice as an activation cost and sacrifice as a casting cost are the same move (you choose to trade a creature for cards). A death trigger is another method altogether: dying is not sacrificing. In deckbuilding this matters - these cards are synergistic (a sac outlet feeds the death trigger) but not similar, and a search for one should not surface the other.*

7.
    **Anchor:** Llanowar Elves - `{T}: Add {G}.`
    **Match:** Elvish Mystic - `{T}: Add {G}.`
    **NOT:** Rampant Growth - `Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    *Mana dorks and land ramp serve similar deckbuilding goals but use different mechanics. Final verdict: not similar.*
