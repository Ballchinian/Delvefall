#the axis-2 exam: scores common/concept.py against testing_list/axis2.md plus the
#judged separation pairs, showing raw and displayed side by side so the
#calibration map stays honest.
#    python -m finetune.exam_concepts
#with DATABASE_URL set

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import psycopg
from common.concept import raw_sim, to_display, MIN_CONCEPT

#(anchor, match), must display at or above the gate. axis2.md "Pairs"
PAIRS = [
    ("Shadrix Silverquill", "Gluntch, the Bestower"),
]

#(name, anchor, closer, further, known_fail). axis2.md "Triplets", closer must
#beat further. B fails because the scorer overweights mechanism flavored tags
#(removal-destroy)
TRIPLETS = [
    ("A selective hug", "Shadrix Silverquill", "Gluntch, the Bestower", "Font of Mythos", False),
    ("B role beats verb", "Murder", "Swords to Plowshares", "Day of Judgment", True),
]

#judged non-matches, printed for eyeballing: these should sit well under the
#gate, since the concept axis must not blur what axis 1 keeps apart
SEPARATION = [
    ("Sol Ring", "Ulvenwald Captive // Ulvenwald Abomination"),
    ("Merfolk Looter", "Rummaging Goblin"),
    ("Howling Mine", "Underworld Dreams"),
]


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
