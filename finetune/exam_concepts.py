#the axis-2 exam: scores common/concept.py against testing_list/exam_concepts.md plus the
#judged separation pairs, showing raw and displayed side by side so the
#calibration map stays honest.
#    python -m finetune.exam_concepts
#with DATABASE_URL set

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import psycopg
from common.concept import raw_sim, to_display, MIN_CONCEPT

#both invocation styles work: -m puts the repo root on the path, a direct path
#puts only finetune/ there, and examfile has to be importable either way
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import examfile

#all three lists come from testing_list/exam_concepts.md, so the file people edit
#is the file that scores. PAIRS must display at or above the gate, TRIPLETS need
#Closer to beat Further, and SEPARATION is printed rather than scored: each entry
#is where it should be today and must not drift up through the gate
_S = examfile.read("exam_concepts")
PAIRS = [(e["fields"]["Anchor"], e["fields"]["Match"]) for e in _S["Pairs"]]
TRIPLETS = [(e["fields"]["Test"], e["fields"]["Anchor"], e["fields"]["Closer"],
             e["fields"]["Further"], e["note"].upper().startswith("FAILS"))
            for e in _S["Triplets"]]
SEPARATION = [(e["fields"]["Anchor"], e["fields"]["NOT"]) for e in _S["Separations"]]


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    conn = psycopg.connect(db_url)

    def oid(name):
        row = conn.execute("SELECT oracle_id FROM cards WHERE name = %s", (name,)).fetchone()
        if not row:
            sys.exit("card not in database: " + name)
        return row[0]

    score = 0
    total = 0
    print("pairs (gate: displayed >= " + str(MIN_CONCEPT) + ")")
    for a, b in PAIRS:
        raw = raw_sim(conn, oid(a), oid(b))
        shown = to_display(raw)
        ok = shown >= MIN_CONCEPT
        total += 1
        score += ok
        print("  %s %s vs %s: raw %.2f -> %d%%" % ("PASS" if ok else "FAIL", a, b, raw, shown))

    print("triplets (closer must beat further)")
    for name, anchor, closer, further, known_fail in TRIPLETS:
        a = oid(anchor)
        rc, rf = raw_sim(conn, a, oid(closer)), raw_sim(conn, a, oid(further))
        ok = rc > rf
        total += 1
        score += ok
        tag = "PASS" if ok else ("known FAIL" if known_fail else "FAIL")
        print("  %s %s: %s %d%% vs %s %d%%" % (tag, name, closer, to_display(rc), further, to_display(rf)))

    print("separation (should sit well under the gate)")
    for a, b in SEPARATION:
        raw = raw_sim(conn, oid(a), oid(b))
        print("  %s vs %s: raw %.2f -> %d%%" % (a, b, raw, to_display(raw)))

    conn.close()
    print(str(score) + "/" + str(total))


if __name__ == "__main__":
    main()
