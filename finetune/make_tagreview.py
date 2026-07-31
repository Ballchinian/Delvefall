#builds finetune/testing_list/make_tagreview.md, the hand judged answer to "is this
#tag about what the rules text says?"
#
#learnable_tags() in make_training.py keeps a tag if the CURRENT model puts its
#cards in one tight blob, which is a different question and in the 0.5 to 0.75
#band mostly a wrong one: ramp (0.638), rummage (0.541), scry-like (0.525),
#converge (0.538) and triggered-ability (0.727) are all printed in plain words
#and all excluded. using a model to decide what its successor may learn is
#circular, and it costs exactly the mechanics a retrain is meant to fix.
#
#so the AUC answers "already well represented" and this file answers "learnable
#in principle".
#    python finetune/make_tagreview.py
#with DATABASE_URL set. it MERGES: verdicts already in make_tagreview.md win and
#anything new arrives as ?, so rerunning after a tagger update loses no decision

import os
import re
import sys
import json

import psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "traindata")
#with the other hand-marked files, not beside the script: nothing can rebuild the
#verdicts in it, and it is an INPUT on every run after the first
REVIEW = os.path.join(HERE, "testing_list", "make_tagreview.md")

#the four verdicts and what each means downstream:
#  text  the rules text says this. train on it, attribute it to lines normally
#  card  true of the card but not of any one line (mana cost, type line, colour
#        identity). never a training pair, and the step 2 card_level candidate:
#        it should survive picking a line, not vanish
#  junk  not about gameplay at all (provenance, art, a rules curiosity). never
#        train, never attribute
#  ?     not yet judged
VERDICTS = ("text", "card", "junk", "?")

