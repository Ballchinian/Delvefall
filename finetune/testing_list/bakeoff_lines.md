# The line similarity exam

v1's exam, still run against v2 as a regression guard. The list that actually
scores is `TRIPLETS` in `bakeoff_lines.py`; this file is the readable copy and
the place new questions get drafted, so the two are kept in step by hand.

Each triplet is (anchor, should-match, should-NOT-match). "Should match" means the model ought to score it clearly closer to the anchor than the should-NOT card -> not that the negative must score 0%. Every negative here is a *hard* negative on purpose: it shares surface wording with the anchor but means something different.

Form:
## Letter - test

num.
    **Anchor:** name - `Desc`
    **Match:** name - `Desc`
    **NOT:** name - `Desc`
    *context*

## A - Draw/discard order (the original Reddit complaint)

1.
    **Anchor:** Merfolk Looter - `{T}: Draw a card, then discard a card.`
    **Match:** Careful Study - `Draw two cards, then discard two cards.`
    **NOT:** Rummaging Goblin - `{T}, Discard a card: Draw a card.`
    *Same three verbs, opposite order. Looting (draw first) vs rummaging (discard first).*

2. 
    **Anchor:** Frantic Search - `Draw two cards, then discard two cards. Untap up to three lands.`
    **Match:** Merfolk Looter - `{T}: Draw a card, then discard a card.`
    **NOT:** Cathartic Reunion - `As an additional cost to cast this spell, discard two cards.` (then `Draw three cards.`)
    *Discard-as-cost-before-drawing is rummaging in disguise.*


## B - Tap vs untap (one-word meaning flip)

1. 
    **Anchor:** Pressure Point - `Tap target creature.`
    **Match:** Frost Breath - `Tap up to two target creatures. Those creatures don't untap during their controller's next untap step.`
    **NOT:** Refocus - `Untap target creature.`
    *Anchor and negative differ by two letters. (Both cards also have a separate `Draw a card.` line - the site embeds lines separately, so the test is the tap/untap line.)*

## C - Death drain vs lifegain, and whose creatures count

1. 
    **Anchor:** Blood Artist - `Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.`
    **Match:** Zulaport Cutthroat - `Whenever this creature or another creature you control dies, each opponent loses 1 life and you gain 1 life.`
    **NOT:** Soul Warden - `Whenever another creature enters, you gain 1 life.`
    *Dies vs enters. Both are "creature event → 1 life" on the surface.*

2. 
    **Anchor:** Soul Warden - `Whenever another creature enters, you gain 1 life.`
    **Match:** Ajani's Welcome - `Whenever a creature you control enters, you gain 1 life.`
    **NOT:** Blood Seeker - `Whenever a creature an opponent controls enters, you may have that player lose 1 life.`
    *Subject flip: whose creatures, and gain vs drain.*

## D - Graveyard recursion: to hand vs to battlefield

1. 
    **Anchor:** Raise Dead - `Return target creature card from your graveyard to your hand.`
    **Match:** Gravedigger - `When this creature enters, you may return target creature card from your graveyard to your hand.`
    **NOT:** Zombify - `Return target creature card from your graveyard to the battlefield.`
    *One word (hand/battlefield) separates a common from a reanimation staple.*

2.
    **Anchor:** Zombify - `Return target creature card from your graveyard to the battlefield.`
    **Match:** Reanimate - `Put target creature card from a graveyard onto the battlefield under your control. You lose life equal to that card's mana value.`
    **NOT:** Raise Dead - `Return target creature card from your graveyard to your hand.`
    *The positive uses different verbs ("put... onto") - function over phrasing.*

## E - Bounce vs blink

1.
    **Anchor:** Unsummon - `Return target creature to its owner's hand.`
    **Match:** Vapor Snag - `Return target creature to its owner's hand. Its controller loses 1 life.`
    **NOT:** Cloudshift - `Exile target creature you control, then return that card to the battlefield under your control.`
    *"Return target creature" appears in both, but blink is a completely different mechanic.*

## F - What is the library search FOR

