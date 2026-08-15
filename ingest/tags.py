#scryfall tagger's community tags into card_tags + tags + card_tag_vecs, for the
#concept axis. taggings are rolled up the tag tree BEFORE anything is counted, so
#a card tagged gives-nimble is gives-evasion too and the counts, idf, norms and
#vectors all agree.
#    python -m ingest.tags
#with DATABASE_URL set. reruns are free, the meta gate skipping the work unless
#scryfall published a newer file.
#
#curation is a BLOCKLIST, not an allowlist: rare tags are the high-precision
#signal (sharing "wheel" says more than sharing "removal") and idf weighting
#already mutes the mega-broad ones

import os
import sys
import json
import math

import psycopg

from common.cards import read_bulk
from ingest.update import BULK_URL, get_with_retries, download_bulk

TAGS_FILE = "oracle-tags.jsonl.gz"

#subtree roots that say nothing about what a card does. "cycle" is set-design
#cycles, NOT the cycling mechanic, which has no bare tag of its own (taggers only
#tag interactions like synergy-cycling)
BLOCKED_ROOTS = [
    "card-names",
    "cycle",
    "alliteration",
    "flavors-of-vanilla",
    "type-errata",
    "unique-type-line",
    "namesake-spell",
    "intervening-if-clause",
]

