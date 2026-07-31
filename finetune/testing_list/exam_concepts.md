# Axis 2 - the concept engine's own tests

The list that actually scores is `PAIRS`, `TRIPLETS` and `SEPARATION` in `exam_concepts.py`; this file is the readable copy, kept in step by hand.

Pairs are absolute and must clear the axis-2 gate. Triplets are relative orderings that have to survive a scorer swap, so they hold whatever comes after the idf tag overlap in use today. Separations are judged non-matches: axis 2 must not blur what axis 1 keeps apart.

# Pairs

1.
    **Anchor:** Shadrix Silverquill
    **Match:** Gluntch, the Bestower
    *Same idea and same gameplan, hands boons to several players via selective-group-hug + donate-token. Axis 1 honestly scores it 78; this axis owns it (0.55 raw).*

2.
    **Anchor:** Rhystic Study
    **Match:** Mystic Remora
    *Same job, taxing the table for card draw. Almost no shared wording, so axis 1 cannot see it at all.*

3.
    **Anchor:** Smothering Tithe
    **Match:** Ghostly Prison
    *FAILS today at raw 0.00, and that zero is the point: these two share not one tag, so the concept axis has nothing at all to score. Both tax an opponent's action rather than stopping it.*

4.
    **Anchor:** Grave Pact
    **Match:** Dictate of Erebos
    *The same effect on a different card type. If axis 2 misses this one it is broken.*

5.
    **Anchor:** Sakura-Tribe Elder
    **Match:** Wood Elves
    *FAILS today at 75%, just under the gate. Both are a creature body that fetches a land onto the battlefield, so this one is close rather than blind.*

# Triplets

## A - Selective group hug beats generic group hug

1.
    **Anchor:** Shadrix Silverquill
    **Closer:** Gluntch, the Bestower
    **Further:** Font of Mythos
    *Choosing WHO gets the gift is the concept. Passes today, 0.55 against 0.35.*

## B - Role beats verb (spot removal is the role)

1.
    **Anchor:** Murder
    **Closer:** Swords to Plowshares
    **Further:** Day of Judgment
    *FAILS today, 0.24 against 0.51: the scorer overweights removal-destroy, a mechanism tag wearing concept clothes. The axis-2 version of the questions every stock model failed.*

## C - The tax is the concept, not the permanent type

1.
    **Anchor:** Rhystic Study
    **Closer:** Smothering Tithe
    **Further:** Howling Mine
    *Taxing beats symmetric giving. Howling Mine draws cards for everyone with nothing to pay.*

## D - A sacrifice outlet is not a sacrifice payoff

1.
    **Anchor:** Ashnod's Altar
    **Closer:** Phyrexian Altar
    **Further:** Blood Artist
    *The outlet and the payoff share every sacrifice tag, so this is where tag overlap alone should struggle.*

## E - Land ramp is not artifact ramp

1.
    **Anchor:** Rampant Growth
    **Closer:** Sakura-Tribe Elder
    **Further:** Sol Ring
    *All three make mana. Only two of them do it by fetching a land.*

## F - A drain payoff is not a sacrifice tax

1.
    **Anchor:** Zulaport Cutthroat
    **Closer:** Blood Artist
    **Further:** Grave Pact
    *All three are "creatures dying matter". Two drain on the death, one taxes the table with it.*

# Separations

Judged non-matches. These must sit well under the gate.

1.  **Sol Ring** / **Ulvenwald Captive // Ulvenwald Abomination** &mdash; *both mana, but colourless ramp is not a green dork.*
2.  **Merfolk Looter** / **Rummaging Goblin** &mdash; *the axis-1 trap, and axis 2 must not rescue it.*
3.  **Howling Mine** / **Underworld Dreams** &mdash; *both "everyone draws", opposite sides of it.*
