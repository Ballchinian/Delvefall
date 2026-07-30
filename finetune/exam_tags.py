#the exam for the line -> tag objective, and the bar a retrain has to clear.
#with DATABASE_URL set:
#    python -m finetune.exam_tags
#
#it asks a retrieval question: shown one line and every learnable tag in the
#game, does the model rank the right tags first?
#
#NOT the obvious harness, which would score ingest/attribute.py against the held
#out cards. that one cannot fail: attribute.py narrows a card's own typed tags
#onto its own lines, and a single-line card's held out set is those tags, so
#every attribution is right by construction (100.0% precision on 4392 hits).
#scoring unlearnable tags drops it to 76.4%, but those are holes in the answer
#key rather than errors, and a harness whose failures are holes in its own ground
#truth cannot show a model improving.
#
#two ways to represent a tag, and a fair comparison uses each model's own:
#  centroid  mean vector of the training cards carrying the tag. needs no model,
#            only the stored vectors, so it runs locally. the only fair scorer
#            for the line-to-line model, never taught what a slug says
#  text      cosine against the embedded "slug: description", what the retrain is
#            taught directly. needs the model, so it wants the gpu box
#
#judge the old model by centroid, the new one by BOTH: one that cannot beat the
#old centroid score on centroid did not work, whatever its text number says.

import os
import sys
import json
import argparse

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "traindata")
#both invocation styles work: -m puts the repo root on the path, the direct path
#puts only finetune/ there, and the imports here need both
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

#below this the mean is one or two cards' noise, and the tag would be unrankable
#for reasons that have nothing to do with the model
MIN_CENTROID_CARDS = 5

#1 is "is the top answer right at all", 10 is roughly the size of a tag list a
#human would skim
KS = (1, 3, 5, 10)

#of the tags a line really is about, what share land in its top ten. that is what
#the line picker puts in front of a person, which is why this metric and not one
#of the other three printed. the baseline sits a long way off at 47.0%
SHIP_METRIC = "recall @10"
SHIP_BAR = 0.95


def load_testset():
    path = os.path.join(DATA_DIR, "tag_testset.jsonl")
    if not os.path.exists(path):
        print("no tag_testset.jsonl, run: python finetune/make_training.py --tags-only")
        sys.exit(1)
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    if rows and "oracle_id" not in rows[0]:
        print("tag_testset.jsonl predates the oracle_id column, regenerate it:")
        print("  python finetune/make_training.py --tags-only")
        sys.exit(1)
    return rows


def load_learnability():
    #the candidate pool has to be the set the model was TRAINED on, not the set
    #the AUC happens to like, or the exam asks for tags nobody taught and marks
    #down tags it did. trainable_tags is the one place that decides, shared with
    #make_training.py so the two cannot drift
    from make_tagreview import trainable_tags
    path = os.path.join(DATA_DIR, "tag_learnability.json")
    if not os.path.exists(path):
        print("no tag_learnability.json, run: python finetune/make_training.py --tags-only")
        sys.exit(1)
    blob = json.load(open(path, encoding="utf-8"))
    bar = blob["threshold"]
    pool, rescued, removed = trainable_tags(blob["auc"], bar)
    if rescued or removed:
        print("tag_review.md rescued " + str(len(rescued)) + " tags the AUC excluded and pulled "
              + str(len(removed)) + " it kept")
    return pool, bar


def load_single_line_cards(conn):
    #the test set is drawn from exactly this population, so the training half of
    #it is what the centroids are built from.
    #
    #the column comes from EMBED_COLUMN, the same switch the site reads: after
    #backfill_embeddings.py fills embedding_v2,
    #    EMBED_COLUMN=embedding_v2 python -m finetune.exam_tags
    #scores the new model's stored vectors on the same exam as the old one's
    from ingest.attribute import embed_column
    col = embed_column()
    if col != "embedding":
        print("reading " + col + " rather than the live column")
    rows = conn.execute("""
        WITH one AS (SELECT oracle_id FROM lines WHERE NOT whole
                     GROUP BY oracle_id HAVING count(*) = 1)
        SELECT l.oracle_id, l.line_text, l.""" + col + """ FROM lines l
        JOIN one o ON o.oracle_id = l.oracle_id
        WHERE NOT l.whole AND l.""" + col + """ IS NOT NULL
    """).fetchall()
    out = {}
    for oid, text, vec in rows:
        out[str(oid)] = (text, vec.to_numpy())
    return out


