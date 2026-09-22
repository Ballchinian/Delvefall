#does swapping lines_new in change what a card page shows? two questions per
#sampled card, both against exact searches of the new table, whose halfvec
#scores sit within 1e-5 of the old float32 ones:
#
#  its lines   each line searched 400 deep, the rows a page is built from,
#              through the old index and through the new one. scores only, so
#              no tie can fool it. the new table fails on any line whose best
#              match the old index finds and it does not, or if it is less right
#              than the old index over all of them
#  its page    find_similar itself over each table, whichever is not called
#              lines laid under that name by a temporary view on a pool of its
#              own. where both indexes answer every line exactly and none ties at
#              the cut, the badge at every rank holds within 1 point,
#              check_custom.py's bar for the same reason
#
#a line TIED at the 400 cut, rank 400 scoring the same as 401, leaves its rows an
#arbitrary pick among equals: the hunt has no tiebreak, so each graph hands back
#its own 400 of Flying's 2,566. those pages are counted, not judged.
#
#the page side runs the site's own query and plan, which the forced walk on the
#line side does not always reproduce: on lines_old the site's query put Battlefly
#Swarm 398th for Fear of the Dark where it is 408th exactly, and read as a 2
#point move against the table that had it right. read a judged page's two lists
#before counting it against the new table.
#
#nothing is written and a view goes with its connection. the line searches get
#a connection of their own: RESET on a pooled one put ef_search back to the
#server's 40, and the next page on it was cut to 40 rows
#
#    python tools/check_rebuild_pages.py               lines against lines_new, before --swap
#    python tools/check_rebuild_pages.py --after-swap  lines_old against lines, while --rollback still can
#    python tools/check_rebuild_pages.py --cards 50    fewer, while iterating
#    python tools/check_rebuild_pages.py --include "Wind Zendikon"   plus a named card
#
#needs DATABASE_URL

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
#old index
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


