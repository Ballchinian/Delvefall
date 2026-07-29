#the daily updater. asks scryfall if their bulk card file changed, and if it
#did, only does the heavy embedding work for cards that are actually new or
#have different text than last time. most days thats a handful of cards, so
#the run finishes in seconds after the download.
#
#prices take a second, bigger download: the oracle file carries one price
#per card (whatever printing scryfall prefers), so the default_cards file
#(every printing) gets streamed through to find each card's cheapest paper
#printing instead.
#
#running this against a brand new empty database seeds the whole thing
#(everything counts as new, ~61k lines to embed, takes a few minutes).
#github actions runs it every day, or run it yourself from the repo root:
#    python -m ingest.update
#with DATABASE_URL set to the postgres connection string

import os
import sys
import json
import time
import hashlib

import requests
import psycopg
from pgvector.psycopg import register_vector

from common.cards import (HEADERS, keep_card, split_lines, get_text, get_image, get_back_image,
                          bulk_uri, bulk_size, read_bulk)
from common.concept import CALIBRATION as CONCEPT_CALIBRATION

BULK_URL = "https://api.scryfall.com/bulk-data"
DOWNLOAD_FILE = "oracle-cards.jsonl.gz"
PRICES_FILE = "default-cards.jsonl.gz"

#my fine tuned embeddinggemma (a sentence-transformers model), taught to score
#a line against what it is about. it sits in a private repo on hugging face, so
#HF_TOKEN has to be set or the download 401s. the prompt was glued to the front
#of every line during training, encoding without it gives useless vectors.
#pointing EMBED_MODEL at anything else makes the next run rebuild every vector
#on its own.
#
#it scores 78% recall @10 on the tag exam, 26/31 on the line-to-line regression
#guard and 94% precision on line attribution. lines.embedding_v1 still holds the
#vectors the model before it produced
EMBED_MODEL = "BallchinianMan/mtg-tagtuned-embeddinggemma-300m"
EMBED_PROMPT = "task: sentence similarity | query: "
EMBED_DIMS = 768

#axis 1's calibration map: raw cosine -> the percent the site shows, piecewise
#linear. raw cosine is arbitrary per model, so this map belongs to the model
#above and lives right next to it. a swap needs the anchors refitted, and a map
#left behind on the wrong model reads a near verbatim match as 62%.
#
#the anchors put a hand judged "yes these match" at 88 and a "no" at 59, so the
#two separate by nearly thirty points, and about three quarters of results clear
#the 70 gate. sat lower, too many results land in the 60-70 band and the axis
#reads stingy next to concepts.
#
#both maps ride to the website through the meta table (written in main
#below, next to the model name they belong to), so the site and the
#pipeline can never disagree about what a percent means
MECH_CALIBRATION = [(0.0, 0), (0.30, 30), (0.42, 45), (0.62, 65), (0.76, 80), (0.90, 92), (1.0, 100)]


def get_with_retries(url, tries=3):
    #scryfall hiccups sometimes, no reason to fail the whole run over it
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == tries - 1:
                raise
            wait = 5 * (attempt + 1)
            print("request failed (" + str(e) + "), retrying in " + str(wait) + "s...")
            time.sleep(wait)


