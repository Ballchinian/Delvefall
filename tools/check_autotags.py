#does web/autotags.py still do what finetune/exam_autotags.py does?
#
#the chip rule was PORTED, and the numbers behind it (98% marked precision at 5
#chips, list overlap 0.71) belong to the exam's copy. a constant nudged on one
#side, or a roll-up that takes a sum where the other takes a best, and the site
#quietly stops being the thing that was measured.
#
#    python tools/check_autotags.py --cards 50
#with DATABASE_URL set. READ ONLY.
#
#BOTH SIDES GET THE SAME INPUTS. each card's line vectors, its ten nearest
#neighbours and their tags, and its probe scores are fetched ONCE out of the
#live database, then handed to the exam's own functions and to the site's. so a
#difference here is a difference in the two rules and nothing else.
#
#that is deliberately not how the exam runs on its own: it reads a frozen copy
#of the tables and scores each card with probe_crossfit.npz, the half-probe that
#never saw it, which is what makes ITS published numbers honest. neither of
#those belongs in a question about whether two pieces of code agree.

import os
import sys
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
#web/ first, its modules importing each other by bare name
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "finetune"))
sys.path.insert(0, ROOT)

#the exam is numbered in ints: lines and tags are indexes into its frozen
#arrays. the site is named in text. this stands in for its Data object and hands
#its functions live rows under the numbers they expect
class Standin:
    def __init__(self, tags):
        self.tags = list(tags)
        self.tag_of = {t: i for i, t in enumerate(self.tags)}
        self.card_lines = {}
        self.line_tags = {}
        self._near = {}

    def neighbours(self, line, how_many):
        idx, sim = self._near[line]
        return idx[:how_many], sim[:how_many]


def both_sides(conn, card, known):
    #one fetch, two rules. returns (site chips, exam chips) as {tag: score}
    import numpy as np

    import autotags
    import exam_autotags as ea
    from mirror import EMBED_COL
    from views.custom import line_neighbours, probe_rows

    #the column line_neighbours searches, or a trial column's neighbours are
    #found for the other model's vectors
    lines = conn.execute("""
        SELECT id, """ + EMBED_COL + """ AS embedding FROM lines
        WHERE oracle_id = %s AND NOT whole ORDER BY id
    """, (card,)).fetchall()
    if not lines:
        return None, None
    vectors = [r["embedding"].to_numpy() for r in lines]
    #the card is kept out of its own neighbours, the way the exam scores one:
    #otherwise its own lines are the nearest ten and the vote is its own tags
    around = line_neighbours(conn, vectors, card)

    ids = [r["id"] for rows in around for r in rows]
    carried = {}
    for r in conn.execute("SELECT line_id, tag FROM line_tags WHERE line_id = ANY(%s)", (ids,)):
        carried.setdefault(r["line_id"], []).append(r["tag"])

    probe = probe_rows(conn, vectors)

    banned = {t for t, is_banned in known if is_banned}

    #---- the site's rule ----
    share_in = [[(r["sim"], carried.get(r["id"], ())) for r in rows] for rows in around]
    mine = autotags.chips(autotags.blend(autotags.probe_scores(probe),
                                         autotags.share_scores(share_in)), banned=banned)

    #---- the exam's own rule, over the same rows ----
    every = sorted({t for t, _ in known} | {t for ts in carried.values() for t in ts})
    d = Standin(every)
    d.card_lines[0] = list(range(len(vectors)))
    #the exam reads its neighbours out of one big array per line index, so the
    #live rows are filed under this card's line positions
    for q, rows in enumerate(around):
        d._near[q] = (np.array([r["id"] for r in rows], dtype=np.int64),
                      np.array([r["sim"] for r in rows], dtype=np.float64))
    for line_id, tags in carried.items():
        d.line_tags[line_id] = {d.tag_of[t] for t in tags if t in d.tag_of}
    #probe_scores and banned read a module level cache rather than taking
    #arguments, so they are seeded instead of called with anything
    ea._probe["idx"] = {q: [d.tag_of[t] for t in scores] for q, scores in enumerate(probe)}
    ea._probe["p"] = {q: list(scores.values()) for q, scores in enumerate(probe)}
    ea._probe["ban"] = {d.tag_of[t] for t in banned if t in d.tag_of}
    theirs = {d.tags[t]: s for t, s in ea.rule_both(d, 0).items()}
    return mine, theirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=50, help="how many cards to compare")
    ap.add_argument("--seed", type=float, default=None, help="fix the sample, -1 to 1")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    from db import pool

    same, tied, differ = 0, [], []
    with pool.connection() as conn:
        known = [(r["tag"], r["banned"]) for r in
                 conn.execute("SELECT tag, banned FROM tag_probe")]
        if not known:
            print("tag_probe is empty: run tools/load_tag_probe.py first")
            sys.exit(1)

        if args.seed is not None:
            conn.execute("SELECT setseed(%s)", (args.seed,))
        cards = conn.execute("""
            SELECT c.oracle_id, c.name FROM cards c
            WHERE c.legal_commander
              AND EXISTS (SELECT 1 FROM lines l WHERE l.oracle_id = c.oracle_id AND NOT l.whole)
            ORDER BY random() LIMIT %s
        """, (args.cards,)).fetchall()

        for i, card in enumerate(cards):
            mine, theirs = both_sides(conn, card["oracle_id"], known)
            if mine is None:
                continue
            #the SCORES too, not just which tags came out: a blend that drifts
            #without changing this card's picks is still a rule that has moved,
            #and it would change somebody else's picks. both sides do the same
            #arithmetic on the same floats, so exactly equal is the right bar
            if set(mine) == set(theirs):
                if all(abs(mine[t] - theirs[t]) < 1e-12 for t in mine):
                    same += 1
                else:
                    worst = max(abs(mine[t] - theirs[t]) for t in mine)
                    differ.append((card["name"] + " (same chips, scores differ by %.2e)" % worst,
                                   [], []))
            elif sorted(round(s, 12) for s in mine.values()) == \
                    sorted(round(s, 12) for s in theirs.values()):
                #the same scores, a different pick among tags tied at the cut:
                #the exam breaks that tie on its own tag numbers and the site on
                #the tag's name. not a disagreement about the rule
                tied.append((card["name"], sorted(set(mine) ^ set(theirs))))
            else:
                differ.append((card["name"], sorted(set(theirs) - set(mine)),
                               sorted(set(mine) - set(theirs))))
            if (i + 1) % 10 == 0:
                print("  %d/%d" % (i + 1, len(cards)))

    print("\n---- over %d cards ----" % (same + len(tied) + len(differ)))
    print("identical:            %d" % same)
    print("tied at the cut:      %d" % len(tied))
    print("actually different:   %d" % len(differ))
    for name, swapped in tied:
        print("  tie  %s: %s" % (name, ", ".join(swapped)))
    for name, only_exam, only_site in differ:
        print("  DIFF %s" % name)
        print("       only the exam: " + (", ".join(only_exam) or "-"))
        print("       only the site: " + (", ".join(only_site) or "-"))
    if differ:
        print("\nFAILED: the port and the exam disagree about the rule.")
        sys.exit(1)
    print("\nthe port answers what the exam answers.")


if __name__ == "__main__":
    sys.exit(main())
