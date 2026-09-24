#a frozen local copy of everything tag inference reads, so exam_autotags.py runs
#offline and never touches production. read-only connection.
#    python finetune/freeze_tagdata.py
#with DATABASE_URL set, or in .env. writes finetune/tagdata/, about 250mb

import os
import sys
import json
import time
import datetime

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tagdata")
DIM = 768


def db_url():
    url = os.environ.get("DATABASE_URL")
    env_path = os.path.join(HERE, "..", ".env")
    if not url and os.path.exists(env_path):
        for raw in open(env_path, encoding="utf-8"):
            if raw.strip().startswith("DATABASE_URL="):
                url = raw.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    return url


def dump(name, obj):
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def columns(conn, sql, names):
    #column-oriented, so a 300k row table loads as a handful of lists
    out = {n: [] for n in names}
    for row in conn.execute(sql):
        for n, v in zip(names, row):
            out[n].append(v)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    conn = psycopg.connect(db_url(), options="-c default_transaction_read_only=on")
    register_vector(conn)
    counts = {}
    t0 = time.time()

    #::vector so the copy reads the same before and after the halfvec swap
    print("lines, one binary copy...")
    ids, owners, texts, faces, nn = [], [], [], [], []
    emb = np.zeros((70000, DIM), dtype=np.float32)
    with conn.cursor() as cur:
        with cur.copy("COPY (SELECT id, oracle_id, line_text, face, nn_sim, embedding::vector FROM lines "
                      "WHERE NOT whole ORDER BY id) TO STDOUT (FORMAT BINARY)") as copy:
            copy.set_types(["int8", "uuid", "text", "int2", "float4", "vector"])
            for lid, oid, text, face, sim, vec in copy.rows():
                i = len(ids)
                if i == len(emb):
                    emb = np.concatenate([emb, np.zeros_like(emb)])
                emb[i] = vec.to_numpy()
                ids.append(lid)
                owners.append(str(oid))
                texts.append(text)
                faces.append(face)
                nn.append(sim)
                if i % 10000 == 0:
                    print("  " + str(i) + "  " + str(round(time.time() - t0)) + "s")
    np.save(os.path.join(OUT, "embeddings.npy"), emb[:len(ids)])
    dump("lines", {"id": ids, "oracle_id": owners, "line_text": texts, "face": faces, "nn_sim": nn})
    counts["lines"] = len(ids)

    print("cards...")
    names = ["oracle_id", "name", "layout", "legal_commander", "uniqueness", "concept_uniqueness",
             "type_line", "mana_cost", "oracle_text"]
    cards = columns(conn, "SELECT oracle_id::text, " + ", ".join(names[1:]) + " FROM cards ORDER BY oracle_id", names)
    dump("cards", cards)
    counts["cards"] = len(cards["oracle_id"])

    print("tags...")
    tables = {
        "card_tags": ("SELECT oracle_id::text, tag, inherited, weight FROM card_tags",
                      ["oracle_id", "tag", "inherited", "weight"]),
        "tags": ("SELECT tag, parents, card_count, idf, description FROM tags",
                 ["tag", "parents", "card_count", "idf", "description"]),
        "tag_dims": ("SELECT tag, dim FROM tag_dims", ["tag", "dim"]),
        "card_tag_vecs": ("SELECT oracle_id::text, vec::text FROM card_tag_vecs", ["oracle_id", "vec"]),
        "line_tags": ("SELECT line_id, tag, lift, card_level FROM line_tags", ["line_id", "tag", "lift", "card_level"]),
        "line_stats": ("SELECT line_text, count FROM line_stats", ["line_text", "count"]),
    }
    for name, (sql, cols) in tables.items():
        data = columns(conn, sql, cols)
        dump(name, data)
        counts[name] = len(data[cols[0]])
        print("  " + name + " " + str(counts[name]))

    meta = {k: v for k, v in conn.execute(
        "SELECT key, value FROM meta WHERE key IN ('tag_vec_width', 'mech_calibration', 'concept_calibration', "
        "'embed_model', 'embed_sha256')")}
    meta["frozen_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta["counts"] = counts
    dump("meta", meta)
    conn.close()
    print("done in " + str(round(time.time() - t0)) + "s: " + json.dumps(counts))


if __name__ == "__main__":
    main()
