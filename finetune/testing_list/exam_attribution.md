# Which tags is each line about?

The answer key for `ingest/attribute.py`. Read at runtime by `exam_attribution.py`.

## Labels

Line numbers are the card's lines in id order, whole-card rows excluded. A line number that is not listed is not scored; a line listed as `(none)` is scored and expects no tags. List only the tags a line is GENUINELY about: one the card carries for reasons outside its rules text belongs to no line.

1.
    **Card:** Shadrix Silverquill
    **Line 0:** evasion
    **Line 2:** donate-token, evasion, modal, repeatable-creature-tokens, selective-group-hug
    **Line 3:** draw-engine, force-draw, opponent-loses-life, repeatable-crime, repeatable-pure-draw
    **Line 4:** gains-pp-counters, gives-pp-counters-to-all, repeatable-pp-counters, selective-group-hug
    *line 1 is the "choose two" header, not scored*

2.
    **Card:** Omnath, Locus of Creation
    **Line 0:** cantrip, hand-neutral, triggered-ability
    **Line 1:** adds-multiple-mana, burn-planeswalker, burn-player, group-slug, landfall, mana-producer, non-mana-ability-mana, repeatable-lifegain, repeatable-removal, sweeper-one-sided, times-resolved-matters, triggered-ability

3.
    **Card:** Kratos, God of War
    **Line 0:** (none)
    **Line 1:** burn-player-each, catch-22, gives-haste, keyword-anthem, symmetrical
    **Line 2:** burn-player-each, catch-22, symmetrical, triggered-ability
    *line 0 is "Double strike", about none of this card's tags*

4.
    **Card:** The One Ring
    **Line 0:** creature-ability-noncreature
    **Line 1:** damage-prevention-you, fog-selective, gives-player-protection
    **Line 2:** drawback, life-for-cards, unique-counter
    **Line 3:** activated-ability, burst-draw, draw-engine, hand-positive, quadratic, repeatable-pure-draw, tome, unique-counter
    *no triggered-ability on lines 1 and 2: tagger never typed it onto this card, and a label the card does not carry is a hole in the answer key rather than a miss*

5.
    **Card:** Boros Charm
    **Line 1:** burn-planeswalker, burn-player, single-target-instant-sorcery
    **Line 2:** gives-indestructible, protects-all, protects-creature
    **Line 3:** combat-trick, gives-double-strike, single-target-instant-sorcery
    *line 0 is the "Choose one" header, not scored*

6.
    **Card:** The Great Henge
    **Line 0:** discount-self, scales-with-power
    **Line 1:** activated-ability, adds-multiple-mana, full-refund, mana-ability-with-extra-effect, repeatable-lifegain, utility-mana-rock
    **Line 2:** creaturefall, draw-engine, gives-pp-counters, repeatable-pp-counters, repeatable-pure-draw, triggered-ability

7.
    **Card:** Goldspan Dragon
    **Line 0:** evasion
    **Line 1:** attacking-matters-self, hate-target, heroic, repeatable-treasures, synergy-treasure, triggered-ability
    **Line 2:** gives-mana-ability, refund, synergy-treasure

8.
    **Card:** Dauthi Voidwalker
    **Line 0:** evasion, restricted-blocker
    **Line 1:** aesthetic-counter, graveyard-seal
    **Line 2:** activated-ability, free-cast-another, gives-castable-from-exile, martyr, theft-cast
    *hatebear is why this card is here. It is about the mana cost and the power/toughness box, so it belongs to no line and attribute.py is expected to leave it out*

9.
    **Card:** Professional Face-Breaker
    **Line 0:** evasion
    **Line 1:** combat-ramp, per-player, repeatable-treasures, synergy-treasure, triggered-ability
    **Line 2:** activated-ability, free-sacrifice-outlet, impulsive-curiosity, repeatable-impulsive-draw, synergy-treasure
