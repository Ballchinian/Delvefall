#fills a second embedding column so a new model can be tried without losing
#the old vectors.
#
#the problem it solves: swapping EMBED_MODEL and running the daily update
#overwrites every vector in place. that is a one way door. the old numbers are
#gone, and the only way back is rerunning the old model over the whole corpus,
#which needs the gpu and the private repo all over again. a code tag cannot
#resurrect vectors that were never stored.
#
#so this writes into lines.embedding_v2 instead, leaving lines.embedding
#exactly as the site is serving it. when the fill is done:
#    EMBED_COLUMN=embedding_v2   on the web service   -> the site reads the new model
#    unset it                                         -> straight back to the old one
#both sets of numbers stay in the database the whole time, so the comparison is
#a variable flip rather than a restore, and it happens on one deployment rather
#than prod against a staging copy.
#
#run it from the repo root, with DATABASE_URL and HF_TOKEN set:
#    python -m ingest.backfill_embeddings --model BallchinianMan/whatever-is-new
#it needs torch and the model, so it belongs wherever the training ran rather
#than on a laptop. reruns are safe: it only fills rows that are still NULL,
#so a run that dies halfway picks up where it stopped.
#
#when the trial ends, whichever way it went:
#    ALTER TABLE lines DROP COLUMN embedding_v2;      (drops the index with it)
#and if the new model won, swap EMBED_MODEL in update.py and let the next daily
#run rebuild the real column from scratch.

import os
import sys
import argparse

import psycopg
from pgvector.psycopg import register_vector

from ingest.update import EMBED_MODEL, EMBED_PROMPT

TARGET = "embedding_v2"

#rows per encode-and-write cycle. the whole corpus is ~60k lines, and doing it
#in one go means holding every vector in memory and losing the lot if the
#connection drops an hour in. committing per batch is what makes a rerun cheap
BATCH = 2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None,
                    help="hugging face repo to embed with, defaults to the ingest's own model")
    ap.add_argument("--prompt", default=None,
                    help="task prefix, defaults to the ingest's. it must match what the model was trained with")
    ap.add_argument("--index", action="store_true",
                    help="build the hnsw index when the fill is complete")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    model_name = args.model or EMBED_MODEL
    prompt = args.prompt if args.prompt is not None else EMBED_PROMPT

    conn = psycopg.connect(db_url)
    register_vector(conn)
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()

    total = conn.execute("SELECT count(*) FROM lines").fetchone()[0]
    todo = conn.execute("SELECT count(*) FROM lines WHERE " + TARGET + " IS NULL").fetchone()[0]
    print(str(total) + " lines, " + str(todo) + " still need " + TARGET)
    if not todo:
        print("nothing to fill")
    else:
        print("embedding with " + model_name)
        if model_name == EMBED_MODEL:
            print("WARNING: that is the model already in lines.embedding, so this fills")
            print("the second column with a copy of the first. pass --model to use a new one.")
        #imported down here so a finished run costs nothing: the torch import
        #alone takes longer than everything else in this script
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)

        done = 0
        while True:
            rows = conn.execute(
                "SELECT id, line_text FROM lines WHERE " + TARGET + " IS NULL LIMIT %s",
                (BATCH,)).fetchall()
            if not rows:
                break
            texts = [r[1] for r in rows]
            embs = model.encode(texts, batch_size=64, show_progress_bar=False,
                                normalize_embeddings=True, prompt=prompt)
            with conn.cursor() as cur:
                cur.executemany("UPDATE lines SET " + TARGET + " = %s WHERE id = %s",
                                [(embs[i], rows[i][0]) for i in range(len(rows))])
            conn.commit()
            done += len(rows)
            print("  " + str(done) + "/" + str(todo))

    left = conn.execute("SELECT count(*) FROM lines WHERE " + TARGET + " IS NULL").fetchone()[0]
    print(str(total - left) + "/" + str(total) + " rows carry " + TARGET)

    #the index is built at the end rather than existing during the fill: an
    #hnsw graph that has to absorb 60k updates one batch at a time is both slow
    #to write and worse connected than one built over the finished column
    if args.index:
        if left:
            print("not building the index, " + str(left) + " rows are still empty")
        else:
            #SERIAL BUILD ON PURPOSE. a parallel maintenance worker allocates a
            #shared memory segment, and railway's container cannot grow
            #/dev/shm to the ~61mb one asks for: the build dies with DiskFull
            #"could not resize shared memory segment", which reads like the
            #disk is full when there is plenty of room (847mb database, and it
            #was the fill that needed the space, not this). zero workers means
            #no segment, no failure, and a build that is slower but finishes.
            #
            #maintenance_work_mem is raised for this session too where the plan
            #allows it. 64mb cannot hold a 60k by 768 graph, so pgvector spills
            #to a slower on-disk path and warns about it. neither setting
            #outlives the connection
            print("building the hnsw index, this takes a few minutes...")
            try:
                conn.execute("SET max_parallel_maintenance_workers = 0")
                conn.execute("SET maintenance_work_mem = '512MB'")
            except Exception as e:
                print("  could not raise the build settings, continuing: " + str(e)[:90])
            try:
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS lines_embedding_v2_hnsw ON lines
                    USING hnsw (""" + TARGET + """ vector_cosine_ops)
                    WITH (m = 32, ef_construction = 200) WHERE (NOT whole)
                """)
                conn.commit()
                print("done")
            except Exception as e:
                #the vectors are the expensive part and they are already
                #committed, so say so loudly rather than let a failed index
                #read as a failed run
                conn.rollback()
                print("\nINDEX BUILD FAILED: " + str(e)[:160])
                print("the vectors are fine and committed, this is only the index.")
                print("evaluation does not need it (tag_eval reads vectors into numpy),")
                print("so measure first, then retry the index with:")
                print("  python -m ingest.backfill_embeddings --model " + model_name + " --index")
                print("which skips straight to it, no model download, since nothing is NULL.")
                conn.close()
                sys.exit(1)
    elif not left:
        print("\nrerun with --index to build the hnsw index, the searches need it")

    conn.close()
    print("\nthen point the web service at it with EMBED_COLUMN=" + TARGET)
    print("and unset that variable to go straight back to the live model")


if __name__ == "__main__":
    main()
