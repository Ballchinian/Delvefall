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

#(anchor, match), must display at or above the gate. exam_concepts.md "Pairs".
#two fail today and are kept because they are the gap: Smothering Tithe against
#Ghostly Prison scores a raw 0.00, the two sharing no tag whatsoever, and
#Sakura-Tribe Elder against Wood Elves lands at 75% just under the gate
PAIRS = [
    ("Shadrix Silverquill", "Gluntch, the Bestower"),
    ("Rhystic Study", "Mystic Remora"),
    ("Smothering Tithe", "Ghostly Prison"),
    ("Grave Pact", "Dictate of Erebos"),
    ("Sakura-Tribe Elder", "Wood Elves"),
]

#(name, anchor, closer, further, known_fail). exam_concepts.md "Triplets", closer must
#beat further. B fails because the scorer overweights mechanism flavored tags
#(removal-destroy). D is the one to watch: outlet and payoff share every sacrifice
#tag, so tag overlap alone has little to separate them on
TRIPLETS = [
    ("A selective hug", "Shadrix Silverquill", "Gluntch, the Bestower", "Font of Mythos", False),
    ("B role beats verb", "Murder", "Swords to Plowshares", "Day of Judgment", True),
    ("C tax beats giving", "Rhystic Study", "Smothering Tithe", "Howling Mine", False),
    ("D outlet is not payoff", "Ashnod's Altar", "Phyrexian Altar", "Blood Artist", False),
    ("E land ramp is not artifact ramp", "Rampant Growth", "Sakura-Tribe Elder", "Sol Ring", False),
    ("F drain payoff is not sacrifice tax", "Zulaport Cutthroat", "Blood Artist", "Grave Pact", False),
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