#seeds, and only for tags make_tagreview.md has never listed. a verdict already in
#the file wins, so revising one means editing the file rather than this dict.
#
#the typal-* and synergy-* families are settled by counting: of the 42 typal tags
#with 20+ cards, 89% of their cards print the thing the tag names in their own
#rules text, and the named creature types are at 100% (typal-vampire 82 of 82,
#typal-zombie 120 of 120). synergy-* is 80% the same way. the handful reading 0%
#are slug WORDING rather than absent concepts, a card tagged synergy-blocker
#saying "blocks" and typal-coupling never naming itself at all. the tag goes on
#the card that cares about the type, not on every card that is that type
PROPOSED = {
    #plainly printed on the card
    "triggered-ability": "text", "symmetrical": "text", "burn-you": "text",
    "hate-green": "text", "gains-vigilance": "text", "toughness-matters": "text",
    "hate-artifact": "text", "untracked-indefinite-effect": "text",
    "mini-refund": "text", "force-attacker": "text", "gives-haste": "text",
    "cost-ignorer": "text", "copy-equipment": "text", "ritual": "text",
    "pseudo-proliferate": "text", "drain-life": "text", "burn-player": "text",
    "synergy-flying": "text", "lure-limited": "text", "leaves-trigger-self": "text",
    "drawback": "text", "synergy-commander": "text", "synergy-token-creature": "text",
    "protects-creature": "text", "hate-discard": "text", "synergy-vehicle": "text",
    "card-types-in-graveyard-matter": "text", "support": "text", "earthbend": "text",
    "tutor-self": "text", "bribery": "text", "group-hug": "text",
    "theft-creature": "text", "copy-legendary": "text", "prevent-mass-blockers": "text",
    "gives-shroud": "text", "lands-matter": "text", "gives-indestructible": "text",
    "inverted-effects": "text", "donate-rampant-growth": "text", "hate-low-power": "text",
    "repeatable-removal": "text", "hand-negative": "text", "ferocious": "text",
    "donate-token": "text", "scales-with-multiple": "text", "keyword-soup": "text",
    "synergy-trample": "text", "tap-fuel-artifact": "text", "non-mana-ability-mana": "text",
    "discard-outlet": "text", "exile-self": "text", "per-player": "text",
    "hellbent": "text", "ritual-untap": "text", "opponent-chooses": "text",
    "self-replacement-effect": "text", "mana-value-matters": "text",
    "synergy-shrine": "text", "refund": "text", "manaless-value": "text",
    "hate-white": "text", "synergy-snow": "text", "threshold": "text",
    "synergy-desert": "text", "power-matters-self": "text", "rhystic": "text",
    "reflexive-trigger": "text", "retaliate-to-damage": "text", "punisher": "text",
    "cards-in-graveyard-matter": "text", "castable-from-exile": "text",
    "type-change": "text", "ramp": "text", "clash-like": "text", "pseudo-fog": "text",
    "defector": "text", "exponential": "text", "power-matters": "text",
    "delayed-trigger": "text", "unique-counter": "text", "hate-blue": "text",
    "scales-with-power": "text", "the-ring-tempts-you": "text", "synergy-island": "text",
    "discarded-type-matters": "text", "mana-spent-matters": "text",
    "synergy-treasure": "text", "hate-set-mechanic": "text", "synergy-modified": "text",
    "name-matters": "text", "color-spent-matters": "text", "references-keyword": "text",
    "set-life-total": "text", "hate-color-share": "text", "long-term-impulsive-draw": "text",
    "amount-spent-matters": "text", "full-refund": "text", "rummage": "text",
    "power-matters-total": "text", "converge": "text", "synergy-legendary": "text",
    "multiplayer": "text", "scry-like": "text", "prevent-cast": "text",
    "lockdown-creature": "text", "tuck-self": "text", "hate-token": "text",

    #true of the card, not of any line on it
    "color-break": "card", "unique-mana-cost": "card", "phyrexian-mana-cost": "card",
    "utility-land": "card", "class-type-only": "card", "multiple-species-types": "card",

    #nothing to do with how the card plays
    "meme": "junk", "dnd-monster": "junk", "rules-nightmare": "junk",
    "potentially-black-border": "junk", "fun-ruling": "junk", "day-zero-errata": "junk",
    "tmp-storyline-in-cards": "junk", "wth-storyline-in-cards": "junk",
    "usg-storyline-in-cards": "junk", "sth-storyline-in-cards": "junk",
    "40k-model": "junk", "commander-set-booster-cards": "junk", "vanity-card": "junk",
    "deprecated-p-t-counter": "junk",

    #tags the seed-averaged AUC excludes where a single draw did not. cantrip
    #among them shows how much a lone draw moves the middle of the range
    "cantrip": "text", "hate-red": "text", "repeatable-mulch": "text",
    "power-matters-total": "text", "leaves-battlefield-trigger": "text",
    "synergy-party": "text", "synergy-enchantment": "text", "auto-buyback": "text",
    "selective-group-hug": "text", "consult-cast": "text", "aikido": "text",
    "graveyard-order-matters": "text", "times-resolved-matters": "text",
    "synergy-planeswalker": "text", "hand-size-matters": "text",
    "counters-matter": "text", "catch-up": "text", "creature-count-matters": "text",
    "synergy-plains": "text", "aesthetic-counter": "text", "faux-targeting": "text",
    "mana-sink": "text", "donate": "text", "opponent-lifegain": "text",
    "morbid": "text", "cheaper-than-mv": "text", "tutor-copy": "text",
    "reanimate-cast": "text", "undergrowth": "text", "restock-self": "text",
    "unpreventable-damage": "text", "powerstone-mana": "text", "dnd-mechanic": "text",
    "unnoted-tracked-information": "text", "unique-counter": "text",
    "gives-castable-from-exile": "text", "morbid-like": "text",
    "dnd-character": "junk", "staple-with-set-s-mechanic": "junk",
    "notorious-templating": "junk", "unprinted-token": "junk",
    "out-of-color-token": "card", "manaless-land": "card",
    #the examples settle these: Traumatize mills half a library and Wanted
    #Scoundrels hands an opponent Treasure, which is the text saying exactly the
    #thing the tag is named for
    "division": "text", "donate-mana": "text",

    #tags whose definition reaches for something off the line. the model is
    #shown one line of rules text and nothing else, so a tag depending on the
    #mana cost, the power and toughness or the card's colours cannot be learned
    #from what it sees, however true it is. tagger's own descriptions convict
    #these, each naming something the line does not carry:
    "cheaper-than-mv": "card",      #"lower than the card's mana value"
    "hatebear": "card",             #"low-cost (2 MV or less) and low power/toughness"
    "doom-blade": "card",           #'2 MV "Destroy target creature, unless it is X"'
    "offcolor-ability": "card",     #"a mana cost outside the card's colors"
    "full-refund": "card",          #"mana equal to or greater than the amount spent"
    "manaless-value": "card",       #"value without untapped lands", ie weigh every cost
    #and the same test applied to history and wording rather than to the card:
    "unique-cr-reference": "junk",  #"an entire rule in the CR just to cover this card"
    "references-keyword": "junk",   #"call back to a keyword from an older set"
    "sneaky-self-trigger": "junk",  #"worded so it is easy to miss", a note on phrasing

    #tags the AUC keeps, found by scanning the kept list for the shapes judged
    #junk or card on the excluded side. the set-mechanic family scores 0.86 to
    #0.999 because "enters tapped" templating really is distinctive text, which
    #is the point: a high AUC says a tag is EASY TO SPOT, never that it is worth
    #learning
    "token-errata": "junk", "discard-with-set-s-mechanic": "junk",
    "burn-with-set-s-mechanic": "junk", "ramp-with-set-s-mechanic": "junk",
    "threaten-with-set-s-mechanic": "junk", "tapland-with-set-s-mechanic": "junk",
    #judged text: "as long as you control a Vivien planeswalker" names a
    #planeswalker in the text, which is a pattern a model can read. where the
    #card came from is trivia, but what it says about a planeswalker is not
    "pwdeck-sidekick": "text",
}

