#does this copy of the weights still produce the vectors already in the table?
#
#the gate in front of two things: publishing the release asset (M2), and
#pointing the ingest at it instead of hugging face (M6). both replace where the
#weights come from, and a model that disagrees with the stored vectors does not
#fail loudly. it just makes every percent on the site slightly wrong, against a
#table embedded by something else.
#
#read only. it opens production, takes a sample of lines with their stored
#vectors, embeds the same text, and compares.
#
#    python tools/check_embed_parity.py --model /path/to/extracted/release
#    python tools/check_embed_parity.py            (whatever EMBED_MODEL names)
#
#the bar is a cosine of 0.999999 on EVERY sampled line, and it is UNIQUE_NOISE
#that sets it: web/app.py ties every card under 1e-6 at "other cards already do
#everything it does", so an error smaller than that cannot lift a card off the
#tie or move a percent. the halfvec rounding already in the column spends
#1.8e-7 of it and passes.

import os
import sys
import time
import argparse

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from common.vectors import unit_rows
from ingest.update import EMBED_MODEL, EMBED_PROMPT

#the same number web/app.py ties under. spelled here rather than imported,
#web/ not being importable from tools/ without its own sys.path games
UNIQUE_NOISE = 1e-6
BAR = 1 - UNIQUE_NOISE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="a folder of weights. default: whatever EMBED_MODEL names")
    ap.add_argument("--lines", type=int, default=400, help="how many stored lines to sample")
    ap.add_argument("--seed", type=int, default=None, help="fix the sample, for comparing two runs")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    register_vector(conn)
    if args.seed is not None:
        conn.execute("SELECT setseed(%s)", (args.seed / 2**31,))
    #whole rows included: they are text the model embedded too, and they are the
    #longest, which is where a tokenizer difference shows up first
    rows = conn.execute("SELECT line_text, embedding FROM lines ORDER BY random() LIMIT %s",
                        (args.lines,)).fetchall()
    conn.close()
    if not rows:
        print("no lines in the table, nothing to compare against")
        sys.exit(1)

    texts = [r[0] for r in rows]
    stored = unit_rows([r[1].to_numpy() for r in rows])

    print("loading " + (args.model or EMBED_MODEL) + "...")
    started = time.time()
    from sentence_transformers import SentenceTransformer
    #device fixed, or this machine's gpu answers for a service that has none
    model = SentenceTransformer(args.model or EMBED_MODEL, device="cpu")
    print("  %.1fs" % (time.time() - started))

    print("embedding " + str(len(texts)) + " lines, the call ingest/update.py makes...")
    started = time.time()
    fresh = model.encode(texts, batch_size=64, show_progress_bar=False,
                         normalize_embeddings=True, prompt=EMBED_PROMPT)
    print("  %.1fs" % (time.time() - started))

    cos = (unit_rows(fresh) * stored).sum(axis=1)
    order = np.argsort(cos)
    print("\ncosine against the stored vectors, over %d lines" % len(cos))
    print("  worst  %.9f" % cos[order[0]])
    print("  median %.9f" % float(np.median(cos)))
    print("  best   %.9f" % cos[order[-1]])

    failed = int((cos < BAR).sum())
    if failed:
        print("\n%d of %d below the bar of %.6f:" % (failed, len(cos), BAR))
        for i in order[:10]:
            if cos[i] < BAR:
                print("  %.9f  %s" % (cos[i], texts[i][:90]))
        print("\nFAILED. these weights are not the ones the table was embedded with.")
        sys.exit(1)
    print("\nevery line clears the bar of %.6f. these are the same weights." % BAR)


if __name__ == "__main__":
    main()