#what an inherited tag is worth next to a typed one. undamped rollup left only
#.078 between a real concept match and a generic near-miss (.199 before rollup)
#and pushed 1 in 1000 random pairs above the near-substitute anchor. 0.5 keeps
#the sibling links it was all for (delney/tetsuko .000 -> .158) with the random
#pair tail at .695 against .677 for no rollup at all.
#CHANGING THIS means refitting common/concept.py's CALIBRATION
INHERITED_WEIGHT = 0.5


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()

    print("asking scryfall where the tag bulk file lives...")
    bulk = None
    for item in get_with_retries(BULK_URL).json()["data"]:
        if item["type"] == "oracle_tags":
            bulk = item
    updated_at = bulk["updated_at"]

    #the same gate as the card updater, plus the checks that catch a run which
    #died halfway. a weight of 0 counts as unfilled: schema.sql having just added
    #the column, skipping here would leave the concept axis scoring every pair at
    #zero until scryfall happened to publish a new tag file
    row = conn.execute("SELECT value FROM meta WHERE key = 'tagger_updated_at'").fetchone()
    width = conn.execute("SELECT value FROM meta WHERE key = 'tag_vec_width'").fetchone()
    if (row and row[0] == updated_at
            and conn.execute("SELECT 1 FROM card_tags LIMIT 1").fetchone()
            and conn.execute("SELECT 1 FROM card_tag_norms LIMIT 1").fetchone()
            and not conn.execute("SELECT 1 FROM card_tags WHERE weight = 0 LIMIT 1").fetchone()
            #an empty card_tag_vecs counts as unfilled for the same reason a
            #weight of 0 does: schema.sql has just added the table, and skipping
            #here would leave the concept axis with nothing to score against
            #until scryfall happened to publish a new tag file
            and conn.execute("SELECT 1 FROM card_tag_vecs LIMIT 1").fetchone()
            #and so does a column that has been widened since the vectors were
            #built, every stored vector declaring the old width
            and width and width[0] == str(conn.execute("""
                SELECT atttypmod FROM pg_attribute
                WHERE attrelid = 'card_tag_vecs'::regclass AND attname = 'vec'
            """).fetchone()[0])
            and conn.execute("SELECT 1 FROM cards WHERE concept_uniqueness IS NOT NULL LIMIT 1").fetchone()):
        print("already processed the tag file from " + updated_at + ", nothing to do")
        conn.close()
        return

    #the whole list is held in memory either way, the tree walk below needing
    #every tag before it can decide which subtrees to drop
    download_bulk(bulk, TAGS_FILE)
    all_tags = list(read_bulk(TAGS_FILE))
    os.remove(TAGS_FILE)
    print("scryfall gave us " + str(len(all_tags)) + " oracle tags")

    #walk the hierarchy down from every blocked root and drop whole subtrees
    by_id = {t["id"]: t for t in all_tags}
    blocked_ids = set()
    frontier = [t["id"] for t in all_tags if t["slug"] in BLOCKED_ROOTS]
    while frontier:
        tid = frontier.pop()
        if tid in blocked_ids:
            continue
        blocked_ids.add(tid)
        frontier.extend(by_id[tid].get("child_ids", []))
    kept = [t for t in all_tags if t["id"] not in blocked_ids]
    print("blocked " + str(len(blocked_ids)) + " trivia tags, kept " + str(len(kept)))

    #tagger knows cards this database filters out (un-sets, digital only)
    ours = set()
    for (oid,) in conn.execute("SELECT oracle_id FROM cards"):
        ours.add(str(oid))

    links = set()
    for t in kept:
        for tagging in t.get("taggings", []):
            if tagging["oracle_id"] in ours:
                links.add((tagging["oracle_id"], t["slug"]))

    #parents only count if they survived the blocklist themselves
    kept_ids = {t["id"] for t in kept}
    parent_of = {}
    for t in kept:
        parent_of[t["slug"]] = [by_id[p]["slug"] for p in t.get("parent_ids", []) if p in kept_ids]

    #the cache doubles as the CYCLE GUARD: the placeholder set is in place before
    #the walk climbs, so a tag reaching itself finds a partial answer rather than
    #recursing forever
    anc_cache = {}

    def ancestors(slug):
        if slug in anc_cache:
            return anc_cache[slug]
        out = {slug}
        anc_cache[slug] = out
        for p in parent_of.get(slug, []):
            out |= ancestors(p)
        return out

    #tagger expects tools to climb: gives-nimble and gives-unblockable are both
    #gives-evasion, and exact name matching scores those two zero against each
    #other
    rolled = set()
    for oid, slug in links:
        for a in ancestors(slug):
            rolled.add((oid, a))
    print("rolled " + str(len(links)) + " taggings into " + str(len(rolled)) + " card-tag rows")

    #counted off the ROLLED set, so idf means "how many cards have this concept".
    #dozens of tagger's parent tags carry no direct taggings at all (recursion,
    #mill) and counted raw they take the highest idf in the table
    count_of = {}
    for oid, slug in rolled:
        count_of[slug] = count_of.get(slug, 0) + 1

    #idf and the per-tagging weight are worked out HERE rather than by the two
    #UPDATEs this replaced. those rewrote all 323k card_tags rows from inside the
    #rebuild's transaction, and TRUNCATE holds ACCESS EXCLUSIVE, so every search
    #on the site queued behind them: 3.6 seconds of the 3.8 the whole swap took
    n_cards = len(ours)
    idf = {t["slug"]: math.log(n_cards / max(count_of.get(t["slug"], 0), 1)) for t in kept}

    tag_rows = []
    for t in kept:
        tag_rows.append((t["slug"], parent_of[t["slug"]], count_of.get(t["slug"], 0),
                         idf[t["slug"]], t.get("description") or ""))

    #STAGED FIRST, in temp tables, because none of this needs a lock on anything
    #the site reads. only the swap below does
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE new_card_tags (LIKE card_tags)")
        cur.execute("CREATE TEMP TABLE new_tags (LIKE tags)")
        with cur.copy("COPY new_card_tags (oracle_id, tag, inherited, weight) FROM STDIN") as copy:
            for oid, slug in rolled:
                typed = (oid, slug) in links
                copy.write_row((oid, slug, not typed, idf[slug] * (1.0 if typed else INHERITED_WEIGHT)))
        with cur.copy("COPY new_tags (tag, parents, card_count, idf, description) FROM STDIN") as copy:
            for r in tag_rows:
                copy.write_row(r)

        #a dim for every tag that has not got one. append only, so the numbers
        #already in card_tag_vecs keep meaning what they meant
        cur.execute("""
            INSERT INTO tag_dims (tag, dim)
            SELECT n.tag, (SELECT coalesce(max(dim), 0) FROM tag_dims)
                          + row_number() OVER (ORDER BY n.tag)
            FROM new_tags n
            WHERE NOT EXISTS (SELECT 1 FROM tag_dims d WHERE d.tag = n.tag)
        """)
        #the declared width of card_tag_vecs.vec, read back rather than repeated
        #here, so schema.sql stays the only place it is written down
        width = cur.execute("""
            SELECT atttypmod FROM pg_attribute
            WHERE attrelid = 'card_tag_vecs'::regclass AND attname = 'vec'
        """).fetchone()[0]
        highest = cur.execute("SELECT max(dim) FROM tag_dims").fetchone()[0]
        if highest > width:
            #a sparsevec cannot hold a dim past its declared width, so this would
            #fail on the INSERT below anyway. saying it in words beats a cast
            #error. nothing is committed yet, so the old data is still standing
            print("the tag vocabulary outgrew card_tag_vecs: dim " + str(highest)
                  + " against a declared " + str(width) + ". widen the column in "
                  "common/schema.sql (it rewrites the table) and rerun")
            sys.exit(1)

        cur.execute("CREATE TEMP TABLE new_vecs (LIKE card_tag_vecs)")
        cur.execute("""
            INSERT INTO new_vecs (oracle_id, vec)
            SELECT ct.oracle_id,
                   ('{' || string_agg(d.dim || ':' || ct.weight::float8, ',' ORDER BY d.dim)
                        || '}/' || %s)::sparsevec
            FROM new_card_tags ct
            JOIN tag_dims d ON d.tag = ct.tag
            GROUP BY ct.oracle_id
        """, (width,))
        cur.execute("""
            CREATE TEMP TABLE new_norms AS
            SELECT oracle_id, sqrt(sum(weight * weight))::real AS norm
            FROM new_card_tags GROUP BY oracle_id
        """)
    conn.commit()

    #THE SWAP, one transaction so a crash leaves the old data standing and no
    #reader ever sees half of it. everything here is a straight copy between
    #tables already sitting on the server, which is what keeps the lock short
    with conn.cursor() as cur:
        cur.execute("TRUNCATE card_tags, tags, card_tag_norms, card_tag_vecs")
        cur.execute("INSERT INTO card_tags (oracle_id, tag, inherited, weight) "
                    "SELECT oracle_id, tag, inherited, weight FROM new_card_tags")
        cur.execute("INSERT INTO tags (tag, parents, card_count, idf, description) "
                    "SELECT tag, parents, card_count, idf, description FROM new_tags")
        cur.execute("INSERT INTO card_tag_norms SELECT oracle_id, norm FROM new_norms")
        cur.execute("INSERT INTO card_tag_vecs SELECT oracle_id, vec FROM new_vecs")
        cur.execute("""
            INSERT INTO meta (key, value) VALUES ('tagger_updated_at', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (updated_at,))
        #which width the stored vectors were built for. widening the column has to
        #rebuild every one of them, and this is what the gate above compares
        cur.execute("""
            INSERT INTO meta (key, value) VALUES ('tag_vec_width', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (str(width),))
    conn.commit()

    #the tag-space counterpart of lines.nn_sim, same all-pairs-in-blocks trick as
    #the uniqueness pass. untagged cards stay NULL: unknown is not unique
    print("computing concept uniqueness...")
    import numpy as np

    tag_col = {slug: i for i, slug in enumerate(sorted(idf))}
    card_row = {}
    for oid, slug in rolled:
        card_row.setdefault(oid, len(card_row))
    m = np.zeros((len(card_row), len(tag_col)), dtype=np.float32)
    for oid, slug in rolled:
        m[card_row[oid], tag_col[slug]] = idf[slug] * (1.0 if (oid, slug) in links else INHERITED_WEIGHT)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1  #cant happen unless a tag covers every card, but nan poisons everything
    m /= norms

    best = np.zeros(len(card_row), dtype=np.float32)
    block = 256
    for start in range(0, len(card_row), block):
        sims = m[start:start + block] @ m.T
        for r in range(sims.shape[0]):
            sims[r, start + r] = -2.0  #a card is not its own neighbor
        best[start:start + block] = sims.max(axis=1)

    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE cu_tmp (oracle_id uuid PRIMARY KEY, cu real) ON COMMIT DROP")
        with cur.copy("COPY cu_tmp (oracle_id, cu) FROM STDIN") as copy:
            for oid, i in card_row.items():
                copy.write_row((oid, float(1.0 - best[i])))
        cur.execute("UPDATE cards c SET concept_uniqueness = t.cu FROM cu_tmp t WHERE c.oracle_id = t.oracle_id")
        cur.execute("UPDATE cards SET concept_uniqueness = NULL WHERE oracle_id NOT IN (SELECT oracle_id FROM card_tags)")
    conn.commit()

    covered = conn.execute("SELECT count(DISTINCT oracle_id) FROM card_tags").fetchone()[0]
    total = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
    vecs = conn.execute("SELECT count(*) FROM card_tag_vecs").fetchone()[0]
    conn.close()
    print("done! " + str(len(links)) + " card-tag links across " + str(len(tag_rows)) + " tags, "
          + str(covered) + "/" + str(total) + " cards have at least one tag, "
          + str(vecs) + " vectors over " + str(highest) + " dimensions")


if __name__ == "__main__":
    main()
