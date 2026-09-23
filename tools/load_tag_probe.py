#fills tag_probe, which is what /custom reads to guess what typed text is about.
#
#run it after finetune/make_tagprobe.py has retrained, or after a verdict changes
#in finetune/testing_list/make_tagreview.md. nothing runs it on a schedule: the
#probe is trained on line_tags, and line_tags moves slowly.
#
#    python tools/load_tag_probe.py
#    python tools/load_tag_probe.py --probe some/other/tagprobe.npz --dry-run
#with DATABASE_URL set.
#
#three things go in, from three places: the weights from tagprobe.npz, which is
#gitignored and lives only on the machine that trained it; the never-a-chip
#verdicts from make_tagreview.md, which is in the repo; and the type shares,
#counted here out of card_tags so they are never a second copy of anything.
#
#one transaction, and DELETE rather than TRUNCATE: truncating takes ACCESS
#EXCLUSIVE and every /custom reading the table would queue behind it, where a
#delete of 1,933 rows blocks nobody
#
#SAFE TO RERUN: it replaces every row or writes none, and reads nothing it
#wrote last time

import os
import sys
import argparse

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from pgvector.psycopg import register_vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
#the ONE definition of how a type line is read, rather than a second copy of it
#in SQL: the site has to filter on the same word this counts by
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "finetune"))

from common import locks
from common.db import KEEPALIVE
from autotags import TYPES, card_type

PROBE = os.path.join(ROOT, "finetune", "tagdata", "tagprobe.npz")

#never chips whatever the score, on top of the review's verdicts. it needs the
#type line, which typed rules text does not carry, and it is deliberately not in
#make_tagreview.md: dropping it there would drop it from training too, where the
#model learns it at auc 0.91
UNSEEN = ("single-target-instant-sorcery",)


def read_probe(path):
    z = np.load(path, allow_pickle=True)
    return list(z["tags"]), z["weight"].astype(np.float32), z["bias"].astype(np.float32)


def read_banned():
    from make_tagreview import read_verdicts
    banned = {t for t, v in read_verdicts().items() if v in ("card", "junk")}
    return banned | set(UNSEEN)


def type_shares(conn):
    #what share of the cards carrying a tag are each type. inherited rows count:
    #a card that gives evasion is a creature whether a human typed the tag or the
    #tree implied it, and the question here is what the tag lands on
    counts = {}
    for tag, type_line in conn.execute("""
        SELECT ct.tag, c.type_line
        FROM card_tags ct JOIN cards c ON c.oracle_id = ct.oracle_id
    """):
        per = counts.setdefault(tag, {})
        kind = card_type(type_line)
        per[kind] = per.get(kind, 0) + 1
    shares = {}
    for tag, per in counts.items():
        total = sum(per.values()) or 1
        shares[tag] = {k: round(n / total, 6) for k, n in per.items()}
    return shares


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default=PROBE, help="the npz make_tagprobe.py wrote")
    ap.add_argument("--dry-run", action="store_true", help="say what would be written and stop")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    if not os.path.exists(args.probe):
        print(args.probe + " is not there. train it first: python finetune/make_tagprobe.py")
        sys.exit(1)

    tags, weight, bias = read_probe(args.probe)
    banned = read_banned()
    print("probe: %d tags, %d dims" % (len(tags), weight.shape[1]))
    print("never a chip: %d tags" % len(banned))

    conn = psycopg.connect(db_url, **KEEPALIVE)
    register_vector(conn)
    if not locks.claim(conn):
        print("something else holds the ingest lock, waiting for it...")
        locks.hold(conn)

    shares = type_shares(conn)
    print("type shares: %d tags counted over %s" % (len(shares), ", ".join(TYPES)))

    #the weights are fitted to ONE model's vector space, so they have to be stamped
    #with the model whose vectors they were trained against. a swap refills
    #lines.embedding and leaves tag_probe alone, and then every chip is noise that
    #still scores in [0,1]: views/custom.py's probe_stale is what refuses it, and
    #this row is the only thing it has to go on
    row = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
    model = row[0] if row else None
    print("vectors: embed_model = " + (model or "NOT SET, this database has no ingest behind it"))

    #every tag either half of the rule can name, so a tag with no probe still
    #arrives with its ban verdict and its type shares
    every = sorted(set(tags) | set(shares) | banned)
    probe_of = {t: i for i, t in enumerate(tags)}
    rows = []
    for tag in every:
        i = probe_of.get(tag)
        rows.append((tag,
                     None if i is None else weight[i],
                     None if i is None else float(bias[i]),
                     tag in banned,
                     Jsonb(shares.get(tag, {}))))
    print("%d rows: %d with a probe, %d without" %
          (len(rows), sum(1 for r in rows if r[1] is not None),
           sum(1 for r in rows if r[1] is None)))

    if args.dry_run:
        print("dry run, nothing written")
        conn.close()
        return

    #the table arrives with common/schema.sql, which the ingest runs and web
    #creates its own copy of at boot. before either has happened against this
    #database the write below is an UndefinedTable nobody can read, so it says
    #so instead. checked here and not before the dry run, which is worth having
    #while the deploy is still waiting
    if conn.execute("SELECT to_regclass('tag_probe')").fetchone()[0] is None:
        print("tag_probe is not in this database yet: deploy web, or let the daily "
              "ingest run, and try again")
        conn.close()
        sys.exit(1)

    #without this there is nothing to stamp the weights with, and chips that cannot
    #be proved to match the vectors do not show at all. a database with no ingest
    #behind it has no vectors to match either
    if not model:
        print("meta has no embed_model: run the ingest against this database first")
        conn.close()
        sys.exit(1)

    #plain inserts rather than a COPY: 1,933 rows is nothing, and a COPY of a
    #vector column has to go through binary mode and set_types to say what it
    #is carrying.
    #
    #the commit is the whole of it: everything above ran in the transaction the
    #first SELECT opened, so the delete and the inserts land together, and
    #without this line closing the connection throws them away. a conn.transaction()
    #block here would be a SAVEPOINT inside that same transaction and commit nothing
    conn.execute("DELETE FROM tag_probe")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO tag_probe (tag, w, b, banned, types) "
                        "VALUES (%s, %s, %s, %s, %s)", rows)
    #in the SAME transaction as the rows, so the stamp can never name a model the
    #weights beside it were not loaded against
    conn.execute("INSERT INTO meta (key, value) VALUES ('tag_probe_model', %s) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (model,))
    conn.commit()
    print("wrote %d rows to tag_probe, stamped %s" % (len(rows), model))
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
