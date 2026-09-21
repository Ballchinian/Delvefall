#does /custom give a printed card the same answer the ingest already gave it?
#
#the page embeds typed text at request time; the ingest embedded the same text
#months ago and stored the result. if the two ever stop agreeing, nothing breaks
#and nothing 500s: the percentages on the page just quietly become wrong,
#measured against a table built by something else. this is what notices.
#
#    python tools/check_custom.py                  50 cards
#    python tools/check_custom.py --cards 10       fewer, while iterating
#
#needs DATABASE_URL and EMBED_URL. read only, and run LOCALLY against the local
#model service from embed/, not in CI: CI has no torch and no weights.
#
#a failure is one of four things, and check_embed_parity.py says which:
#  the prefix      EMBED_PROMPT drifted between embed/app.py and ingest/update.py
#  the cleaning    clean_line or split_lines drifted between web/ and common/
#  the pins        a library moved under ingest/requirements.txt
#  the weights     the service is serving a different model than the table holds

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

#the same bar tools/check_embed_parity.py uses: under UNIQUE_NOISE nothing can
#lift a card off the tie at zero. 1e-5 leaves two orders of room above the
#2.95e-07 a healthy run measures
UNIQUENESS_BAR = 1e-5
#the badge at each RANK, typed against stored. measured over 24 cards on
#2026-09-21 it was exactly equal every time, worst delta 0, so a point of slack
#is generous. it is there because the calibration map turns a cosine into an
#integer, and a card whose whole top 20 sits on one tie can cross a rounding
#boundary together when the last bits of the query vector differ
BADGE_DELTA = 1

#the NAMES are deliberately not asserted. over those same 24 cards the overlap
#ran from 0% to 100%, and every low one was a card whose list is one wide tie:
#Feiyi Snake 0% and Craven Knight 20%, both with all 20 results on the same
#percent, against 100% for cards whose scores separate. the hunt query carries
#no tiebreak on purpose (a second sort key pushes the planner off the hnsw
#index), so which members of a tie surface is not something the ranking
#promises. the share is printed as information and nothing hangs on it


def load_env(root):
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=50)
    ap.add_argument("--seed", type=int, default=None, help="fix the sample, to compare two runs")
    args = ap.parse_args()

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    load_env(root)
    if not os.environ.get("DATABASE_URL"):
        print("set DATABASE_URL first")
        sys.exit(1)
    if not os.environ.get("EMBED_URL"):
        print("set EMBED_URL first, eg http://127.0.0.1:8081 with embed/app.py running")
        sys.exit(1)

    #the visit counter would file a visit per card. it is wired by a call rather
    #than a decorator exactly so this can be done
    import visitors
    visitors.register = lambda app: None
    import app as web
    from views.custom import Rejected, custom_score, read_custom

    with web.app.test_request_context("/custom"):
        filters = web.read_filters()

    with web.pool.connection() as conn:
        if args.seed is not None:
            conn.execute("SELECT setseed(%s)", (args.seed / 2**31,))
        cards = conn.execute("""
            SELECT oracle_id, name, oracle_text, uniqueness
            FROM cards
            WHERE legal_commander AND layout = 'normal' AND uniqueness IS NOT NULL
              AND oracle_text IS NOT NULL AND oracle_text <> ''
            ORDER BY random() LIMIT %s""", (args.cards,)).fetchall()

    print("%d cards, scored as typed text with the card itself excluded\n" % len(cards))
    worst_gap = 0.0
    worst_badges = 0
    failures = []
    started = time.time()

    for c in cards:
        try:
            lines = read_custom(c["oracle_text"], c["name"])
        except Rejected as e:
            #a printed card its own page would turn away means a limit is set
            #below what the game actually prints
            failures.append((c["name"], "the form refused a printed card: " + str(e)))
            continue

        typed = custom_score(lines, filters, "match", exclude_id=c["oracle_id"])

        #1. the score the ingest stored, recomputed from the text alone
        gap = abs(typed["uniqueness"] - c["uniqueness"])
        worst_gap = max(worst_gap, gap)
        if gap > UNIQUENESS_BAR:
            failures.append((c["name"], "uniqueness %.9f against the stored %.9f, gap %.2e"
                             % (typed["uniqueness"], c["uniqueness"], gap)))

        #2. the SAME function over the card's stored vectors, with the same
        #empty anchor. everything is held still except where the numbers came
        #from, so a difference is the embedding and nothing else
        with web.pool.connection() as conn:
            qlines = conn.execute("""
                SELECT l.line_text, l.""" + web.EMBED_COL + """ AS embedding,
                       coalesce(s.count, 1) AS count
                FROM lines l LEFT JOIN line_stats s ON s.line_text = l.line_text
                WHERE l.oracle_id = %s AND NOT l.whole
                  AND l.""" + web.EMBED_COL + """ IS NOT NULL
            """, (c["oracle_id"],)).fetchall()
        stored = web.similar_from_lines(qlines, ((), (), None), c["oracle_id"], filters,
                                        web.TIER_CUT, "match")
        want = [r["name"] for r in stored[0]]
        got = [r["name"] for r in typed["results"]]
        if len(want) != len(got):
            failures.append((c["name"], "%d results typed against %d stored" % (len(got), len(want))))
        else:
            deltas = [abs(a["percent"] - b["percent"])
                      for a, b in zip(typed["results"], stored[0])]
            worst = max(deltas) if deltas else 0
            worst_badges = max(worst_badges, worst)
            if worst > BADGE_DELTA:
                failures.append((c["name"], "a badge moved %d points, typed against stored" % worst))
        overlap = len(set(got) & set(want)) / len(want) if want else 1.0

        print("  %-34s gap %.2e  names %3.0f%%" % (c["name"][:34], gap, overlap * 100))

    #3. the same cards NOT excluded. a card whose lines are all in the table has
    #nothing more original than it, so the sentence bottoms out and something in
    #the list is a perfect match.
    #
    #NOT "first in its own list", and not even "in its own list": 32 cards print
    #"this card deals 3 damage to any target." verbatim, every one of them scores
    #the same on rules text alone, and 20 results cannot hold a tie that wide. a
    #card can legitimately be absent from its own top 20
    print("\nthe same cards without excluding themselves:")
    for c in cards[:min(10, len(cards))]:
        try:
            lines = read_custom(c["oracle_text"], c["name"])
        except Rejected:
            continue
        mine = custom_score(lines, filters, "match")
        names = [r["name"] for r in mine["results"]]
        if mine["uniqueness"] > UNIQUENESS_BAR:
            failures.append((c["name"], "reads %.2e original against its own lines" % mine["uniqueness"]))
        if "0.0%" not in mine["words"]:
            failures.append((c["name"], "the sentence reads " + mine["words"]))
        if not mine["results"] or mine["results"][0]["percent"] != 100:
            top = mine["results"][0]["percent"] if mine["results"] else None
            failures.append((c["name"], "its best match reads %s, not 100" % top))
        print("  %-34s top %3s%%  %s" % (c["name"][:34],
                                         mine["results"][0]["percent"] if mine["results"] else "-",
                                         mine["words"]))

    print("\n%.0fs. worst uniqueness gap %.2e (bar %.0e), worst badge move %d points"
          % (time.time() - started, worst_gap, UNIQUENESS_BAR, worst_badges))
    if failures:
        print("\n%d FAILURES:" % len(failures))
        for name, why in failures:
            print("  %-36s %s" % (name[:36], why))
        print("\nrun tools/check_embed_parity.py to tell the weights apart from the cleaning.")
        sys.exit(1)
    print("every card agrees with what the ingest stored for it.")


if __name__ == "__main__":
    main()