def load_typed_tags(conn):
    tags = {}
    for oid, tag in conn.execute("SELECT oracle_id, tag FROM card_tags WHERE NOT inherited"):
        tags.setdefault(str(oid), set()).add(tag)
    return tags


def normalize(m):
    return m / (np.linalg.norm(m, axis=-1, keepdims=True) + 1e-9)


def build_centroids(cards, typed, pool, test_texts):
    #excluded by LINE TEXT, not oracle_id: a functional reprint prints the same
    #sentence under a different id, and letting one into a centroid leaks the
    #exam line into the thing being ranked against it
    members = {}
    for oid, (text, vec) in cards.items():
        if text in test_texts:
            continue
        for tag in typed.get(oid, ()):
            if tag in pool:
                members.setdefault(tag, []).append(vec)
    tags, mat, counts = [], [], {}
    for tag in sorted(members):
        if len(members[tag]) < MIN_CENTROID_CARDS:
            continue
        tags.append(tag)
        mat.append(normalize(np.asarray(members[tag], dtype=np.float32)).mean(axis=0))
        counts[tag] = len(members[tag])
    return tags, normalize(np.asarray(mat, dtype=np.float32)), counts


def build_tag_texts(conn, tags, model_name, prompt):
    #only reachable where the model can actually be loaded
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("the text scorer needs sentence-transformers and torch, which are not installed here.")
        print("run it on the box that trains the model, or stay with --scorer centroid")
        sys.exit(1)
    desc = {r[0]: r[1] for r in conn.execute("SELECT tag, description FROM tags")}
    texts = [t + (": " + desc[t].strip() if (desc.get(t) or "").strip() else "") for t in tags]
    print("embedding " + str(len(texts)) + " tag texts with " + model_name + "...")
    model = SentenceTransformer(model_name)
    return normalize(np.asarray(model.encode([prompt + t for t in texts]), dtype=np.float32))