def download_bulk(item, path):
    #stream the file straight to disk rather than holding it in memory on top of
    #the objects parsed out of it. item is one entry from the bulk-data listing,
    #which knows its own url and its own size
    url = bulk_uri(item)
    print("downloading " + url)
    print("(its about " + str(bulk_size(item) // (1024 * 1024)) + "mb compressed so this can take a while)")
    for attempt in range(3):
        try:
            with requests.get(url, headers=HEADERS, timeout=300, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            return
        except Exception as e:
            if attempt == 2:
                raise
            print("download failed (" + str(e) + "), retrying...")
            time.sleep(10)


def finish_price(prices, keys):
    #the cheapest finish (nonfoil, foil, etched) of one printing. scryfall
    #sends strings like "0.25" or None for finishes that dont exist
    best = None
    for k in keys:
        p = prices.get(k)
        if p is not None:
            p = float(p)
            if best is None or p < best:
                best = p
    return best


def cheapest_prices(item):
    #oracle_id -> [usd, eur], the lowest price across every paper printing,
    #plus oracle_id -> the earliest released_at, when the card first existed.
    #the default_cards file is a couple of gigabytes opened up, so read_bulk
    #walks it a line at a time instead of holding the whole thing
    download_bulk(item, PRICES_FILE)
    print("scanning every printing for the cheapest price and first release...")
    best = {}
    debut = {}
    printings = 0
    for c in read_bulk(PRICES_FILE):
        printings += 1
        oid = c.get("oracle_id")
        if not oid and c.get("card_faces"):
            oid = c["card_faces"][0].get("oracle_id")  #reversible cards keep it per face
        if not oid:
            continue
        #the debut counts every printing, even the ones the price hunt
        #skips below: a digital only debut is still the card's debut.
        #iso dates compare fine as strings
        rel = c.get("released_at")
        if rel and (oid not in debut or rel < debut[oid]):
            debut[oid] = rel
        #versions you cant actually buy as the real paper card dont
        #count: arena/mtgo printings, oversized promos, and memorabilia
        #(gold border world championship decks would underprice half the
        #expensive staples in the game)
        if c.get("digital") or c.get("oversized") or c.get("set_type") == "memorabilia":
            continue
        prices = c.get("prices", {})
        usd = finish_price(prices, ("usd", "usd_foil", "usd_etched"))
        eur = finish_price(prices, ("eur", "eur_foil", "eur_etched"))
        low = best.get(oid)
        if low is None:
            best[oid] = [usd, eur]
        else:
            if usd is not None and (low[0] is None or usd < low[0]):
                low[0] = usd
            if eur is not None and (low[1] is None or eur < low[1]):
                low[1] = eur
    os.remove(PRICES_FILE)
    print("checked " + str(printings) + " printings of " + str(len(best)) + " cards")
    return best, debut


def card_hash(card):
    #hashed over the cleaned lines, which is what actually gets embedded, rather
    #than over the raw oracle text they come from. a change to clean_line, to
    #REMINDER_KEYWORDS or to the prefix word catalogs moves the hash of exactly
    #the cards it affects, and they rebuild on the next run without anyone
    #having to force one.
    #
    #the raw text is only a proxy for that input, and the two come apart the
    #moment the cleaner changes: the text sits still, nothing reembeds, and the
    #database goes on holding a line the site no longer computes. since the line
    #picker matches page lines to rows by text, picking one then silently
    #searches the whole card. tools/check_sync.py cannot catch that either, since
    #both copies of clean_line agree with each other and only disagree with what
    #is already on disk.
    #
    #the face rides along too, so a line moving from front to back is a change
    #even when its text is identical. the name rides along because clean_line
    #swaps it for "this card" inside the text, so a rename rewrites every line
    #without touching the raw text either
    parts = [card["name"]]
    for line, face in split_lines(card):
        parts.append(str(face) + ":" + line)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def recompute_uniqueness(conn):
    #fills lines.nn_sim (how close the closest line on any OTHER card gets to
    #this one) and rolls the scores up into cards.uniqueness for the /unique
    #page. its the search query turned inside out: search asks "whats
    #closest", this asks "how far away is even the closest thing".
    #
    #everything gets recomputed from scratch whenever lines changed, same
    #philosophy as line_stats. incremental sounds tempting until you notice a
    #new card can make an old card less unique (it might be its new nearest
    #neighbor), and a deleted card can make its old neighbors more unique, so
    #patching only the changed rows would quietly rot every score around them.
    #
    #this pulls every embedding out of postgres and does the math in numpy,
    #which is fine here and would not be in the web app. asking pgvector for 31k
    #exact nearest neighbors takes ~370ms each on the railway box (measured),
    #call it three hours of pegged production database, while one big matrix
    #multiply on the ingest runner takes about a minute. all-pairs work belongs
    #next to the big cpu, one-query-at-a-time work belongs next to the data
    print("recomputing uniqueness scores...")
    import numpy as np  #late import like torch below, the no-op runs skip it

    ids = []
    owners = []      #row i belongs to card owners[i]
    vecs = []
    for lid, oid, vec in conn.execute("SELECT id, oracle_id, embedding FROM lines WHERE NOT whole"):
        ids.append(lid)
        owners.append(oid)
        #pgvector hands back its own Vector class, not a numpy array
        vecs.append(vec.to_numpy())
    if not ids:
        return  #empty lines table, nothing to score
    emb = np.asarray(vecs, dtype=np.float32)
    print("  pulled " + str(len(ids)) + " embeddings, multiplying...")

    #which rows belong to each card, so a card never counts as its own neighbor
    rows_of_card = {}
    for i, oid in enumerate(owners):
        rows_of_card.setdefault(oid, []).append(i)

    #the embeddings are normalized so cosine similarity is just a dot product.
    #block by block keeps the similarity matrix at ~100mb instead of 13gb
    nn_sim = np.zeros(len(ids), dtype=np.float32)
    block = 512
    for start in range(0, len(ids), block):
        sims = emb[start:start + block] @ emb.T
        for r in range(sims.shape[0]):
            sims[r, rows_of_card[owners[start + r]]] = -2.0  #below any real cosine
        nn_sim[start:start + block] = sims.max(axis=1)

    #COPY the scores into a temp table and update from there, one round trip
    #instead of 58k. the IS DISTINCT FROM means unchanged rows dont get
    #rewritten, which on a normal day is nearly all of them
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE nn_tmp (id bigint PRIMARY KEY, nn_sim real) ON COMMIT DROP")
        with cur.copy("COPY nn_tmp (id, nn_sim) FROM STDIN") as copy:
            for i, lid in enumerate(ids):
                copy.write_row((lid, float(nn_sim[i])))
        cur.execute("""
            UPDATE lines l SET nn_sim = t.nn_sim
            FROM nn_tmp t
            WHERE l.id = t.id AND l.nn_sim IS DISTINCT FROM t.nn_sim
        """)

        #a card is as unique as its most isolated line. DISTINCT ON keeps one
        #row per card and the ORDER BY makes it the line with the lowest
        #nearest neighbor similarity, so a card with Flying plus one ability
        #nobody else has still counts as unique, the Flying line just never
        #wins the argmin
        cur.execute("""
            UPDATE cards c SET uniqueness = (1 - s.nn_sim)::real, unique_line = s.line_text
            FROM (SELECT DISTINCT ON (oracle_id) oracle_id, nn_sim, line_text
                  FROM lines
                  WHERE nn_sim IS NOT NULL
                  ORDER BY oracle_id, nn_sim ASC) s
            WHERE c.oracle_id = s.oracle_id
              AND (c.uniqueness IS DISTINCT FROM (1 - s.nn_sim)::real
                   OR c.unique_line IS DISTINCT FROM s.line_text)
        """)
    conn.commit()
    print("uniqueness done")


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)

    #make sure the tables exist. schema.sql is all IF NOT EXISTS so this is
    #free on every run after the first
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()
    register_vector(conn)

    #the calibration maps go into meta before the gate below, so even a
    #nothing-changed run leaves them in place for the website to read. the
    #site carries seed copies but the database's word wins, which is what
    #keeps a model swap atomic: new vectors and their new map arrive together
    for key, cal in (("mech_calibration", MECH_CALIBRATION),
                     ("concept_calibration", CONCEPT_CALIBRATION)):
        conn.execute("""
            INSERT INTO meta (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, json.dumps(cal)))
    conn.commit()

    #vectors from two different models cant be compared with each other, so
    #if the database was embedded by anything other than the model above,
    #every line needs redoing this run
    row = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
    model_changed = row is None or row[0] != EMBED_MODEL
    if model_changed:
        print("embedding model changed, this run rebuilds every vector (the slow full reseed)")

    print("asking scryfall where the bulk files live...")
    bulk = None
    prices_bulk = None
    for item in get_with_retries(BULK_URL).json()["data"]:
        #oracle_cards = one entry per unique card instead of every single
        #printing. default_cards = every printing, the price scan needs those
        if item["type"] == "oracle_cards":
            bulk = item
        if item["type"] == "default_cards":
            prices_bulk = item
    updated_at = bulk["updated_at"]

    #the gate: if we already processed this exact bulk file, stop right here.
    #this is what makes rerunning the workflow basically free. unless the
    #model changed, then theres a full rebuild to do either way
    row = conn.execute("SELECT value FROM meta WHERE key = 'scryfall_updated_at'").fetchone()
    if not model_changed and row and row[0] == updated_at:
        #the bulk file might be old news while the uniqueness scores arent:
        #the first run after the /unique feature shipped, or a recompute that
        #died halfway. any line without a score means theres finishing to do
        if conn.execute("SELECT 1 FROM lines WHERE nn_sim IS NULL AND NOT whole LIMIT 1").fetchone():
            recompute_uniqueness(conn)
        else:
            print("already processed the bulk file from " + updated_at + ", nothing to do")
        conn.close()
        return

    download_bulk(bulk, DOWNLOAD_FILE)
    print("loading cards...")
    #filtered while the file is read rather than after, so the two thirds of
    #scryfall's list that keep_card throws out are never all in memory at once
    offered = 0
    cards = []
    for c in read_bulk(DOWNLOAD_FILE):
        offered += 1
        if keep_card(c):
            cards.append(c)
    os.remove(DOWNLOAD_FILE)
    print("scryfall gave us " + str(offered) + " cards")
    print("kept " + str(len(cards)) + " real cards that have rules text")

    cheapest, debut = cheapest_prices(prices_bulk)

    #what do we already have? oracle_id -> hash of the text we embedded last time
    have = {}
    for oracle_id, text_hash in conn.execute("SELECT oracle_id, text_hash FROM cards"):
        have[str(oracle_id)] = text_hash

    #which cards the database is holding, off the same query rather than asked
    #for again. kept separately because the model check below empties the hash
    #map and the stale scan still needs the ids
    held = set(have)

    if model_changed:
        #forget the stored hashes so every card counts as new and gets
        #embedded again. the old vectors stay put for now, the site keeps
        #searching on them while the new ones compute. only the hashes go, so a
        #swap run still removes the cards scryfall dropped
        have = {}

    new_cards = []
    changed_cards = []
    unchanged = 0
    card_rows = []  #every kept card, for the upsert below
    for c in cards:
        h = card_hash(c)
        #the cheapest printing's price when the scan found one, falling back
        #to the oracle file's own (scryfall's preferred printing). strings,
        #floats or None, postgres takes any of them into a numeric column
        prices = c.get("prices", {})
        low = cheapest.get(c["oracle_id"], [None, None])
        usd = low[0] if low[0] is not None else prices.get("usd")
        eur = low[1] if low[1] is not None else prices.get("eur")
        #the earliest printing's date from the scan, falling back to the
        #oracle file's own (scryfall's preferred printing, could be a reprint)
        rel = debut.get(c["oracle_id"]) or c.get("released_at")
        card_rows.append((c["oracle_id"], c["name"], c.get("mana_cost", ""), c.get("type_line", ""),
                          get_text(c), get_image(c), c.get("scryfall_uri", ""), h,
                          "".join(c.get("color_identity", [])), usd, eur,
                          c.get("cmc", 0), c.get("game_changer", False),
                          c.get("legalities", {}).get("commander") == "legal",
                          c.get("layout", "normal"), get_back_image(c), c.get("edhrec_rank"), rel))
        old = have.get(c["oracle_id"])
        if old is None:
            new_cards.append((c, h))
        elif old != h:
            changed_cards.append((c, h))
        else:
            unchanged += 1

    #cards in the database that arent in the kept list anymore, either scryfall
    #dropped them or the filters got stricter. they need to go or they sit in
    #search results forever
    kept_ids = set()
    for c in cards:
        kept_ids.add(c["oracle_id"])
    stale = []
    for oid in held:
        if oid not in kept_ids:
            stale.append(oid)
    print(str(len(new_cards)) + " new, " + str(len(changed_cards)) + " changed, "
          + str(unchanged) + " unchanged, " + str(len(stale)) + " to remove")

    #every card row gets offered every run, not just the new and changed ones.
    #prices move daily and wizards edits the game changer list now and then,
    #so waiting for a rules text change would leave those stale forever. the
    #WHERE on the conflict clause skips rows where nothing actually differs,
    #otherwise every run rewrites all ~31k rows (a day of dead tuples and wal
    #for the autovacuum to mop up) just to store the same values. it also
    #makes updated_at mean "last actually changed". the slow embedding work
    #below still only happens when text changed
    print("writing " + str(len(card_rows)) + " card rows (keeps prices and filters fresh)...")
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO cards (oracle_id, name, mana_cost, type_line, oracle_text, image, scryfall_uri, text_hash,
                               color_identity, price_usd, price_eur, cmc, game_changer, legal_commander,
                               layout, image_back, edhrec_rank, released_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (oracle_id) DO UPDATE SET
                name = EXCLUDED.name,
                mana_cost = EXCLUDED.mana_cost,
                type_line = EXCLUDED.type_line,
                oracle_text = EXCLUDED.oracle_text,
                image = EXCLUDED.image,
                scryfall_uri = EXCLUDED.scryfall_uri,
                text_hash = EXCLUDED.text_hash,
                color_identity = EXCLUDED.color_identity,
                price_usd = EXCLUDED.price_usd,
                price_eur = EXCLUDED.price_eur,
                cmc = EXCLUDED.cmc,
                game_changer = EXCLUDED.game_changer,
                legal_commander = EXCLUDED.legal_commander,
                layout = EXCLUDED.layout,
                image_back = EXCLUDED.image_back,
                edhrec_rank = EXCLUDED.edhrec_rank,
                released_at = EXCLUDED.released_at,
                updated_at = now()
            WHERE (cards.name, cards.mana_cost, cards.type_line, cards.oracle_text, cards.image,
                   cards.scryfall_uri, cards.text_hash, cards.color_identity, cards.price_usd,
                   cards.price_eur, cards.cmc, cards.game_changer, cards.legal_commander,
                   cards.layout, cards.image_back, cards.edhrec_rank, cards.released_at)
                  IS DISTINCT FROM
                  (EXCLUDED.name, EXCLUDED.mana_cost, EXCLUDED.type_line, EXCLUDED.oracle_text, EXCLUDED.image,
                   EXCLUDED.scryfall_uri, EXCLUDED.text_hash, EXCLUDED.color_identity, EXCLUDED.price_usd,
                   EXCLUDED.price_eur, EXCLUDED.cmc, EXCLUDED.game_changer, EXCLUDED.legal_commander,
                   EXCLUDED.layout, EXCLUDED.image_back, EXCLUDED.edhrec_rank, EXCLUDED.released_at)
        """, card_rows)

    work = new_cards + changed_cards
    if work:
        #collect every line from every new or changed card so the model runs
        #once over one big batch instead of once per card
        texts = []
        faces = []
        wholes = []
        owners = []  #texts[i] belongs to work[owners[i]]
        for i, (c, h) in enumerate(work):
            card_lines = split_lines(c)
            for line, face in card_lines:
                texts.append(line)
                faces.append(face)
                wholes.append(False)
                owners.append(i)
            #multi-line cards also get one whole-card row (all their cleaned
            #lines together), retrieval material for the line-merging blind
            #spot. single-line cards would just duplicate their line
            if len(card_lines) > 1:
                texts.append("\n".join(line for line, face in card_lines))
                faces.append(0)
                wholes.append(True)
                owners.append(i)

        #imported down here so the nothing-changed runs never pay the slow
        #torch import, it takes longer than the entire rest of the script
        print("loading the model (downloads ~1.2gb the very first time)...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBED_MODEL)
        print("embedding " + str(len(texts)) + " lines, this is the slow part...")
        embs = model.encode(texts, batch_size=64, show_progress_bar=True,
                            normalize_embeddings=True, prompt=EMBED_PROMPT)

        #all the writes ride in one transaction (one commit at the very end),
        #so a crash halfway through leaves the database exactly how it was.
        #executemany batches the rows into pipelined round trips, one insert
        #at a time would take half an hour from github's servers on the seed
        with conn.cursor() as cur:
            if model_changed:
                #the truncate lives down here on purpose: doing it before the
                #slow encode above would hold the table lock the whole time
                #and hang every search on the site. the alter resizes the
                #column to the new model's dims.
                #
                #CASCADE is required, not decoration. line_tags carries a foreign
                #key onto lines(id), and postgres refuses to truncate a table
                #that is referenced by one whether or not the referencing table
                #holds a single row. dropping the attribution is right anyway:
                #line ids are bigserial and every row is about to be rebuilt, so
                #the old line_tags point at ids that stop meaning anything.
                #ingest/attribute.py builds them again from the new lines.
                #
                #what this costs even down here: TRUNCATE takes an ACCESS
                #EXCLUSIVE lock on lines and holds it until this transaction
                #commits, and the commit is after all 61k rows have gone in from
                #a github runner over the network. every search on the site
                #blocks for that whole stretch, because every search reads lines.
                #the COPY below is what keeps it to seconds instead of minutes.
                #
                #this branch is for a model already chosen. trying one out goes
                #through ingest/backfill_embeddings.py instead: it fills
                #embedding_v2, which nothing is reading yet, the site flips over
                #with EMBED_COLUMN, no lock anybody waits on, and it can be
                #put back
                cur.execute("TRUNCATE lines CASCADE")
                cur.execute("ALTER TABLE lines ALTER COLUMN embedding TYPE vector(" + str(EMBED_DIMS) + ")")
            #changed cards get their old lines thrown out and rebuilt fresh
            elif changed_cards:
                old_ids = []
                for c, h in changed_cards:
                    old_ids.append((c["oracle_id"],))
                cur.executemany("DELETE FROM lines WHERE oracle_id = %s", old_ids)

            rows = []
            for j, text in enumerate(texts):
                c = work[owners[j]][0]
                rows.append((c["oracle_id"], text, embs[j], faces[j], wholes[j]))
            print("writing " + str(len(rows)) + " lines...")
            #COPY, like the uniqueness pass above and the salt and tag ingests.
            #executemany pipelines its round trips and is fine for the handful of
            #rows a normal day brings, but a full reseed is 61k of them carrying
            #a 3kb vector each.
            #
            #TEXT format on purpose, not binary. binary wants a real uuid object
            #per row and scryfall hands us strings, so it would mean converting
            #61k ids to buy back less than the conversion costs. the vector
            #round trips exactly either way, since pgvector prints every float
            #it stores
            with cur.copy("COPY lines (oracle_id, line_text, embedding, face, whole) FROM STDIN") as copy:
                for r in rows:
                    copy.write_row(r)

    #deleting a card cascades to its lines, so this cleans up everything
    if stale:
        print("removing " + str(len(stale)) + " cards that are gone or filtered out now...")
        gone = []
        for oid in stale:
            gone.append((oid,))
        with conn.cursor() as cur:
            cur.executemany("DELETE FROM cards WHERE oracle_id = %s", gone)

    if work or stale:
        #recount how common every line is. its one group by over ~61k rows,
        #way easier than trying to patch the counts incrementally.
        #
        #counted per shape, not per exact text: a run of mana symbols collapses
        #to one placeholder first, so "Overload {4}{R}" and "Overload {2}{R}"
        #share a bucket. count exact text and any keyword with a varying cost
        #dodges the idf weighting, fragmenting into one and two card texts that
        #each draw the full 1.0 weight a unique ability gets (overload: 27
        #card-lines, 22 texts, biggest on 2), which is enough to match
        #Vandalblast to Dynacharge at 99% on the keyword alone. still keyed by
        #exact text, which is what the search joins on. no braces, no change:
        #Flying = 2517
        print("recounting how common every line is...")
        conn.execute("TRUNCATE line_stats")
        conn.execute(r"""
            INSERT INTO line_stats
            SELECT line_text, sum(n) OVER (PARTITION BY shape)
            FROM (
                SELECT line_text, count(*) AS n,
                       regexp_replace(line_text, '(\{[^}]*\})+', '{C}', 'g') AS shape
                FROM lines WHERE NOT whole GROUP BY line_text
            ) t
        """)

    #remember which bulk file this was so tomorrow's run can skip it, and
    #which model made the vectors so the next swap rebuilds automatically
    conn.execute("""
        INSERT INTO meta (key, value) VALUES ('scryfall_updated_at', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (updated_at,))
    conn.execute("""
        INSERT INTO meta (key, value) VALUES ('embed_model', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (EMBED_MODEL,))
    conn.commit()

    #uniqueness runs after the commit above on purpose: its derived data, so
    #if it dies halfway the database is still fully consistent and the NULL
    #check at the gate finishes the job on the next run. the NULL check here
    #catches databases from before the /unique feature even on days when no
    #cards changed
    if work or stale or conn.execute("SELECT 1 FROM lines WHERE nn_sim IS NULL AND NOT whole LIMIT 1").fetchone():
        recompute_uniqueness(conn)

    conn.close()
    print("done! " + str(len(new_cards)) + " added, " + str(len(changed_cards)) + " updated, " + str(len(stale)) + " removed")


if __name__ == "__main__":
    main()
