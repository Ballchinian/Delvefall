#rewrites lines into a fresh table and swaps it in. the rows arrive at EMBED_TYPE,
#and the empty space a model swap or a backfill leaves behind stays with the old
#table: postgres never hands it back on its own, and the live table measured
#1,049mb around 236mb of vectors.
#
#the site reads the old table throughout. the copy and the index builds take
#minutes and hold no lock a search waits on. the swap is renames in one short
#transaction, refused if anything wrote to lines after the copy or if lines_new
#never passed the recall check.
#
#from the repo root with DATABASE_URL set. every step refuses while an ingest run
#holds the lock, and an ingest run waits while a step of this holds it:
#    python -m ingest.rebuild_lines             copy and build lines_new, then check its recall
#    python -m ingest.rebuild_lines --check     check an existing lines_new's recall again
#    python -m ingest.rebuild_lines --swap      put lines_new live, the old one kept as lines_old
#    python -m ingest.rebuild_lines --rollback  put lines_old back
#    python -m ingest.rebuild_lines --drop-old  once the new table has held up
#    python -m ingest.rebuild_lines --discard   drop a lines_new that should not go live

import os
import sys
import time
import argparse

import psycopg
from psycopg import sql
from pgvector.psycopg import register_vector

from common import locks
from ingest.update import EMBED_TYPE

COLUMNS = ["id", "oracle_id", "line_text", "embedding", "nn_sim", "face", "whole"]

#what schema.sql builds on lines, spelled for a table named t. anything else on
#the live table and the tool refuses, rather than swap in a table missing it
INDEXES = {
    "_oracle_id": "CREATE INDEX {t}_oracle_id ON {t} (oracle_id)",
    "_embedding_hnsw": "CREATE INDEX {t}_embedding_hnsw ON {t} USING hnsw (embedding {ops}) "
                       "WITH (m = 64, ef_construction = 400) WHERE (NOT whole)",
}
CONSTRAINTS = {
    "_pkey": "ALTER TABLE {t} ADD CONSTRAINT {t}_pkey PRIMARY KEY (id)",
    "_oracle_id_fkey": "ALTER TABLE {t} ADD CONSTRAINT {t}_oracle_id_fkey FOREIGN KEY (oracle_id) "
                       "REFERENCES cards(oracle_id) ON DELETE CASCADE",
}

#the swap waits this long for searches to finish before giving up and changing
#nothing. every search that arrives behind it queues for as long as it waits
LOCK_TIMEOUT = "3s"

#the recall check: the NEAR texts closest to each of the GROUPS biggest groups
#of identical lines, plus RANDOM others. about 1,100 texts, each searched twice,
#ten minutes or so from a laptop
GROUPS, NEAR, RANDOM = 25, 40, 300
TOLERANCE = 1e-3
PASSED = "recall check passed"

#find_similar's hunt without the columns it only displays: the join and the
#filters are what decide which rows the walk has to get past
HUNT = ("SELECT 1 - (l.embedding <=> %s) AS sim FROM lines_new l JOIN cards c ON c.oracle_id = l.oracle_id "
        "WHERE l.oracle_id <> %s AND NOT l.whole AND l.embedding IS NOT NULL "
        "ORDER BY l.embedding <=> %s LIMIT 400")

#HUNT's exact twin: + 0 leaves nothing the index can order by, so it reads every
#row whatever the settings. switching enable_* over one query text is not
#enough: psycopg prepares it from the fifth run, postgres keeps that plan through
#the switch, and the exact searches walked the graph and passed a build with 55
#texts blind
EXACT = HUNT.replace("ORDER BY l.embedding <=> %s", "ORDER BY (l.embedding <=> %s) + 0")


class Refused(Exception):
    pass


def exists(conn, table):
    return conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None


def fingerprint(conn, table):
    #every write to lines moves one of these: the update deletes and reinserts a
    #changed card under new ids, and the uniqueness pass rewrites nn_sim. the
    #vectors stay out of it, reading them being the slow part of a scan
    return conn.execute("""
        SELECT count(*), coalesce(max(id), 0),
               coalesce(sum(hashtextextended(id || '|' || line_text || '|' || coalesce(nn_sim::text, '') ||
                                             '|' || face || '|' || whole, 0)::numeric), 0)
        FROM """ + table).fetchone()


