#does swapping lines_new in change what a card page shows? two questions per
#sampled card, both against exact searches of lines_new, whose halfvec scores
#sit within 1e-5 of the live float32 ones:
#
#  its lines   each line searched 400 deep, the rows a page is built from,
#              through the live index and through lines_new's. scores only, so
#              no tie can fool it. lines_new fails on any line whose best match
#              the live index finds and it does not, or if it is less right than
#              the live index over all of them
#  its page    find_similar itself over lines, then over lines_new laid under
#              the name lines by a temporary view on a second pool. where both
#              indexes answer every line exactly and none ties at the cut, the
#              badge at every rank holds within 1 point, check_custom.py's bar
#              for the same reason
#
#a line TIED at the 400 cut, rank 400 scoring the same as 401, leaves its rows an
#arbitrary pick among equals: the hunt has no tiebreak, so each graph hands back
#its own 400 of Flying's 2,566. those pages are counted, not judged.
#
#nothing is written and the view goes with its connection. the line searches get
#a connection of their own: RESET on a pooled one put ef_search back to the
#server's 40, and the next page on it was cut to 40 rows
#
#    python tools/check_rebuild_pages.py              400 cards
#    python tools/check_rebuild_pages.py --cards 50   fewer, while iterating
#    python tools/check_rebuild_pages.py --include "Wind Zendikon"   plus a named card
#
#needs DATABASE_URL, and a lines_new from python -m ingest.rebuild_lines

import os
import sys
import time
import argparse
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

BADGE_DELTA = 1
DEPTH = 400
#reported, not failed: a line that drops this many of its 400 rows against the
#live index
DROP = 20


