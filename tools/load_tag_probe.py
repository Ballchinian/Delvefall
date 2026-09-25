#fills tag_probe, which is what /custom reads to guess what typed text is about.
#
#run it after finetune/make_tagprobe.py has retrained, or after a verdict changes
#in finetune/testing_list/make_tagreview.md. nothing runs it on a schedule: the
#probe is trained on line_tags, and line_tags moves slowly. it refuses a probe
#trained against other weights than the ones that made the vectors.
#
#    python tools/load_tag_probe.py
#    python tools/load_tag_probe.py --probe some/other/tagprobe.npz --dry-run
#with DATABASE_URL set.
#
#two things go in, from two places: the weights from tagprobe.npz, which is
#gitignored and lives only on the machine that trained it, and the never-a-chip
#verdicts from make_tagreview.md, which is in the repo. the types column is left
#at its default: /custom has no type filter.
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
from pgvector.psycopg import register_vector

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "finetune"))

from common import locks
from common.db import KEEPALIVE

PROBE = os.path.join(ROOT, "finetune", "tagdata", "tagprobe.npz")

#never chips whatever the score, on top of the review's verdicts. it needs the
#type line, which typed rules text does not carry, and it is deliberately not in
#make_tagreview.md: dropping it there would drop it from training too, where the
#model learns it at auc 0.91
UNSEEN = ("single-target-instant-sorcery",)


def read_probe(path):
    #model and sha256 are the weights whose vectors it was trained on, which
    #finetune/make_tagprobe.py copies out of the frozen meta. an npz without
    #them is refused
    z = np.load(path, allow_pickle=True)
    trained = (str(z["model"]), str(z["sha256"])) if "sha256" in z.files else (None, None)
    return list(z["tags"]), z["weight"].astype(np.float32), z["bias"].astype(np.float32), trained


def mismatch(trained, weights):
    #why a probe trained against the weights `trained` cannot score vectors made
    #by `weights`, or "". both are release sha256s. the fix for a stale probe is
    #a new one, since reloading the same npz stamps the same old weights
    retrain = ("refreeze (finetune/freeze_tagdata.py), retrain (finetune/make_tagprobe.py), "
               "then load")
    if not trained:
        return "the probe records no weights it was trained against: " + retrain
    if not weights:
        return "meta has no embed_sha256: run the ingest against this database first"
    if trained != weights:
        return ("the probe was trained against weights " + trained[:12] + " and the vectors are " +
                weights[:12] + ": " + retrain)
    return ""


def read_banned():
    from make_tagreview import read_verdicts
    banned = {t for t, v in read_verdicts().items() if v in ("card", "junk")}
    return banned | set(UNSEEN)


def carried(conn):
    #every tag a card carries, inherited rows included. each gets a row whether
    #or not it has a probe, since tag_chips reads a chip's description through it
    return {r[0] for r in conn.execute("SELECT DISTINCT tag FROM card_tags")}


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

    tags, weight, bias, (trained_on, trained) = read_probe(args.probe)
    banned = read_banned()
    print("probe: %d tags, %d dims" % (len(tags), weight.shape[1]))
    print("never a chip: %d tags" % len(banned))

    conn = psycopg.connect(db_url, **KEEPALIVE)
    register_vector(conn)
    if not locks.claim(conn):
        print("something else holds the ingest lock, waiting for it...")
        locks.hold(conn)

    on_cards = carried(conn)
    print("tags on cards: %d" % len(on_cards))

    #the weights are fitted to ONE model's vector space, so they have to be stamped
    #with the model whose vectors they were trained against. a swap refills
    #lines.embedding and leaves tag_probe alone, and then every chip is noise that
    #still scores in [0,1]: views/custom.py's probe_stale is what refuses it, and
    #these rows are the only thing it has to go on
    said = dict(conn.execute("SELECT key, value FROM meta WHERE key IN ('embed_model', 'embed_sha256')"))
    weights = said.get("embed_sha256")
    print("vectors: %s at %s" % (said.get("embed_model") or "no embed_model",
                                 (weights or "no embed_sha256")[:12]))
    print("probe trained against: %s at %s" % (trained_on or "no model", (trained or "no sha256")[:12]))
    why = mismatch(trained, weights)
    if why:
        print(why)

    #every tag either half of the rule can name, so a tag with no probe still
    #arrives with its ban verdict
    every = sorted(set(tags) | on_cards | banned)
    probe_of = {t: i for i, t in enumerate(tags)}
    rows = []
    for tag in every:
        i = probe_of.get(tag)
        rows.append((tag,
                     None if i is None else weight[i],
                     None if i is None else float(bias[i]),
                     tag in banned))
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

    #a stamp naming weights the probe was not trained against would pass
    #probe_stale and show noise as chips
    if why:
        print("refused, nothing written")
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
        cur.executemany("INSERT INTO tag_probe (tag, w, b, banned) "
                        "VALUES (%s, %s, %s, %s)", rows)
    #in the SAME transaction as the rows, so the stamp can never name a model the
    #weights beside it were not trained against
    for key, value in (("tag_probe_model", trained_on), ("tag_probe_sha256", trained)):
        conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))
    conn.commit()
    print("wrote %d rows to tag_probe, stamped %s at %s" % (len(rows), trained_on, trained[:12]))
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
