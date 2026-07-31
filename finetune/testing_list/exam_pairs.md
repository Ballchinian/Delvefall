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
    *class: preprocessing, fixed 2026-07-15 (26% -> 51%). the leftover gap is model: the ETB
    trigger wrapper and permanent-vs-creatures scope. minable: same effect with and without a
    "When this creature enters," wrapper. Promoted to CA.*
    *user report 2026-07-13; scored 26% against the cutoff; reason: Same effect, each player sacrices a creature/or permanent of their choice. Should be 90% match at least*

2.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **Match:** Dracogenesis - `You may cast Dragon spells without paying their mana costs.`
    *class: model gap - subtype scope rider, minable at scale. Match leg of CD and CE.*
    *user report 2026-07-13; scored 86% against the cutoff; reason: Very similar, it just specifies dragons*

3.
    **Anchor:** Swiftfoot Boots - `Equipped creature has hexproof and haste.`
    **Match:** Lightning Greaves - `Equipped creature has haste and shroud.`
    *class: model gap - keyword lists sharing most of their keywords. Promoted to CC.*
    *user report 2026-07-13; scored 80% against the cutoff; reason: swiftfoot boots always go with lightning greaves, they give haste and a form of protection so if anything the similarity should be 99% or above, not 80%*

4.
    **Anchor:** Cloud's Limit Break - `• Omnislash — {3}{W} — Destroy all tapped creatures.`
    **Match:** Guan Yu's 1,000-Li March - `Destroy all tapped creatures.`
    *class: preprocessing - clean_line keeps the modal bullet and the "Omnislash — {3}{W} —" mode prefix, so the embedded anchor never reduces to the bare effect.*
    *user report 2026-07-16; scored 35% mech against the cutoff; reason: This has the exact text yet doesnt appear higher*

5.
    **Anchor:** Cloud's Limit Break - `• Omnislash — {3}{W} — Destroy all tapped creatures.`
    **Match:** Split Up - `Choose one —` + `• Destroy all tapped creatures.` + `• Destroy all untapped creatures.`
    *class: preprocessing - same anchor prefix; both sides also keep their bullets.*
    *user report 2026-07-16; scored 38% mech against the cutoff; reason: This has the exact text yet doesnt appear higher*

6.
    **Anchor:** Cyclonic Rift - `Return target nonland permanent you don't control to its owner's hand.`
    **Match:** Ugin's Binding - `Return target nonland permanent you don't control to its owner's hand.`
    *class: none, passing at 100%. Regression guard: the two cards share only `removal-nonland`
    (354 cards), so nothing tag-shaped connects them and only the text axis can.*
    *audit 2026-07-19; scored 100%.*

7.
    **Anchor:** Exotic Orchard - `{T}: Add one mana of any color that a land an opponent controls could produce.`
    **Match:** Sylvok Explorer - `{T}: Add one mana of any color that a land an opponent controls could produce.`
    *class: none, passing at 100%. Regression guard, and the cleanest example on the site: the
    line is printed identically on both cards and the only tag they share is `activated-ability`,
    on 9539 cards.*
    *audit 2026-07-19; scored 100%.*

8.
    **Anchor:** Kessig Flamebreather - `Whenever you cast a noncreature spell, this creature deals 1 damage to each opponent.`
    **Match:** Firebrand Archer - `Whenever you cast a noncreature spell, this creature deals 1 damage to each opponent.`
    *class: none, passing at 100%. Regression guard for the budget swap the site is meant to
    find: same colour, same mana value, $3.56 against $0.26.*
    *audit 2026-07-19; scored 100%.*

9.
    **Anchor:** Bristly Bill, Spine Sower - `Whenever a land you control enters, put a +1/+1 counter on target creature.`
    **Match:** Ride the Shoopuf - `Whenever a land you control enters, put a +1/+1 counter on target creature you control.`
    *class: none, passing at 98%. Regression guard for a "you control" rider, which is the
    forgivable kind of scope change. $40.30 against $0.32.*
    *audit 2026-07-19; scored 98%.*

10.
    **Anchor:** Entish Restoration - `Sacrifice a land. Search your library for up to two basic land cards, put them onto the battlefield tapped, then shuffle. If you control a creature with power 4 or greater, instead search your library for up to three basic land cards, put them onto the battlefield tapped, then shuffle.`
    **Match:** Cycle of Renewal - `Sacrifice a land. Search your library for up to two basic land cards, put them onto the battlefield tapped, then shuffle.`
    *class: none, passing at 98%. Regression guard for a conditional upgrade rider on an
    otherwise identical effect.*
    *audit 2026-07-19; scored 98%.*

# Should-NOT (flagged card scored too high)

1.
    **Anchor:** Sol Ring - `{T}: Add {C}{C}.`
    **NOT:** Ulvenwald Captive // Ulvenwald Abomination - `{T}: Add {G}.`
    *class: model gap - mana produced is payload, ruling in CB.*
    *user report 2026-07-13; the flagged card showed at 100%; reason: This produces green mana, not colourless mana*