1.
    **Anchor:** Rampant Growth - `Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    **Match:** Nature's Lore - `Search your library for a Forest card, put that card onto the battlefield, then shuffle.`
    **NOT:** Diabolic Tutor - `Search your library for a card, put that card into your hand, then shuffle.`
    *Identical shell, but one ramps while the other tutors.*

## G - Countermagic: spells vs abilities, scope

1.
    **Anchor:** Cancel - `Counter target spell.`
    **Match:** Mana Leak - `Counter target spell unless its controller pays {3}.`
    **NOT:** Stifle - `Counter target activated or triggered ability.`
    *"Counter target" shell; Stifle can't touch spells.*

2.
    **Anchor:** Dismiss - `Counter target spell.` (also has a separate `Draw a card.` line)
    **Match:** Exclude - `Counter target creature spell.` (also cantrips)
    **NOT:** Stifle - `Counter target activated or triggered ability.`
    *Scope-narrowed counter is still a spell counter; abilities are different.*

## H - Unless-pays punishers (the site's flagship match)

1.
    **Anchor:** Rhystic Study - `Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.`
    **Match:** Mystic Remora - `Whenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.`
    **NOT:** Forced Fruition - `Whenever an opponent casts a spell, that player draws seven cards.`
    *Same trigger and tax structure, opposite beneficiary.*

## I - Numbers shouldn't matter, verbs should

1.
    **Anchor:** Divination - `Draw two cards.`
    **Match:** Concentrate - `Draw three cards.`
    **NOT:** Mind Rot - `Target player discards two cards.`
    *The shared verb matters more than the shared number.*

## J - One vs all

1.
    **Anchor:** Murder - `Destroy target creature.`
    **Match:** Hero's Downfall - `Destroy target creature or planeswalker.`
    **NOT:** Day of Judgment - `Destroy all creatures.`
    *Spot removal versus board wipe.*

## K - Counter polarity (+1/+1 vs -1/-1)

1.
    **Anchor:** Battlegrowth - `Put a +1/+1 counter on target creature.`
    **Match:** Increasing Savagery - `Put five +1/+1 counters on target creature.`
    **NOT:** Grim Affliction - `Put a -1/-1 counter on target creature, then proliferate.`
    *A single sign flips the mechanic from buffing to weakening.*

## M - Group hug vs draw punishment

1.
    **Anchor:** Howling Mine - `At the beginning of each player's draw step, if this artifact is untapped, that player draws an additional card.`
    **Match:** Font of Mythos - `At the beginning of each player's draw step, that player draws two additional cards.`
    **NOT:** Underworld Dreams - `Whenever an opponent draws a card, this enchantment deals 1 damage to that player.`
    *Both mention opponents drawing; one rewards it, one punishes it.*

## N - Mill is not draw

1.
    **Anchor:** Glimpse the Unthinkable - `Target player mills ten cards.`
    **Match:** Tome Scour - `Target player mills five cards.`
    **NOT:** Concentrate - `Draw three cards.`
    *Putting cards into the graveyard isn't drawing cards.*

## O - Identical cost, different payload

1.
    **Anchor:** Village Rites - `As an additional cost to cast this spell, sacrifice a creature.` + `Draw two cards.`
    **Match:** Altar's Reap - `As an additional cost to cast this spell, sacrifice a creature.` + `Draw two cards.`
    **NOT:** Bone Splinters - `As an additional cost to cast this spell, sacrifice a creature.` + `Destroy target creature.`
    *The sacrifice cost is identical; only the payoff distinguishes them.*

## L - Harder calls

1.
    **Anchor:** Lightning Bolt - `Lightning Bolt deals 3 damage to any target.`
    **Match:** Acorn Catapult - `{1}, {T}: This artifact deals 1 damage to any target. That permanent's controller or that player creates a 1/1 green Squirrel creature token.`
    **NOT:** Murder - `Destroy target creature.`
    *Both positives deal damage despite different wording; direct damage is distinct from destroy effects.*

2.
    **Anchor:** Swords to Plowshares - `Exile target creature. Its controller gains life equal to its power.`
    **Match:** Path to Exile - `Exile target creature. Its controller may search their library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    **NOT:** Murder - `Destroy target creature.`
    *Same cheap exile removal with different drawback riders.*

3.
    **Anchor:** Raise the Alarm - `Create two 1/1 white Soldier creature tokens.`
    **Match:** Dragon Fodder - `Create two 1/1 red Goblin creature tokens.`
    **NOT:** Parallel Lives - `If an effect would create one or more tokens under your control, it creates twice that many of those tokens instead.`
    *Color and creature type change, but both create two small creature tokens. Should appear above generic token cases*

4.
    **Anchor:** Rhystic Study - `Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.`
    **Match:** Mystic Remora - `Whenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.`
    **NOT:** Smothering Tithe - `Whenever an opponent draws a card, that player may pay {2}. If the player doesn't, you create a Treasure token.`
    *Different trigger and payoff despite sharing a tax mechanic.*

---

# Round 2

## BA - Can't block vs can't attack

1.
    **Anchor:** Bedlam - `Creatures can't block.`
    **Match:** Falter - `Creatures without flying can't block this turn.`
    **NOT:** Peacekeeper - `Creatures can't attack.`
    *Attack/block one-word flip. The match adds a duration and a flying carve-out but keeps the mechanism.*

## BB - Bare keyword lines (the domain-knowledge test)

1.
    **Anchor:** Slippery Bogle - `Hexproof`
    **Match:** Deadly Insect - `Shroud`
    **NOT:** Boggart Brute - `Menace`
    *Reminder text gets stripped by the cleaner, so these embed as single bare words. Tests if fine-tuning has worked.*

## BC - Same replacement-effect shell, different domain

1.
    **Anchor:** Parallel Lives - `If an effect would create one or more tokens under your control, it creates twice that many of those tokens instead.`
    **Match:** Mondrak, Glory Dominus - `If one or more tokens would be created under your control, twice that many of those tokens are created instead.`
    **NOT:** Dictate of the Twin Gods - `If a source would deal damage to a permanent or player, it deals double that damage to that permanent or player instead.`
    *All three share the "if X would happen, twice/double instead" shell; the match is a rewording (function over phrasing), the negative doubles damage, not tokens.*

