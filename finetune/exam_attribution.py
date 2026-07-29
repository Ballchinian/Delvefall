#the exam for ingest/attribute.py, the same idea as the axis files in
#testing_list: hand-judged answers that outlive whatever the scorer does
#today. run it from the repo root with DATABASE_URL set, after an attribute
#run, and it prints precision and recall per card and overall:
#    python -m finetune.exam_attribution
#
#the labels were read off the live site card by card. the rule for
#adding more: list ONLY the tags a line is genuinely about. a tag the card
#carries for reasons outside its rules text (unique-mana-cost, which is about
#the mana cost, or invitational-card, which is about where the card came
#from) belongs to NO line, so it goes in no set here and attribute.py is
#expected to leave it out of line_tags entirely. whole-card searches read
#card_tags and still see it, so nothing is lost by that.
#
#known and accepted: "modal" lands on a modal card's mode lines rather than
#on the "choose two" header that declares the modality. the mode lines
#neighbour other cards' mode lines, so the statistics genuinely say that, and
#it is consistent, so the header line is excluded from scoring below rather
#than counted as a miss.

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
