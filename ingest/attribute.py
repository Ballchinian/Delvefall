#which tags each LINE is about, so the search page can narrow the concept axis to
#the ability you picked. tagger tags cards, not lines, so a card tagged
#donate-token and evasion gives no way to know the first belongs to its token
#mode and the last to its "Flying, double strike" line.
#
#the inference is corpus-shaped rather than semantic: for a line, pull its
#nearest neighbour lines from other cards, then ask of each of its card's tags
#what share of those neighbours carry it against the share the whole game does.
#that ratio is the LIFT. no model and no understanding needed, which is the point
#- "Overload {6}{U}" means nothing by itself, but its neighbours are other
#overload cards tagged sweeper-one-sided, so the tag still lands right.
#
#from the repo root, after the card and tag ingests:
#    python -m ingest.attribute
#with DATABASE_URL set. no torch, every embedding it reads is already stored

import os
import sys

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

#how many neighbour lines vote. wide enough that a common line still gathers a
#varied neighbourhood, narrow enough that a rare one does not reach past its real
#family into noise
NEIGHBOURS = 200

#the minimum lift before a line is credited with a tag. low because the RATIO is
#what decides which line owns a tag and this only rejects neighbourhoods that are
#indifferent to it. evergreen tags sit near the bottom ("Flying, double strike"
#lifts evasion 2.4x, weak but still the right line)
FLOOR = 1.5

#below this a line has no claim at all. 1.0 is the neutral point of a lift ratio,
#so anything near it is evidence of nothing and the tag goes on NO line rather
#than the least-bad one
NOISE = 1.15

#once a tag's best line is known, other lines within this fraction of it share
#the credit. modal cards are why: each mode lifts "modal" hard, and crediting
#only the strongest would make picking any other mode drop the tag.
#
#tuned for PRECISION over recall, a set-aside tag costing one click on the page's
#yestags while a wrong one drags the whole search sideways. against a
#hand-labelled Shadrix Silverquill, 0.4 gives 88% precision / 82% recall and 0.6
#gives 93% / 76%. one card is thin, so the third digit here means nothing
RATIO = 0.6

#so a trial model's attribution can be built without disturbing the live one.
#tools/check_sync.py fails the push if this drifts from web/mirror.py
EMBED_COLUMNS = ("embedding", "embedding_v2")


def embed_column():
    col = os.environ.get("EMBED_COLUMN", "").strip() or "embedding"
    if col not in EMBED_COLUMNS:
        raise ValueError("EMBED_COLUMN must be one of " + ", ".join(EMBED_COLUMNS))
    return col


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

    #neighbours vote with a card's whole rolled-up set, but only the TYPED tags
    #get attributed: the inherited ancestors follow from the tree at query time
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
    col = embed_column()
    if col != "embedding":
        print("  reading " + col + " rather than the live column")
    for lid, oid, vec in conn.execute(
            "SELECT id, oracle_id, " + col + " FROM lines WHERE NOT whole AND "
            + col + " IS NOT NULL ORDER BY id"):
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

    #the same blocked multiply as the uniqueness pass, keeping the similarity
    #matrix near 100mb instead of 13gb. argpartition rather than a sort, nothing
    #caring about the order within a neighbourhood, only who is in it
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

    #how many lines each card has, for the first pass's damping below
    lines_on_card = {oid: len(idxs) for oid, idxs in rows_of_card.items()}

    def assign(lift_of):
        #a tag no line shows evidence for lands on NO line. tags like
        #invitational-card describe the card rather than an ability, and Omnath's
        #unique-mana-cost has no business turning up under "when this card
        #enters, draw a card". parking those on every line instead was the single
        #largest source of false positives on the hand-labelled cards
        out = {}
        for oid, line_idxs in rows_of_card.items():
            for tag in typed_tags.get(oid, ()):
                lifts = [(i, lift_of.get((i, tag), 0.0)) for i in line_idxs]
                best = max(l for _, l in lifts)
                #a bar of "above zero" is not enough: Omnath's unique-mana-cost
                #sits at exactly 1.0x on "when this card enters, draw a card",
                #which is no evidence at all, and would clear it
                if best < NOISE:
                    continue
                #near-best only when the signal is weak, since RATIO of a
                #small number would wave nearly every line through
                bar = max(best * RATIO, FLOOR) if best >= FLOOR else best * 0.9
                for i, l in lifts:
                    if l >= bar:
                        out[(i, tag)] = l
        return out

    #pass one: neighbours vote with their whole CARD's tags, card-level tags
    #being all there is to start from. that is also its flaw, a five-line
    #neighbour donating all five lines' worth of tags to whichever line matched,
    #so each vote is damped by the line count. a one-line card speaks at full
    #volume, knowing exactly which line earned its tags
    print("scoring, pass one (cards vote)...")
    lift_of = {}
    for i in range(len(ids)):
        mine = typed_tags.get(owners[i])
        if not mine:
            continue
        votes = {}
        for j in neighbours[i]:
            cid = owners[j]
            if cid != owners[i]:
                votes[cid] = 1.0 / lines_on_card.get(cid, 1)
        if not votes:
            continue
        total_vote = sum(votes.values())
        for tag in mine:
            hit = 0.0
            for cid, w in votes.items():
                if tag in all_tags.get(cid, ()):
                    hit += w
            lift_of[(i, tag)] = (hit / total_vote) / base_rate.get(tag, 1.0)
    first = assign(lift_of)

    #pass two: with a provisional guess on every line, neighbours can now vote
    #with their own LINE's tags. against a hand-labelled card this lifts
    #precision from 60% to 88% at the same neighbourhood, a line merely sitting
    #on a card with an unrelated ability stopping donating it
    print("scoring, pass two (lines vote)...")
    line_tags_now = {}
    for (i, tag) in first:
        line_tags_now.setdefault(i, set()).add(tag)
    lift2 = {}
    for i in range(len(ids)):
        mine = typed_tags.get(owners[i])
        if not mine:
            continue
        nb = [j for j in neighbours[i] if owners[j] != owners[i]]
        if not nb:
            continue
        for tag in mine:
            hits = 0
            for j in nb:
                if tag in line_tags_now.get(j, ()):
                    hits += 1
            lift2[(i, tag)] = (hits / len(nb)) / base_rate.get(tag, 1.0)

    #pass two SHARPENS, it does not erase. a rare tag can be real on one line and
    #still have no neighbour line carrying it yet (Omnath's sweeper-one-sided),
    #where pass two reads zero. so it wins wherever it found anything for a tag,
    #and pass one stands where it found nothing
    print("assigning...")
    second = assign(lift2)
    seen_in_second = {(owners[i], tag) for i, tag in second}
    final = dict(second)
    for (i, tag), l in first.items():
        if (owners[i], tag) not in seen_in_second:
            final[(i, tag)] = l

    rows = [(ids[i], tag, l, False) for (i, tag), l in final.items()]

    print("writing " + str(len(rows)) + " line-tag rows...")
    with conn.cursor() as cur:
        cur.execute("TRUNCATE line_tags")
        with cur.copy("COPY line_tags (line_id, tag, lift, card_level) FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)
    conn.commit()

    covered = conn.execute("SELECT count(DISTINCT line_id) FROM line_tags").fetchone()[0]
    conn.close()
    print("done! " + str(covered) + "/" + str(len(ids)) + " lines carry tags")


if __name__ == "__main__":
    main()