2.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **NOT:** Fierce Guardianship - `If you control a commander, you may cast this spell without paying its mana cost.`
    *class: model gap - "your spells" vs "this spell" scope flip. REF: CD.*
    *user report 2026-07-13; the flagged card showed at 90%; reason: Not paying mana cost for a card is not the same as not paying mana cost for all your cards*

3.
    **Anchor:** Omniscience - `You may cast spells from your hand without paying their mana costs.`
    **NOT:** Hogaak, Arisen Necropolis - `You can't spend mana to cast this spell.`
    *class: model gap - "may" vs "can't" polarity flip. REF: CE.*
    *user report 2026-07-13; the flagged card showed at 92%; reason: not paying mana costs for cards is not the same as providing another mekanism for paying less mana cost for a card*

4.
    **Anchor:** Lightning Greaves - `Equip {0}`
    **NOT:** Grafted Wargear - `Equip {0}`
    *class: ranking (idf). The equip cost is printed identically, so the pair really is 100%, but
    it was the whole reason Grafted Wargear ranked FIRST for Lightning Greaves ahead of every
    piece of protection equipment in the game. `line_stats` counts exact text, and "Equip {0}" is
    on 4 cards, so it scored the full 1.000 weight a unique wordy ability gets. Bucketing the
    cost away puts it with the other 567 equip lines at 0.327: Grafted Wargear falls to rank 393,
    Whispersilk Cloak climbs from 113 to 4, and the winning pair becomes the ability line, which
    is what drops this entry to 40%.*
    *audit 2026-07-19; the flagged card showed at 100% and at rank 1.*

5.
    **Anchor:** Vandalblast - `Overload {4}{R}`
    **NOT:** Dynacharge - `Overload {2}{R}`
    *class: ranking (idf). Same root cause, worse spread: Overload's cost varies so its 27
    card-lines fragment into 22 distinct texts on 1 or 2 cards each, and every one of them
    collects the full 1.000 weight. Vandalblast destroys artifacts, Dynacharge pumps creatures,
    and they met on the keyword line alone. Bucketing removes Dynacharge, Electrickery and
    Weapon Surge from Vandalblast's top 8 outright. It does NOT move this entry: force-compared,
    the Overload pair still beats destroy-artifact against pump-creatures, so the score stays 99%.
    Judge this one on rank, not here.*
    *audit 2026-07-19; the flagged card showed at 99%, top 8 for the anchor.*

6.
    **Anchor:** Cyclonic Rift - `Overload {6}{U}`
    **NOT:** Blustersquall - `Overload {3}{U}`
    *class: ranking (idf). As above. The real abilities are a bounce and a tap, which share
    nothing. Bucketing drops Blustersquall, March of Progress, Downsize and Mizzium Skin out of
    Cyclonic Rift's top 8 and pulls in Rushing River, Depart the Realm and Disperse, which are
    actual bounce spells. Score unchanged here for the same reason as 5.*
    *audit 2026-07-19; the flagged card showed at 99%, top 8 for the anchor.*

7.
    **Anchor:** Toxic Deluge - `All creatures get -X/-X until end of turn.`
    **NOT:** Hell Swarm - `All creatures get -1/-0 until end of turn.`
    *class: model gap - a numeric change that crosses a functional threshold. "Same mechanism,
    flexible parameters" holds right up until the parameter nulls the effect: -1/-0 kills nothing
    and is not a sweeper. This is the site's number ONE result for Toxic Deluge, at 99%. Not
    minable by any existing flip; needs its own negative class pairing -N/-N lines against the
    -N/-0 rewrite of themselves.*
    *audit 2026-07-19; the flagged card showed at 99% and at rank 1.*

8.
    **Anchor:** Deflecting Swat - `If you control a commander, you may cast this spell without paying its mana cost.`
    **NOT:** Elminster - `this card can be your commander.`
    *class: model gap - rare-word latch. The only thing these share is the word "commander", and
    it dragged five separate planeswalkers into one top 20.*
    *DELIBERATELY UNTRAINED, and the only entry here that is. The game prints one line text on
    each side (the free cast on 5 cards, "can be your commander" on 21), so this pair can be
    taught or examined, not both, and nothing in make_training.py mines it. Passing therefore means
    the model generalised "a shared rare word is not shared meaning" rather than memorising a
    pair. To train it instead, delete this entry: both lines are quoted above, which is all a
    negative needs.*
    *audit 2026-07-19; the flagged card showed at 82%, four more like it in the same top 20.*

9.
    **Anchor:** Propaganda - `Creatures can't attack you unless their controller pays {2} for each creature they control that's attacking you.`
    **NOT:** Mogg Toady - `This creature can't attack unless you control more creatures than defending player.`
    *class: model gap - beneficiary flip. Propaganda taxes the opponent's attack; Mogg Toady
    restricts its own. The existing flips cover tap/untap, enters/dies, gain/lose and
    attack/block, but nothing covers who a restriction points at. Ten of Propaganda's top 20 were
    creatures with an attack drawback.*
    *audit 2026-07-19; the flagged card showed at 80%.*