def read_lines(conn, oracle_id, old, new):
    from ingest import rebuild_lines as rl
    old_hunt = rl.HUNT.replace("lines_new", old)
    new_hunt = rl.HUNT.replace("lines_new", new)
    exact_hunt = rl.EXACT.replace("lines_new", new).replace("LIMIT 400", "LIMIT %d" % (DEPTH + 1))
    out = []
    for ln in conn.execute("""
            SELECT o.line_text, o.embedding AS old, n.embedding AS new
            FROM """ + old + """ o JOIN """ + new + """ n ON n.id = o.id
            WHERE o.oracle_id = %s AND NOT o.whole""", (oracle_id,)).fetchall():
        exact = [r["sim"] for r in conn.execute(exact_hunt, (ln["new"], oracle_id, ln["new"]))]
        conn.execute("SET enable_seqscan = off; SET enable_sort = off")
        was = [r["sim"] for r in conn.execute(old_hunt, (ln["old"], oracle_id, ln["old"]), prepare=False)]
        now = [r["sim"] for r in conn.execute(new_hunt, (ln["new"], oracle_id, ln["new"]), prepare=False)]
        conn.execute("SET enable_seqscan = on; SET enable_sort = on")
        right = lambda found: sum(1 for a, b in zip(found[:DEPTH], exact[:DEPTH]) if abs(a - b) < rl.TOLERANCE)
        out.append({"text": ln["line_text"], "n": min(DEPTH, len(exact)),
                    "tied": len(exact) > DEPTH and exact[DEPTH - 1] - exact[DEPTH] < 1e-6,
                    "old": right(was), "new": right(now),
                    "old_blind": rl.verdict(was, exact)[1], "new_blind": rl.verdict(now, exact)[1]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=400)
    ap.add_argument("--seed", type=int, default=None, help="fix the sample, to compare two runs")
    ap.add_argument("--include", action="append", default=[], help="a card name to add to the sample")
    ap.add_argument("--after-swap", action="store_true", help="lines_old against lines")
    args = ap.parse_args()
    old, new = ("lines_old", "lines") if args.after_swap else ("lines", "lines_new")

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

    with psycopg.connect(os.environ["DATABASE_URL"]) as plain:
        for t in (old, new):
            if not rl.exists(plain, t):
                print("there is no " + t + (". before --swap run it plain, after it with --after-swap"))
                sys.exit(1)
        #each side reads its own table and the truth reads the new one, so an
        #ingest between the copy and this run would mix two tables' rows. tuple
        #rows: dict rows fold the fingerprint's two coalesce columns into one
        if rl.fingerprint(plain, old) != rl.fingerprint(plain, new):
            print(old + " and " + new + " no longer hold the same rows, an ingest has run since the copy")
            sys.exit(1)

    def pool_over(table):
        def configure(conn):
            db.setup(conn)
            conn.execute("CREATE TEMP VIEW lines AS SELECT * FROM public." + table)
            conn.commit()
        return ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=4,
                              kwargs={"row_factory": dict_row}, configure=configure, open=True)

    site = db.pool
    pools = {t: site if t == "lines" else pool_over(t) for t in (old, new)}

    def use(chosen):
        #every module that did `from db import pool` holds its own name for it
        for m in list(sys.modules.values()):
            if getattr(m, "pool", None) in pools.values():
                m.pool = chosen

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
    one = probe.execute("SELECT o.oracle_id, o.embedding AS old, n.embedding AS new FROM " + old + " o JOIN " +
                        new + " n ON n.id = o.id WHERE NOT o.whole LIMIT 1").fetchone()
    probe.execute("SET enable_seqscan = off; SET enable_sort = off")
    for table, side in ((old, "old"), (new, "new")):
        plan = " ".join(r["QUERY PLAN"] for r in probe.execute(
            "EXPLAIN " + rl.HUNT.replace("lines_new", table), (one[side], one["oracle_id"], one[side])))
        assert " " + table + "_embedding_hnsw" in plan, "the forced search on " + table + " did not walk its index"
    probe.execute("SET enable_seqscan = on; SET enable_sort = on")
    print("%s against %s: %d cards, each line searched 400 deep and each list computed over both\n"
          % (old, new, len(cards)))

    all_lines, blind, drops = [], [], []
    judged, page_moves, fixed, reshuffled = 0, [], [], []
    worst_judged = 0
    started = time.time()
    for n, c in enumerate(cards):
        lines = read_lines(probe, c["oracle_id"], old, new)
        with web.app.test_request_context("/search?q=" + urllib.parse.quote(c["name"])):
            card = web.find_card(c["name"])
            if card is None or card["oracle_id"] != c["oracle_id"]:
                continue
            filters = web.read_filters()
            lists = []
            for t in (old, new):
                use(pools[t])
                results, _, _ = web.find_similar(card["oracle_id"], [], filters, web.TIER_CUT, web.read_sort(),
                                                 currency=filters["cur"],
                                                 anchor_price=web.price_in(card, filters["cur"]),
                                                 anchor_rank=card["edhrec_rank"], anchor_salt=card["salt"],
                                                 anchor_released=card["released_at"])
                lists.append(results)
            use(site)
        a, b = lists
        delta = max([abs(x["percent"] - y["percent"]) for x, y in zip(a, b)] + [0])
        if len(a) != len(b):
            delta = max(delta, 100)

        for ln in lines:
            all_lines.append(ln)
            if ln["new_blind"] and not ln["old_blind"]:
                blind.append((c["name"], ln))
            if ln["old"] - ln["new"] >= DROP:
                drops.append((c["name"], ln))
        wrong = ["old %d new %d/%d %s" % (ln["old"], ln["new"], ln["n"], ln["text"][:40])
                 for ln in lines if ln["old"] < ln["n"] or ln["new"] < ln["n"]]
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
    for p in pools.values():
        if p is not site:
            p.close()

    old_right = sum(ln["old"] for ln in all_lines)
    new_right = sum(ln["new"] for ln in all_lines)
    possible = sum(ln["n"] for ln in all_lines)
    print("\nlines: %d, rows right of %d possible: old index %d, new index %d"
          % (len(all_lines), possible, old_right, new_right))
    print("  missing a best match the old index finds: %d" % len(blind))
    for name, ln in blind:
        print("    %-28s %s" % (name[:28], ln["text"][:70]))
    print("  finding a best match the old index misses: %d"
          % sum(1 for ln in all_lines if ln["old_blind"] and not ln["new_blind"]))
    print("  dropping %d or more of 400 against the old index: %d" % (DROP, len(drops)))
    for name, ln in drops[:15]:
        print("    old %3d new %3d  %-28s %s" % (ln["old"], ln["new"], name[:28], ln["text"][:50]))

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
        failed.append("%d line(s) miss a best match the old index finds" % len(blind))
    if new_right < old_right:
        failed.append("the new index gets %d fewer rows right than the old one" % (old_right - new_right))
    if page_moves:
        failed.append("%d judged page(s) moved more than %d point" % (len(page_moves), BADGE_DELTA))
    print("\n" + ("FAIL: " + "; ".join(failed) if failed else
                  "PASS: the new index is as right as the old on every line, and no judged page moved"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