#the kept side needs examining too, or a tag the AUC waves through gets trained
#on with nobody having asked. reviewing all 547 is not an evening well spent, so
#it is filtered to the shapes that turned out junk or card on the excluded side
SUSPECT_KEPT = (
    r"storyline|booster|-model$|^40k|^dnd-|errata|black-border|vanity|invitational"
    r"|set-s?-mechanic|^staple|^bear-with|^meme|fun-ruling|notorious|rules-nightmare"
    r"|mana-cost|^utility-land|^class-type|species-types|^color-break|^manaless-land"
    r"|singleton-formats|^pwdeck|multiplayer"
)


def inherit_verdicts(parents, proposed):
    #a slug pattern is the wrong tool for finding a family: SUSPECT_KEPT looks for
    #"set-s-mechanic" and sails past counterspell-with-set-mechanic,
    #giant-growth-with-set-mechanic and naturalize-with-set-mechanic, spelled
    #without the s, all three in the training set at AUC 0.96 to 0.99.
    #
    #so this asks tagger's TREE instead of the spelling.
    #staple-with-set-s-mechanic is a root with sixteen children, each naming a
    #design slot ("bear" is a 2/2 for 2), so a tag under a junk root is junk until
    #someone says otherwise. same principle as BLOCKED_ROOTS in ingest/tags.py.
    #a verdict in the file still wins, so an inherited proposal is never a decision
    out = {}
    for tag in parents:
        seen, frontier = set(), list(parents.get(tag, ()))
        while frontier:
            up = frontier.pop()
            if up in seen:
                continue
            seen.add(up)
            if proposed.get(up) in ("junk", "card"):
                out[tag] = proposed[up]
                break
            frontier.extend(parents.get(up, ()))
    return out


def read_verdicts():
    #make_training.py imports this rather than keeping its own copy of the regex,
    #so the two can never drift about what the file says
    if not os.path.exists(REVIEW):
        return {}
    out = {}
    for line in open(REVIEW, encoding="utf-8"):
        m = re.match(r"^- \[([a-z?]+)\]\s+`([a-z0-9-]+)`", line.strip())
        if m and m.group(1) in VERDICTS:
            out[m.group(2)] = m.group(1)
    return out


