#what /custom's chips say about cards that already exist.
#
#a card's STORED line vectors are exactly what the model answers for that card's
#text, so this runs the site's own rule over real cards without calling the
#model service, which has no public address to call from out here anyway. the
#card itself is excluded from its own neighbours, the way the exam scores a
#card: otherwise its own lines are the nearest ten and the vote is its own tags
#read back.
#
#    python tools/show_chips.py --cards 20
#    python tools/show_chips.py --cards 5 --name "Shivan Dragon"
#with DATABASE_URL set. READ ONLY.
#
#WHAT IT CANNOT SAY: the probe was trained on these cards' lines, so the overlap
#printed at the end is optimistic by construction and is NOT the gate. what it
#is for is the faults a number would hide: chip lists that come back empty, the
#same chips on every card, a banned tag leaking through, a type line that drops
#everything.

import os
import sys
import argparse

#a windows console writes unicode fine, a redirected stdout goes through the
#locale codepage instead, and the first card with an accent in its name raises
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
#web/ first: its modules import each other by bare name, railway deploying that
#folder on its own
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, ROOT)


def cards_to_show(conn, how_many, name):
    if name:
        return conn.execute("""
            SELECT oracle_id, name, type_line FROM cards
            WHERE name ILIKE %s ORDER BY name LIMIT %s
        """, ("%" + name + "%", how_many)).fetchall()
    #commander legal, the pool the site's own sentence counts over, and only
    #cards with a line to score
    return conn.execute("""
        SELECT c.oracle_id, c.name, c.type_line FROM cards c
        WHERE c.legal_commander
          AND EXISTS (SELECT 1 FROM lines l WHERE l.oracle_id = c.oracle_id AND NOT l.whole)
        ORDER BY random() LIMIT %s
    """, (how_many,)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=20, help="how many cards to show")
    ap.add_argument("--name", default="", help="show cards matching this name instead of random ones")
    ap.add_argument("--seed", type=float, default=None, help="fix the random sample")
    ap.add_argument("--no-type", action="store_true", help="score as if no type line was typed")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    #imported down here: web/db.py opens its pool the moment it is imported, so
    #the check above has to happen first
    from db import pool
    from views.custom import line_neighbours, tag_chips

    overlaps, counts, leaked = [], [], 0
    with pool.connection() as conn:
        if args.seed is not None:
            conn.execute("SELECT setseed(%s)", (args.seed,))
        banned = {r["tag"] for r in conn.execute("SELECT tag FROM tag_probe WHERE banned")}
        rows = cards_to_show(conn, args.cards, args.name)
        if not rows:
            print("no cards matched")
            return

        for card in rows:
            lines = conn.execute("""
                SELECT line_text, embedding FROM lines
                WHERE oracle_id = %s AND NOT whole ORDER BY id
            """, (card["oracle_id"],)).fetchall()
            vectors = [r["embedding"].to_numpy() for r in lines]
            around = line_neighbours(conn, vectors, card["oracle_id"])
            type_line = "" if args.no_type else card["type_line"]
            chips = [c["tag"] for c in tag_chips(conn, vectors, around, type_line)]
            stored = {r["tag"] for r in conn.execute(
                "SELECT tag FROM card_tags WHERE oracle_id = %s", (card["oracle_id"],))}

            print("\n== " + card["name"] + "   " + (card["type_line"] or ""))
            for r in lines:
                print("   | " + r["line_text"][:96])
            print("   chips:  " + (", ".join(chips) if chips else "(none)"))
            missed = [t for t in chips if t not in stored]
            print("   not among its stored tags: " + (", ".join(missed) if missed else "none"))
            counts.append(len(chips))
            leaked += sum(1 for t in chips if t in banned)
            if chips:
                overlaps.append(sum(1 for t in chips if t in stored) / len(chips))

    counts.sort()
    overlaps.sort()
    print("\n---- over %d cards ----" % len(counts))
    print("chips per card: fewest %d, median %d, most %d" %
          (counts[0], counts[len(counts) // 2], counts[-1]))
    print("cards with fewer than 2: %d" % sum(1 for n in counts if n < 2))
    print("banned tags that got through: %d" % leaked)
    if overlaps:
        print("share of chips the card already carries: median %.2f (optimistic, see the top "
              "of this file)" % overlaps[len(overlaps) // 2])


if __name__ == "__main__":
    sys.exit(main())
