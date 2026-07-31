# Which tags are about the rules text?

Verdicts for every tag the AUC bar excluded, plus the ones it kept that look wrong. The
AUC answers "already well represented by the current model", which is a different question
and in the middle of the range mostly a wrong one: `ramp`, `rummage`, `scry-like`,
`converge` and `triggered-ability` are all printed in plain words on the card and all
excluded. This file answers "learnable in principle" instead.

**The test: can the card's own text infer the tag?** The model is shown one line of rules
text and nothing else. Not the mana cost, not the type line, not the power and toughness,
not the set, not even the card's name. A tag can be perfectly true and still be unlearnable
here. Tagger's own descriptions convict several: `hatebear` is "low-cost (2 MV or less) and
low power/toughness", `offcolor-ability` is "a mana cost outside the card's colors". Both
real, neither visible.

## Marking

| verdict | means | what it changes |
| --- | --- | --- |
| `text` | the card's own text can infer it | trained on, and picking a line can land it on that line |
| `card` | true of the card, not of any one line | never trained on. Picking a line sets it aside |
| `junk` | nothing to do with how the card plays | never trained on, always set aside |
| `?` | not judged yet | treated as `junk`, so an unreviewed tag is never learned by accident |

## Proposed text list

Excluded today, and every one of them is printed on the card in words.

- [text] `cantrip` &mdash; auc 0.750, 602 cards  
  Cards that let you draw a card as they resolve or enter the battlefield.  
  > *Serum Visions* &mdash; Draw a card. Scry 2.  
  > *Preordain* &mdash; Scry 2, then draw a card.  

- [text] `symmetrical` &mdash; auc 0.749, 819 cards  
  Cards that affect the whole battlefield/all players in symmetrical, equal manner.  
  > *Final Judgment* &mdash; Exile all creatures.  
  > *Creeping Corrosion* &mdash; Destroy all artifacts.  

- [text] `hate-red` &mdash; auc 0.749, 125 cards  
  > *Voice of Law* &mdash; Flying, protection from red  
  > *Sea Sprite* &mdash; Flying, protection from red  

- [text] `hate-white` &mdash; auc 0.749, 117 cards  
  > *Goblin Outlander* &mdash; Protection from white  
  > *Ihsan's Shade* &mdash; Protection from white  

- [text] `repeatable-mulch` &mdash; auc 0.749, 48 cards  
  > *Rick Jones, Destined Sidekick* &mdash; {3}, {T}: Mill four cards. You may put a Hero or enchantment card from among those cards into your hand.  

- [text] `typal-merfolk` &mdash; auc 0.748, 75 cards  
  > *Merfolk Mistbinder* &mdash; Other Merfolk you control get +1/+1.  
  > *Lord of Atlantis* &mdash; Other Merfolk get +1/+1 and have islandwalk.  

- [text] `gives-castable-from-exile` &mdash; auc 0.747, 692 cards  
  Cards that let you cast things from exile.  
  > *Apex Devastator* &mdash; Cascade, cascade, cascade, cascade  
  > *Primordial Gnawer* &mdash; When this creature dies, discover 3.  

- [text] `gives-shroud` &mdash; auc 0.747, 49 cards  
  > *Crystalline Sliver* &mdash; All Slivers have shroud.  
  > *Hanna's Custody* &mdash; All artifacts have shroud.  

- [text] `typal-warrior` &mdash; auc 0.747, 100 cards  
  > *Kargan Warleader* &mdash; Other Warriors you control get +1/+1.  
  > *Rushblade Commander* &mdash; Warriors your team controls have haste.  

- [text] `typal-cleric` &mdash; auc 0.744, 77 cards  
  > *Akroma's Devoted* &mdash; Cleric creatures have vigilance.  
  > *Ancestor's Prophet* &mdash; Tap five untapped Clerics you control: You gain 10 life.  

- [text] `hate-blue` &mdash; auc 0.744, 94 cards  
  > *Guma* &mdash; Protection from blue  
  > *Nacatl Outlander* &mdash; Protection from blue  

- [text] `typal-pirate` &mdash; auc 0.743, 64 cards  
  > *Dire Fleet Neckbreaker* &mdash; Attacking Pirates you control get +2/+0.  
  > *Fiery Cannonade* &mdash; this card deals 2 damage to each non-Pirate creature.  

- [text] `power-matters-total` &mdash; auc 0.743, 55 cards  
  Effects which care about the total power of some set of creatures.  
  > *Reunion of the House* &mdash; Return any number of target creature cards with total power 10 or less from your graveyard to the battlefield. Exile this card.  
  > *Slaughter the Strong* &mdash; Each player chooses any number of creatures they control with total power 4 or less, then sacrifices all other creatures they control.  

- [text] `ritual` &mdash; auc 0.742, 60 cards  
  Spells that add mana.  
  > *Seething Song* &mdash; Add {R}{R}{R}{R}{R}.  
  > *Channel the Suns* &mdash; Add {W}{U}{B}{R}{G}.  

- [text] `leaves-battlefield-trigger` &mdash; auc 0.741, 207 cards  
  Cards that trigger on something leaving the battlefield. See also [death trigger](death-trigger).  
  > *Flaming Fist Officer* &mdash; Whenever another creature you control leaves the battlefield, put a +1/+1 counter on this creature.  
  > *Ninth Bridge Patrol* &mdash; Whenever another creature you control leaves the battlefield, put a +1/+1 counter on this creature.  

- [text] `pseudo-fog` &mdash; auc 0.739, 74 cards  
  Effects that can protect you from an entire combat phase, similar to the card Fog, but using less conventional means than damage prevention.  
  > *Deluge* &mdash; Tap all creatures without flying.  
  > *Disrupt Decorum* &mdash; Goad all creatures you don't control.  

- [text] `burn-you` &mdash; auc 0.738, 248 cards  
  Sometimes your own cards hurt you the most.  
  > *Ancient Tomb* &mdash; {T}: Add {C}{C}. This land deals 2 damage to you.  
  > *Smoldering Efreet* &mdash; When this creature dies, it deals 2 damage to you.  

- [text] `synergy-party` &mdash; auc 0.738, 45 cards  
  > *Ardent Electromancer* &mdash; When this creature enters, add {R} for each creature in your party.  
  > *Cascade Seer* &mdash; When this creature enters, scry X, where X is the number of creatures in your party.  

- [text] `synergy-token-creature` &mdash; auc 0.736, 106 cards  
  > *Song of the Worldsoul* &mdash; Whenever you cast a spell, populate.  
  > *Trostani's Judgment* &mdash; Exile target creature, then populate.  

- [text] `synergy-enchantment` &mdash; auc 0.735, 246 cards  
  > *Serra's Sanctum* &mdash; {T}: Add {W} for each enchantment you control.  
  > *Fountain Watch* &mdash; Artifacts and enchantments you control have shroud.  

- [text] `auto-buyback` &mdash; auc 0.735, 22 cards  
  Derived from the buyback keyword, this ability will automatically return a card to your hand after casting it usually after a  condition is met.  
  > *Research the Deep* &mdash; Draw a card. Clash with an opponent. If you win, return this card to its owner's hand.  
  > *Pulse of the Fields* &mdash; You gain 4 life. Then if an opponent has more life than you, return this card to its owner's hand.  

- [text] `synergy-snow` &mdash; auc 0.734, 61 cards  
  > *Sculptor of Winter* &mdash; {T}: Untap target snow land.  
  > *Rime Tender* &mdash; {T}: Untap another target snow permanent.  

- [text] `typal-vampire` &mdash; auc 0.733, 82 cards  
  > *Thirsting Bloodlord* &mdash; Other Vampires you control get +1/+1.  
  > *Legion Lieutenant* &mdash; Other Vampires you control get +1/+1.  

- [text] `selective-group-hug` &mdash; auc 0.732, 202 cards  
  Group Hug cards that benefit only certain opponents in particular.  
  > *Hunters' Feast* &mdash; Any number of target players each gain 6 life.  
  > *Secret Rendezvous* &mdash; You and target opponent each draw three cards.  

- [text] `triggered-ability` &mdash; auc 0.732, 13601 cards  
  > *Thrumming Stone* &mdash; Spells you cast have ripple 4.  
  > *Professor of Symbology* &mdash; When this creature enters, learn.  