def trainable_tags(scores, bar):
    #THE one place deciding which tags the pipeline may train on: make_training.py
    #builds the pairs from this and exam_tags.py scores against it, so a model is
    #never judged on a tag set it was not taught.
    #
    #the review outranks the AUC both ways, the two answering different questions:
    #  rescued  ramp, rummage, scry-like, converge and triggered-ability are
    #           printed in plain words and the AUC excludes them
    #  removed  the *-with-set-s-mechanic family scores 0.86 to 0.999 on
    #           templating alone, and is still set-design trivia
    #
    #an unreviewed tag falls through to the AUC, the review covering the excluded
    #side plus the suspicious kept ones rather than all 706. a tag left at ?
    #counts as unlearnable: not judged is not approved
    verdicts = read_verdicts()
    auc_keep = {t for t, a in scores.items() if a >= bar}
    if not verdicts:
        return auc_keep, [], []
    out, rescued, removed = set(), [], []
    for tag in scores:
        verdict = verdicts.get(tag)
        if verdict == "text":
            out.add(tag)
            if tag not in auc_keep:
                rescued.append(tag)
        elif verdict in ("card", "junk", "?"):
            if tag in auc_keep:
                removed.append(tag)
        elif tag in auc_keep:
            out.add(tag)
    return out, sorted(rescued), sorted(removed)


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = os.path.join(HERE, "..", ".env")
        if os.path.exists(env_path):
            for raw in open(env_path, encoding="utf-8"):
                if raw.strip().startswith("DATABASE_URL="):
                    db_url = raw.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    path = os.path.join(DATA_DIR, "tag_learnability.json")
    if not os.path.exists(path):
        print("no tag_learnability.json, run: python finetune/make_training.py --tags-only")
        sys.exit(1)
    blob = json.load(open(path, encoding="utf-8"))
    auc, bar = blob["auc"], blob["threshold"]

    conn = psycopg.connect(db_url)
    counts = {t: c for t, c in conn.execute("SELECT tag, card_count FROM tags")}
    desc = {t: (d or "").strip() for t, d in conn.execute("SELECT tag, description FROM tags")}
    parents = {t: list(p or ()) for t, p in conn.execute("SELECT tag, parents FROM tags")}
    existing = read_verdicts()
    #ancestry consults the file's verdicts as well as the proposals, or a root
    #judged in the file rather than the dict would never reach its children
    inherited = inherit_verdicts(parents, {**PROPOSED, **existing})

    #short ones: a whole paragraph of oracle text does not help anyone judge a
    #tag at a glance
    print("pulling examples...")
    examples = {}
    for tag, name, text in conn.execute("""
        WITH one AS (SELECT oracle_id FROM lines WHERE NOT whole
                     GROUP BY oracle_id HAVING count(*) = 1),
        pick AS (
            SELECT ct.tag, c.name, l.line_text,
                   row_number() OVER (PARTITION BY ct.tag ORDER BY length(l.line_text)) AS rn
            FROM card_tags ct
            JOIN one o ON o.oracle_id = ct.oracle_id
            JOIN lines l ON l.oracle_id = o.oracle_id AND NOT l.whole
            JOIN cards c ON c.oracle_id = o.oracle_id
            WHERE NOT ct.inherited AND length(l.line_text) BETWEEN 20 AND 140
        )
        SELECT tag, name, line_text FROM pick WHERE rn <= 3
    """):
        examples.setdefault(tag, []).append((name, text))
    conn.close()

    excluded = sorted((t for t, a in auc.items() if a < bar), key=lambda t: -auc[t])
    #three ways a kept tag reaches the review: its slug looks like something
    #already judged junk, the TREE puts it under something judged junk (catching
    #families not spelled alike, which the slug missed), or a verdict already
    #exists for it, in which case it belongs where it can be argued with
    flagged = sorted((t for t, a in auc.items()
                      if a >= bar and (re.search(SUSPECT_KEPT, t) or t in inherited
                                       or t in PROPOSED or t in existing)),
                     key=lambda t: -auc[t])
    kept_side = set(flagged)

    def verdict(tag):
        if tag in existing:
            return existing[tag]
        if tag in PROPOSED:
            return PROPOSED[tag]
        if tag in inherited:
            return inherited[tag]
        #a rule rather than fifty dictionary lines, so a new typal tag next set
        #arrives already judged
        if tag.startswith("typal-") or tag.startswith("synergy-"):
            return "text"
        return "?"

    #a judged tag that fell out of the AUC population (renamed by tagger, or its
    #single-line cards dropped under 10) is still listed, or regenerating would
    #silently forget a human's decision. it keeps its verdict, minus a score
    unmeasured = sorted(t for t in existing if t not in auc)

    groups = {"?": [], "text": [], "card": [], "junk": []}
    for tag in excluded + flagged + unmeasured:
        groups[verdict(tag)].append(tag)

    os.makedirs(os.path.dirname(REVIEW), exist_ok=True)
    with open(REVIEW, "w", encoding="utf-8") as f:
        f.write("""# Which tags are about the rules text?

The hand-judged answer to a question the AUC bar cannot answer.
`finetune/make_training.py` keeps a tag if the current model already clusters it, which is
a different question, and in the middle of the range mostly a wrong one: `ramp`,
`rummage`, `scry-like`, `converge` and `triggered-ability` are all printed in plain words
on the card and all excluded, because the model doing the judging does not cluster them.
Using a model to decide what its successor may learn is circular.

So this file decides instead. The AUC keeps a smaller job: it says a tag is *already well
represented*, not that it is *learnable in principle*.

**The test: can the card's own text infer the tag it is assigned?** The model is shown one
line of rules text and nothing else. Not the mana cost, not the type line, not the power
and toughness, not the set, not even the card's name. So a tag can be perfectly true, and
useful, and still be unlearnable here, because what it depends on is not in front of the
model. Tagger's own descriptions convict several outright: `hatebear` is "low-cost (2 MV
or less) and low power/toughness", `offcolor-ability` is "a mana cost outside the card's
colors". Both real, neither visible.

## How to review

Every tag below carries a verdict in brackets. Change the word if it is wrong, leave it
if it is right. Nothing else in the file matters, and rerunning `make_tagreview.py` keeps
whatever is written here.

| verdict | means | what it changes |
| --- | --- | --- |
| `text` | the card's own text can infer it | the model trains on it, and picking a line can land it on that line |
| `card` | true of the card, not of any one line | never trained on. Picking a line sets it aside today; whether it should instead ride every line is what `card_level` has to settle, see below |
| `junk` | nothing to do with how the card plays | never trained on, and picking a line always sets it aside |
| `?` | not judged yet | treated as `junk` for training, so an unreviewed tag is never learned by accident |

**What none of this takes away.** The chips under a card come from `card_tags`, so every
tag stays on the page whatever its verdict here. A whole-card search, which is the
default, reads every tag exactly as it does today: `vanity-card` still shows and still
scores. The verdict only decides what happens when a line is picked, and even then the tag
is not gone, it goes to the `aside` state, greyed with an explanation, and one click puts
it back. A wrong verdict costs a tag sitting aside when it should have counted, not a tag
vanishing.

**Start with the `?` section**, it is the short one and the only part with no read on it
at all. The `text` section is the long one but it is skimmable: the claim is that every
tag in it is printed on the card in words, so anything that is not should jump out.

The `typal-*` and `synergy-*` families are pre-answered as `text` by a rule rather than
one line each, so a new creature type next set arrives already judged. The evidence: of
the 42 `typal-` tags with 20 or more cards, 89% of their cards print the thing the tag
names in their own rules text, and the named creature types are at 100% (`typal-vampire`
82 of 82, `typal-zombie` 120 of 120). `synergy-*` is 80% the same way. The few reading 0%
are slug wording rather than missing concepts: a card tagged `synergy-blocker` says
"blocks", not "blocker". Disagreeing with the family call means changing the rule in
`make_tagreview.py`, not the fifty lines below.

## Before growing the `card` pile

TODO.md's step two says to revive `card_level` so those tags ride every line instead of
being set aside. Attaching every unexplained tag to every line is the single largest
source of false positives on the hand-labelled cards, worth 58% -> 88% precision to stop
doing, so it is not a small thing to undo. `ingest/attribute.py` carries the detail.

What makes `card_level` worth a second look is this review. What leaked was attaching
*every* unexplained tag, and most unexplained tags are not card-shaped, they are just
weakly evidenced. A hand-judged `card` list is a different proposition: eight tags, each
genuinely about the card, rather than a long tail. So the pile below is small on purpose.
If it grows past a couple of dozen, that is a sign the verdict is being used as a dumping
ground and the leak is coming back.

""")
        f.write("Counts: " + ", ".join("%s %d" % (k, len(groups[k])) for k in VERDICTS
                                       if groups[k]) + ".\n")

        for kind, title, blurb in [
            ("?", "Unjudged",
             "No confident read on these. The two families above are most of it."),
            ("text", "Proposed: about the rules text (rescue these)",
             "Excluded today, and every one of them is printed on the card in words."),
            ("card", "Proposed: about the card, not a line",
             "Correctly kept out of training, but they are the `card_level` candidates for "
             "step 2: picking a line should not lose them."),
            ("junk", "Proposed: nothing to do with gameplay",
             "Correctly excluded, and they should stay excluded. This is the poison the "
             "filter exists to catch."),
        ]:
            if not groups[kind]:
                continue
            f.write("\n## " + title + " (" + str(len(groups[kind])) + ")\n\n" + blurb + "\n\n")
            for tag in groups[kind]:
                #judging a KEPT tag junk removes training data rather than adding
                #it, so each one says which side of the bar it came from
                side = " **(the AUC keeps this one)**" if tag in kept_side else ""
                score = ("auc %.3f" % auc[tag]) if tag in auc else "not measured this round"
                f.write("- [" + verdict(tag) + "] `" + tag + "` "
                        + "&mdash; " + score + ", %d cards" % counts.get(tag, 0)
                        + side + "  \n")
                if desc.get(tag):
                    f.write("  " + desc[tag].replace("\n", " ")[:200] + "  \n")
                for name, text in examples.get(tag, [])[:2]:
                    f.write("  > *" + name + "* &mdash; " + text.replace("\n", " ") + "  \n")
                f.write("\n")

    print("wrote " + REVIEW)
    for k in VERDICTS:
        print("  %-5s %d" % (k, len(groups[k])))
    print("\nedit the verdicts in that file, then rerun this to check it parses.")


if __name__ == "__main__":
    main()