def load_env(root):
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_lines(conn, oracle_id):
    from ingest import rebuild_lines as rl
    live_hunt = rl.HUNT.replace("lines_new", "lines")
    exact_hunt = rl.EXACT.replace("LIMIT 400", "LIMIT %d" % (DEPTH + 1))
    out = []
    for ln in conn.execute("""
            SELECT o.line_text, o.embedding AS live, n.embedding AS new
            FROM lines o JOIN lines_new n ON n.id = o.id
            WHERE o.oracle_id = %s AND NOT o.whole""", (oracle_id,)).fetchall():
        exact = [r["sim"] for r in conn.execute(exact_hunt, (ln["new"], oracle_id, ln["new"]))]
        conn.execute("SET enable_seqscan = off; SET enable_sort = off")
        live = [r["sim"] for r in conn.execute(live_hunt, (ln["live"], oracle_id, ln["live"]), prepare=False)]
        new = [r["sim"] for r in conn.execute(rl.HUNT, (ln["new"], oracle_id, ln["new"]), prepare=False)]
        conn.execute("SET enable_seqscan = on; SET enable_sort = on")
        right = lambda found: sum(1 for a, b in zip(found[:DEPTH], exact[:DEPTH]) if abs(a - b) < rl.TOLERANCE)
        out.append({"text": ln["line_text"], "n": min(DEPTH, len(exact)),
                    "tied": len(exact) > DEPTH and exact[DEPTH - 1] - exact[DEPTH] < 1e-6,
                    "live": right(live), "new": right(new),
                    "live_blind": rl.verdict(live, exact)[1], "new_blind": rl.verdict(new, exact)[1]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=400)
    ap.add_argument("--seed", type=int, default=None, help="fix the sample, to compare two runs")
    ap.add_argument("--include", action="append", default=[], help="a card name to add to the sample")
    args = ap.parse_args()

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    load_env(root)
    if not os.environ.get("DATABASE_URL"):
        print("set DATABASE_URL first")
        sys.exit(1)

    #the visit counter would file a visit per card
    import visitors
    visitors.register = lambda app: None
    import db
    import app as web
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from pgvector.psycopg import register_vector
    from ingest import rebuild_lines as rl

    def over_lines_new(conn):
        db.setup(conn)
        conn.execute("CREATE TEMP VIEW lines AS SELECT * FROM public.lines_new")
        conn.commit()

    live = db.pool
    new = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=4,
                         kwargs={"row_factory": dict_row}, configure=over_lines_new, open=True)

    def use(chosen):
        #every module that did `from db import pool` holds its own name for it
        for m in list(sys.modules.values()):
            if getattr(m, "pool", None) in (live, new):
                m.pool = chosen

    #the live side reads lines and the truth reads lines_new, so a day's ingest
    #between the copy and this run would mix two tables' rows. tuple rows: dict
    #rows fold the fingerprint's two coalesce columns into one
    with psycopg.connect(os.environ["DATABASE_URL"]) as plain:
        if rl.fingerprint(plain, "lines") != rl.fingerprint(plain, "lines_new"):
            print("lines has changed since lines_new was copied from it. rebuild first")
            sys.exit(1)
        note = rl.exists(plain, "lines_new") and plain.execute(
            "SELECT obj_description('lines_new'::regclass, 'pg_class')").fetchone()[0]

    probe = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    register_vector(probe)
    probe.execute("SET hnsw.ef_search = 400; SET hnsw.iterative_scan = 'strict_order'; "
                  "SET max_parallel_workers_per_gather = 0")
    if args.seed is not None:
        probe.execute("SELECT setseed(%s)", (args.seed / 2**31,))
    cards = probe.execute("""
        SELECT c.oracle_id, c.name FROM cards c
        WHERE EXISTS (SELECT 1 FROM lines l WHERE l.oracle_id = c.oracle_id AND NOT l.whole)
        ORDER BY random() LIMIT %s""", (args.cards,)).fetchall()
    cards += probe.execute("SELECT oracle_id, name FROM cards WHERE name = ANY(%s)", (args.include,)).fetchall()
    #both forced searches have to walk the graphs they are named for
    one = probe.execute("""SELECT o.oracle_id, o.embedding AS live, n.embedding AS new FROM lines o
                           JOIN lines_new n ON n.id = o.id WHERE NOT o.whole LIMIT 1""").fetchone()
    probe.execute("SET enable_seqscan = off; SET enable_sort = off")
    for table, query, vec in (("lines", rl.HUNT.replace("lines_new", "lines"), one["live"]),
                              ("lines_new", rl.HUNT, one["new"])):
        plan = " ".join(r["QUERY PLAN"] for r in probe.execute("EXPLAIN " + query, (vec, one["oracle_id"], vec)))
        assert table + "_embedding_hnsw" in plan, "the forced search on " + table + " did not walk its index"
    probe.execute("SET enable_seqscan = on; SET enable_sort = on")
    print("lines_new: %s" % (note or "never checked"))
    print("%d cards, each line searched 400 deep and each list computed over lines and over lines_new\n"
          % len(cards))

    all_lines, blind, drops = [], [], []
    judged, page_moves, fixed, reshuffled = 0, [], [], []
    worst_judged = 0
    started = time.time()
    for n, c in enumerate(cards):
        lines = read_lines(probe, c["oracle_id"])
        with web.app.test_request_context("/search?q=" + urllib.parse.quote(c["name"])):
            card = web.find_card(c["name"])
            if card is None or card["oracle_id"] != c["oracle_id"]:
                continue
            filters = web.read_filters()
            lists = []
            for chosen in (live, new):
                use(chosen)
                results, _, _ = web.find_similar(card["oracle_id"], [], filters, web.TIER_CUT, web.read_sort(),
                                                 currency=filters["cur"],
                                                 anchor_price=web.price_in(card, filters["cur"]),
                                                 anchor_rank=card["edhrec_rank"], anchor_salt=card["salt"],
                                                 anchor_released=card["released_at"])
                lists.append(results)
            use(live)
        a, b = lists
        delta = max([abs(x["percent"] - y["percent"]) for x, y in zip(a, b)] + [0])
        if len(a) != len(b):
            delta = max(delta, 100)

        for ln in lines:
            all_lines.append(ln)
            if ln["new_blind"] and not ln["live_blind"]:
                blind.append((c["name"], ln))
            if ln["live"] - ln["new"] >= DROP:
                drops.append((c["name"], ln))
        wrong = ["live %d new %d/%d %s" % (ln["live"], ln["new"], ln["n"], ln["text"][:40])
                 for ln in lines if ln["live"] < ln["n"] or ln["new"] < ln["n"]]
        if any(ln["tied"] for ln in lines):
            reshuffled.append(delta)
        elif wrong:
            fixed.append((c["name"], delta, wrong))
        else:
            judged += 1
            worst_judged = max(worst_judged, delta)
            if delta > BADGE_DELTA:
                page_moves.append((c["name"], delta, len(a), len(b)))
        if (n + 1) % 50 == 0:
            print("  %d/%d cards, %.0fs" % (n + 1, len(cards), time.time() - started), flush=True)
    probe.close()
    new.close()

    live_right = sum(ln["live"] for ln in all_lines)
    new_right = sum(ln["new"] for ln in all_lines)
    possible = sum(ln["n"] for ln in all_lines)
    print("\nlines: %d, rows right of %d possible: live index %d, lines_new %d"
          % (len(all_lines), possible, live_right, new_right))
    print("  missing a best match the live index finds: %d" % len(blind))
    for name, ln in blind:
        print("    %-28s %s" % (name[:28], ln["text"][:70]))
    print("  dropping %d or more of 400 against the live index: %d" % (DROP, len(drops)))
    for name, ln in drops[:15]:
        print("    live %3d new %3d  %-28s %s" % (ln["live"], ln["new"], name[:28], ln["text"][:50]))

    print("\npages judged (no tied line, both indexes exact on every line): %d, worst badge move %d"
          % (judged, worst_judged))
    for name, delta, la, lb in page_moves:
        print("  MOVED %3d points  %s  (%d results against %d)" % (delta, name, la, lb))
    print("\npages where an index is wrong on a line: %d" % len(fixed))
    for name, delta, wrong in sorted(fixed, key=lambda r: -r[1])[:20]:
        print("  %3d points  %-28s %s" % (delta, name[:28], "; ".join(wrong)[:90]))
    reshuffled.sort()
    print("\npages with a line tied at the 400 cut, reshuffled by any rebuild: %d, median move %d, worst %d"
          % (len(reshuffled), reshuffled[len(reshuffled) // 2] if reshuffled else 0,
             reshuffled[-1] if reshuffled else 0))

    failed = []
    if blind:
        failed.append("%d line(s) miss a best match the live index finds" % len(blind))
    if new_right < live_right:
        failed.append("lines_new gets %d fewer rows right than the live index" % (live_right - new_right))
    if page_moves:
        failed.append("%d judged page(s) moved more than %d point" % (len(page_moves), BADGE_DELTA))
    print("\n" + ("FAIL: " + "; ".join(failed) if failed else
                  "PASS: lines_new is as right as the live index on every line, and no judged page moved"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