def evaluate(sims, golds, tags, label):
    #sims is one row per held out card, one column per candidate tag, already
    #cosine. golds is the matching gold sets, already cut to the candidate pool
    ix = {t: i for i, t in enumerate(tags)}
    order = np.argsort(-sims, axis=1)

    hits = {k: 0 for k in KS}
    prec = {k: 0.0 for k in KS}
    rec = {k: 0.0 for k in KS}
    rprec_sum = ap_sum = 0.0
    scored = 0
    for row in range(len(golds)):
        gold = golds[row]
        if not gold:
            continue
        scored += 1
        ranked = [tags[i] for i in order[row]]
        gold_ranks = [i for i, t in enumerate(ranked) if t in gold]
        for k in KS:
            got = len(set(ranked[:k]) & gold)
            prec[k] += got / k
            rec[k] += got / len(gold)
            hits[k] += 1 if got else 0
        n = len(gold)
        rprec_sum += len(set(ranked[:n]) & gold) / n
        ap_sum += sum((j + 1) / (r + 1) for j, r in enumerate(gold_ranks)) / n

    #the best a single global cutoff could do, the number that would matter if
    #attribution ever scored tags directly instead of voting
    flat = sims.reshape(-1)
    truth = np.zeros(sims.shape, dtype=bool)
    for row, gold in enumerate(golds):
        for t in gold:
            truth[row, ix[t]] = True
    truth = truth.reshape(-1)
    o = np.argsort(-flat)
    tp = np.cumsum(truth[o])
    picked = np.arange(1, len(flat) + 1)
    total = truth.sum()
    f1 = 2 * tp / (picked + total)
    best = int(np.argmax(f1))

    print()
    print("== " + label + "  (" + str(scored) + " cards, " + str(len(tags)) + " candidate tags)")
    for k in KS:
        print("  @%-3d precision %5.1f%%  recall %5.1f%%   %5.1f%% of cards get one right"
              % (k, 100 * prec[k] / scored, 100 * rec[k] / scored, 100 * hits[k] / scored))
    print("  R-precision %.1f%%   MAP %.1f%%" % (100 * rprec_sum / scored, 100 * ap_sum / scored))
    print("  best single cutoff: precision %.1f%% recall %.1f%% F1 %.1f%% at cosine %.3f"
          % (100 * tp[best] / picked[best], 100 * tp[best] / total, 100 * f1[best], flat[o][best]))
    ship = rec[10] / scored
    print("  SHIP BAR " + SHIP_METRIC + " %.1f%% of %.0f%%: %s"
          % (100 * ship, 100 * SHIP_BAR, "PASS" if ship >= SHIP_BAR else "not yet"))
    return {"map": ap_sum / scored, "rprec": rprec_sum / scored,
            "f1": float(f1[best]), "ship": ship}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorer", default="centroid", choices=["centroid", "text", "both"])
    ap.add_argument("--model", default=None, help="only for the text scorer, defaults to the ingest model")
    ap.add_argument("--worst", type=int, default=12, help="how many hardest tags to list")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = os.path.join(HERE, "..", ".env")
        if os.path.exists(env_path):
            for raw in open(env_path, encoding="utf-8"):
                if raw.strip().startswith("DATABASE_URL="):
                    db_url = raw.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    register_vector(conn)

    held = load_testset()
    pool, _ = load_learnability()
    print(str(len(held)) + " held out cards, " + str(len(pool)) + " trainable tags to rank")

    cards = load_single_line_cards(conn)
    typed = load_typed_tags(conn)
    test_texts = {h["line"] for h in held}
    tags, centroids, counts = build_centroids(cards, typed, pool, test_texts)
    print(str(len(tags)) + " of those have at least " + str(MIN_CENTROID_CARDS)
          + " training cards, so they are rankable")

    #a card goes missing when the daily ingest changed its text since the test
    #set was written: a stale test set rather than a model failure
    rows, golds, missing = [], [], 0
    for h in held:
        entry = cards.get(h["oracle_id"])
        if entry is None:
            missing += 1
            continue
        rows.append(entry[1])
        golds.append(set(h["tags"]) & set(tags))
    if missing:
        print(str(missing) + " held out cards are no longer single-line cards, skipped")

    gold_total = sum(len(h["tags"]) for h in held)
    reachable = sum(len(g) for g in golds)
    print("ceiling: " + str(reachable) + " of " + str(gold_total)
          + " gold tags (%.1f%%) are rankable at all, the rest have too few training cards"
          % (100 * reachable / max(gold_total, 1)))

    lines = normalize(np.asarray(rows, dtype=np.float32))
    results = {}

    if args.scorer in ("centroid", "both"):
        sims = lines @ centroids.T
        results["centroid"] = evaluate(sims, golds, tags, "centroid: line vs its tag's training cards")

        #a model that knows nothing still scores above zero by guessing the
        #commonest tags, so the floor prints next to the real number
        freq = np.array([counts[t] for t in tags], dtype=np.float32)
        base = np.tile(freq / freq.max(), (len(golds), 1))
        evaluate(base, golds, tags, "baseline: guess the commonest tags, no model at all")

        #the raw material for the next round
        order = np.argsort(-sims, axis=1)
        miss, seen = {}, {}
        for row, gold in enumerate(golds):
            top10 = {tags[i] for i in order[row][:10]}
            for t in gold:
                seen[t] = seen.get(t, 0) + 1
                if t not in top10:
                    miss[t] = miss.get(t, 0) + 1
        hard = sorted(((miss[t] / seen[t], t, miss[t], seen[t]) for t in miss if seen[t] >= 5),
                      reverse=True)[:args.worst]
        if hard:
            print("\nhardest tags (missed from the top 10 most often, 5+ chances):")
            for rate, t, m, s in hard:
                print("  %-38s %3d/%-3d missed   %.0f%%" % (t, m, s, 100 * rate))

    if args.scorer in ("text", "both"):
        from ingest.update import EMBED_MODEL, EMBED_PROMPT
        name = args.model or EMBED_MODEL
        vecs = build_tag_texts(conn, tags, name, EMBED_PROMPT)
        results["text"] = evaluate(lines @ vecs.T, golds, tags, "text: line vs the tag's own words")

    conn.close()
    print("\nthe baseline to beat, current model, 2026-07-21: recall @10 47.0%, MAP 34.8%,")
    print("against 26.9% and 17.8% for guessing the commonest tags and using no model.")


if __name__ == "__main__":
    main()
