#the exam for ingest/attribute.py: hand judged answers that outlive whatever the
#scorer does today. after an attribute run, prints precision and recall per card:
#    python -m finetune.exam_attribution.
#
#the rule for adding labels: list only the tags a line is GENUINELY about. a tag
#the card carries for reasons outside its rules text (unique-mana-cost is about
#the mana cost, invitational-card about where the card came from).
#
#known and accepted: "modal" lands on the mode lines rather than the "choose two"
#header declaring the modality, because those lines neighbour other cards' mode
#lines and the statistics genuinely say so. consistent, so the header is excluded
#from scoring below rather than counted as a miss

import os
import sys

import psycopg
from psycopg.rows import dict_row

#card name -> {line index (in id order, whole rows excluded) -> tags it is about}.
#a line index that is absent is not scored at all
LABELS = {
    "Shadrix Silverquill": {
        #line 1 is the "choose two" header, excluded: see the modal note above
        0: {"evasion"},
        2: {"donate-token", "selective-group-hug", "modal", "repeatable-creature-tokens", "evasion"},
        3: {"force-draw", "opponent-loses-life", "repeatable-pure-draw", "draw-engine", "repeatable-crime"},
        4: {"gives-pp-counters-to-all", "selective-group-hug", "repeatable-pp-counters", "gains-pp-counters"},
    },
    "Omnath, Locus of Creation": {
        0: {"cantrip", "hand-neutral", "triggered-ability"},
        1: {"times-resolved-matters", "non-mana-ability-mana", "sweeper-one-sided", "landfall",
            "adds-multiple-mana", "group-slug", "mana-producer", "burn-planeswalker",
            "repeatable-lifegain", "repeatable-removal", "burn-player", "triggered-ability"},
    },
    "Kratos, God of War": {
        0: set(),  #"Double strike" is about none of this card's tags
        1: {"catch-22", "burn-player-each", "keyword-anthem", "gives-haste", "symmetrical"},
        2: {"catch-22", "burn-player-each", "symmetrical", "triggered-ability"},
    },
    "The One Ring": {
        #a keyword usually printed on creatures, sitting on an artifact
        0: {"creature-ability-noncreature"},
        #no triggered-ability here: tagger never typed it onto this card, and a
        #label the card does not carry is a hole in the answer key, not a miss
        1: {"gives-player-protection", "damage-prevention-you", "fog-selective"},
        2: {"drawback", "life-for-cards", "unique-counter"},
        3: {"activated-ability", "burst-draw", "draw-engine", "repeatable-pure-draw",
            "hand-positive", "quadratic", "unique-counter", "tome"},
    },
    "Boros Charm": {
        #line 0 is the "Choose one" header, excluded: see the modal note above
        1: {"burn-player", "burn-planeswalker", "single-target-instant-sorcery"},
        2: {"gives-indestructible", "protects-all", "protects-creature"},
        3: {"gives-double-strike", "combat-trick", "single-target-instant-sorcery"},
    },
    "The Great Henge": {
        0: {"discount-self", "scales-with-power"},
        1: {"activated-ability", "adds-multiple-mana", "mana-ability-with-extra-effect",
            "repeatable-lifegain", "utility-mana-rock", "full-refund"},
        2: {"creaturefall", "gives-pp-counters", "repeatable-pp-counters", "draw-engine",
            "repeatable-pure-draw", "triggered-ability"},
    },
    "Goldspan Dragon": {
        0: {"evasion"},
        1: {"attacking-matters-self", "heroic", "hate-target", "repeatable-treasures",
            "synergy-treasure", "triggered-ability"},
        2: {"gives-mana-ability", "refund", "synergy-treasure"},
    },
    "Dauthi Voidwalker": {
        #hatebear is the reason this card is here: it is 2 mana with small stats,
        #which is the mana cost and the power/toughness box, so it belongs to no
        #line and attribute.py is expected to leave it out entirely
        0: {"evasion", "restricted-blocker"},
        1: {"graveyard-seal", "aesthetic-counter"},
        2: {"activated-ability", "free-cast-another", "gives-castable-from-exile",
            "theft-cast", "martyr"},
    },
    "Professional Face-Breaker": {
        0: {"evasion"},
        1: {"combat-ramp", "repeatable-treasures", "synergy-treasure", "per-player",
            "triggered-ability"},
        2: {"activated-ability", "free-sacrifice-outlet", "impulsive-curiosity",
            "repeatable-impulsive-draw", "synergy-treasure"},
    },
}


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    conn = psycopg.connect(db_url, row_factory=dict_row)

    TP = FP = FN = 0
    for name, per_line in LABELS.items():
        card = conn.execute("SELECT oracle_id FROM cards WHERE name = %s", (name,)).fetchone()
        if card is None:
            print("MISSING CARD: " + name + " (renamed, or not in this database)")
            continue
        lines = conn.execute("""
            SELECT id, line_text FROM lines
            WHERE oracle_id = %s AND NOT whole ORDER BY id
        """, (card["oracle_id"],)).fetchall()
        tp = fp = fn = 0
        print("== " + name)
        for idx, want in sorted(per_line.items()):
            if idx >= len(lines):
                print("  line " + str(idx) + " no longer exists, the card's text changed")
                continue
            line = lines[idx]
            got = {r["tag"] for r in conn.execute(
                "SELECT tag FROM line_tags WHERE line_id = %s", (line["id"],)).fetchall()}
            tp += len(got & want)
            fp += len(got - want)
            fn += len(want - got)
            print("  " + line["line_text"][:58])
            if got - want:
                print("     wrong: " + ", ".join(sorted(got - want)))
            if want - got:
                print("     missed: " + ", ".join(sorted(want - got)))
            if not (got - want) and not (want - got):
                print("     exact")
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        print("  precision %.0f%%  recall %.0f%%" % (100 * p, 100 * r))
        TP += tp
        FP += fp
        FN += fn

    p = TP / max(TP + FP, 1)
    r = TP / max(TP + FN, 1)
    print()
    print("OVERALL precision %.0f%%  recall %.0f%%  (tp %d fp %d fn %d)" % (100 * p, 100 * r, TP, FP, FN))
    conn.close()


if __name__ == "__main__":
    main()