- [text] `punisher` &mdash; auc 0.731, 156 cards  
  Effects that give you a choice of two damnations.  
  > *Tyrannize* &mdash; Target player discards their hand unless they pay 7 life.  
  > *Vectis Dominator* &mdash; {T}: Tap target creature unless its controller pays 2 life.  

- [text] `typal-elemental` &mdash; auc 0.730, 45 cards  
  > *Caterwauling Boggart* &mdash; Goblins you control and Elementals you control have menace.  
  > *Seething Pathblazer* &mdash; Sacrifice an Elemental: This creature gets +2/+0 and gains first strike until end of turn.  

- [text] `synergy-vehicle` &mdash; auc 0.729, 116 cards  
  > *Bounce Off* &mdash; Return target creature or Vehicle to its owner's hand.  
  > *Daring Mechanic* &mdash; {3}{W}: Put a +1/+1 counter on target Mount or Vehicle.  

- [text] `consult-cast` &mdash; auc 0.728, 122 cards  
  Consult effects that let you cast the card you find.  
  > *Apex Devastator* &mdash; Cascade, cascade, cascade, cascade  
  > *Primordial Gnawer* &mdash; When this creature dies, discover 3.  

- [text] `aikido` &mdash; auc 0.727, 174 cards  
  Effects that turn your opponent's strength against them.  
  > *Soul's Grace* &mdash; You gain life equal to target creature's power.  
  > *Blessed Reversal* &mdash; You gain 3 life for each creature attacking you.  

- [text] `hate-low-power` &mdash; auc 0.725, 88 cards  
  > *Kor Line-Slinger* &mdash; {T}: Tap target creature with power 3 or less.  
  > *Stern Scolding* &mdash; Counter target creature spell with power or toughness 2 or less.  

- [text] `typal-knight` &mdash; auc 0.724, 43 cards  
  > *Inspiring Veteran* &mdash; Other Knights you control get +1/+1.  
  > *Kinsbaile Cavalier* &mdash; Knight creatures you control have double strike.  

- [text] `amount-spent-matters` &mdash; auc 0.723, 96 cards  
  The amount of mana you spent to do the thing matters.  
  > *Bark-Knuckle Boxer* &mdash; Whenever you expend 4, this creature gains indestructible until end of turn.  
  > *Graven Lore* &mdash; Scry X, where X is the amount of {S} spent to cast this spell, then draw three cards.  

- [text] `synergy-blue` &mdash; auc 0.723, 150 cards  
  > *Sapphire Medallion* &mdash; Blue spells you cast cost {1} less to cast.  
  > *Deepchannel Mentor* &mdash; Blue creatures you control can't be blocked.  

- [text] `hate-token` &mdash; auc 0.722, 29 cards  
  > *Illness in the Ranks* &mdash; Creature tokens get -1/-1.  
  > *Virulent Plague* &mdash; Creature tokens get -2/-2.  

- [text] `graveyard-order-matters` &mdash; auc 0.722, 23 cards  
  These cards care about the order of cards in a graveyard, or rearrange them somehow. If any of these cards are in a player's deck, care must be taken to preserve the order of the graveyard.  
  > *Soldevi Digger* &mdash; {2}: Put the top card of your graveyard on the bottom of your library.  
  > *Zombie Scavengers* &mdash; Exile the top creature card of your graveyard: Regenerate this creature.  

- [text] `typal-beast` &mdash; auc 0.721, 25 cards  
  > *Ravenous Baloth* &mdash; Sacrifice a Beast: You gain 4 life.  
  > *Totem Speaker* &mdash; Whenever a Beast enters, you may gain 3 life.  

- [text] `times-resolved-matters` &mdash; auc 0.721, 29 cards  
  Effects that check how many times they've resolved and do something different based on the result.  
  > *Rumor Gatherer* &mdash; Whenever another creature you control enters, scry 1. If this is the second time this ability has resolved this turn, draw a card instead.  

- [text] `synergy-island` &mdash; auc 0.720, 84 cards  
  > *Flow of Ideas* &mdash; Draw a card for each Island you control.  
  > *Flow of Knowledge* &mdash; Draw a card for each Island you control, then discard two cards.  

- [text] `hand-size-matters` &mdash; auc 0.719, 275 cards  
  > *Inner Fire* &mdash; Add {R} for each card in your hand.  
  > *Gerrard's Wisdom* &mdash; You gain 2 life for each card in your hand.  

- [text] `synergy-planeswalker` &mdash; auc 0.719, 188 cards  
  > *Search the Premises* &mdash; Whenever a creature attacks you or a planeswalker you control, investigate.  
  > *Spark Reaper* &mdash; {3}, Sacrifice a creature or planeswalker: You gain 1 life and draw a card.  

- [text] `rhystic` &mdash; auc 0.718, 228 cards  
  Effects that opponents can buy off if they pay mana.  
  > *Rhystic Deluge* &mdash; {U}: Tap target creature unless its controller pays {1}.  
  > *Excise* &mdash; Exile target attacking creature unless its controller pays {X}.  

- [text] `catch-up` &mdash; auc 0.718, 90 cards  
  Players who have less get more.  
  > *Repay in Kind* &mdash; Each player's life total becomes the lowest life total among all players.  
  > *Blazing Hope* &mdash; Exile target creature with power greater than or equal to your life total.  

- [text] `counters-matter` &mdash; auc 0.718, 1230 cards  
  > *Expansion Algorithm* &mdash; Proliferate X times.  
  > *Tezzeret's Gambit* &mdash; Draw two cards, then proliferate.  

- [text] `discard-outlet` &mdash; auc 0.718, 1231 cards  
  Ways to discard your own cards.  
  > *Mind Rot* &mdash; Target player discards two cards.  
  > *Wit's End* &mdash; Target player discards their hand.  

- [text] `creature-count-matters` &mdash; auc 0.717, 299 cards  
  > *Battle Hymn* &mdash; Add {R} for each creature you control.  
  > *Collective Unconscious* &mdash; Draw a card for each creature you control.  

- [text] `typal-soldier` &mdash; auc 0.717, 51 cards  
  > *Yotian Tactician* &mdash; Other Soldiers you control get +1/+1.  
  > *Veteran Armorsmith* &mdash; Other Soldier creatures you control get +0/+1.  

- [text] `opponent-chooses` &mdash; auc 0.716, 140 cards  
  > *Cruel Edict* &mdash; Target opponent sacrifices a creature of their choice.  
  > *Strategic Betrayal* &mdash; Target opponent exiles a creature they control and their graveyard.  

- [text] `hand-negative` &mdash; auc 0.715, 236 cards  
  Card (dis)advantage spells and abilities that leave you with less cards in hand after resolving.  
  > *Hypnotic Grifter* &mdash; {3}: This creature connives.  
  > *Professor of Symbology* &mdash; When this creature enters, learn.  

- [text] `cost-ignorer` &mdash; auc 0.714, 527 cards  
  Cards that allow you to bypass mana costs. This could be by making the spell free or by setting a static cost that's independent of the original.  
  > *Molecule Man* &mdash; Nonland cards in your hand have miracle {0}.  
  > *Brass Squire* &mdash; {T}: Attach target Equipment you control to target creature you control.  

- [text] `synergy-black` &mdash; auc 0.714, 166 cards  
  > *Bad Moon* &mdash; Black creatures get +1/+1.  
  > *Corrosive Mentor* &mdash; Black creatures you control have wither.  

- [text] `power-matters-self` &mdash; auc 0.714, 285 cards  
  > *Viridian Joiner* &mdash; {T}: Add an amount of {G} equal to this creature's power.  
  > *Wandering Wolf* &mdash; Creatures with power less than this creature's power can't block it.  

- [text] `per-player` &mdash; auc 0.713, 435 cards  
  Effects that scale positively with the number of players; i. e., "for each player", "for each opponent", etc.  
  > *Celestial Force* &mdash; At the beginning of each upkeep, you gain 3 life.  
  > *Baleful Force* &mdash; At the beginning of each upkeep, you draw a card and you lose 1 life.  

