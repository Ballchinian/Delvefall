#works out which tags each LINE of a card is about, so the search page can
#narrow the concept axis to the ability you picked instead of always scoring
#the whole card's tag vector.
#
#the problem this solves: tagger tags CARDS. a card tagged donate-token,
#gives-pp-counters-to-all and evasion offers no way to know that the first
#belongs to its token mode and the last to its "Flying, double strike" line,
#so picking one line used to change the rules-text axis and leave the concept
#axis searching all of them at once.
#
#the inference is corpus-shaped rather than semantic. for a line, pull its
#nearest neighbour lines from every OTHER card, then ask of each of its card's
#tags: what share of those neighbour cards carry this tag, against the share
#the whole game carries it? that ratio is the lift, and a high one means this
#line is why the card got the tag. it needs no model and no understanding:
#"Overload {6}{U}" carries no meaning at all, but its neighbours are other
#overload cards, and those are tagged sweeper-one-sided, so the tag lands on
#the right line anyway.
#
#run it from the repo root, after the card and tag ingests:
#    python -m ingest.attribute
#with DATABASE_URL set. needs numpy and psycopg, no torch and no model, since
#every embedding it reads is already in the database.

import os
import sys

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

#how many neighbour lines vote. 200 is wide enough that a common line still
#gathers a varied neighbourhood and narrow enough that a rare one doesn't
#reach past its real family into noise
NEIGHBOURS = 200

#a tag has to appear in a line's neighbourhood at least this many times more
#often than in the game at large before that line is credited with it. 1.5 is
#deliberately low: the ratio decides which line OWNS a tag, and the floor only
#exists to reject lines whose neighbourhood is indifferent to it. evergreen
#tags sit near the bottom of this range on purpose ("Flying, double strike"
#lifts evasion 2.4x, which is weak but still the right line for it)
FLOOR = 1.5

#once a tag's best line is known, any other line within this fraction of that
#best also gets it. modal cards are why: each mode line lifts "modal" hard,
#and crediting only the single strongest would make picking any other mode
#silently drop the tag
RATIO = 0.4


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    register_vector(conn)  #without this the embeddings arrive as strings
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()

    total_cards = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
    if not total_cards:
        print("no cards yet, nothing to attribute")
        return

    #every tag a card carries, rolled up, is what the neighbours vote WITH.
    #only the typed ones get attributed though: the inherited ancestors follow
    #from the tree at query time, the same way they do for a whole card
    print("reading tags...")
    all_tags = {}
    typed_tags = {}
    for oid, tag, inherited in conn.execute("SELECT oracle_id, tag, inherited FROM card_tags"):
        oid = str(oid)
        all_tags.setdefault(oid, set()).add(tag)
        if not inherited:
            typed_tags.setdefault(oid, set()).add(tag)
    base_rate = {}
    for tag, count in conn.execute("SELECT tag, card_count FROM tags"):
        base_rate[tag] = max(count, 1) / total_cards
    print("  " + str(len(typed_tags)) + " cards carry at least one typed tag")

    #whole-card rows stay out, exactly like every other line-shaped pass
    print("reading line embeddings...")
    ids = []
    owners = []
    vecs = []
    for lid, oid, vec in conn.execute("SELECT id, oracle_id, embedding FROM lines WHERE NOT whole ORDER BY id"):
        ids.append(lid)
        owners.append(str(oid))
        vecs.append(vec.to_numpy())  #pgvector hands back its own Vector class
    if not ids:
        print("no lines yet, nothing to attribute")
        return
    emb = np.asarray(vecs, dtype=np.float32)
    del vecs
    print("  pulled " + str(len(ids)) + " embeddings")

    rows_of_card = {}
    for i, oid in enumerate(owners):
        rows_of_card.setdefault(oid, []).append(i)

    #same blocked multiply as the uniqueness pass: the embeddings are
    #normalized so cosine is a plain dot product, and blocking keeps the
    #similarity matrix around 100mb instead of the 13gb the whole thing would
    #need. argpartition beats a sort here, nothing cares about the order
    #within a neighbourhood, only who is in it
    print("finding neighbourhoods...")
    k = min(NEIGHBOURS, len(ids) - 1)
    neighbours = np.zeros((len(ids), k), dtype=np.int32)
    block = 512
    for start in range(0, len(ids), block):
        sims = emb[start:start + block] @ emb.T
        for r in range(sims.shape[0]):
            sims[r, rows_of_card[owners[start + r]]] = -2.0  #a card never votes on itself
        neighbours[start:start + block] = np.argpartition(sims, -k, axis=1)[:, -k:]
        if start % (block * 20) == 0:
            print("  " + str(start) + "/" + str(len(ids)))
    del emb

    #the vote. only a line's own card's typed tags are ever scored, so this is
    #~6 lookups per neighbour rather than a pass over all 8k tags
    print("scoring...")
    lift_of = {}  #(line index, tag) -> lift
    for i in range(len(ids)):
        mine = typed_tags.get(owners[i])
        if not mine:
            continue
        nb_cards = {owners[j] for j in neighbours[i]}
        nb_cards.discard(owners[i])
        if not nb_cards:
            continue
        for tag in mine:
            hits = 0
            for cid in nb_cards:
                if tag in all_tags.get(cid, ()):
                    hits += 1
            lift_of[(i, tag)] = (hits / len(nb_cards)) / base_rate.get(tag, 1.0)

    #now decide, per card and per tag, which of its lines earned it. the best
    #line sets the bar, everything within RATIO of it shares the credit, and a
    #tag whose best line never clears FLOOR belongs to the card rather than to
    #any one ability, so every line gets it
    print("assigning...")
    rows = []
    for oid, line_idxs in rows_of_card.items():
        for tag in typed_tags.get(oid, ()):
            lifts = [(i, lift_of.get((i, tag), 0.0)) for i in line_idxs]
            best = max(l for _, l in lifts)
            if best < FLOOR:
                for i, l in lifts:
                    rows.append((ids[i], tag, l, True))
                continue
            bar = max(best * RATIO, FLOOR)
            for i, l in lifts:
                if l >= bar:
                    rows.append((ids[i], tag, l, False))

    print("writing " + str(len(rows)) + " line-tag rows...")
    with conn.cursor() as cur:
        cur.execute("TRUNCATE line_tags")
        with cur.copy("COPY line_tags (line_id, tag, lift, card_level) FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)
    conn.commit()

    covered = conn.execute("SELECT count(DISTINCT line_id) FROM line_tags").fetchone()[0]
    card_level = conn.execute("SELECT count(*) FROM line_tags WHERE card_level").fetchone()[0]
    conn.close()
    print("done! " + str(covered) + "/" + str(len(ids)) + " lines carry tags, "
          + str(card_level) + " rows are card-level")


if __name__ == "__main__":
    main()
