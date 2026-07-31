# Absolute tests, from user-reported gaps

Axis 1 as displayed. `exam_pairs.py` parses this file at runtime and
`make_training.py` holds every card named here out of training, so an edit
changes both the score and what the next model may learn.

Two polarities, both pasted straight from the /admin export:
- **Should-match** ('missing' reports): the Match belongs in the anchor's results. Passes when it clears the live cutoff.
- **Should-NOT** ('misplaced' reports): the NOT was flagged as wrong. Passes when it drops below the cutoff.

# Should-match (expected card scored too low)

1.
    **Anchor:** Earth-Cult Elemental - `1—9 | Each player sacrifices a permanent of their choice.`
    **Match:** Abyssal Gorestalker - `When this creature enters, each player sacrifices two creatures of their choice.`
    *preprocessing, fixed 2026-07-15 (26% -> 51%). the rest is the ETB wrapper, and permanent against creatures*

2.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    *model gap, a subtype scope rider. minable at scale*

3.
    **Anchor:** Swiftfoot Boots - `Equipped creature has hexproof and haste.`
    **Match:** Lightning Greaves - `Equipped creature has haste and shroud.`
    *model gap, keyword lists sharing most of their keywords*

4.
    **Anchor:** Cloud's Limit Break - `• Omnislash — {3}{W} — Destroy all tapped creatures.`
    **Match:** Guan Yu's 1,000-Li March - `Destroy all tapped creatures.`
    *preprocessing, clean_line keeps the modal bullet and mode prefix, so the anchor never reduces to the bare effect*

5.
    **Anchor:** Cloud's Limit Break - `• Omnislash — {3}{W} — Destroy all tapped creatures.`
    **Match:** Split Up - `Choose one —` + `• Destroy all tapped creatures.` + `• Destroy all untapped creatures.`
    *preprocessing, same anchor prefix and both sides keep their bullets*

6.
    **Anchor:** Cyclonic Rift - `Return target nonland permanent you don't control to its owner's hand.`
    **Match:** Ugin's Binding - `Return target nonland permanent you don't control to its owner's hand.`
    *passing at 100%. regression guard: they share only `removal-nonland` (354 cards), so only the text axis can connect them*

7.
    **Anchor:** Exotic Orchard - `{T}: Add one mana of any color that a land an opponent controls could produce.`
    **Match:** Sylvok Explorer - `{T}: Add one mana of any color that a land an opponent controls could produce.`
    *passing at 100%. the cleanest case on the site, an identical printed line and only `activated-ability` shared*

8.
    **Anchor:** Kessig Flamebreather - `Whenever you cast a noncreature spell, this creature deals 1 damage to each opponent.`
    **Match:** Firebrand Archer - `Whenever you cast a noncreature spell, this creature deals 1 damage to each opponent.`
    *passing at 100%. the budget swap the site exists to find, $3.56 against $0.26*

9.
    **Anchor:** Bristly Bill, Spine Sower - `Whenever a land you control enters, put a +1/+1 counter on target creature.`
    **Match:** Ride the Shoopuf - `Whenever a land you control enters, put a +1/+1 counter on target creature you control.`
    *passing at 98%. a "you control" rider, the forgivable kind of scope change*

10.
    **Anchor:** Entish Restoration - `Sacrifice a land. Search your library for up to two basic land cards, put them onto the battlefield tapped, then shuffle. If you control a creature with power 4 or greater, instead search your library for up to three basic land cards, put them onto the battlefield tapped, then shuffle.`
    **Match:** Cycle of Renewal - `Sacrifice a land. Search your library for up to two basic land cards, put them onto the battlefield tapped, then shuffle.`
    *passing at 98%. a conditional upgrade rider on an otherwise identical effect*

# Should-NOT (flagged card scored too high)

1.
    **Anchor:** Sol Ring - `{T}: Add {C}{C}.`
    **NOT:** Ulvenwald Captive // Ulvenwald Abomination - `{T}: Add {G}.`
    *model gap, the mana produced is the payload, not a parameter*

2.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **NOT:** Fierce Guardianship - `If you control a commander, you may cast this spell without paying its mana cost.`
    *model gap, "your spells" against "this spell"*

3.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **NOT:** Hogaak, Arisen Necropolis - `You can't spend mana to cast this spell.`
    *model gap, permission against restriction*

4.
    **Anchor:** Lightning Greaves - `Equip {0}`
    **NOT:** Grafted Wargear - `Equip {0}`
    *ranking (idf). "Equip {0}" is on 4 cards, so it drew full weight and ranked FIRST. bucketing the cost puts it with 567 equip lines at 0.327, dropping it to rank 393*

5.
    **Anchor:** Vandalblast - `Overload {4}{R}`
    **NOT:** Dynacharge - `Overload {2}{R}`
    *ranking (idf). Overload's varying cost splits 27 card-lines into 22 texts, each at full weight. bucketing clears the anchor's top 8 but not this score, so judge on rank*

6.
    **Anchor:** Cyclonic Rift - `Overload {6}{U}`
    **NOT:** Blustersquall - `Overload {3}{U}`
    *ranking (idf). as above, a bounce against a tap. bucketing pulls real bounce spells into the top 8. judge on rank*

7.
    **Anchor:** Toxic Deluge - `All creatures get -X/-X until end of turn.`
    **NOT:** Hell Swarm - `All creatures get -1/-0 until end of turn.`
    *model gap, a number crossing a functional threshold: -1/-0 kills nothing and is not a sweeper. the site's number ONE result for the anchor, and it needs its own negative class*

8.
    **Anchor:** Deflecting Swat - `If you control a commander, you may cast this spell without paying its mana cost.`
    **NOT:** Elminster - `this card can be your commander.`
    *model gap, rare-word latch on "commander" alone. DELIBERATELY UNTRAINED and the only entry that is: one line text on each side means it can be taught or examined, not both, so passing means the model generalised rather than memorised*

9.
    **Anchor:** Propaganda - `Creatures can't attack you unless their controller pays {2} for each creature they control that's attacking you.`
    **NOT:** Mogg Toady - `This creature can't attack unless you control more creatures than defending player.`
    *model gap, beneficiary flip. the anchor taxes the opponent's attack, the NOT restricts its own. no existing flip covers who a restriction points at*