- [text] `hate-discard` &mdash; auc 0.712, 131 cards  
  Your opponent had better think twice before targeting you with that [Mind Rot](https://tagger.scryfall.com/card/ori/281)!  
  > *Confessor* &mdash; Whenever a player discards a card, you may gain 1 life.  
  > *Lazotep Chancellor* &mdash; Whenever you discard a card, you may pay {1}. If you do, amass Zombies 2.  

- [text] `synergy-plains` &mdash; auc 0.708, 62 cards  
  > *Landbind Ritual* &mdash; You gain 2 life for each Plains you control.  
  > *Dire Wolves* &mdash; This creature has banding as long as you control a Plains.  

- [text] `long-term-impulsive-draw` &mdash; auc 0.707, 106 cards  
  Impulsive draw effects that let you play the exiled cards beyond this turn, letting you untap and have access to your full resources.  
  > *Commune with Lava* &mdash; Exile the top X cards of your library. Until the end of your next turn, you may play those cards.  
  > *Reckless Impulse* &mdash; Exile the top two cards of your library. Until the end of your next turn, you may play those cards.  

- [text] `typal-wizard` &mdash; auc 0.706, 114 cards  
  > *Azami, Lady of Scrolls* &mdash; Tap an untapped Wizard you control: Draw a card.  
  > *Riptide Director* &mdash; {2}{U}{U}, {T}: Draw a card for each Wizard you control.  

- [text] `typal-kithkin` &mdash; auc 0.705, 26 cards  
  > *Wizened Cenn* &mdash; Other Kithkin creatures you control get +1/+1.  
  > *Ballyrush Banneret* &mdash; Kithkin spells and Soldier spells you cast cost {1} less to cast.  

- [text] `typal-coupling` &mdash; auc 0.704, 304 cards  
  Cards that care about two or more different creature types.  
  > *Shoot the Sheriff* &mdash; Destroy target non-outlaw creature.  
  > *Deeproot Historian* &mdash; Merfolk and Druid cards in your graveyard have retrace.  

- [text] `aesthetic-counter` &mdash; auc 0.704, 299 cards  
  Counters that have no rules meaning, just aesthetic.  
  > *Free from Flesh* &mdash; Target creature gets +2/+2 until end of turn. Put two oil counters on it.  
  > *Cephalid Vandal* &mdash; At the beginning of your upkeep, put a shred counter on this creature. Then mill a card for each shred counter on this creature.  

- [text] `force-attacker` &mdash; auc 0.703, 153 cards  
  > *Disrupt Decorum* &mdash; Goad all creatures you don't control.  
  > *Goblin Diplomats* &mdash; {T}: Each creature attacks this turn if able.  

- [text] `synergy-treasure` &mdash; auc 0.703, 49 cards  
  > *Academy Manufactor* &mdash; If you would create a Clue, Food, or Treasure token, instead create one of each.  
  > *Hired Hexblade* &mdash; When this creature enters, if mana from a Treasure was spent to cast it, you draw a card and you lose 1 life.  

- [text] `drawback` &mdash; auc 0.703, 1677 cards  
  Cards that have some kind of disadvantage.  
  > *Uktabi Efreet* &mdash; Cumulative upkeep {G}  
  > *Dragon's Eye Sentry* &mdash; Defender, first strike  

- [text] `faux-targeting` &mdash; auc 0.703, 127 cards  
  Things that have to choose "targets", but don't actually *target*, meaning this bypasses keywords such as hexproof, protection, and shroud.  
  > *Spectral Searchlight* &mdash; {T}: Choose a player. That player adds one mana of any color they choose.  
  > *Split the Party* &mdash; Choose target player. Return half the creatures they control to their owner's hand, rounded up.  

- [text] `typal-elf` &mdash; auc 0.700, 114 cards  
  > *Pride of the Perfect* &mdash; Elves you control get +2/+0.  
  > *Priest of Titania* &mdash; {T}: Add {G} for each Elf on the battlefield.  

- [text] `mana-sink` &mdash; auc 0.699, 1489 cards  
  Cards with repeatable effects that you can dump a bunch of mana (at least 3) into each turn.  
  > *Floodhound* &mdash; {3}, {T}: Investigate.  
  > *Horseshoe Crab* &mdash; {U}: Untap this creature.  

- [text] `donate` &mdash; auc 0.699, 66 cards  
  Effects that give control of a card you control to another player  
  > *Wrong Turn* &mdash; Target opponent gains control of target creature.  
  > *Donate* &mdash; Target player gains control of target permanent you control.  

- [text] `defector` &mdash; auc 0.697, 58 cards  
  Permanents that move around the board on their own  
  > *Goblin Cadets* &mdash; Whenever this creature blocks or becomes blocked, target opponent gains control of it.  
  > *Drooling Ogre* &mdash; Whenever a player casts an artifact spell, that player gains control of this creature.  

- [text] `opponent-lifegain` &mdash; auc 0.693, 56 cards  
  Cards that make your opponents gain life.  
  > *Hunters' Feast* &mdash; Any number of target players each gain 6 life.  
  > *Centaur Peacemaker* &mdash; When this creature enters, each player gains 4 life.  

- [text] `self-replacement-effect` &mdash; auc 0.691, 337 cards  
  A resolving spell or ability partially or completely replacing one of its own effects.  
  > *River of Tears* &mdash; {T}: Add {U}. If you played a land this turn, add {B} instead.  
  > *Life Goes On* &mdash; You gain 4 life. If a creature died this turn, you gain 8 life instead.  

- [text] `protects-creature` &mdash; auc 0.690, 881 cards  
  Effects that can protect a creature, e.g. with protection,  hexproof, indestructible, etc.  
  > *Crystalline Sliver* &mdash; All Slivers have shroud.  
  > *Regenerate* &mdash; this card target creature.  

- [text] `division` &mdash; auc 0.689, 85 cards  
  Cards that ask for a divided value. For cards that include a fractional value or a number that is not a whole number, see [non-integer](non-integer).  
  > *Traumatize* &mdash; Target player mills half their library, rounded down.  
  > *Contaminated Drink* &mdash; Draw X cards, then you get half X rad counters, rounded up.  

- [text] `hate-green` &mdash; auc 0.689, 91 cards  
  > *Zombie Outlander* &mdash; Protection from green  
  > *Vodalian Zombie* &mdash; Protection from green  

- [text] `morbid` &mdash; auc 0.688, 122 cards  
  Effects that care about at least one creature dying this turn.  
  > *Life Goes On* &mdash; You gain 4 life. If a creature died this turn, you gain 8 life instead.  
  > *Undercity Scrounger* &mdash; {T}: Create a Treasure token. Activate only if a creature died this turn.  

- [text] `scry-like` &mdash; auc 0.688, 46 cards  
  > *Spin into Myth* &mdash; Put target creature on top of its owner's library, then fateseal 2.  
  > *Research the Deep* &mdash; Draw a card. Clash with an opponent. If you win, return this card to its owner's hand.  

- [text] `hellbent` &mdash; auc 0.686, 50 cards  
  Effects that care about having no cards in hand.  
  > *Idle Thoughts* &mdash; {2}: Draw a card if you have no cards in hand.  
  > *Cutthroat il-Dal* &mdash; This creature has shadow as long as you have no cards in hand.  

- [text] `lockdown-creature` &mdash; auc 0.683, 103 cards  
  > *Root Cage* &mdash; Mercenaries don't untap during their controllers' untap steps.  
  > *Juntu Stakes* &mdash; Creatures with power 1 or less don't untap during their controllers' untap steps.  

- [text] `untracked-indefinite-effect` &mdash; auc 0.681, 395 cards  
  Effects that last forever but aren't tracked by anything. For these purposes we're not counting ETB clones.  
  > *Chaoslace* &mdash; Target spell or permanent becomes red.  
  > *Thoughtlace* &mdash; Target spell or permanent becomes blue.  

- [text] `repeatable-removal` &mdash; auc 0.679, 1686 cards  
  > *Night of Souls' Betrayal* &mdash; All creatures get -1/-1.  
  > *Dwarven Demolition Team* &mdash; {T}: Destroy target Wall.  

- [text] `type-change` &mdash; auc 0.679, 1143 cards  
  > *Cyber Conversion* &mdash; Turn target creature face down. It's a 2/2 Cyberman artifact creature.  
  > *Circle of the Moon Druid* &mdash; During your turn, this creature is a Bear with base power and toughness 4/2.  

- [text] `clash-like` &mdash; auc 0.678, 35 cards  
  Cards that compare the mana values of multiple players' revealed cards  
  > *Research the Deep* &mdash; Draw a card. Clash with an opponent. If you win, return this card to its owner's hand.  
  > *Hoarder's Greed* &mdash; You lose 2 life and draw two cards, then clash with an opponent. If you win, repeat this process.  

- [text] `reflexive-trigger` &mdash; auc 0.677, 261 cards  
  An ability that triggers based on actions taken earlier during a spell or ability's resolution.  
  > *Thousand Moons Crackshot* &mdash; Whenever this creature attacks, you may pay {2}{W}. When you do, tap target creature.  
  > *Tolarian Kraken* &mdash; Whenever you draw a card, you may pay {1}. When you do, you may tap or untap target creature.  

- [text] `donate-token` &mdash; auc 0.677, 173 cards  
  Effects that can create tokens under an opponents control.  
  > *Marching Duodrone* &mdash; Whenever this creature attacks, each player creates a Treasure token.  
  > *Wanted Scoundrels* &mdash; When this creature dies, target opponent creates two Treasure tokens.  

- [text] `donate-mana` &mdash; auc 0.676, 33 cards  
  > *Wanted Scoundrels* &mdash; When this creature dies, target opponent creates two Treasure tokens.  
  > *Marching Duodrone* &mdash; Whenever this creature attacks, each player creates a Treasure token.  

- [text] `typal-human` &mdash; auc 0.672, 101 cards  
  > *Mass Appeal* &mdash; Draw a card for each Human you control.  
  > *Skirsdag Flayer* &mdash; {3}{B}, {T}, Sacrifice a Human: Destroy target creature.  

- [text] `tutor-copy` &mdash; auc 0.670, 16 cards  
  Tutors for something with the same name as something else  
  > *Pack Hunt* &mdash; Search your library for up to three cards with the same name as target creature, reveal them, put them into your hand, then shuffle.  
  > *Bifurcate* &mdash; Search your library for a permanent card with the same name as target nontoken creature, put that card onto the battlefield, then shuffle.  

- [text] `mana-value-matters` &mdash; auc 0.670, 778 cards  
  > *Fleshwrither* &mdash; Transfigure {1}{B}{B}  
  > *Forked-Branch Garami* &mdash; Soulshift 4, soulshift 4  

- [text] `exile-self` &mdash; auc 0.669, 1262 cards  
  Cards which exile themselves (from the battlefield, from the graveyard, from your hand, etc.)  
  > *Curious Pair // Treats to Share* &mdash; Create a Food token.  
  > *Embereth Shieldbreaker // Battle Display* &mdash; Destroy target artifact.  

- [text] `multiplayer` &mdash; auc 0.669, 571 cards  
  Cards that interact with all of the players in the game. They might scale with the number of players or affect the turn order for example.  
  > *Turbulent Moor* &mdash; This land enters tapped unless your opponents control eight or more lands.  
  > *Turbulent Wilderness* &mdash; This land enters tapped unless your opponents control eight or more lands.  

- [text] `reanimate-cast` &mdash; auc 0.668, 134 cards  
  Cast a permanent spell from your graveyard.  
  > *Deeproot Historian* &mdash; Merfolk and Druid cards in your graveyard have retrace.  
  > *Squee, the Immortal* &mdash; You may cast this card from your graveyard or from exile.  

- [text] `bribery` &mdash; auc 0.667, 21 cards  
  Give an opponent something in exchange for a benefit to you.  
  > *Tempting Contract* &mdash; At the beginning of your upkeep, each opponent may create a Treasure token. For each opponent who does, you create a Treasure token.  

- [text] `discarded-type-matters` &mdash; auc 0.666, 104 cards  
  The type of card you discard matters for some effect.  
  > *Hypnotic Grifter* &mdash; {3}: This creature connives.  
  > *Red Room Recruit* &mdash; When this creature enters, it connives.  

- [text] `inverted-effects` &mdash; auc 0.666, 470 cards  
  > *Mindculling* &mdash; You draw two cards and target opponent discards two cards.  
  > *Thoughtweft Gambit* &mdash; Tap all creatures your opponents control and untap all creatures you control.  

- [text] `undergrowth` &mdash; auc 0.665, 130 cards  
  Cards that care about the number of creature cards in your graveyard.  
  > *Songs of the Damned* &mdash; Add {B} for each creature card in your graveyard.  
  > *Grim Flowering* &mdash; Draw a card for each creature card in your graveyard.  

- [text] `exponential` &mdash; auc 0.662, 116 cards  
  Effects that involve some amount of exponential growth. This can be an exponential value, or a token creation effect that would be exponential if allowed to progress unhindered. See [quadratic](quadra  
  > *Mathemagics* &mdash; Target player draws 2ˣ cards.  
  > *Myr Propagator* &mdash; {3}, {T}: Create a token that's a copy of this creature.  

- [text] `unique-counter` &mdash; auc 0.661, 130 cards  
  These cards use a type of counter no other card does.  
  > *Cephalid Vandal* &mdash; At the beginning of your upkeep, put a shred counter on this creature. Then mill a card for each shred counter on this creature.  

- [text] `ferocious` &mdash; auc 0.651, 114 cards  
  Cards that care about you controlling creatures with power 4 or greater.  
  > *Kavu Lair* &mdash; Whenever a creature with power 4 or greater enters, its controller draws a card.  
  > *Life Finds a Way* &mdash; Whenever a nontoken creature you control with power 4 or greater enters, populate.  

- [text] `the-ring-tempts-you` &mdash; auc 0.649, 49 cards  
  > *Birthday Escape* &mdash; Draw a card. The Ring tempts you.  
  > *Claim the Precious* &mdash; Destroy target creature. The Ring tempts you.  

- [text] `toughness-matters` &mdash; auc 0.637, 187 cards  
  Other than in, you know, the usual way.  
  > *Pillar of Light* &mdash; Exile target creature with toughness 4 or greater.  
  > *Repel Calamity* &mdash; Destroy target creature with power or toughness 4 or greater.  

- [text] `scales-with-power` &mdash; auc 0.633, 635 cards  
  Effects which scale with the power of one or more creatures.  
  > *Soul's Grace* &mdash; You gain life equal to target creature's power.  
  > *Wave of Reckoning* &mdash; Each creature deals damage to itself equal to its power.  

- [text] `castable-from-exile` &mdash; auc 0.632, 459 cards  
  Cards you can cast or access from exile.  
  > *Curious Pair // Treats to Share* &mdash; Create a Food token.  
  > *Embereth Shieldbreaker // Battle Display* &mdash; Destroy target artifact.  

- [text] `rummage` &mdash; auc 0.632, 267 cards  
  Discard a card, then draw a card. Mainly red. See also [loot](/tags/card/loot), the blue version, which draws then discards.  
  > *Professor of Symbology* &mdash; When this creature enters, learn.  
  > *Blood Servitor* &mdash; When this creature enters, create a Blood token.  

- [text] `non-mana-ability-mana` &mdash; auc 0.625, 170 cards  
  Abilities that produce mana, but aren't mana abilities (as defined by CR 605.1)  
  > *Myr Moonvessel* &mdash; When this creature dies, add {C}.  
  > *Akki Rockspeaker* &mdash; When this creature enters, add {R}.  

- [text] `cards-in-graveyard-matter` &mdash; auc 0.624, 556 cards  
  Mechanics that care about the cards in one or more graveyards.  
  > *Cosmic Epiphany* &mdash; Draw cards equal to the number of instant and sorcery cards in your graveyard.  
  > *Sudden Insight* &mdash; Draw a card for each different mana value among nonland cards in your graveyard.  

- [text] `typal-dragon` &mdash; auc 0.624, 124 cards  
  > *Crucible of Fire* &mdash; Dragon creatures you control get +3/+3.  
  > *Dragonspeaker Shaman* &mdash; Dragon spells you cast cost {2} less to cast.  

- [text] `synergy-legendary` &mdash; auc 0.621, 254 cards  
  > *Day of Destiny* &mdash; Legendary creatures you control get +2/+2.  
  > *Reki, the History of Kamigawa* &mdash; Whenever you cast a legendary spell, draw a card.  

- [text] `ramp` &mdash; auc 0.618, 2133 cards  
  Effects that increase available mana for current or later turns.  
  > *Braid of Fire* &mdash; Cumulative upkeep-Add {R}.  
  > *Candelabra of Tawnos* &mdash; {X}, {T}: Untap X target lands.  

- [text] `restock-self` &mdash; auc 0.608, 57 cards  
  Cards that restock themselves.  
  > *Undying Beast* &mdash; When this creature dies, put it on top of its owner's library.  
  > *Blue Sun's Zenith* &mdash; Target player draws X cards. Shuffle this card into its owner's library.  

- [text] `unpreventable-damage` &mdash; auc 0.607, 32 cards  
  Damage can't be prevented, whether universally or for specific sources.  
  > *Excruciator* &mdash; Damage that would be dealt by this creature can't be prevented.  
  > *Pinpoint Avalanche* &mdash; this card deals 4 damage to target creature. The damage can't be prevented.  

- [text] `name-matters` &mdash; auc 0.601, 410 cards  
  Effects that care about card names: different names, same name, specific name, etc.  
  > *Thrumming Stone* &mdash; Spells you cast have ripple 4.  
  > *Wake of Destruction* &mdash; Destroy target land and all other lands with the same name as that land.  

- [text] `power-matters` &mdash; auc 0.601, 1423 cards  
  > *Repel Calamity* &mdash; Destroy target creature with power or toughness 4 or greater.  
  > *Golden Ratio* &mdash; Draw a card for each different power among creatures you control.  

- [text] `unnoted-tracked-information` &mdash; auc 0.595, 204 cards  
  Spells or abilities that require tracking events without explicitly noting them. See also [noted tracked information](noted-tracked-information).  
  > *Floating-Dream Zubera* &mdash; When this creature dies, draw a card for each Zubera that died this turn.  
  > *Stonehorn Dignitary* &mdash; When this creature enters, target opponent skips their next combat phase.  

- [text] `scales-with-multiple` &mdash; auc 0.593, 58 cards  
  Cards that scale as you play more copies of themselves.  
  > *Powerstone Shard* &mdash; {T}: Add {C} for each artifact you control named this card.  
  > *Rite of Flame* &mdash; Add {R}{R}, then add {R} for each card named this card in each graveyard.  

- [text] `synergy-desert` &mdash; auc 0.563, 29 cards  
  > *Dune Diviner* &mdash; {1}, Tap an untapped Desert you control: You gain 1 life.  
  > *Failed Fording* &mdash; Return target nonland permanent to its owner's hand. If you control a Desert, surveil 1.  

- [text] `refund` &mdash; auc 0.558, 665 cards  
  Immediately get mana or untapped lands back.  
  > *Azorius Signet* &mdash; {1}, {T}: Add {W}{U}.  
  > *Rakdos Signet* &mdash; {1}, {T}: Add {B}{R}.  

- [text] `delayed-trigger` &mdash; auc 0.554, 1166 cards  
  Create a triggered ability that may trigger later. Similar to a [reflexive trigger](reflexive-trigger).  
  > *Cybermen Squadron* &mdash; Nonlegendary artifact creatures you control have myriad.  
  > *Glimpse of Nature* &mdash; Whenever you cast a creature spell this turn, draw a card.  

- [text] `converge` &mdash; auc 0.551, 49 cards  
  Spells that do something equal to the number of colors spent to cast them.  
  > *Unified Front* &mdash; Create a 1/1 white Kor Ally creature token for each color of mana spent to cast this spell.  
  > *Arcane Omens* &mdash; Target player discards X cards, where X is the number of colors of mana spent to cast this spell.  

- [text] `powerstone-mana` &mdash; auc 0.547, 42 cards  
  Mana that can't be spent to cast nonartifact spells.  
  > *Fallaji Excavation* &mdash; Create three tapped Powerstone tokens. You gain 3 life.  
  > *Powerstone Engineer* &mdash; When this creature dies, create a tapped Powerstone token.  

- [text] `mana-spent-matters` &mdash; auc 0.497, 210 cards  
  Effects that care about the amount, type, and/or qualities of mana spent to do a thing.  
  > *Hired Hexblade* &mdash; When this creature enters, if mana from a Treasure was spent to cast it, you draw a card and you lose 1 life.  
  > *Unravel* &mdash; Counter target spell. If the amount of mana spent to cast that spell was less than its mana value, you draw a card.  

- [text] `color-spent-matters` &mdash; auc 0.492, 114 cards  
  Spells and abilities that care about the color(s) of mana spent on them.  
  > *Tin Street Hooligan* &mdash; When this creature enters, if {G} was spent to cast it, destroy target artifact.  
  > *Steamcore Weird* &mdash; When this creature enters, if {R} was spent to cast it, it deals 2 damage to any target.  

- [text] `synergy-modified` &mdash; auc 0.401, 47 cards  
  > *Upriser Renegade* &mdash; This creature gets +2/+0 for each other modified creature you control.  
  > *Heir of the Ancient Fang* &mdash; This creature enters with a +1/+1 counter on it if you control a modified creature.  

- [text] `tuck-self` &mdash; auc 0.378, 55 cards  
  > *Blue Sun's Zenith* &mdash; Target player draws X cards. Shuffle this card into its owner's library.  
  > *Sanguine Sacrament* &mdash; You gain twice X life. Put this card on the bottom of its owner's library.  

- [text] `set-life-total` &mdash; auc 0.898, 48 cards **(the AUC keeps this one)**  
  Your life total becomes N. See also [life divider](/tags/card/life-divider) and [life doubler](/tags/card/life-doubler).  
  > *Platinum Emperion* &mdash; Your life total can't change.  
  > *Blessed Wind* &mdash; Target player's life total becomes 20.  

- [text] `earthbend` &mdash; auc 0.896, 36 cards **(the AUC keeps this one)**  
  Collection tag used to apply the various tags that comprise the keyword Earthbend. Should be 1:1 with kw:earthbend.  
  > *Earth Village Ruffians* &mdash; When this creature dies, earthbend 2.  
  > *Cracked Earth Technique* &mdash; Earthbend 3, then earthbend 3. You gain 3 life.  

- [text] `keyword-soup` &mdash; auc 0.892, 23 cards **(the AUC keeps this one)**  
  These cards list out all or almost all the keyword abilities found in their set, possibly restricted by color.  

- [text] `leaves-trigger-self` &mdash; auc 0.885, 149 cards **(the AUC keeps this one)**  
  Permanents with abilities that trigger when they leave the battlefield.  
  > *Goblin Firebug* &mdash; When this creature leaves the battlefield, sacrifice a land.  
  > *Servant of Volrath* &mdash; When this creature leaves the battlefield, sacrifice a creature.  

- [text] `prevent-mass-blockers` &mdash; auc 0.880, 40 cards **(the AUC keeps this one)**  
  Cards that sweepingly prevent blocks from happening.  
  > *Bedlam* &mdash; Creatures can't block.  
  > *Razorjaw Oni* &mdash; Black creatures can't block.  

- [text] `copy-legendary` &mdash; auc 0.879, 43 cards **(the AUC keeps this one)**  
  These cards can give you a copy of a legendary permanent you control that you can actually keep (instead of immediately sacrificing).  
  > *Double Major* &mdash; Copy target creature spell you control, except it isn't legendary if the spell is legendary.  
  > *Irenicus's Vile Duplication* &mdash; Create a token that's a copy of target creature you control, except the token has flying and it isn't legendary.  

- [text] `tutor-self` &mdash; auc 0.873, 24 cards **(the AUC keeps this one)**  
  > *Whisper Squad* &mdash; {1}{B}: Search your library for a card named this card, put it onto the battlefield tapped, then shuffle.  
  > *Wretched Throng* &mdash; When this creature dies, you may search your library for a card named this card, reveal it, put it into your hand, then shuffle.  

- [text] `lure-limited` &mdash; auc 0.871, 42 cards **(the AUC keeps this one)**  
  This creature must be blocked, but not necessarily by all creatures like a true lure.  
  > *Gaea's Protector* &mdash; This creature must be blocked if able.  
  > *Satyr Piper* &mdash; {3}{G}: Target creature must be blocked this turn if able.  

- [text] `synergy-shrine` &mdash; auc 0.857, 27 cards **(the AUC keeps this one)**  
  > *Honden of Seeing Winds* &mdash; At the beginning of your upkeep, draw a card for each Shrine you control.  
  > *Honden of Cleansing Fire* &mdash; At the beginning of your upkeep, you gain 2 life for each Shrine you control.  

- [text] `pseudo-proliferate` &mdash; auc 0.855, 37 cards **(the AUC keeps this one)**  
  Effects that sorta-proliferate some counters.  
  > *Gilder Bairn* &mdash; {2}{G/U}, {Q}: Double the number of each kind of counter on target permanent.  
  > *Scale Blessing* &mdash; Bolster 1, then put a +1/+1 counter on each creature you control with a +1/+1 counter on it.  

- [text] `support` &mdash; auc 0.855, 62 cards **(the AUC keeps this one)**  
  Put a +1/+1 counter on each of up to N target creatures.  
  > *Joraga Auxiliary* &mdash; {4}{G}{W}: Support 2.  
  > *Relief Captain* &mdash; When this creature enters, support 3.  

- [text] `tap-fuel-artifact` &mdash; auc 0.853, 94 cards **(the AUC keeps this one)**  
  > *Clock of Omens* &mdash; Tap two untapped artifacts you control: Untap target artifact.  
  > *Waterbending Lesson* &mdash; Draw three cards. Then discard a card unless you waterbend {2}.  

- [text] `drain-life` &mdash; auc 0.851, 373 cards **(the AUC keeps this one)**  
  Hurt your opponent and gain life to match.  
  > *Soul Feast* &mdash; Target player loses 4 life and you gain 4 life.  
  > *Sovereign's Bite* &mdash; Target player loses 3 life and you gain 3 life.  

- [text] `copy-equipment` &mdash; auc 0.849, 23 cards **(the AUC keeps this one)**  
  > *Second Harvest* &mdash; For each token you control, create a token that's a copy of that permanent.  
  > *Masterwork of Ingenuity* &mdash; You may have this Equipment enter as a copy of any Equipment on the battlefield.  

- [text] `donate-rampant-growth` &mdash; auc 0.826, 28 cards **(the AUC keeps this one)**  
  Cards that allow you to ramp another player's mana by putting a land from their (or your) deck onto the battlefield. Compare [donate mana](donate-mana), which lets you add mana directly to their mana   
  > *Emergency Eject* &mdash; Destroy target nonland permanent. Its controller creates a Lander token.  
  > *Veteran Explorer* &mdash; When this creature dies, each player may search their library for up to two basic land cards, put them onto the battlefield, then shuffle.  

- [text] `gains-vigilance` &mdash; auc 0.824, 87 cards **(the AUC keeps this one)**  
  > *Towering Thunderfist* &mdash; {W}: This creature gains vigilance until end of turn.  
  > *Llanowar Cavalry* &mdash; {W}: This creature gains vigilance until end of turn.  

- [text] `retaliate-to-damage` &mdash; auc 0.812, 37 cards **(the AUC keeps this one)**  
  Effects that retaliate to damage inflicted upon you, by benefitting you or punishing the opponent.  
  > *Avenging Arrow* &mdash; Destroy target creature that dealt damage this turn.  
  > *Reciprocate* &mdash; Exile target creature that dealt damage to you this turn.  

- [text] `synergy-flying` &mdash; auc 0.801, 101 cards **(the AUC keeps this one)**  
  > *Serra Aviary* &mdash; Creatures with flying get +1/+1.  
  > *Deluge* &mdash; Tap all creatures without flying.  

- [text] `synergy-trample` &mdash; auc 0.792, 27 cards **(the AUC keeps this one)**  
  > *Tanglesap* &mdash; Prevent all combat damage that would be dealt this turn by creatures without trample.  

- [text] `threshold` &mdash; auc 0.790, 105 cards **(the AUC keeps this one)**  
  Cards that care about you having seven or more cards in your graveyard.  
  > *Deep-Sea Terror* &mdash; This creature can't attack unless there are seven or more cards in your graveyard.  
  > *Metamorphic Wurm* &mdash; This creature gets +4/+4 as long as there are seven or more cards in your graveyard.  

- [text] `mini-refund` &mdash; auc 0.787, 329 cards **(the AUC keeps this one)**  
  Immediately gives you a small amount of mana or untapped lands back (typically no more than about one-third of the mana cost you paid)  
  > *Drake-Skull Cameo* &mdash; {T}: Add {U} or {B}.  
  > *Bloodstone Cameo* &mdash; {T}: Add {B} or {R}.  

- [text] `prevent-cast` &mdash; auc 0.785, 80 cards **(the AUC keeps this one)**  
  > *Steel Golem* &mdash; You can't cast creature spells.  
  > *Grid Monitor* &mdash; You can't cast creature spells.  

- [text] `gives-haste` &mdash; auc 0.781, 608 cards **(the AUC keeps this one)**  
  > *Mass Hysteria* &mdash; All creatures have haste.  
  > *Concordant Crossroads* &mdash; All creatures have haste.  

- [text] `gives-indestructible` &mdash; auc 0.779, 263 cards **(the AUC keeps this one)**  
  > *Terra Eternal* &mdash; All lands have indestructible.  
  > *Darksteel Forge* &mdash; Artifacts you control have indestructible.  

- [text] `burn-player` &mdash; auc 0.775, 1721 cards **(the AUC keeps this one)**  
  > *Boltwave* &mdash; this card deals 3 damage to each opponent.  
  > *Sizzle* &mdash; this card deals 3 damage to each opponent.  

- [text] `group-hug` &mdash; auc 0.772, 394 cards **(the AUC keeps this one)**  
  Cards that can be used to benefit other players, including opponents, usually by giving them resources  
  > *Prosperity* &mdash; Each player draws X cards.  
  > *Vision Skeins* &mdash; Each player draws two cards.  

- [text] `pwdeck-sidekick` &mdash; auc 0.770, 38 cards **(the AUC keeps this one)**  
  Cards from Planeswalker Decks that care about having the corresponding planeswalker out.  
  > *Vivien's Crocodile* &mdash; This creature gets +1/+1 as long as you control a Vivien planeswalker.  
  > *Teferi's Sentinel* &mdash; As long as you control a Teferi planeswalker, this creature gets +4/+0.  

- [text] `hate-artifact` &mdash; auc 0.768, 191 cards **(the AUC keeps this one)**  
  > *Yavimaya Scion* &mdash; Protection from artifacts  
  > *Tel-Jilad Chosen* &mdash; Protection from artifacts  

- [text] `lands-matter` &mdash; auc 0.765, 475 cards **(the AUC keeps this one)**  
  > *Magus of the Coffers* &mdash; {2}, {T}: Add {B} for each Swamp you control.  
  > *Fruition* &mdash; You gain 1 life for each Forest on the battlefield.  

- [text] `theft-creature` &mdash; auc 0.765, 218 cards **(the AUC keeps this one)**  
  > *Switcheroo* &mdash; Exchange control of two target creatures.  
  > *Entrancing Melody* &mdash; Gain control of target creature with mana value X.  

- [text] `synergy-commander` &mdash; auc 0.764, 167 cards **(the AUC keeps this one)**  
  > *Flamekin Herald* &mdash; Commander spells you cast have cascade.  
  > *Slash the Ranks* &mdash; Destroy all creatures and planeswalkers except for commanders.  

- [text] `ritual-untap` &mdash; auc 0.760, 20 cards **(the AUC keeps this one)**  
  Single use effects that untap mana-producing permanents greater than or equal to their cost  
  > *Rewind* &mdash; Counter target spell. Untap up to four lands.  
  > *Llanowar Druid* &mdash; {T}, Sacrifice this creature: Untap all Forests.  

- [text] `card-types-in-graveyard-matter` &mdash; auc 0.754, 101 cards **(the AUC keeps this one)**  
  Cards that care about the card types of cards in a graveyard.  
  > *Lucid Dreams* &mdash; Draw X cards, where X is the number of card types among cards in your graveyard.  
  > *Hound of the Farbogs* &mdash; This creature has menace as long as there are four or more card types among cards in your graveyard.  

- [text] `hate-color-share` &mdash; auc 0.754, 26 cards **(the AUC keeps this one)**  
  > *Earnest Fellowship* &mdash; Each creature has protection from its colors.  
  > *Jaded Response* &mdash; Counter target spell if it shares a color with a creature you control.  


## Proposed: about the card, not a line

Correctly kept out of training. These are the `card_level` candidates: picking a line should not lose them.

- [card] `manaless-value` &mdash; auc 0.734, 195 cards  
  Cards that can provide some amount of value without untapped lands.  
  > *Spellbook* &mdash; You have no maximum hand size.  
  > *Zuran Orb* &mdash; Sacrifice a land: You gain 2 life.  

- [card] `useless-in-singleton-formats` &mdash; auc 0.729, 25 cards  
  Cards that have little to no use in formats that are Singleton (allowing only one of most cards save for basic lands) such as commander  
  > *Thrumming Stone* &mdash; Spells you cast have ripple 4.  
  > *Locket of Yesterdays* &mdash; Spells you cast cost {1} less to cast for each card with the same name as that spell in your graveyard.  

- [card] `manaless-land` &mdash; auc 0.712, 19 cards  
  The vast majority of lands in the game can either tap for mana or be exchanged for another land that does. This tag represents the rare exceptions to that rule.  
  > *Bazaar of Baghdad* &mdash; {T}: Draw two cards, then discard three cards.  
  > *Island of Wak-Wak* &mdash; {T}: Target creature with flying has base power 0 until end of turn.  

- [card] `utility-land` &mdash; auc 0.712, 579 cards  
  > *Bazaar of Baghdad* &mdash; {T}: Draw two cards, then discard three cards.  
  > *Island of Wak-Wak* &mdash; {T}: Target creature with flying has base power 0 until end of turn.  

- [card] `cheaper-than-mv` &mdash; auc 0.682, 1834 cards  
  The actual cost you pay for an effect (or for an alternate mode) will often be lower than the card's mana value.  
  > *Curious Pair // Treats to Share* &mdash; Create a Food token.  
  > *Embereth Shieldbreaker // Battle Display* &mdash; Destroy target artifact.  

- [card] `pwdeck-tutor` &mdash; auc 0.631, 36 cards  
  Cards from Planeswalker Decks that tutor for the corresponding planeswalker.  
  > *Journey for the Elixir* &mdash; Search your library and graveyard for a basic land card and a card named Jiang Yanggu, reveal them, put them into your hand, then shuffle.  

- [card] `weaker-in-singleton-formats` &mdash; auc 0.629, 108 cards  
  Cards that have reduced use in formats that do not allow more than one card with the same name to be used, such as in Commander or Highlander.  
  > *Timberpack Wolf* &mdash; This creature gets +1/+1 for each other creature you control named this card.  
  > *Accumulated Knowledge* &mdash; Draw a card, then draw cards equal to the number of cards named this card in all graveyards.  

- [card] `color-break` &mdash; auc 0.611, 150 cards  
  Cards known to break the modern color pie, granting a color access to something it shouldn't be able to do.  
  > *Acid Rain* &mdash; Destroy all Forests.  
  > *Desert Twister* &mdash; Destroy target permanent.  

- [card] `out-of-color-token` &mdash; auc 0.604, 398 cards  
  Cards which create tokens which are one or more colours the original card isn't.  
  > *Proven Combatant* &mdash; Eternalize {4}{U}{U}  
  > *Ral's Reinforcements* &mdash; Create two 1/1 blue and red Elemental creature tokens.  

- [card] `class-type-only` &mdash; auc 0.599, 54 cards  
  These creatures have only a class type, and no type correlating to whatever fantasy race they might belong to.  
  > *Adarkar Sentinel* &mdash; {1}: This creature gets +0/+1 until end of turn.  
  > *Servant of Volrath* &mdash; When this creature leaves the battlefield, sacrifice a creature.  

- [card] `multiple-species-types` &mdash; auc 0.573, 84 cards  
  Creatures that have two or more types that are considered to be a species, such as "Human" or "Elf"  
  > *Voltaic Construct* &mdash; {2}: Untap target artifact creature.  
  > *Razorfin Hunter* &mdash; {T}: This creature deals 1 damage to any target.  

- [card] `noncreature-typal` &mdash; auc 0.572, 1511 cards  
  Cards that care about creature types, but not necessarily on a creature card-so they're compatible with the Kindred cards from Lorwyn, for example.  
  > *Tivadar's Crusade* &mdash; Destroy all Goblins.  
  > *Ali Baba* &mdash; {R}: Tap target Wall.  

- [card] `mix-and-match` &mdash; auc 0.554, 153 cards  
  Two or more non-evergreen mechanics blended together on the same card.  
  > *Evolution Sage* &mdash; Whenever a land you control enters, proliferate.  
  > *Cutthroat il-Dal* &mdash; This creature has shadow as long as you have no cards in hand.  

- [card] `phyrexian-mana-cost` &mdash; auc 0.543, 37 cards  
  Cards where the casting cost includes phyrexian mana  
  > *Tezzeret's Gambit* &mdash; Draw two cards, then proliferate.  
  > *Gut Shot* &mdash; this card deals 1 damage to any target.  

- [card] `unique-mana-cost` &mdash; auc 0.509, 300 cards  
  This card's mana cost isn't found on any other card.  
  > *Violent Ultimatum* &mdash; Destroy three target permanents.  
  > *Ramses Overdark* &mdash; {T}: Destroy target enchanted creature.  

- [card] `full-refund` &mdash; auc 0.509, 89 cards  
  Cards that give you mana equal to or greater than the amount of mana spent for it, either in the form of a immediately usable mana ability, a ritual effect, or untapped lands  
  > *Burst of Energy* &mdash; Untap target permanent.  
  > *Skirk Prospector* &mdash; Sacrifice a Goblin: Add {R}.  

- [card] `dnd-mechanic` &mdash; auc 0.421, 51 cards  
  Cards named after and representing DnD mechanics.  
  > *Circle of Dreams Druid* &mdash; {T}: Add {G} for each creature you control.  
  > *Breath Weapon* &mdash; this card deals 2 damage to each non-Dragon creature.  

- [card] `doom-blade` &mdash; auc 0.986, 59 cards **(the AUC keeps this one)**  
  2 MV "Destroy target creature, unless it's X"  
  > *Swift Response* &mdash; Destroy target tapped creature.  
  > *Death Stroke* &mdash; Destroy target tapped creature.  

- [card] `offcolor-ability` &mdash; auc 0.838, 313 cards **(the AUC keeps this one)**  
  Abilities with a mana cost outside the card's colors.  
  > *Simic Ragworm* &mdash; {U}: Untap this creature.  
  > *Benalish Heralds* &mdash; {3}{U}, {T}: Draw a card.  

- [card] `hatebear` &mdash; auc 0.829, 60 cards **(the AUC keeps this one)**  
  Creatures that are low-cost (2 MV or less) and have low-power/toughness with relevant effects that may disrupt an opponent's strategy. These are traditionally associated with white.  
  > *Yixlid Jailer* &mdash; Cards in graveyards lose all abilities.  
  > *Imposing Sovereign* &mdash; Creatures your opponents control enter tapped.  


## Proposed: nothing to do with gameplay

Correctly excluded, and they should stay excluded. This is the poison the filter exists to catch.

- [junk] `dnd-monster` &mdash; auc 0.710, 83 cards  
  Cards named after and representing monsters from DnD.  
  > *Adult Gold Dragon* &mdash; Flying, lifelink, haste  
  > *Vampire Spawn* &mdash; When this creature enters, each opponent loses 2 life and you gain 2 life.  

- [junk] `dnd-character` &mdash; auc 0.710, 82 cards  
  Cards that represent Dungeons and Dragons characters: name, rules text, etc. See also the [dungeons and dragons](/tags/artwork/dungeons-and-dragons) art tag.  
  > *Trelasarra, Moon Dancer* &mdash; Whenever you gain life, put a +1/+1 counter on this card and scry 1.  
  > *Gretchen Titchwillow* &mdash; {2}{G}{U}: Draw a card. You may put a land card from your hand onto the battlefield.  

- [junk] `unprinted-token` &mdash; auc 0.706, 80 cards  
  Cards whose tokens haven't yet been printed in paper.  
  > *Errand of Duty* &mdash; Create a 1/1 white Knight creature token with banding.  
  > *Flurry of Horns* &mdash; Create two 2/3 red Minotaur creature tokens with haste.  

- [junk] `staple-with-set-s-mechanic` &mdash; auc 0.704, 1516 cards  
  A common card design that is related to one or more of the main mechanics in a set  
  > *Claim the Precious* &mdash; Destroy target creature. The Ring tempts you.  
  > *Bake into a Pie* &mdash; Destroy target creature. Create a Food token.  

- [junk] `references-keyword` &mdash; auc 0.692, 44 cards  
  Cards that call back to a keyword or mechanic from an older set. It's like the "References/Referenced By" relationship, but for a mechanic instead of an individual card.  
  > *Jukai Trainee* &mdash; Whenever this creature blocks or becomes blocked, it gets +1/+1 until end of turn.  
  > *Bane of Bala Ged* &mdash; Whenever this creature attacks, defending player exiles two permanents they control.  

- [junk] `bear-with-set-s-mechanic` &mdash; auc 0.676, 262 cards  
  A 2/2 for 2 with one of the set's iconic mechanics  
  > *Sculptor of Winter* &mdash; {T}: Untap target snow land.  
  > *Martyr for the Cause* &mdash; When this creature dies, proliferate.  

- [junk] `notorious-templating` &mdash; auc 0.672, 74 cards  
  Cards with effects that have to be templated in such a way that they are confusing to read at first glance. They don't have to be complex effects in practice (such as Animate Dead), but require a larg  
  > *Dead Ringers* &mdash; Destroy two target nonblack creatures unless either one is a color the other isn't. They can't be regenerated.  

- [junk] `day-zero-errata` &mdash; auc 0.652, 33 cards  
  These cards received errata before or immediately after their initial release.  
  > *Walking Atlas* &mdash; {T}: You may put a land card from your hand onto the battlefield.  
  > *Irenicus's Vile Duplication* &mdash; Create a token that's a copy of target creature you control, except the token has flying and it isn't legendary.  

- [junk] `potentially-black-border` &mdash; auc 0.647, 102 cards  
  Cards not intended for constructed play that could have been printed in a vintage/commander legal product instead if they were printed today.  
  > *Gobland* &mdash; this card can't block.  
  > *Sliver of Hope* &mdash; Slivers you control have hope.  

- [junk] `hate-set-mechanic` &mdash; auc 0.589, 253 cards  
  Cards that "hate" on one or more mechanics in the set they were printed in.  
  > *Shoreline Raider* &mdash; Protection from Kavu  
  > *Nath's Buffoon* &mdash; Protection from Elves  

- [junk] `fun-ruling` &mdash; auc 0.588, 306 cards  
  Cards with rulings where the rules manager is having fun with us. Not necessarily laugh-out-loud funny.  
  > *Intangible Vibes* &mdash; All creatures are tokens.  
  > *Braid of Fire* &mdash; Cumulative upkeep-Add {R}.  

- [junk] `meme` &mdash; auc 0.587, 117 cards  
  Cards that have become memes in Magic, or are explicitly based off of memes.  
  > *Counterspell* &mdash; Counter target spell.  
  > *Vindicate* &mdash; Destroy target permanent.  

- [junk] `commander-set-booster-cards` &mdash; auc 0.578, 100 cards  
  Card that debuted in a Commander Set but were only obtainable through boosters of the set it was released with.  
  > *Rootpath Purifier* &mdash; Lands you control and land cards in your library are basic.  
  > *Monumental Corruption* &mdash; Target player draws X cards and loses X life, where X is the number of artifacts you control.  

- [junk] `40k-model` &mdash; auc 0.576, 128 cards  
  Cards named after and representing a Warhammer 40,000 model.  
  > *Venomthrope* &mdash; Flying, deathtouch, hexproof  
  > *Cryptothrall* &mdash; Other artifact creatures you control have hexproof.  

- [junk] `vanity-card` &mdash; auc 0.555, 38 cards  
  Cards named after specific people or real things  
  > *Jayemdae Tome* &mdash; {4}, {T}: Draw a card.  
  > *Jalum Tome* &mdash; {2}, {T}: Draw a card, then discard a card.  

- [junk] `usg-storyline-in-cards` &mdash; auc 0.497, 62 cards  
  > *Darkest Hour* &mdash; All creatures are black.  
  > *Stroke of Genius* &mdash; Target player draws X cards.  

- [junk] `sth-storyline-in-cards` &mdash; auc 0.484, 34 cards  
  > *Death Stroke* &mdash; Destroy target tapped creature.  
  > *Smite* &mdash; Destroy target blocked creature.  

- [junk] `deprecated-p-t-counter` &mdash; auc 0.474, 36 cards  
  In the early days Magic used all kinds of power/toughness modifying counters. Nowadays it just sticks with +1/+1 and -1/-1 counters.  
  > *Armor Thrull* &mdash; {T}, Sacrifice this creature: Put a +1/+2 counter on target creature.  
  > *Dwarven Armorer* &mdash; {R}, {T}, Discard a card: Put a +0/+1 counter or a +1/+0 counter on target creature.  

- [junk] `tmp-storyline-in-cards` &mdash; auc 0.458, 60 cards  
  > *Natural Spring* &mdash; Target player gains 8 life.  
  > *Root Maze* &mdash; Artifacts and lands enter tapped.  

- [junk] `wth-storyline-in-cards` &mdash; auc 0.419, 16 cards  
  > *Vitalize* &mdash; Untap all creatures you control.  
  > *Gerrard's Wisdom* &mdash; You gain 2 life for each card in your hand.  

- [junk] `tapland-with-set-s-mechanic` &mdash; auc 0.999, 81 cards **(the AUC keeps this one)**  
  > *Glacial Floodplain* &mdash; This land enters tapped.  
  > *Sulfurous Mire* &mdash; This land enters tapped.  

- [junk] `threaten-with-set-s-mechanic` &mdash; auc 0.999, 45 cards **(the AUC keeps this one)**  
  > *Besmirch* &mdash; Until end of turn, gain control of target creature and it gains haste. Untap and goad that creature.  
  > *Portent of Betrayal* &mdash; Gain control of target creature until end of turn. Untap that creature. It gains haste until end of turn. Scry 1.  

- [junk] `counterspell-with-set-mechanic` &mdash; auc 0.987, 155 cards **(the AUC keeps this one)**  
  > *Dissolve* &mdash; Counter target spell. Scry 1.  
  > *Hisoka's Defiance* &mdash; Counter target Spirit or Arcane spell.  

- [junk] `naturalize-with-set-mechanic` &mdash; auc 0.962, 62 cards **(the AUC keeps this one)**  
  > *Artisan's Sorrow* &mdash; Destroy target artifact or enchantment. Scry 2.  
  > *Sundering Growth* &mdash; Destroy target artifact or enchantment, then populate.  

- [junk] `giant-growth-with-set-mechanic` &mdash; auc 0.961, 132 cards **(the AUC keeps this one)**  
  > *Honor's Reward* &mdash; You gain 4 life. Bolster 2.  
  > *Monstrous Growth* &mdash; Target creature gets +4/+4 until end of turn.  

- [junk] `ramp-with-set-s-mechanic` &mdash; auc 0.928, 68 cards **(the AUC keeps this one)**  
  > *Sami's Curiosity* &mdash; You gain 2 life. Create a Lander token.  
  > *Fallaji Excavation* &mdash; Create three tapped Powerstone tokens. You gain 3 life.  

- [junk] `burn-with-set-s-mechanic` &mdash; auc 0.917, 261 cards **(the AUC keeps this one)**  
  Burn spells that have the mechanic of the set they debuted in.  
  > *Tarfire* &mdash; this card deals 2 damage to any target.  
  > *Magma Jet* &mdash; this card deals 2 damage to any target. Scry 2.  

- [junk] `discard-with-set-s-mechanic` &mdash; auc 0.864, 181 cards **(the AUC keeps this one)**  
  > *Waking Nightmare* &mdash; Target player discards two cards.  
  > *Delirium Skeins* &mdash; Each player discards three cards.  

- [junk] `token-errata` &mdash; auc 0.860, 47 cards **(the AUC keeps this one)**  
  These cards used to make a different type of token, which has since been updated. For type lines, see [Type Errata](type-errata)  
  > *Carrion Call* &mdash; Create two 1/1 green Phyrexian Insect creature tokens with infect.  
  > *Tooth and Claw* &mdash; Sacrifice two creatures: Create a 3/1 red Beast creature token named Carnivore.  

- [junk] `sneaky-self-trigger` &mdash; auc 0.792, 25 cards **(the AUC keeps this one)**  
  Cards that are worded in a way that makes it easy to miss that they trigger one of their own abilities.  
  > *Mesmeric Sliver* &mdash; All Slivers have "When this permanent enters, you may fateseal 1."  
  > *Ulvenwald Observer* &mdash; Whenever a creature you control with toughness 4 or greater dies, draw a card.  

- [junk] `rules-nightmare` &mdash; auc 0.776, 43 cards **(the AUC keeps this one)**  
  Cards that are known for having interactions that are difficult or nearly impossible to resolve within comprehensive rules  
  > *Gobland* &mdash; this card can't block.  
  > *Harbinger of the Seas* &mdash; Nonbasic lands are Islands.  

- [junk] `unique-cr-reference` &mdash; auc 0.764, 62 cards **(the AUC keeps this one)**  
  There is an entire rule in the CR just to cover this card and no other card.  
  > *Fleshwrither* &mdash; Transfigure {1}{B}{B}  
  > *Frenzy Sliver* &mdash; All Sliver creatures have frenzy 1.  

