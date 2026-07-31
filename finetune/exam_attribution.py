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

#both invocation styles work: -m puts the repo root on the path, a direct path
#puts only finetune/ there, and examfile has to be importable either way
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import examfile


def load_labels():
    #card -> {line index: tags it is about}. "(none)" is an empty set, scored and
    #expecting nothing; a line index absent from the file is not scored at all
    labels = {}
    for e in examfile.read("exam_attribution")["Labels"]:
        per = {}
        for label, body in e["fields"].items():
            if not label.startswith("Line "):
                continue
            per[int(label.split()[1])] = set() if body == "(none)" else {
                t.strip() for t in body.split(",") if t.strip()}
        labels[e["fields"]["Card"]] = per
    return labels

LABELS = load_labels()


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