## BD - Extra turn vs end the turn

1.
    **Anchor:** Time Warp - `Target player takes an extra turn after this one.`
    **Match:** Temporal Manipulation - `Take an extra turn after this one.`
    **NOT:** Time Stop - `End the turn.`
    *Opposite directions of time manipulation, also tests behavior on very short lines.*

## BE - Graveyard retrieval vs graveyard hate

1.
    **Anchor:** Regrowth - `Return target card from your graveyard to your hand.`
    **Match:** Eternal Witness - `When this creature enters, you may return target card from your graveyard to your hand.`
    **NOT:** Coffin Purge - `Exile target card from a graveyard.`
    *Getting a card back vs deleting it; "target card ... graveyard" shared.*

## BF - The effect vs immunity to the effect

1.
    **Anchor:** Counterspell - `Counter target spell.`
    **Match:** Negate - `Counter target noncreature spell.`
    **NOT:** Prowling Serpopard - `Creature spells you control can't be countered.`
    *Maximum word overlap ("counter", "spell"), opposite sides of the mechanic.*

## BG - Prevention vs anti-prevention

1.
    **Anchor:** Fog - `Prevent all combat damage that would be dealt this turn.`
    **Match:** Ethereal Haze - `Prevent all damage that would be dealt by creatures this turn.`
    **NOT:** Skullcrack - `Players can't gain life this turn. Damage can't be prevented this turn. Skullcrack deals 3 damage to target player or planeswalker.`
    *"Damage prevented" appears on both sides. Also exercises the name substitution path.*

## BH - Forced enemy discard vs self-discard

1.
    **Anchor:** Mind Rot - `Target player discards two cards.`
    **Match:** Hymn to Tourach - `Target player discards two cards at random.`
    **NOT:** Careful Study - `Draw two cards, then discard two cards.`
    *"Discard two cards" appears in all three; forced discard and self-discard should not be conflated.*

## BI - Harder judgment calls

1.
    **Anchor:** Phyrexian Vault - `{2}, {T}, Sacrifice a creature: Draw a card.`
    **Match:** Village Rites - `As an additional cost to cast this spell, sacrifice a creature.` + `Draw two cards.`
    **NOT:** Grim Haruspex - `Whenever another nontoken creature you control dies, draw a card.`
    *Sacrifice as an activation cost and sacrifice as a casting cost are the same move (you choose to trade a creature for cards). A death trigger is another method altogether: dying is not sacrificing. In deckbuilding this matters - these cards are synergistic (a sac outlet feeds the death trigger) but not similar, and a search for one should not surface the other.*

2.
    **Anchor:** Llanowar Elves - `{T}: Add {G}.`
    **Match:** Elvish Mystic - `{T}: Add {G}.`
    **NOT:** Rampant Growth - `Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.`
    *Mana dorks and land ramp serve similar deckbuilding goals but use different mechanics. Final verdict: not similar.*

# Round 3

Round 3 grew out of user reports (the raw reports live in exam_pairs.md with their scores and
reasons; each entry below names its source).

## CA - Flavour prefixes aren't greater than meaning

1.
    **Anchor:** Farideh's Fireball - `1—9 | Farideh's Fireball deals 2 damage to each player.`
    **Match:** Flame Rift - `Flame Rift deals 4 damage to each player.`
    **NOT:** Thunderwave - `1—9 | Thunderwave deals 3 damage to each creature.`
    *The `1—9 |` die-roll prefix is flavour, it should not overpower the text after but some relevence should be kept.*

## CB - Mana produced is payload, not parameter

1.
    **Anchor:** Sol Ring - `{T}: Add {C}{C}.`
    **Match:** Mind Stone - `{T}: Add {C}.`
    **NOT:** Ulvenwald Captive // Ulvenwald Abomination - `{T}: Add {G}.`
    *Ruling: for a mana ability the mana produced is the payload - {G} vs {C} decides which decks the card works in.*

## CC - Protection-plus-haste beats haste alone

1.
    **Anchor:** Swiftfoot Boots - `Equipped creature has hexproof and haste.`
    **Match:** Lightning Greaves - `Equipped creature has haste and shroud.`
    **NOT:** Ring of Valkas - `Equipped creature has haste.`
    *Hexproof ≈ shroud, so the match shares both halves of the anchor with the keyword order flipped; the negative shares the shell and one keyword but misses the protection half entirely.*

## CD - All your spells vs this spell

1.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    **NOT:** Fierce Guardianship - `If you control a commander, you may cast this spell without paying its mana cost.`
    *Scope narrowed by subtype (Dragons) is a forgivable parameter; scope narrowed to the card itself ("this spell") flips the function from multiple cards to a singular card.*

## CE - No is not the same as yes (consent is key)

1.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    **NOT:** Hogaak, Arisen Necropolis - `You can't spend mana to cast this spell.`
    *Permission vs restriction: "you may cast without paying" grants freedom, "you can't spend mana" takes an option away and demands another payment path.*