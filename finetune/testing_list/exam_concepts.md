# Axis 2, the concept engine's own tests

Scores `common/concept.py`. Read at runtime by `exam_concepts.py`.

## Pairs

Must display at or above the gate.

1.
    **Anchor:** Shadrix Silverquill
    **Match:** Gluntch, the Bestower
    *Choosing WHO gets the gift is the concept. Passes today, 0.55 against 0.35.*

2.
    **Anchor:** Rhystic Study
    **Match:** Mystic Remora
    *Taxing beats symmetric giving. Howling Mine draws cards for everyone with nothing to pay.*

3.
    **Anchor:** Grave Pact
    **Match:** Dictate of Erebos
    *The same effect on a different card type. If axis 2 misses this one it is broken.*

## Triplets

Closer must beat Further. A reason beginning FAILS marks one that does not today.

1.
    **Test:** A selective hug
    **Anchor:** Shadrix Silverquill
    **Closer:** Gluntch, the Bestower
    **Further:** Font of Mythos
    *Choosing WHO gets the gift is the concept. Passes today, 0.55 against 0.35.*

2.
    **Test:** B role beats verb
    **Anchor:** Murder
    **Closer:** Swords to Plowshares
    **Further:** Day of Judgment
    *FAILS today, 0.24 against 0.51: the scorer overweights removal-destroy, a mechanism tag wearing concept clothes. The axis-2 version of the questions every stock model failed.*

3.
    **Test:** C tax beats giving
    **Anchor:** Rhystic Study
    **Closer:** Smothering Tithe
    **Further:** Howling Mine
    *Taxing beats symmetric giving. Howling Mine draws cards for everyone with nothing to pay.*

4.
    **Test:** D outlet is not payoff
    **Anchor:** Ashnod's Altar
    **Closer:** Phyrexian Altar
    **Further:** Blood Artist
    *The outlet and the payoff share every sacrifice tag, so this is where tag overlap alone should struggle.*

5.
    **Test:** E land ramp is not artifact ramp
    **Anchor:** Rampant Growth
    **Closer:** Sakura-Tribe Elder
    **Further:** Sol Ring
    *All three make mana. Only two of them do it by fetching a land.*

6.
    **Test:** F drain payoff is not sacrifice tax
    **Anchor:** Zulaport Cutthroat
    **Closer:** Blood Artist
    **Further:** Grave Pact
    *All three are "creatures dying matter". Two drain on the death, one taxes the table with it.*

## Separations

Printed rather than scored. Each is where it should be, and must not drift up through the gate.

1.
    **Anchor:** Sol Ring
    **NOT:** Ulvenwald Captive // Ulvenwald Abomination
    *both mana, but colourless ramp is not a green dork.*

2.
    **Anchor:** Merfolk Looter
    **NOT:** Rummaging Goblin
    *the axis-1 trap, and axis 2 must not rescue it*

3.
    **Anchor:** Howling Mine
    **NOT:** Underworld Dreams
    *both "everyone draws", opposite sides of it.*

4.
    **Anchor:** Smothering Tithe
    **NOT:** Ghostly Prison
    *FAILS today at raw 0.00, and that zero is the point: these two share not one tag, so the concept axis has nothing at all to score. Both tax an opponent's action rather than stopping it.*

5.
    **Anchor:** Sakura-Tribe Elder
    **NOT:** Wood Elves
    *FAILS today at 75%, just under the gate. Both are a creature body that fetches a land onto the battlefield, so this one is close rather than blind.*