def expect_the_schema_shape(conn):
    columns = [r[0] for r in conn.execute("""
        SELECT attname FROM pg_attribute
        WHERE attrelid = 'lines'::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum""")]
    if sorted(columns) != sorted(COLUMNS):
        raise Refused("lines has columns " + ", ".join(columns) + ", expected " + ", ".join(COLUMNS) +
                      ". a trial column (embedding_v2) is dropped or promoted before a rebuild")
    names = {r[0] for r in conn.execute("""
        SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        WHERE i.indrelid = 'lines'::regclass""")}
    names |= {r[0] for r in conn.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'lines'::regclass")}
    wanted = {"lines" + k for k in list(INDEXES) + list(CONSTRAINTS)}
    if names != wanted:
        raise Refused("lines carries " + ", ".join(sorted(names)) + ", this tool rebuilds " + ", ".join(sorted(wanted)))
    pointing = {r[0] for r in conn.execute("SELECT conname FROM pg_constraint WHERE confrelid = 'lines'::regclass")}
    if pointing != {"line_tags_line_id_fkey"}:
        raise Refused("tables pointing at lines: " + ", ".join(sorted(pointing)) + ", this tool repoints line_tags only")


def alone(conn):
    #the ingest takes the same lock before its first write, so this is the answer
    #to "is a run happening", clock and github schedule both being no help
    if not locks.claim(conn):
        raise Refused("an ingest run holds the lock. it takes 7 to 12 minutes, so try again after that")


def clear(conn):
    for t in ("lines_new", "lines_old"):
        if exists(conn, t):
            raise Refused(t + " already exists, from a rebuild that never finished. --swap, --rollback, "
                          "--drop-old or --discard it first")
    expect_the_schema_shape(conn)


def create(conn):
    #an empty lines_new. fill copies the live rows into it, a model swap in
    #update.py COPYs the new model's rows in from the runner
    alone(conn)
    clear(conn)
    conn.execute("CREATE TABLE lines_new (LIKE lines INCLUDING DEFAULTS INCLUDING STORAGE)")
    conn.execute("ALTER TABLE lines_new ALTER COLUMN embedding TYPE " + EMBED_TYPE)


#the copy is three transactions for main to commit between. every ingest opens
#with schema.sql's ALTER TABLE lines and cards, which queue for ACCESS EXCLUSIVE
#behind whatever lock this holds, and every search queues behind them: holding
#lines or cards through a minutes long index build would stall the site for all
#of it
def fill(conn):
    create(conn)
    cols = ", ".join(COLUMNS)
    conn.execute("INSERT INTO lines_new (" + cols + ") SELECT " + cols + " FROM lines ORDER BY id")


def constrain(conn):
    for sql in CONSTRAINTS.values():
        conn.execute(sql.format(t="lines_new"))


def index(conn):
    #after the fill: grown one insert at a time, the m=32 graph took nearly 4x
    #as long and left 157 and 259 texts missing their best match where building
    #it after the fill left 55, and the m=64 one took 17 minutes against 4 and
    #left 39 and 42 where after the fill left none. SERIAL because a parallel
    #worker's shared memory segment does not fit railway's /dev/shm (see
    #backfill_embeddings.py), and 512mb holds the m=64 graph where the default
    #64mb spills to a slower path
    conn.execute("SET LOCAL max_parallel_maintenance_workers = 0")
    conn.execute("SET LOCAL maintenance_work_mem = '512MB'")
    ops = EMBED_TYPE.split("(")[0] + "_cosine_ops"
    for sql in INDEXES.values():
        conn.execute(sql.format(t="lines_new", ops=ops))
    conn.execute("ANALYZE lines_new")


def sample(conn):
    #identical lines trap the graph walk, so the texts a broken graph loses sit
    #next to the biggest groups of them. over every text of seven lab builds this
    #sample held 22 to 49 of each broken build's misses. the random part is for
    #everything else
    texts = set()
    for group, vec in conn.execute("""
            SELECT DISTINCT ON (line_text) line_text, embedding FROM lines_new
            WHERE NOT whole AND line_text IN (SELECT line_text FROM lines_new WHERE NOT whole
                                              GROUP BY line_text ORDER BY count(*) DESC LIMIT %s)
            ORDER BY line_text, id""", (GROUPS,)).fetchall():
        texts.update(r[0] for r in conn.execute("""
            SELECT line_text FROM lines_new WHERE NOT whole AND line_text <> %s
            GROUP BY line_text ORDER BY min(embedding <=> %s) LIMIT %s""", (group, vec, NEAR)))
    texts.update(r[0] for r in conn.execute("""
        SELECT line_text FROM (SELECT DISTINCT line_text FROM lines_new WHERE NOT whole) t
        ORDER BY random() LIMIT %s""", (RANDOM,)))
    return conn.execute("""
        SELECT DISTINCT ON (line_text) line_text, oracle_id, embedding FROM lines_new
        WHERE NOT whole AND line_text = ANY(%s) ORDER BY line_text, id""", (sorted(texts),)).fetchall()


def verdict(found, exact):
    #scores rank for rank, never names: a tie among identical lines can put its
    #members in either order. blind is the failure that matters, the walk never
    #reaching the line's best match at all
    hits = sum(1 for a, b in zip(found[:20], exact[:20]) if abs(a - b) < TOLERANCE)
    blind = bool(exact) and (not found or found[0] < exact[0] - TOLERANCE)
    return hits, blind


def check(conn):
    #each sampled text searched the way find_similar hunts, once forced onto
    #lines_new's hnsw index and once exact. session wide rather than LOCAL, so
    #they hold across main's autocommit: a transaction per search rather than one
    #snapshot held open for ten minutes
    rows = sample(conn)
    if not rows:
        return {"texts": 0, "passed": False, "worst": [], "blind": 0, "below_20": 0,
                "reason": "lines_new has no searchable rows"}
    conn.execute("SET hnsw.ef_search = 400; SET hnsw.iterative_scan = 'strict_order'; "
                 "SET max_parallel_workers_per_gather = 0")
    try:
        exact = [[r[0] for r in conn.execute(EXACT, (vec, oid, vec))] for _, oid, vec in rows]
        #sort off as well as seq scan: with only seq scan off, a small table walks
        #the oracle_id btree and sorts every row, exact again under another name.
        #unprepared, so each search runs the plan EXPLAIN shows
        conn.execute("SET enable_seqscan = off; SET enable_sort = off")
        _, oid, vec = rows[0]
        plan = " ".join(r[0] for r in conn.execute("EXPLAIN " + HUNT, (vec, oid, vec)))
        if "lines_new_embedding_hnsw" not in plan:
            return {"texts": len(rows), "passed": False, "worst": [], "blind": 0, "below_20": 0,
                    "reason": "the search did not walk lines_new_embedding_hnsw"}
        index = [[r[0] for r in conn.execute(HUNT, (vec, oid, vec), prepare=False)] for _, oid, vec in rows]
    finally:
        conn.execute("RESET enable_seqscan; RESET enable_sort; RESET max_parallel_workers_per_gather; "
                     "RESET hnsw.iterative_scan; RESET hnsw.ef_search")
    scored = []
    for (text, _, _), index_sims, exact_sims in zip(rows, index, exact):
        hits, blind = verdict(index_sims, exact_sims)
        scored.append((hits, blind, text, index_sims[0] if index_sims else 0.0, exact_sims[0] if exact_sims else 0.0))
    blind = sum(1 for s in scored if s[1])
    return {"texts": len(rows), "passed": blind == 0, "blind": blind,
            "below_20": sum(1 for s in scored if s[0] < 20),
            "worst": sorted((s for s in scored if s[0] < 20), key=lambda s: (not s[1], s[0]))[:10],
            "reason": "%d of the %d sampled texts miss their best match" % (blind, len(rows))}


def record(conn, report):
    #--swap reads this back. it rides the table, so a rebuilt or rechecked
    #lines_new carries its own verdict and nothing else can vouch for it
    note = "%s: %d texts, %d missing their best match, %d below 20/20" % (
        PASSED if report["passed"] else "recall check FAILED", report["texts"], report["blind"], report["below_20"])
    conn.execute(sql.SQL("COMMENT ON TABLE lines_new IS {}").format(sql.Literal(note)))


def describe(report):
    print("recall over %d texts: %d miss their best match, %d fall below 20/20"
          % (report["texts"], report["blind"], report["below_20"]))
    for hits, blind, text, best, true in report["worst"]:
        print("  %2d/20  best %.4f of %.4f%s  %s" % (hits, best, true, "  MISSES ITS BEST" if blind else "", text[:60]))


def show(conn, report):
    size = lambda t: conn.execute("SELECT pg_total_relation_size(%s)", (t,)).fetchone()[0] / 1e6
    print("rows: lines %d, lines_new %d" % (fingerprint(conn, "lines")[0], fingerprint(conn, "lines_new")[0]))
    print("size: lines %.0fmb, lines_new %.0fmb" % (size("lines"), size("lines_new")))
    describe(report)
    if report["passed"]:
        print("\nif that all reads right: python -m ingest.rebuild_lines --swap")
    else:
        print("\ndo not swap, --swap will refuse: " + report["reason"])


def exchange(conn, incoming, outgoing, check=True):
    #incoming takes the name lines, lines takes the name outgoing, and every index,
    #constraint and the id sequence follows. the caller commits.
    #
    #SHARE first lets searches carry on while the fingerprints are read, and holds
    #off any write. ACCESS EXCLUSIVE is only wanted for the renames
    alone(conn)
    conn.execute("SET LOCAL lock_timeout = '" + LOCK_TIMEOUT + "'")
    conn.execute("LOCK TABLE lines IN SHARE MODE")
    if check and fingerprint(conn, "lines") != fingerprint(conn, incoming):
        raise Refused("lines has changed since " + incoming + " was copied from it")
    note = conn.execute("SELECT obj_description(%s::regclass, 'pg_class')", (incoming,)).fetchone()[0]
    if incoming == "lines_new" and not (note or "").startswith(PASSED):
        raise Refused("lines_new has not passed the recall check (" + (note or "never run") +
                      "). python -m ingest.rebuild_lines --check runs it again")
    seq = conn.execute("SELECT pg_get_serial_sequence('lines', 'id')").fetchone()[0]
    asked = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.execute("LOCK TABLE lines, " + incoming + ", line_tags IN ACCESS EXCLUSIVE MODE")
    held = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.execute("ALTER TABLE line_tags DROP CONSTRAINT line_tags_line_id_fkey")
    for old, new in (("lines", outgoing), (incoming, "lines")):
        conn.execute("ALTER TABLE " + old + " RENAME TO " + new)
        for suffix in CONSTRAINTS:
            conn.execute("ALTER TABLE " + new + " RENAME CONSTRAINT " + old + suffix + " TO " + new + suffix)
        for suffix in INDEXES:
            conn.execute("ALTER INDEX " + old + suffix + " RENAME TO " + new + suffix)
    conn.execute("ALTER SEQUENCE " + seq + " OWNED BY lines.id")
    #the verdict vouched for lines_new, and whatever leaves as lines_new next
    #gets checked again
    conn.execute("COMMENT ON TABLE lines IS NULL")
    #NOT VALID skips the scan of line_tags under the lock; validate() runs it after
    conn.execute("ALTER TABLE line_tags ADD CONSTRAINT line_tags_line_id_fkey FOREIGN KEY (line_id) "
                 "REFERENCES lines(id) ON DELETE CASCADE NOT VALID")
    done = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    return (held - asked).total_seconds(), (done - held).total_seconds()


def validate(conn):
    conn.execute("ALTER TABLE line_tags VALIDATE CONSTRAINT line_tags_line_id_fkey")


def main():
    ap = argparse.ArgumentParser()
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--check", action="store_true")
    act.add_argument("--swap", action="store_true")
    act.add_argument("--rollback", action="store_true")
    act.add_argument("--drop-old", action="store_true")
    act.add_argument("--discard", action="store_true")
    ap.add_argument("--force", action="store_true", help="roll back over writes the new table has taken")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    conn = psycopg.connect(db_url)
    register_vector(conn)
    try:
        if args.swap or args.rollback:
            incoming, outgoing = ("lines_new", "lines_old") if args.swap else ("lines_old", "lines_new")
            if not exists(conn, incoming):
                raise Refused("there is no " + incoming)
            if exists(conn, outgoing):
                raise Refused(outgoing + " already exists")
            waited, held = exchange(conn, incoming, outgoing, check=args.swap or not args.force)
            conn.commit()
            print("%s is live as lines: waited %.0fms for searches to finish, then held them %.0fms"
                  % (incoming, waited * 1000, held * 1000))
            validate(conn)
            conn.commit()
            print("line_tags' foreign key validated")
        elif args.drop_old or args.discard:
            t = "lines_old" if args.drop_old else "lines_new"
            if not exists(conn, t):
                raise Refused("there is no " + t)
            conn.execute("DROP TABLE " + t)
            conn.commit()
            print("dropped " + t)
        else:
            if args.check:
                alone(conn)
                if not exists(conn, "lines_new"):
                    raise Refused("there is no lines_new")
                conn.commit()
            else:
                for step, what in ((fill, "copying lines into lines_new at " + EMBED_TYPE),
                                   (constrain, "adding its keys"),
                                   (index, "building its indexes, the hnsw graph takes minutes")):
                    started = time.time()
                    print(what + "...")
                    step(conn)
                    conn.commit()
                    print("  %.0fs" % (time.time() - started))
            started = time.time()
            print("checking lines_new's recall against exact searches, about ten minutes...")
            conn.autocommit = True
            report = check(conn)
            record(conn, report)
            print("  %.0fs" % (time.time() - started))
            show(conn, report)
    except Refused as e:
        conn.rollback()
        print("refused, nothing changed: " + str(e))
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
